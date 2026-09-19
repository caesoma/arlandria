from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch
import xml.etree.ElementTree as ET

import evidence
import hypatia
import render
import slides
import storage
from support import ROOT, Sandbox


CLI = ROOT / "skills/hypatia/scripts/hypatia.py"


class OutputTests(Sandbox):
    def test_delivery_artifacts_share_provenance_and_cache_is_read_only(self):
        snapshot, document, context = self.review(fulltext=True)
        document["findings"][0]["disagreements"] = ["c2"]
        document["gaps"][0]["status"] = "partly-addressed"
        document["gaps"][0]["currency"]["claim_ids"] = ["c1"]
        evidence.save_evidence(snapshot, document)
        output = Path(render.render(snapshot))
        expected = {"report.md", "slides.tex", "brief.md", "evidence-matrix.svg", "opportunity-matrix.svg",
                    "gap-directions.svg", "review-flow.svg", "evidence.json", "context.json", "references.bib",
                    "references.csv", "provenance.json"}
        self.assertEqual({p.name for p in output.iterdir()}, expected)
        files = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.iterdir()}
        self.assertEqual(render.render(snapshot), str(output))
        self.assertEqual({p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.iterdir()}, files)
        self.assertEqual(storage.read_json(output / "evidence.json"), document)
        self.assertEqual(storage.read_json(output / "context.json"), context)
        provenance = storage.read_json(output / "provenance.json")
        self.assertEqual(provenance["handoff"], snapshot["handoff"])
        self.assertEqual(provenance["evidence_digest"], evidence.evidence_digest(snapshot))
        for svg in output.glob("*.svg"):
            root = ET.fromstring(svg.read_bytes())
            self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg")
            self.assertIn("aria-labelledby", root.attrib)
        report = (output / "report.md").read_text(encoding="utf-8")
        self.assertIn("PDF page 1", report)
        self.assertIn("[c2](#claim-c2)", report)
        deck = (output / "slides.tex").read_text(encoding="utf-8")
        self.assertEqual(deck.count(r"\begin{frame}"), 6)
        self.assertIn("PDF p. 1", deck)
        self.assertIn("partly-addressed", deck)

    def test_shortlist_requires_low_effort_and_current_open_gap(self):
        _, document, _ = self.review()
        for status in ("open-in-reviewed-corpus", "partly-addressed", "addressed", "unresolved"):
            for effort in ("low", "medium", "high", "unknown"):
                document["gaps"][0]["status"] = status
                document["opportunities"][0]["feasibility"]["effort"] = effort
                self.assertEqual(bool(slides.shortlist(document)),
                                 effort == "low" and status in ("open-in-reviewed-corpus", "partly-addressed"))

    def test_whole_entry_budgets_control_characters_and_unicode(self):
        self.assertEqual(slides.slide_text("α\n\tβ\0 ≤\x7f 5"), "α β ≤ 5")
        self.assertEqual(slides.tex(r"\{}$&#%_^~"), r"\textbackslash{}\{\}\$\&\#\%\_\textasciicircum{}\textasciitilde{}")
        result = slides.slide_list(["abcde", "fghij", "kl"], "Empty", budget=10, limit=3)
        self.assertIn(r"\item abcde", result)
        self.assertIn(r"\item fghij", result)
        self.assertNotIn(r"\item kl", result)
        self.assertIn("1 item(s) omitted", result)
        result = slides.slide_list(["x" * 71, "Short"], "Empty", budget=1000, limit=1)
        self.assertIn(r"\item Short", result)
        self.assertNotIn("x" * 71, result)
        self.assertIn("1 item(s) omitted", result)
        self.assertIn(r"\item Empty", slides.slide_list([], "Empty"))

    def test_unknowns_unreadable_sources_and_no_resources_remain_explicit(self):
        snapshot, document, context = self.review()
        for claim in document["claims"]:
            claim["verification"]["status"] = "uncertain"
            claim["study_id"] = "independent-study"
        document.update(findings=[], gaps=[], opportunities=[])
        document["source_reviews"][0].update(status="unreadable", note="Cannot verify transcription")
        context["resources"] = []
        evidence.save_context(snapshot, context)
        evidence.save_evidence(snapshot, document)
        output = Path(render.render(snapshot))
        for name in ("slides.tex", "report.md", "brief.md"):
            content = (output / name).read_text(encoding="utf-8")
            self.assertIn("uncertain", content)
        self.assertIn("unreadable", (output / "slides.tex").read_text(encoding="utf-8"))
        self.assertIn("No resources supplied", (output / "report.md").read_text(encoding="utf-8"))
        document["claims"] = []
        document["source_reviews"][0].update(status="reviewed")
        evidence.save_evidence(snapshot, document)
        self.assertNotEqual(render.render(snapshot), str(output))

    def test_markdown_svg_and_deck_escape_source_content(self):
        value = '<script>alert("x")</script> & _{}\\#'
        self.assertNotIn("<script>", render.md(value))
        svg = render.svg(value, value, [value, "long " * 80, ""])
        root = ET.fromstring(svg)
        self.assertEqual(root.findtext("{http://www.w3.org/2000/svg}title"), value)
        self.assertNotIn("<script>", svg)
        table = render.table_svg(value, value, [{"label": value, "width": 200}], [["a" * 80], [value], [""]])
        ET.fromstring(table)
        self.assertIn("&lt;script&gt;", table)
        self.assertEqual(render.wrap("", width=10), [""])
        self.assertEqual("".join(render.wrap("x" * 71, width=10)), "x" * 71)

    def test_io_and_mid_render_changes_do_not_publish_partial_delivery(self):
        snapshot, document, _ = self.review()
        first = Path(render.render(snapshot))
        directory = evidence.evidence_directory(snapshot)
        pointer = (directory / "delivery.json").read_bytes()
        document["findings"][0]["strength"] = "Changed"
        evidence.save_evidence(snapshot, document)
        with patch.object(render, "beamer", side_effect=OSError("disk failure")), self.assertRaisesRegex(OSError, "disk failure"):
            render.render(snapshot)
        self.assertEqual((directory / "delivery.json").read_bytes(), pointer)
        with patch.object(render, "evidence_digest", side_effect=["a" * 64, "b" * 64]), self.assertRaisesRegex(ValueError, "Evidence changed"):
            render.render(snapshot)
        self.assertEqual((directory / "delivery.json").read_bytes(), pointer)
        self.assertTrue((first / "slides.tex").is_file())
        self.assertEqual(len([p for p in (directory / "exports").iterdir() if not p.name.endswith(".partial")]), 1)


