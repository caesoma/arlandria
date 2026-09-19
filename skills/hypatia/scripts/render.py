"""Markdown, SVG, Beamer, and provenance exports from validated evidence."""

import re
from uuid import uuid4

from evidence import evidence_digest, evidence_directory, load_context, load_evidence, validate_delivery
from handoff import load_snapshot
from slides import beamer, opportunity_text, shortlist
from storage import atomic_write, digest, inside, json_text


def md(value: str) -> str:
    return re.sub(r"\r?\n", " ", re.sub(r"[\\`*_{}\[\]()<>#|!]", r"\\\g<0>", value))


def xml(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def cites(ids):
    return ", ".join(f"[{claim_id}](#claim-{claim_id})" for claim_id in ids)


def report(snapshot, evidence, context):
    handoff, ledger = snapshot["handoff"], snapshot["ledger"]
    lines = [
        f"# Hypatia — {md(ledger['question'])}", "",
        f"Audience: {md(context['audience'])}. Search cutoff: **{handoff['cutoff']}**.",
        f"Callimachus revision: `{handoff['revision']}`. Final included publications: **{len(handoff['included_ids'])}**.",
        "Publication counts are not independent-study counts or evidence-quality scores.", "",
        "## Executive summary", "",
        *(f"- {md(f['statement'])} ({cites(f['claim_ids'])})" for f in evidence["findings"][:5]),
        "" if evidence["findings"] else "No supported findings were established.",
        f"{len(shortlist(evidence))} direction(s) meet the stated low-effort criteria. Feasibility is Hypatia's assessment, not an author claim.",
        "", "## Scope and methods", "",
        f"Include: {'; '.join(map(md, ledger['criteria']['include'])) or 'None specified'}.",
        f"Exclude: {'; '.join(map(md, ledger['criteria']['exclude'])) or 'None specified'}.",
        f"Callimachus recorded {len(ledger['queries'])} query audit entries and {len(ledger['records'])} deduplicated records. All abstract screening and required human curation dispositions are complete.",
        "The complete search audit and screening decisions are in the pinned Callimachus ledger. No additional search was performed by Hypatia.",
        "", "## Main findings and disagreements", "",
    ]
    for finding in evidence["findings"]:
        lines.extend([
            f"### {finding['id']}: {md(finding['statement'])}", "",
            f"Evidence: {cites(finding['claim_ids'])}. Appraisal: {md(finding['strength'])}.",
            f"Disagreement / counterevidence: {cites(finding['disagreements']) if finding['disagreements'] else 'none recorded; this does not establish consensus'}.", "",
        ])
    lines.extend(["## Literature-identified gaps", ""])
    for gap in evidence["gaps"]:
        lines.extend([
            f"### {gap['id']}: {md(gap['statement'])}", "",
            f"Status: **{gap['status']}**. Evidence: {cites(gap['claim_ids'])}.",
            f"Currency assessment: {md(gap['currency']['rationale'])} ({len(gap['currency']['checked_source_ids'])}/{len(handoff['included_ids'])} included publications checked).",
            f"Subsequent evidence: {cites(gap['currency']['claim_ids']) or 'none recorded'}.", "",
        ])
    lines.extend([
        "An open gap is scoped to this completed corpus and its cutoff; it is not proof of absence across the field.", "",
        "## Low-hanging fruit under stated constraints", "",
    ])
    if not shortlist(evidence):
        lines.extend(["No directions can currently be shortlisted with adequate evidence and known resources.", ""])
    for opportunity in shortlist(evidence):
        lines.extend([
            f"- **{opportunity['id']}** — {md(opportunity_text(evidence, opportunity))} ({cites(opportunity['direction_claim_ids'])}); see the assessment below.", "",
        ])
    lines.extend(["## All author-proposed directions and feasibility", ""])
    for opportunity in evidence["opportunities"]:
        feasibility = opportunity["feasibility"]
        lines.extend([
            f"### {opportunity['id']}: {md(opportunity_text(evidence, opportunity))}", "",
            f"Author-proposal evidence: {cites(opportunity['direction_claim_ids'])}. Gap: {opportunity['gap_id']}.",
            f"Hypatia effort assessment: **{feasibility['effort']}** — {md(feasibility['rationale'])}.",
            f"Prerequisites: {'; '.join(map(md, feasibility['prerequisites'])) or 'unknown'}.",
            f"Unknowns: {'; '.join(map(md, feasibility['unknowns'])) or 'none recorded'}.",
            f"Researcher resource references: {', '.join(feasibility['resource_ids']) or 'none; feasibility remains unestablished'}.", "",
        ])
    lines.extend([
        "## Researcher constraints", "",
        *(f"- {r['id']}: {md(r['description'])}" for r in context["resources"]),
        "" if context["resources"] else "No resources supplied; low-effort shortlisting is disabled.", "",
        "## Coverage, access, and unresolved evidence", "",
    ])
    for source in handoff["sources"]:
        limitation = f" — {md(source['limitation'])}" if source["limitation"] else ""
        lines.append(f"- {md(source['record_id'])}: {source['kind']}{limitation}. {' '.join(map(md, source['warnings']))}")
    for review in evidence["source_reviews"]:
        lines.append(f"- {md(review['source_id'])} — {review['status']}: {md(review['note'])}")
    for claim in evidence["claims"]:
        if claim["verification"]["status"] != "supported":
            lines.append(f"- {claim['id']}: **{claim['verification']['status']}** — {md(claim['verification']['reason'])}.")
    lines.extend(["", "## References", ""])
    for record in ledger["records"]:
        if record["id"] in handoff["included_ids"]:
            year = record["year"] if record["year"] is not None else "year unknown"
            lines.append(f"- **{md(record['id'])}**: {md(', '.join(record['authors']))}. {md(record['title'])} ({year}). DOI: {md(record['doi'] if record['doi'] is not None else 'unavailable')}.")
    lines.extend([
        "", "## Claim-to-source audit", "",
        "Exact quotation matching checks provenance. Semantic support and scientific strength remain explicit, reviewable assessments.", "",
    ])
    for claim in evidence["claims"]:
        source = next(s for s in handoff["sources"] if s["record_id"] == claim["source_id"])
        locator = "abstract" if source["kind"] == "abstract" else f"PDF page {claim['page']}"
        lines.extend([
            f'<a id="claim-{claim["id"]}"></a>', f"### {claim['id']} — {claim['kind']}", "",
            md(claim["statement"]), "", f"> {md(claim['quote'])}", "",
            f"Source: {md(claim['source_id'])}, {locator}; artifact `{source['artifact']}`.",
            f"Verification: **{claim['verification']['status']}** — {md(claim['verification']['reason'])}.",
            f"Appraisal: {md(claim['appraisal'])}. Independent-study identity: {md(claim['study_id'] if claim['study_id'] is not None else 'unknown')}.", "",
        ])
    return "\n".join(lines) + "\n"


def wrap(value, width=110):
    return [s.strip() for s in re.findall(rf".{{1,{width}}}(?:\s|$)|.{{1,{width}}}", value)] or [""]


def svg(title, description, rows):
    lines = [title, description]
    for row in rows:
        lines.extend([*wrap(row), ""])
    content = "\n".join(
        f'<text x="24" y="{38 + i * 25}" font-size="{22 if i == 0 else 15}">{xml(line)}</text>'
        for i, line in enumerate(lines)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title description" viewBox="0 0 1150 {70 + len(lines) * 25}">\n'
        f'<title id="title">{xml(title)}</title><desc id="description">{xml(description)}</desc>\n'
        f'<rect width="100%" height="100%" fill="white"/><g fill="#172b4d" font-family="sans-serif">{content}</g></svg>\n'
    )


def table_svg(title, description, columns, rows):
    elements = []
    y = 125
    for index, row in enumerate([[c["label"] for c in columns], *rows]):
        cells = [wrap(value, max(8, int((columns[i]["width"] - 24) / 8.5))) for i, value in enumerate(row)]
        height = max(map(len, cells)) * 23 + 24
        x = 25
        for i, lines in enumerate(cells):
            fill = "#e6edf5" if index == 0 else "#ffffff" if index % 2 else "#f4f7fb"
            elements.append(f'<rect x="{x}" y="{y}" width="{columns[i]["width"]}" height="{height}" fill="{fill}" stroke="#bdcbdc"/>')
            elements.extend(
                f'<text x="{x + 12}" y="{y + 26 + line * 23}" font-weight="{600 if index == 0 else 400}">{xml(value)}</text>'
                for line, value in enumerate(lines)
            )
            x += columns[i]["width"]
        y += height
    caption = "\n".join(f'<text x="25" y="{67 + i * 22}">{xml(line)}</text>' for i, line in enumerate(wrap(description, 115)))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title description" viewBox="0 0 1150 {y + 35}">\n'
        f'<title id="title">{xml(title)}</title><desc id="description">{xml(description)}</desc>\n'
        '<rect width="100%" height="100%" fill="white"/>\n'
        '<g fill="#172b4d" font-family="sans-serif" font-size="15">\n'
        f'<text x="25" y="38" font-size="24" font-weight="600">{xml(title)}</text>\n'
        f'{caption}\n' + "\n".join(elements) + "</g></svg>\n"
    )


