from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _common import ledger_entry, load_ledger, save_ledger, search_record
from handoff import approve_gate, finalize, gate_fingerprint, load_snapshot
from evidence import save_context, save_evidence
from storage import atomic_write, digest, json_text


ROOT = Path(__file__).resolve().parent.parent
TEXT = "An association was found. Rural clinics remain untested. Future work should evaluate rural clinics."


def run_main(function, *args):
    output = io.StringIO()
    with patch.object(sys, "argv", [function.__module__, *map(str, args)]), redirect_stdout(output):
        function()
    return output.getvalue()


def record(**values):
    return ledger_entry(search_record(
        **{"title": "Café α research", "year": 2025, "authors": ["Renée Researcher"],
           "abstract": TEXT, "source_backend": "fixture", **values},
    ))


class Sandbox(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.root = self.home / "review"
        self.root.mkdir()
        environment = patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)})
        environment.start()
        self.addCleanup(environment.stop)
        network = patch("socket.socket.connect", side_effect=AssertionError("Tests must not contact live services"))
        network.start()
        self.addCleanup(network.stop)
        self.ledger_path = self.root / "ledger.json"
        self.empty_ledger = load_ledger(self.ledger_path)

    def write(self, name, value):
        atomic_write(self.root / name, json_text(value))
        return self.root / name

    def read(self, name="ledger.json"):
        return json.loads((self.root / name).read_bytes())

    def ledger(self, records=None):
        value = deepcopy(self.empty_ledger)
        value["question"] = "What is established?"
        value["criteria"] = {"version": 1, "include": ["Relevant studies"], "exclude": ["Animal-only studies"]}
        value["records"] = records if records is not None else [record()]
        save_ledger(self.ledger_path, value)
        return value

    def review(self, fulltext=False, complete=True):
        value = self.ledger()
        value["queries"] = [{"id": "q1", "round": 1, "source": "fixture", "query_string": "rural",
                             "run_at": "2026-09-19", "n_returned": 1}]
        paper = value["records"][0]
        paper["id"] = "paper-1"
        for stage in ("abstract", "fulltext"):
            paper["screening"][stage].update(
                decision="include", decided_by="human", reason="Approved", criteria_version=1,
            )
        self.write("ledger.json", value)
        source = {"record_id": "paper-1", "kind": "abstract", "limitation": "Full text unavailable"}
        if fulltext:
            atomic_write(self.root / "paper.pdf", b"%PDF synthetic fixture")
            self.write("extraction.json", {
                "schema_version": 1, "pdf_sha256": digest((self.root / "paper.pdf").read_bytes()),
                "extractor": "fixture", "pages": [{"page": 1, "text": TEXT}],
                "warnings": ["Reading order needs manual verification"],
            })
            source = {"record_id": "paper-1", "kind": "fulltext", "pdf": "paper.pdf", "extraction": "extraction.json"}
        self.write("sources.json", {"cutoff": "2026-09-19", "sources": [source]})
        self.approve()
        if not complete:
            return value
        finalize(self.root)
        snapshot = load_snapshot(self.root)
        context = {"audience": "Research peers", "resources": [{"id": "r1", "description": "Approved clinic data"}]}
        evidence = {
            "schema_version": 1, "handoff_revision": snapshot["handoff"]["revision"],
            "claims": [
                {"id": claim_id, "source_id": "paper-1", "page": 1, "quote": quote, "statement": quote,
                 "kind": kind, "verification": {"status": "supported", "reason": "Exact context supports the statement"},
                 "appraisal": "Observational only", "study_id": None}
                for claim_id, kind, quote in (
                    ("c1", "finding", "An association was found."),
                    ("c2", "gap", "Rural clinics remain untested."),
                    ("c3", "direction", "Future work should evaluate rural clinics."),
                )
            ],
            "findings": [{"id": "f1", "statement": "Association is not causation", "claim_ids": ["c1"],
                          "strength": "Observational", "disagreements": []}],
            "gaps": [{"id": "g1", "statement": "Rural clinics remain untested", "claim_ids": ["c2"],
                      "status": "open-in-reviewed-corpus",
                      "currency": {"checked_source_ids": ["paper-1"], "claim_ids": [], "rationale": "Corpus checked"}}],
            "opportunities": [{"id": "o1", "gap_id": "g1", "direction_claim_ids": ["c3"],
                               "feasibility": {"effort": "low", "rationale": "Data available", "prerequisites": ["Data"],
                                               "unknowns": [], "resource_ids": ["r1"]}}],
            "source_reviews": [{"source_id": "paper-1", "status": "reviewed", "note": "Complete source read"}],
        }
        save_context(snapshot, context)
        save_evidence(snapshot, evidence)
        return snapshot, deepcopy(evidence), context

    def approve(self):
        for gate in ("criteria", "triage", "curation"):
            approve_gate(self.root, gate, gate_fingerprint(self.root, gate))
