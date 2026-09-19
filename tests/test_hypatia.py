from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from handoff import approve_gate, finalize, gate_fingerprint, load_snapshot
from hypatia import execute
from schema import SCHEMAS, parse
from slides import beamer
from storage import atomic_write, inside, json_text


ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "skills/hypatia/scripts/hypatia.py"


class StandaloneHypatiaTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.review = self.home / "review with spaces"
        self.review.mkdir()
        self.env = patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def empty_review(self):
        ledger = {
            "review_id": "empty-review", "question": "Are there any eligible papers?",
            "criteria": {"version": 1, "include": ["café α ≤ 5%"], "exclude": ["Not eligible"]},
            "queries": [{
                "id": "q1", "round": 1, "source": "fixture", "query_string": "fixture",
                "run_at": "2026-09-19", "n_returned": 0,
            }], "records": [],
        }
        atomic_write(self.review / "ledger.json", json_text(ledger))
        atomic_write(self.review / "sources.json", json_text({"cutoff": "2026-09-19", "sources": []}))
        for gate in ("criteria", "triage", "curation"):
            approve_gate(self.review, gate, gate_fingerprint(self.review, gate))
        revision = finalize(self.review)
        context = {"audience": "Peers", "resources": []}
        execute("context-save", self.review, revision, context)
        evidence = execute("evidence", self.review, revision, {})
        execute("save", self.review, revision, evidence)
        return revision, evidence, context

    def test_python_only_review_lifecycle_and_historical_deliveries(self):
        revision, evidence, context = self.empty_review()
        original = (self.review / "ledger.json").read_bytes()
        result = subprocess.run(
            [sys.executable, str(CLI), "render", str(self.review), "--revision", revision],
            cwd=self.home, input=b"", capture_output=True, check=True,
            env={**os.environ, "PATH": ""},
        )
        output = Path(json.loads(result.stdout))
        self.assertEqual((output / "slides.tex").read_text(encoding="utf-8").count(r"\begin{frame}"), 6)
        self.assertIn("No supported findings", (output / "report.md").read_text(encoding="utf-8"))
        context["audience"] = "Different audience"
        execute("context-save", self.review, revision, context)
        second = execute("render", self.review, revision, {})
        self.assertNotEqual(str(output), second)
        self.assertIn("Audience: Peers", (output / "report.md").read_text(encoding="utf-8"))
        self.assertEqual(original, (self.review / "ledger.json").read_bytes())
        self.assertEqual(json.loads((output / "evidence.json").read_bytes()), evidence)

    def test_failed_delivery_does_not_publish_or_replace_previous_output(self):
        revision, evidence, _ = self.empty_review()
        output = execute("render", self.review, revision, {})
        pointer = inside(self.review, f".hypatia/{revision}/delivery.json")
        before = pointer.read_bytes()
        evidence["source_reviews"] = [{"source_id": "outside", "status": "reviewed", "note": "Invalid"}]
        with self.assertRaisesRegex(ValueError, "Invalid source review"):
            execute("save", self.review, revision, evidence)
        self.assertEqual(pointer.read_bytes(), before)
        self.assertTrue((Path(output) / "slides.tex").exists())

    def test_standalone_schema_validates_without_modifying_input(self):
        for name, schema in SCHEMAS.items():
            with self.subTest(name=name):
                self.assertEqual(schema["type"], "object")
        context = {"audience": "Peers", "resources": [{"id": "r1", "description": "Data"}]}
        before = deepcopy(context)
        self.assertEqual(parse("Context", context), before)
        self.assertEqual(context, before)
        with self.assertRaisesRegex(ValueError, "Invalid data"):
            parse("Context", {**context, "unexpected": True})

    def test_tex_metacharacters_cannot_add_frames_or_commands(self):
        revision, evidence, context = self.empty_review()
        snapshot = load_snapshot(self.review, revision)
        snapshot["ledger"]["criteria"]["include"] = [r"α ≤ 5% \end{frame} ^^5cinput{file} & # _ $"]
        deck = beamer(snapshot, evidence, context)
        self.assertEqual(deck.count(r"\begin{frame}"), 6)
        self.assertEqual(deck.count(r"\end{frame}"), 6)
        self.assertIn(r"\textbackslash{}end\{frame\}", deck)
        self.assertIn(r"α ≤ 5\%", deck)
        self.assertNotIn(r"\input{file}", deck)

    def test_broken_symlink_is_rejected_before_writing(self):
        alias = self.review / ".hypatia"
        try:
            alias.symlink_to(self.home / "missing-directory", target_is_directory=True)
        except OSError:
            self.skipTest("This host does not allow creating symlinks")
        with self.assertRaisesRegex(ValueError, "Symlinks"):
            execute("prepare", self.review, None, {})
        self.assertFalse((self.home / "missing-directory").exists())

    def test_cli_failure_is_machine_readable_and_nonzero(self):
        result = subprocess.run(
            [sys.executable, str(CLI), "render", str(self.review)],
            input=b"{malformed", capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIsInstance(json.loads(result.stdout)["error"], str)
        self.assertEqual(result.stderr, b"")


if __name__ == "__main__":
    unittest.main()
