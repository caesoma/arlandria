"""Callimachus completion and immutable snapshot verification."""

from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

from schema import parse
from storage import atomic_write, digest, inside, json_text, read_json


GATES = ("criteria", "triage", "curation")


def signing_key(create: bool) -> bytes:
    directory = Path.home() / ".arlandria"
    path = directory / "completion.key"
    if create and not path.exists():
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
                stream.write(os.urandom(32))
        except FileExistsError:
            pass
    return path.read_bytes()


def seal(value, create=False) -> str:
    return hmac.new(signing_key(create), json_text(value).encode("utf-8"), hashlib.sha256).hexdigest()


def gate_fingerprint(root, gate: str) -> str:
    if gate not in GATES:
        raise ValueError("Unknown approval gate")
    root = Path(root)
    ledger = parse("Ledger", read_json(root / "ledger.json"))
    criteria = {"question": ledger["question"], "criteria": ledger["criteria"]}
    if gate == "criteria":
        return digest(json_text(criteria))
    if gate == "triage":
        return digest(json_text({
            **criteria, "queries": ledger["queries"],
            "records": [
                {"id": r["id"], "status": r["status"], "abstract": r["screening"]["abstract"]}
                for r in ledger["records"]
            ],
        }))
    registry = parse("Sources", read_json(root / "sources.json"))
    return digest(json_text({
        "ledger": digest((root / "ledger.json").read_bytes()),
        "registry": digest((root / "sources.json").read_bytes()),
        "artifacts": [
            {"pdf": digest(inside(root, s["pdf"]).read_bytes()),
             "extraction": digest(inside(root, s["extraction"]).read_bytes())}
            for s in registry["sources"] if s["kind"] == "fulltext"
        ],
    }))


def approve_gate(root, gate: str, fingerprint: str) -> None:
    if fingerprint != gate_fingerprint(root, gate):
        raise ValueError("Review changed during approval; review it again")
    path = inside(root, ".callimachus/approvals.json")
    approvals = parse("Approval", read_json(path)) if path.exists() else {}
    atomic_write(path, json_text({**approvals, gate: fingerprint}))


def completion_inputs(root):
    root = Path(root)
    ledger = parse("Ledger", read_json(root / "ledger.json"))
    registry = parse("Sources", read_json(root / "sources.json"))
    approvals = parse("Approval", read_json(inside(root, ".callimachus/approvals.json")))
    for gate in GATES:
        if approvals.get(gate) != gate_fingerprint(root, gate):
            raise ValueError(f"Pending or stale {gate} approval")
    if not ledger["queries"]:
        raise ValueError("No completed search/pool audit")
    if len({r["id"] for r in ledger["records"]}) != len(ledger["records"]):
        raise ValueError("Duplicate record IDs")
    for record in ledger["records"]:
        abstract, fulltext = record["screening"]["abstract"], record["screening"]["fulltext"]
        if abstract["decision"] not in ("include", "exclude", "borderline"):
            raise ValueError(f"Abstract screening incomplete: {record['id']}")
        if abstract["criteria_version"] != ledger["criteria"]["version"] and abstract["decided_by"] != "human":
            raise ValueError(f"Stale abstract decision: {record['id']}")
        if record["status"] == "deferred":
            continue
        if abstract["decision"] != "exclude" or fulltext["decision"] == "include":
            if fulltext["decision"] not in ("include", "exclude") or fulltext["decided_by"] != "human" or not fulltext["reason"]:
                raise ValueError(f"Human full-text disposition required: {record['id']}")
    included = [
        r for r in ledger["records"]
        if r["status"] == "active" and r["screening"]["fulltext"]["decision"] == "include"
    ]
    if sorted(s["record_id"] for s in registry["sources"]) != sorted(r["id"] for r in included):
        raise ValueError("Source registry must match the final included set exactly")
    return ledger, registry, included, approvals