def render(snapshot):
    load_snapshot(snapshot["root"], snapshot["handoff"]["revision"])
    evidence, context = load_evidence(snapshot), load_context(snapshot)
    validate_delivery(snapshot, evidence)
    evidence_hash = evidence_digest(snapshot)
    renderer_version = 3
    export_hash = digest(json_text({"evidence_digest": evidence_hash, "renderer_version": renderer_version}))
    root = evidence_directory(snapshot)
    directory = inside(root, f"exports/{export_hash}")
    delivery = json_text({"digest": export_hash, "directory": str(directory)})
    if directory.exists():
        atomic_write(inside(root, "delivery.json"), delivery)
        return str(directory)
    staging = inside(root, f"exports/{export_hash}.{uuid4()}.partial")
    staging.mkdir(parents=True)

    def save(name, data):
        with (staging / name).open("xb") as stream:
            stream.write(data.encode("utf-8") if isinstance(data, str) else data)

    save("report.md", report(snapshot, evidence, context))
    save("slides.tex", beamer(snapshot, evidence, context))
    save("brief.md", "\n".join([
        f"# {md(snapshot['ledger']['question'])}",
        f"Search cutoff: {snapshot['handoff']['cutoff']}; revision: {snapshot['handoff']['revision']}.",
        "", "## Findings",
        *(f"- {md(f['statement'])} ({', '.join(f['claim_ids'])}; see report audit). Strength: {md(f['strength'])}. Counterevidence: {', '.join(f['disagreements']) or 'none recorded'}." for f in evidence["findings"]),
        "", "## Gaps",
        *(f"- {md(g['statement'])} — {g['status']} ({', '.join(g['claim_ids'])})." for g in evidence["gaps"]),
        "", "## Feasible author-proposed directions",
        *(f"- {md(opportunity_text(evidence, o))} ({', '.join(o['direction_claim_ids'])}). Hypatia feasibility assessment: {md(o['feasibility']['rationale'])}." for o in shortlist(evidence)),
        "" if shortlist(evidence) else "No adequately supported low-effort shortlist.",
        "", "## Limitations", "This summary inherits the report's corpus cutoff, access limitations, uncertainty, and researcher constraints.",
        *(f"- {md(s['record_id'])}: {md(s['limitation'])}" for s in snapshot["handoff"]["sources"] if s["limitation"]),
        *(f"- {c['id']}: {c['verification']['status']} — {md(c['verification']['reason'])}" for c in evidence["claims"] if c["verification"]["status"] != "supported"),
    ]) + "\n")
    caption = f"Cutoff {snapshot['handoff']['cutoff']}. {len(snapshot['handoff']['included_ids'])} included publications; counts are not evidence strength."

    def cells(source_id, kinds):
        return "; ".join(
            f"{c['id']} ({c['verification']['status']})"
            for c in evidence["claims"] if c["source_id"] == source_id and c["kind"] in kinds
        ) or "No extracted claims"

    save("evidence-matrix.svg", table_svg("Evidence matrix — claim IDs and verification status", caption, [
        {"label": "Publication / access", "width": 240}, {"label": "Findings", "width": 215},
        {"label": "Gaps / limitations", "width": 215}, {"label": "Author proposals", "width": 215},
        {"label": "Context", "width": 215},
    ], [
        [f"{s['record_id']} [{s['kind']}]", cells(s["record_id"], ["finding"]), cells(s["record_id"], ["gap", "limitation"]),
         cells(s["record_id"], ["direction"]), cells(s["record_id"], ["context"])]
        for s in snapshot["handoff"]["sources"]
    ]))
    gaps = {g["id"]: g for g in evidence["gaps"]}
    save("opportunity-matrix.svg", table_svg("Opportunity matrix — feasibility is Hypatia's assessment", caption, [
        {"label": "Opportunity", "width": 125}, {"label": "Gap / status", "width": 290},
        {"label": "Effort", "width": 110}, {"label": "Unknowns", "width": 325},
        {"label": "Author-proposal evidence", "width": 250},
    ], [
        [o["id"], f"{o['gap_id']}: {gaps[o['gap_id']]['status']}", o["feasibility"]["effort"],
         "; ".join(o["feasibility"]["unknowns"]) or "None recorded", ", ".join(o["direction_claim_ids"])]
        for o in evidence["opportunities"]
    ]))
    directions = []
    for opportunity in evidence["opportunities"]:
        gap = gaps[opportunity["gap_id"]]
        directions.append([
            f"{gap['id']}: {gap['statement']} [{', '.join(gap['claim_ids'])}] ({gap['status']})", "→",
            f"{opportunity['id']}: {opportunity_text(evidence, opportunity)} [{', '.join(opportunity['direction_claim_ids'])}]",
        ])
    save("gap-directions.svg", table_svg("Literature gaps → author-proposed directions", caption, [
        {"label": "Gap / source claims", "width": 475}, {"label": "Link", "width": 70},
        {"label": "Author direction / source claims", "width": 555},
    ], directions))
    save("review-flow.svg", svg("Callimachus review flow", caption, [
        f"{len(snapshot['ledger']['queries'])} recorded query audit entries → {len(snapshot['ledger']['records'])} deduplicated publications → {len(snapshot['handoff']['included_ids'])} final included publications.",
        f"Deferred: {sum(r['status'] == 'deferred' for r in snapshot['ledger']['records'])}.",
        f"Included with full text: {sum(s['kind'] == 'fulltext' for s in snapshot['handoff']['sources'])}; abstract-only: {sum(s['kind'] == 'abstract' for s in snapshot['handoff']['sources'])}.",
        "All final included sources have human curation dispositions. Access limitations are retained.",
    ]))
    save("evidence.json", json_text(evidence))
    save("context.json", json_text(context))
    for name in ("references.bib", "references.csv"):
        save(name, inside(snapshot["directory"], name).read_bytes())
    save("provenance.json", json_text({
        "handoff": snapshot["handoff"], "evidence_digest": evidence_hash, "renderer_version": renderer_version,
    }))
    load_snapshot(snapshot["root"], snapshot["handoff"]["revision"])
    if evidence_hash != evidence_digest(snapshot):
        raise ValueError("Evidence changed during rendering")
    staging.rename(directory)
    atomic_write(inside(root, "delivery.json"), delivery)
    return str(directory)
