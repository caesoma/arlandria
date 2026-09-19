from contextlib import redirect_stdout
from copy import deepcopy
import csv
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

import _common as common
import dedupe
import export as exports
import ledger
import pdf_extract
import resolve
from support import ROOT, Sandbox, record, run_main


class CommonTests(Sandbox):
    def test_normalization_keeps_unicode_metadata_and_stable_identity(self):
        self.assertEqual(common.canonical_doi("https://doi.org/10.1/ABC"), "10.1/abc")
        self.assertEqual(common.canonical_doi("http://dx.doi.org/10.1/ABC"), "10.1/abc")
        for year, expected in [(2025, 2025), ("2025-01-01", 2025), ("", None), (None, None), ("bad", None)]:
            self.assertEqual(common.search_record(year=year)["year"], expected)
        self.assertEqual(common.norm_title("  Café! α "), "cafe")
        self.assertEqual(record(title="CAFÉ study")["id"], record(title="cafe-study")["id"])
        first, second = record(), record()
        first["screening"]["abstract"]["decision"] = "include"
        self.assertEqual(second["screening"]["abstract"]["decision"], "unscreened")
        enriched = record(doi="10.1/X", arxiv_id="123", pmid="456", raw_id="W1", oa_status="closed")
        self.assertEqual(enriched["ids"], {"arxiv": "123", "pmid": "456", "fixture": "W1"})
        self.assertFalse(enriched["oa"]["is_oa"])
        self.assertTrue(record(oa_status="green")["oa"]["is_oa"])
        self.assertEqual(common.ledger_entry({})["sources"], [])

    def test_utf8_ledger_roundtrip_review_names_and_derived_statistics(self):
        value = self.ledger([record(), record(title="Second"), record(title="Third")])
        value["records"][0]["screening"]["abstract"]["decision"] = "include"
        value["records"][1]["screening"]["fulltext"]["decision"] = "include"
        value["records"][2]["screening"]["fulltext"]["decision"] = "not_applicable"
        value["records"][2]["status"] = "deferred"
        common.recompute_stats(value)
        common.save_ledger(self.ledger_path, value)
        self.assertEqual(common.load_ledger(self.ledger_path), value)
        self.assertIn("Café α".encode(), self.ledger_path.read_bytes())
        self.assertEqual(value["review_id"], "review")
        self.assertEqual(common.load_ledger(self.root / "distinct.json")["review_id"], "distinct")
        self.assertEqual(value["stats"], {"found": 0, "deduped": 3, "screened_abstract": 1,
                                         "included_abstract": 1, "screened_fulltext": 1,
                                         "included_fulltext": 1, "deferred": 1})

    def test_dotenv_does_not_override_exported_values(self):
        (self.home / ".env").write_text("# comment\nARLANDRIA_TEST_VALUE='café'\nEXISTING=ignored\nbad\n", encoding="utf-8")
        with patch("pathlib.Path.cwd", return_value=self.home), patch.dict(os.environ, {"EXISTING": "kept"}, clear=True):
            common._load_dotenv()
            self.assertEqual(os.environ["ARLANDRIA_TEST_VALUE"], "café")
            self.assertEqual(os.environ["EXISTING"], "kept")

    def test_http_rate_limit_backoff_headers_and_timeout(self):
        limited = Mock(status_code=429)
        success = Mock(status_code=200)
        with patch.object(common.requests, "get", side_effect=[limited, limited, success]) as get, patch.object(common.time, "sleep") as sleep:
            self.assertIs(common.get("https://fixture.invalid", {"q": "x"}, {"x-api-key": "fixture"}), success)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])
        self.assertEqual(get.call_args.kwargs["timeout"], common.HTTP_TIMEOUT_SECONDS)
        self.assertIn("mailto:", get.call_args.kwargs["headers"]["User-Agent"])
        self.assertEqual(get.call_args.kwargs["headers"]["x-api-key"], "fixture")

    def test_http_exhaustion_and_non_retryable_failures(self):
        for status in (429, 503):
            response = Mock(status_code=status)
            response.raise_for_status.side_effect = requests.HTTPError(str(status))
            with patch.object(common.requests, "get", return_value=response) as get, patch.object(common.time, "sleep"), self.assertRaises(requests.HTTPError):
                common.get("https://fixture.invalid")
            self.assertEqual(get.call_count, 3 if status == 429 else 1)
        with redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit) as error:
            common.die("café failure")
        self.assertEqual(error.exception.code, 1)
        self.assertEqual(json.loads(output.getvalue()), {"error": "café failure"})


