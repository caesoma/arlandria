"""Grounded evidence validation, source access, and versioned persistence."""

from handoff import load_snapshot
from schema import parse
from storage import atomic_write, digest, inside, json_text, read_json


def source_pages(snapshot, source_id):
    source = next((s for s in snapshot["handoff"]["sources"] if s["record_id"] == source_id), None)
    if source is None:
        raise ValueError("Source is not in the completed Callimachus result")
    return read_json(inside(snapshot["directory"], source["artifact"]))["pages"]


def source_passage(snapshot, source_id, page, offset):
    if type(page) is not int or type(offset) is not int or page < 1 or offset < 0:
        raise ValueError("Invalid page or offset")
    pages = source_pages(snapshot, source_id)
    selected = next((p for p in pages if p["page"] == page), None)
    if selected is None:
        raise ValueError("Page not found")
    end = min(offset + 12000, len(selected["text"]))
    return {
        "source_id": source_id, "page": page, "pages": len(pages),
        "text": selected["text"][offset:end], "next_offset": end if end < len(selected["text"]) else None,
    }


def validate_evidence(snapshot, value, context):
    evidence = parse("Evidence", value)
    parse("Context", context)
    if evidence["handoff_revision"] != snapshot["handoff"]["revision"]:
        raise ValueError("Evidence references a different revision")
    seen = set()
    for item in evidence["claims"] + evidence["findings"] + evidence["gaps"] + evidence["opportunities"]:
        if item["id"] in seen:
            raise ValueError(f"Duplicate evidence ID: {item['id']}")
        seen.add(item["id"])
    claims = {c["id"]: c for c in evidence["claims"]}

    def supported(ids):
        result = []
        for claim_id in ids:
            claim = claims.get(claim_id)
            if claim is None or claim["verification"]["status"] != "supported":
                raise ValueError(f"Unsupported claim: {claim_id}")
            result.append(claim)
        return result

    for claim in evidence["claims"]:
        page = next((p for p in source_pages(snapshot, claim["source_id"]) if p["page"] == claim["page"]), None)
        if page is None or claim["quote"] not in page["text"]:
            raise ValueError(f"Quote not found on cited page: {claim['id']}")
    for finding in evidence["findings"]:
        supported(finding["claim_ids"])
        for claim_id in finding["disagreements"]:
            if claim_id not in claims:
                raise ValueError(f"Missing disagreement evidence: {claim_id}")
    for gap in evidence["gaps"]:
        if any(c["kind"] not in ("gap", "limitation") for c in supported(gap["claim_ids"])):
            raise ValueError(f"Gap requires author-stated gap/limitation evidence: {gap['id']}")
        supported(gap["currency"]["claim_ids"])
        checked = gap["currency"]["checked_source_ids"]
        if any(source_id not in snapshot["handoff"]["included_ids"] for source_id in checked):
            raise ValueError("Currency check cites an external source")
        if gap["status"] != "unresolved" and sorted(checked) != sorted(snapshot["handoff"]["included_ids"]):
            raise ValueError(f"Currency check must cover the completed corpus: {gap['id']}")
        if gap["status"] in ("addressed", "partly-addressed") and not gap["currency"]["claim_ids"]:
            raise ValueError("Addressed gaps require supporting claims")
    for opportunity in evidence["opportunities"]:
        gap = next((g for g in evidence["gaps"] if g["id"] == opportunity["gap_id"]), None)
        if gap is None:
            raise ValueError("Opportunity references a missing gap")
        if any(c["kind"] != "direction" for c in supported(opportunity["direction_claim_ids"])):
            raise ValueError("An opportunity requires an explicit author-proposed direction")
        feasibility = opportunity["feasibility"]
        if any(not any(r["id"] == resource_id for r in context["resources"]) for resource_id in feasibility["resource_ids"]):
            raise ValueError("Feasibility references a resource the researcher did not supply")
        if feasibility["effort"] == "low" and (
            gap["status"] not in ("open-in-reviewed-corpus", "partly-addressed")
            or feasibility["unknowns"] or not feasibility["resource_ids"] or not feasibility["prerequisites"]
        ):
            raise ValueError("Low effort requires current gap, known prerequisites, and researcher resources")
    reviewed = [r["source_id"] for r in evidence["source_reviews"]]
    if len(set(reviewed)) != len(reviewed) or any(source_id not in snapshot["handoff"]["included_ids"] for source_id in reviewed):
        raise ValueError("Invalid source review coverage")
    return evidence


def validate_delivery(snapshot, evidence):
    reviewed = [r["source_id"] for r in evidence["source_reviews"]]
    if sorted(reviewed) != sorted(snapshot["handoff"]["included_ids"]):
        raise ValueError("Every included source needs a review or unreadable disposition before delivery")
    for claim in evidence["claims"]:
        review = next(r for r in evidence["source_reviews"] if r["source_id"] == claim["source_id"])
        if review["status"] == "unreadable" and claim["verification"]["status"] == "supported":
            raise ValueError("Unreadable sources cannot support verified claims")


def evidence_directory(snapshot):
    directory = inside(snapshot["root"], f".hypatia/{snapshot['handoff']['revision']}")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def load_context(snapshot):
    return parse("Context", read_json(inside(evidence_directory(snapshot), "context.json")))


def save_context(snapshot, context):
    atomic_write(inside(evidence_directory(snapshot), "context.json"), json_text(parse("Context", context)))


def load_evidence(snapshot):
    path = inside(evidence_directory(snapshot), "evidence.json")
    if path.exists():
        return validate_evidence(snapshot, read_json(path), load_context(snapshot))
    return {
        "schema_version": 1, "handoff_revision": snapshot["handoff"]["revision"],
        "claims": [], "findings": [], "gaps": [], "opportunities": [], "source_reviews": [],
    }


def save_evidence(snapshot, value):
    load_snapshot(snapshot["root"], snapshot["handoff"]["revision"])
    evidence = validate_evidence(snapshot, value, load_context(snapshot))
    directory = evidence_directory(snapshot)
    encoded = json_text(evidence)
    evidence_hash = digest(encoded)
    path = inside(directory, f"history/{evidence_hash}.json")
    if not path.exists():
        atomic_write(path, encoded)
    atomic_write(inside(directory, "evidence.json"), encoded)
    return evidence_hash


def evidence_digest(snapshot):
    directory = evidence_directory(snapshot)
    return digest(inside(directory, "evidence.json").read_bytes() + b"\n" + inside(directory, "context.json").read_bytes())