class CliTests(Sandbox):
    def test_all_cli_operations_dispatch_to_real_review_behavior(self):
        snapshot, document, context = self.review()
        revision = snapshot["handoff"]["revision"]
        covered = set()

        def run(operation, payload=None):
            covered.add(operation)
            return hypatia.execute(operation, self.root, revision, payload or {})

        self.assertEqual(run("prepare"), str(self.root))
        self.assertIsNone(run("request-read"))
        run("request-write", {"status": "synthesizing", "question": "Question"})
        run("pause", {"question": "Paused question"})
        self.assertEqual(run("request-read")["status"], "paused")
        fingerprint = run("gate-fingerprint", {"gate": "criteria"})
        run("approve-gate", {"gate": "criteria", "fingerprint": fingerprint})
        self.assertEqual(run("load-snapshot"), snapshot)
        self.assertEqual(run("snapshot")["context"], context)
        self.assertEqual(run("source", {"source_id": "paper-1", "page": 1, "offset": 0})["pages"], 1)
        self.assertEqual(run("context"), context)
        run("context-save", context)
        self.assertEqual(run("evidence"), document)
        self.assertIsInstance(run("save", document), str)
        self.assertEqual(run("validate", {"evidence": document, "context": context}), document)
        self.assertEqual(run("evidence-digest"), evidence.evidence_digest(snapshot))
        self.assertTrue(Path(run("render")).exists())
        self.assertEqual(run("evidence-directory"), str(evidence.evidence_directory(snapshot)))
        self.assertEqual(run("inside", {"path": "nested/file"}), str(self.root / "nested/file"))
        self.assertEqual(run("shortlist", document), document["opportunities"])
        self.assertIn(r"\begin{document}", run("beamer", {"snapshot": snapshot, "evidence": document, "context": context}))
        self.assertEqual(run("schema", {"name": "Evidence"})["type"], "object")
        with self.assertRaisesRegex(ValueError, "Unknown operation"):
            run("not-an-operation")
        (evidence.evidence_directory(snapshot) / "context.json").unlink()
        self.assertIsNone(run("context"))
        (evidence.evidence_directory(snapshot) / "evidence.json").unlink()
        self.assertEqual(run("evidence")["claims"], [])
        self.assertNotEqual(run("finalize"), revision)
        self.assertEqual(covered - {"not-an-operation"}, set(hypatia.OPERATIONS))

    def test_cli_json_input_file_stdin_and_machine_readable_errors(self):
        input_file = self.write("input.json", {"name": "Context"})
        success = subprocess.run([sys.executable, str(CLI), "schema", "--input", str(input_file)], capture_output=True)
        self.assertEqual(success.returncode, 0, success.stderr)
        self.assertEqual(json.loads(success.stdout)["type"], "object")
        for args, payload in (
            (["render"], {}),
            (["render", str(self.root)], {}),
            (["schema"], {"name": "Unknown"}),
            (["inside", str(self.root)], {"path": 123}),
            (["schema", "--input", str(self.root / "missing")], {}),
        ):
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, str(CLI), *args], input=json.dumps(payload).encode(), capture_output=True)
                self.assertEqual(result.returncode, 1)
                self.assertTrue(json.loads(result.stdout)["error"])
                self.assertEqual(result.stderr, b"")
        output = io.BytesIO()
        with patch.object(sys, "stdin", SimpleNamespace(isatty=lambda: True)), patch.object(
            sys, "stdout", SimpleNamespace(buffer=output),
        ), patch.object(sys, "argv", ["hypatia", "prepare", str(self.root)]):
            hypatia.main()
        self.assertEqual(json.loads(output.getvalue()), str(self.root))

    def test_unknown_effort_is_not_replaced_by_optimistic_defaults(self):
        snapshot, document, context = self.review()
        revised = deepcopy(document)
        revised["gaps"][0]["status"] = "unresolved"
        revised["opportunities"][0]["feasibility"].update(effort="unknown", prerequisites=[], resource_ids=[], unknowns=["Cost"])
        context["resources"] = []
        evidence.save_context(snapshot, context)
        evidence.save_evidence(snapshot, revised)
        directory = Path(render.render(snapshot))
        report = (directory / "report.md").read_text(encoding="utf-8")
        self.assertIn("**unknown**", report)
        self.assertIn("No directions can currently be shortlisted", report)
        self.assertIn("Unknowns: Cost", report)
