#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema==4.25.1"]
# ///
"""Standalone skill operations. JSON payloads arrive on stdin; results go to stdout."""

import argparse
import json
from pathlib import Path
import sys

from evidence import (
    evidence_digest, evidence_directory, load_context, load_evidence,
    save_context, save_evidence, source_passage, validate_evidence,
)
from handoff import approve_gate, finalize, gate_fingerprint, load_snapshot
from render import render
from schema import SCHEMAS
from slides import beamer, shortlist
from state import pause_request, prepare_review, read_request, write_request
from storage import inside, json_text


OPERATIONS = (
    "prepare", "request-read", "request-write", "pause", "gate-fingerprint", "approve-gate", "finalize",
    "load-snapshot", "snapshot", "source", "context", "context-save", "evidence", "save", "render",
    "evidence-directory", "evidence-digest", "validate", "beamer", "shortlist", "inside", "schema",
)


def execute(operation, root, revision, payload):
    if operation == "schema":
        return SCHEMAS[payload["name"]]
    if operation == "prepare":
        return prepare_review(root, payload.get("question", ""))
    if operation == "request-read":
        return read_request(root)
    if operation == "request-write":
        return write_request(root, payload)
    if operation == "pause":
        return pause_request(root, payload["question"])
    if operation == "gate-fingerprint":
        return gate_fingerprint(root, payload["gate"])
    if operation == "approve-gate":
        return approve_gate(root, payload["gate"], payload["fingerprint"])
    if operation == "finalize":
        return finalize(root)
    if operation == "inside":
        return str(inside(root, payload["path"]))
    if operation == "shortlist":
        return shortlist(payload)
    if operation == "beamer":
        return beamer(payload["snapshot"], payload["evidence"], payload["context"])
    snapshot = load_snapshot(root, revision)
    if operation == "load-snapshot":
        return snapshot
    if operation == "evidence-directory":
        return str(evidence_directory(snapshot))
    if operation == "snapshot":
        return {
            "handoff": snapshot["handoff"], "ledger": snapshot["ledger"],
            "context": load_context(snapshot), "evidence": load_evidence(snapshot),
        }
    if operation == "source":
        return source_passage(snapshot, payload["source_id"], payload["page"], payload["offset"])
    if operation == "context":
        path = inside(evidence_directory(snapshot), "context.json")
        return load_context(snapshot) if path.exists() else None
    if operation == "context-save":
        return save_context(snapshot, payload)
    if operation == "evidence":
        return load_evidence(snapshot)
    if operation == "save":
        return save_evidence(snapshot, payload)
    if operation == "validate":
        return validate_evidence(snapshot, payload["evidence"], payload["context"])
    if operation == "evidence-digest":
        return evidence_digest(snapshot)
    if operation == "render":
        return render(snapshot)
    raise ValueError("Unknown operation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=OPERATIONS)
    parser.add_argument("review", nargs="?", type=Path, help="Callimachus review folder")
    parser.add_argument("--revision", help="Pin to the expected completed revision")
    parser.add_argument("--input", type=Path, help="JSON payload file; otherwise read piped stdin")
    args = parser.parse_args()
    try:
        raw = args.input.read_bytes() if args.input else (b"" if sys.stdin.isatty() else sys.stdin.buffer.read())
        payload = json.loads(raw) if raw.strip() else {}
        if args.review is None and args.operation not in ("schema", "beamer", "shortlist"):
            raise ValueError("A review folder is required")
        result = execute(args.operation, args.review, args.revision, payload)
        sys.stdout.buffer.write(json_text(result).encode("utf-8"))
    except (ValueError, OSError, KeyError, TypeError) as error:
        sys.stdout.buffer.write(json_text({"error": str(error)}).encode("utf-8"))
        sys.exit(1)


if __name__ == "__main__":
    main()