def finalize(root) -> str:
    root = Path(root).resolve()
    ledger, registry, included, approvals = completion_inputs(root)
    revision = str(uuid4())
    base = inside(root, ".callimachus/completed")
    base.mkdir(parents=True, exist_ok=True)
    pending = inside(root, f".callimachus/completed/{revision}.partial")
    pending.mkdir()
    artifacts = {}

    def write(name, data):
        raw = data.encode("utf-8") if isinstance(data, str) else data
        with (pending / name).open("xb") as stream:
            stream.write(raw)
        artifacts[name] = digest(raw)

    write("ledger.json", (root / "ledger.json").read_bytes())
    write("sources.json", json_text(registry))
    sources = []
    for index, entry in enumerate(registry["sources"]):
        record = next(r for r in included if r["id"] == entry["record_id"])
        artifact = f"source-{index}.json"
        if entry["kind"] == "fulltext":
            extraction = parse("Extraction", read_json(inside(root, entry["extraction"])))
            pdf = inside(root, entry["pdf"]).read_bytes()
            if digest(pdf) != extraction["pdf_sha256"]:
                raise ValueError(f"PDF/extraction mismatch: {record['id']}")
            if not any(p["text"].strip() for p in extraction["pages"]):
                raise ValueError(f"Empty extraction: {record['id']}")
            if any(p["page"] != i + 1 for i, p in enumerate(extraction["pages"])):
                raise ValueError("Invalid page sequence")
            write(f"source-{index}.pdf", pdf)
            write(artifact, json_text(extraction))
            sources.append({
                "record_id": record["id"], "kind": "fulltext", "artifact": artifact,
                "limitation": "", "warnings": extraction["warnings"],
            })
        else:
            if not (record["abstract"] or "").strip():
                raise ValueError(f"No usable abstract: {record['id']}")
            write(artifact, json_text({"pages": [{"page": 1, "text": record["abstract"]}]}))
            sources.append({
                "record_id": record["id"], "kind": "abstract", "artifact": artifact,
                "limitation": entry["limitation"], "warnings": [],
            })
    exporter = Path(__file__).resolve().parents[2] / "callimachus/scripts/export.py"
    for fmt in ("bibtex", "csv"):
        result = subprocess.run(
            [sys.executable, str(exporter), "--ledger", str(pending / "ledger.json"), "--format", fmt, "--stdout"],
            capture_output=True, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        if result.returncode:
            raise ValueError(f"Final export failed: {result.stderr.decode('utf-8', errors='replace')}")
        write("references.bib" if fmt == "bibtex" else "references.csv", result.stdout)
    unsigned = {
        "schema_version": 1, "producer": "callimachus", "status": "completed", "run_id": revision,
        "review_id": ledger["review_id"], "revision": revision,
        "completed_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "criteria_version": ledger["criteria"]["version"], "cutoff": registry["cutoff"],
        "ledger_sha256": digest((root / "ledger.json").read_bytes()),
        "sources_sha256": digest((root / "sources.json").read_bytes()),
        "included_ids": [r["id"] for r in included],
        "stages": {stage: "completed" for stage in (
            "question", "criteria", "query", "pool", "screen", "triage", "refine", "export", "curation",
        )},
        "gates": {gate: approvals[gate] for gate in GATES}, "sources": sources, "artifacts": artifacts,
    }
    with (pending / "handoff.json").open("xb") as stream:
        stream.write(json_text({**unsigned, "seal": seal(unsigned, True)}).encode("utf-8"))
    completion_inputs(root)
    if unsigned["ledger_sha256"] != digest((root / "ledger.json").read_bytes()) or unsigned["sources_sha256"] != digest((root / "sources.json").read_bytes()):
        raise ValueError("Review changed during finalization")
    pending.rename(base / revision)
    atomic_write(inside(root, ".callimachus/current.json"), json_text({"revision": revision}))
    return revision


def load_snapshot(root, revision=None):
    root = Path(root).resolve()
    current = read_json(inside(root, ".callimachus/current.json"))
    if not isinstance(current, dict) or not isinstance(current.get("revision"), str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", current["revision"]):
        raise ValueError("Invalid completion pointer")
    if revision and revision != current["revision"]:
        raise ValueError("A newer Callimachus revision requires a new synthesis")
    directory = inside(root, f".callimachus/completed/{current['revision']}")
    handoff = parse("Handoff", read_json(inside(directory, "handoff.json")))
    signature = handoff["seal"]
    unsigned = {k: v for k, v in handoff.items() if k != "seal"}
    if not re.fullmatch(r"[a-f0-9]{64}", signature) or not hmac.compare_digest(signature, seal(unsigned)):
        raise ValueError("Untrusted Callimachus completion record")
    if handoff["revision"] != current["revision"]:
        raise ValueError("Revision mismatch")
    for name, expected in handoff["artifacts"].items():
        if digest(inside(directory, name).read_bytes()) != expected:
            raise ValueError(f"Modified snapshot artifact: {name}")
    if digest((root / "ledger.json").read_bytes()) != handoff["ledger_sha256"] or digest((root / "sources.json").read_bytes()) != handoff["sources_sha256"]:
        raise ValueError("Callimachus has changed; complete its workflow before continuing Hypatia")
    ledger, registry, _, _ = completion_inputs(root)
    for entry in registry["sources"]:
        if entry["kind"] != "fulltext":
            continue
        source = next(s for s in handoff["sources"] if s["record_id"] == entry["record_id"])
        extraction = parse("Extraction", read_json(inside(root, entry["extraction"])))
        original = parse("Extraction", read_json(inside(directory, source["artifact"])))
        if digest(json_text(extraction)) != handoff["artifacts"][source["artifact"]] or digest(inside(root, entry["pdf"]).read_bytes()) != original["pdf_sha256"]:
            raise ValueError(f"Upstream source changed: {entry['record_id']}")
    return {"root": str(root), "directory": str(directory), "handoff": handoff, "ledger": ledger, "registry": registry}