class LedgerTests(Sandbox):
    def test_all_commands_keep_human_override_and_criteria_history(self):
        value = self.ledger()
        rid = value["records"][0]["id"]
        for include in ("Relevant", "New criteria"):
            run_main(ledger.main, "criteria", "--ledger", self.ledger_path, "--include", include, "--question", "Question?")
        self.assertEqual(self.read()["criteria"]["version"], 3)
        self.assertEqual(len(self.read()["criteria"]["history"]), 2)
        run_main(ledger.main, "decide", "--ledger", self.ledger_path, "--id", rid, "--stage", "abstract",
                 "--decision", "include", "--by", "llm", "--relevance", "high", "--reason", "Initial",
                 "--covers", "rural", "--summary", "Summary")
        run_main(ledger.main, "decide", "--ledger", self.ledger_path, "--id", rid, "--stage", "abstract",
                 "--decision", "exclude", "--by", "human", "--reason", "Out of scope")
        before = self.ledger_path.read_bytes()
        result = json.loads(run_main(ledger.main, "decide", "--ledger", self.ledger_path, "--id", rid,
                                    "--stage", "abstract", "--decision", "include", "--by", "llm"))
        self.assertTrue(result["locked"])
        self.assertEqual(before, self.ledger_path.read_bytes())
        decision = self.read()["records"][0]["screening"]["abstract"]
        self.assertEqual(decision["proposed"], {"decision": "include", "reason": "Initial", "relevance": "high"})
        for status in ("deferred", "active"):
            run_main(ledger.main, "status", "--ledger", self.ledger_path, "--id", rid, "missing", "--status", status)
            self.assertEqual(self.read()["records"][0]["status"], status)
        for text in ("First discussion", "Revised"):
            run_main(ledger.main, "note", "--ledger", self.ledger_path, "--gate", "criteria", "--text", text)
        self.assertEqual([e["text"] for e in self.read()["exchanges"]], ["First discussion", "Revised"])

    def test_errors_never_rewrite_ledger(self):
        value = self.ledger()
        before = self.ledger_path.read_bytes()
        for rid, stage in (("unknown", "abstract"), (value["records"][0]["id"], "fulltext")):
            result = json.loads(run_main(ledger.main, "decide", "--ledger", self.ledger_path, "--id", rid,
                                        "--stage", stage, "--decision", "borderline", "--by", "human"))
            self.assertIn("error", result)
            self.assertEqual(before, self.ledger_path.read_bytes())
        result = ledger.cmd_criteria(value, SimpleNamespace(include=None, exclude=None, question=None))
        self.assertEqual(result["question"], "What is established?")

    def test_cli_under_ascii_locale_roundtrips_non_ascii_json(self):
        self.ledger()
        result = subprocess.run(
            [sys.executable, str(ROOT / "skills/callimachus/scripts/ledger.py"), "criteria", "--ledger",
             str(self.ledger_path), "--include", "Relevant"],
            capture_output=True, env={**os.environ, "LC_ALL": "C", "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read()["records"][0]["title"], "Café α research")


class DedupeTests(Sandbox):
    def ingest(self, records, *args):
        path = self.write("search.json", {"source": "fixture", "query": "rural", "n": len(records), "records": records})
        return json.loads(run_main(dedupe.main, "--ledger", self.ledger_path, "--in", path, *args))

    def test_all_identity_tiers_and_version_of_record_upgrade(self):
        for field, identifier in (("doi", "10.1/x"), ("arxiv_id", "123"), ("pmid", "42")):
            with self.subTest(field=field):
                self.ledger([])
                records = [common.search_record(title=title, year=2025, **{field: identifier}) for title in ("One", "Different")]
                self.assertEqual(self.ingest(records)["deduped_total"], 1)
        self.ledger([])
        preprint = common.search_record(title="Café study", year=2025, arxiv_id="123", source_backend="arxiv", raw_id="123")
        self.ingest([preprint])
        value = self.read()
        value["records"][0]["screening"]["abstract"]["decision"] = "include"
        self.write("ledger.json", value)
        published = common.search_record(title="Cafe study", year=2025, doi="10.1/VOR", source_backend="openalex",
                                        raw_id="W1", abstract="New abstract", venue="Journal", oa_status="gold",
                                        cited_by_count=9, referenced_works=["W2"], pdf_url="https://fixture.invalid/paper.pdf")
        self.ingest([published, published])
        result = self.read()
        paper = result["records"][0]
        self.assertEqual(paper["id"], value["records"][0]["id"])
        self.assertEqual(paper["doi"], "10.1/vor")
        self.assertEqual(paper["screening"]["abstract"]["decision"], "include")
        self.assertEqual(paper["sources"], ["arxiv", "openalex"])
        self.assertEqual(paper["ids"], {"arxiv": "123", "openalex": "W1"})
        self.assertEqual(paper["citations"], 9)
        self.assertEqual(paper["referenced_works"], ["W2"])
        self.assertTrue(paper["oa"]["is_oa"])
        self.assertEqual([q["round"] for q in result["queries"]], [1, 2])
        self.assertEqual(result["stats"]["found"], 3)

    def test_backfill_missing_metadata_without_clobbering_existing_data(self):
        original = record(title="Stable", year=None)
        incoming = record(title="Replacement", year=2024, abstract="Other", venue="Journal", cited_by_count=5,
                          oa_status="green", pdf_url="https://fixture.invalid", referenced_works=["ref"])
        dedupe.merge(original, incoming)
        self.assertEqual(original["title"], "Stable")
        self.assertEqual(original["year"], 2024)
        self.assertEqual(original["venue"], "Journal")
        self.assertEqual(original["citations"], 5)
        self.assertEqual(original["oa_status"], "green")
        self.assertEqual(original["referenced_works"], ["ref"])

    def test_exclude_known_skips_only_previously_screened_records(self):
        decided = record(doi="10.1/known", arxiv_id="123", pmid="42")
        decided["screening"]["abstract"]["decision"] = "exclude"
        prior = self.write("prior.json", {"records": [decided, record(title="Unscreened")]})
        self.ledger([])
        output = self.ingest([
            common.search_record(doi="10.1/known"),
            common.search_record(title=decided["title"], year=decided["year"]),
            common.search_record(title="Unscreened"),
        ], "--exclude-known", prior)
        self.assertEqual(output, {"found_this_run": 3, "skipped_known": 2, "deduped_total": 1})
        self.assertEqual(self.read()["records"][0]["title"], "Unscreened")

    def test_dedupe_script_runs_as_a_real_cli(self):
        path = self.write("search.json", {"source": "fixture", "query": "q", "n": 0, "records": []})
        subprocess.run([sys.executable, str(ROOT / "skills/callimachus/scripts/dedupe.py"),
                        "--ledger", str(self.ledger_path), "--in", str(path)], capture_output=True, check=True)
        self.assertEqual(self.read()["records"], [])


class ExportTests(Sandbox):
    def test_effective_include_truth_table_and_csv_provenance(self):
        for status in ("active", "deferred"):
            for abstract in ("include", "exclude", "borderline", "unscreened"):
                for fulltext in ("include", "exclude", "unscreened"):
                    paper = record()
                    paper["status"] = status
                    paper["screening"]["abstract"]["decision"] = abstract
                    paper["screening"]["fulltext"].update(decision=fulltext, decided_by="human")
                    expected = status == "active" and (fulltext == "include" or fulltext == "unscreened" and abstract == "include")
                    self.assertEqual(bool(exports.effective_include({"records": [paper]})), expected)
        for stage in ("abstract", "fulltext"):
            paper = record(doi="10.1/x", title='Café, "study"\nsecond line')
            paper["screening"][stage].update(decision="include", decided_by="human")
            paper["assessment"]["covers"] = ["a", "b"]
            output = io.StringIO()
            exports.write_export(output, "csv", [paper])
            row = list(csv.DictReader(io.StringIO(output.getvalue())))[0]
            self.assertEqual(row["title"], paper["title"])
            self.assertEqual(row["decided_by"], "human")
            self.assertEqual(row["covers"], "a; b")

    def test_bibtex_identifier_fallbacks_and_empty_fields(self):
        self.assertIn("@article{42,", exports.bibtex([record(pmid="42", doi="10.1/x")]))
        self.assertIn("@article{10.1_x,", exports.bibtex([record(doi="10.1/x")]))
        paper = record(title=None, authors=None, year=None)
        self.assertIn(f"@article{{{paper['id']},", exports.bibtex([paper]))
        self.assertIn("title={}", exports.bibtex([paper]))
        self.assertEqual(exports.bibtex([]), "")

    def test_export_modes_do_not_change_the_ledger(self):
        paper = record()
        paper["screening"]["abstract"]["decision"] = "include"
        self.ledger([paper])
        original = self.ledger_path.read_bytes()
        for fmt in ("csv", "bibtex"):
            content = run_main(exports.main, "--ledger", self.ledger_path, "--format", fmt, "--stdout")
            default = Path(run_main(exports.main, "--ledger", self.ledger_path, "--format", fmt).strip())
            override = Path(run_main(exports.main, "--ledger", self.ledger_path, "--format", fmt,
                                     "--out-dir", self.home / "exports").strip())
            self.assertEqual(default.read_bytes(), override.read_bytes())
            self.assertEqual(default.read_text(encoding="utf-8"), content.replace("\r\n", "\n"))
        self.assertEqual(self.ledger_path.read_bytes(), original)
        result = subprocess.run([sys.executable, str(ROOT / "skills/callimachus/scripts/export.py"), "--ledger",
                                 str(self.ledger_path)], capture_output=True, env={**os.environ, "PYTHONUTF8": "0", "LC_ALL": "C"})
        self.assertEqual(result.returncode, 0, result.stderr)


class ResolveTests(Sandbox):
    def resolve(self):
        return json.loads(run_main(resolve.main, "--ledger", self.ledger_path, "--id", self.read()["records"][0]["id"]))

    def test_unpaywall_and_crossref_backfill_preserve_screening(self):
        self.ledger([record(doi="10.1/x", abstract=None, venue=None)])
        before = deepcopy(self.read()["records"][0]["screening"])
        with patch.object(resolve, "get", side_effect=[
            Mock(json=lambda: {"is_oa": True, "oa_status": "gold", "best_oa_location": {"url_for_pdf": "https://fixture.invalid/pdf"}}),
            Mock(json=lambda: {"message": {"abstract": "<jats:p>Useful <b>result</b></jats:p>", "container-title": ["Journal"]}}),
        ]):
            result = self.resolve()
        self.assertEqual(result["url"], "https://fixture.invalid/pdf")
        paper = self.read()["records"][0]
        self.assertEqual(paper["abstract"], "Useful result")
        self.assertEqual(paper["venue"], "Journal")
        self.assertEqual(paper["screening"], before)

    def test_resolution_failure_retains_metadata_and_known_legal_url(self):
        self.ledger([record(doi="10.1/x", pdf_url="https://fixture.invalid/known")])
        with patch.object(resolve, "get", side_effect=requests.ConnectionError("offline")):
            result = self.resolve()
        self.assertEqual(result["url"], "https://fixture.invalid/known")
        self.assertEqual(len(result["warnings"]), 2)
        self.assertEqual(len(self.read()["records"]), 1)

    def test_closed_no_doi_and_missing_record(self):
        self.ledger([record(oa_status="closed")])
        with patch.object(resolve, "get") as get:
            result = self.resolve()
        get.assert_not_called()
        self.assertEqual(result["fulltext"], "closed, metadata-only")
        before = self.ledger_path.read_bytes()
        self.assertIn("error", json.loads(run_main(resolve.main, "--ledger", self.ledger_path, "--id", "missing")))
        self.assertEqual(before, self.ledger_path.read_bytes())
        subprocess.run([sys.executable, str(ROOT / "skills/callimachus/scripts/resolve.py"), "--ledger",
                        str(self.ledger_path), "--id", "missing"], capture_output=True, check=True)

    def test_partial_metadata_and_landing_page_fallbacks(self):
        self.ledger([record(doi="10.1/x", abstract=None, venue=None)])
        with patch.object(resolve, "get", side_effect=[
            Mock(json=lambda: {"best_oa_location": {"url": "https://fixture.invalid/landing"}}),
            Mock(json=lambda: {"message": {"abstract": "<p></p>"}}),
        ]):
            result = self.resolve()
        self.assertEqual(result["url"], "https://fixture.invalid/landing")
        self.assertIsNone(self.read()["records"][0]["abstract"])


class PdfTests(Sandbox):
    def test_real_pdf_plain_structured_and_sidecar_output(self):
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 20 200 Td (Research evidence) Tj ET")
        page[NameObject("/Contents")] = stream
        writer.add_blank_page(width=300, height=300)
        path = self.root / "paper.pdf"
        writer.write(path)
        text = run_main(pdf_extract.main, "--pdf", path)
        self.assertIn("Research evidence", text)
        structured = json.loads(run_main(pdf_extract.main, "--pdf", path, "--structured"))
        self.assertEqual([p["page"] for p in structured["pages"]], [1, 2])
        self.assertEqual(structured["pages"][1]["text"], "")
        self.assertTrue(any("OCR" in w for w in structured["warnings"]))
        sidecar = self.root / "text.txt"
        run_main(pdf_extract.main, "--pdf", path, "--out", sidecar)
        self.assertEqual(sidecar.read_text(encoding="utf-8"), text)
        subprocess.run([sys.executable, str(ROOT / "skills/callimachus/scripts/pdf_extract.py"), "--pdf", str(path)],
                       capture_output=True, check=True)

    def test_missing_and_invalid_pdf_fail_without_sidecar(self):
        for name, raw in (("missing.pdf", None), ("invalid.pdf", b"not a PDF")):
            if raw:
                (self.root / name).write_bytes(raw)
            result = subprocess.run(
                [sys.executable, str(ROOT / "skills/callimachus/scripts/pdf_extract.py"),
                 "--pdf", str(self.root / name), "--out", str(self.root / "out.txt")], capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.root / "out.txt").exists())
