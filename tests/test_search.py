from contextlib import redirect_stdout
import io
import json
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from defusedxml.common import EntitiesForbidden
import requests

import search
from support import ROOT, Sandbox, run_main


def options(**values):
    return SimpleNamespace(**{"limit": 50, "since": None, "filter": None, "no_api_key": True, **values})


ATOM = """<feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>https://arxiv.org/abs/1234.5678v2</id><title> Café study </title>
<published>2026-08-01T00:00:00Z</published><summary>Useful evidence</summary><author><name>Renée</name></author></entry>
<entry><id>https://arxiv.org/abs/old</id><published>2024-01-01</published></entry></feed>"""


class SearchTests(Sandbox):
    def test_openalex_normalizes_closed_work_and_uses_key_filter_and_cost(self):
        work = {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/ABC", "title": "Café",
                "abstract_inverted_index": {"result": [1, 3], "A": [0], "another": [2]},
                "authorships": [{"author": {"display_name": "Renée"}}], "publication_year": 2025,
                "primary_location": {"source": {"display_name": "Journal"}}, "open_access": {"oa_status": "closed"},
                "referenced_works": ["https://openalex.org/W2"], "cited_by_count": 7}
        with patch.dict(os.environ, {"OPENALEX_API_KEY": "synthetic"}), patch.object(
            search, "get", return_value=Mock(json=lambda: {"results": [work], "meta": {"cost_usd": 0.01}}),
        ) as get:
            papers, meta = search.openalex("q", options(limit=999, since="2026-01-01", filter="type:article", no_api_key=False))
        params = get.call_args.args[1]
        self.assertEqual(params["per-page"], 200)
        self.assertEqual(params["api_key"], "synthetic")
        self.assertEqual(params["filter"], "from_publication_date:2026-01-01,type:article")
        self.assertNotIn("is_oa", params["filter"])
        self.assertEqual(papers[0]["abstract"], "A result another result")
        self.assertEqual(papers[0]["doi"], "10.1/abc")
        self.assertEqual(papers[0]["oa_status"], "closed")
        self.assertEqual(papers[0]["referenced_works"], ["W2"])
        self.assertEqual(meta, {"cost_usd": 0.01})

    def test_openalex_keyless_missing_key_and_pdf_priority(self):
        with patch.dict(os.environ, {}, clear=True), redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit):
            search.openalex("q", options(no_api_key=False))
        self.assertIn("OPENALEX_API_KEY", json.loads(output.getvalue())["error"])
        for location, oa, expected in (
            ({"pdf_url": "pdf", "landing_page_url": "landing"}, {"oa_url": "oa"}, "pdf"),
            ({"landing_page_url": "landing"}, {"oa_url": "oa"}, "landing"),
            (None, {"oa_url": "oa"}, "oa"), (None, None, None),
        ):
            with patch.object(search, "get", return_value=Mock(json=lambda: {
                "results": [{"best_oa_location": location, "open_access": oa}],
            })) as get:
                records, meta = search.openalex("q", options())
            self.assertEqual(records[0]["pdf_url"], expected)
            self.assertEqual(meta, {})
            self.assertNotIn("api_key", get.call_args.args[1])
            self.assertIsNone(records[0]["abstract"])

    def test_arxiv_filters_dates_and_retains_versioned_identity(self):
        with patch.object(search, "get", return_value=Mock(text=ATOM)) as get:
            papers = search.arxiv("q", options(since="2026-01-01"))
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["arxiv_id"], "1234.5678v2")
        self.assertEqual(papers[0]["authors"], ["Renée"])
        self.assertEqual(papers[0]["year"], 2026)
        self.assertEqual(get.call_args.args[1]["sortOrder"], "descending")
        with patch.object(search, "get", return_value=Mock(text=ATOM)):
            self.assertEqual(len(search.arxiv("q", options())), 2)

    def test_rxiv_date_requirement_and_limit_for_both_servers(self):
        for backend in (search.biorxiv, search.medrxiv):
            with redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit):
                backend("q", options())
            self.assertIn("--since", json.loads(output.getvalue())["error"])
            collection = [
                {"title": "Unrelated"}, {"title": "RURAL", "abstract": "clinic result", "doi": "10.1/x",
                                       "authors": "A; B; ", "date": "2026-01-01"},
                {"title": "Rural clinic", "doi": None},
            ]
            with patch.object(search, "get", return_value=Mock(json=lambda: {"collection": collection})):
                papers = backend("rural clinic", options(since="2026-01-01", limit=1))
            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0]["authors"], ["A", "B"])
            self.assertIn(backend.__name__, papers[0]["pdf_url"])
            with patch.object(search, "get", return_value=Mock(json=lambda: {"collection": collection})):
                self.assertIsNone(backend("rural clinic", options(since="2026-01-01"))[1]["pdf_url"])

    def test_rxiv_pagination_is_bounded_and_stops_at_last_page(self):
        full_page = [{"title": "unrelated"}] * 100
        with patch.object(search, "get", return_value=Mock(json=lambda: {"collection": full_page})) as get:
            self.assertEqual(search.biorxiv("wanted", options(since="2026-01-01")), [])
        self.assertEqual(get.call_count, 5)
        self.assertEqual([call.args[0].rsplit("/", 1)[1] for call in get.call_args_list], ["0", "100", "200", "300", "400"])
        with patch.object(search, "get", side_effect=[
            Mock(json=lambda: {"collection": full_page}),
            Mock(json=lambda: {"collection": [{"title": "wanted"}]}),
        ]) as get:
            self.assertEqual(len(search.biorxiv("wanted", options(since="2026-01-01"))), 1)
        self.assertEqual(get.call_count, 2)

    def test_europepmc_keeps_closed_records_and_selects_pdf(self):
        papers = [
            {"id": "1", "pmid": "42", "doi": "10.1/X", "title": "Café", "pubYear": "2025",
             "authorList": {"author": [{"fullName": "Renée"}]}, "isOpenAccess": "N",
             "fullTextUrlList": {"fullTextUrl": [{"documentStyle": "html", "url": "html"}, {"documentStyle": "pdf", "url": "pdf"}]}},
            {"id": "2", "isOpenAccess": "Y"}, {"id": "3"},
        ]
        with patch.object(search, "get", return_value=Mock(json=lambda: {"resultList": {"result": papers}})) as get:
            output = search.europepmc("q", options(limit=500))
        self.assertEqual(get.call_args.args[1]["pageSize"], 100)
        self.assertEqual([r["oa_status"] for r in output], ["closed", "open", None])
        self.assertEqual(output[0]["pdf_url"], "pdf")
        self.assertEqual(output[0]["year"], 2025)

    def test_pubmed_batches_metadata_and_preserves_inline_abstract_text(self):
        xml = "<PubmedArticleSet><PubmedArticle><PMID>42</PMID><Abstract><AbstractText>Alpha <i>beta</i> gamma.</AbstractText><AbstractText>Second section.</AbstractText></Abstract></PubmedArticle></PubmedArticleSet>"
        with patch.object(search, "get", side_effect=[
            Mock(json=lambda: {"esearchresult": {"idlist": ["42", "43"]}}),
            Mock(json=lambda: {"result": {"42": {"title": "Result", "authors": [{"name": "Author"}],
                                                    "articleids": [{"idtype": "doi", "value": "10.1/X"}], "pubdate": "2025 Jan"}}}),
            Mock(text=xml),
        ]) as get:
            papers = search.pubmed("q", options())
        self.assertEqual(get.call_count, 3)
        self.assertEqual(get.call_args.args[1]["id"], "42,43")
        self.assertEqual(papers[0]["abstract"], "Alpha beta gamma. Second section.")
        self.assertEqual(papers[0]["doi"], "10.1/x")
        self.assertIsNone(papers[1]["abstract"])
        with patch.object(search, "get", return_value=Mock(json=lambda: {"esearchresult": {"idlist": []}})) as get:
            self.assertEqual(search.pubmed("q", options()), [])
        self.assertEqual(get.call_count, 1)

    def test_semantic_scholar_optional_key_and_identifiers(self):
        for env, expected in (({}, None), ({"S2_API_KEY": "fixture"}, {"x-api-key": "fixture"})):
            with patch.dict(os.environ, env, clear=True), patch.object(search, "get", return_value=Mock(json=lambda: {
                "data": [{"paperId": "p1", "externalIds": {"DOI": "10.1/X", "ArXiv": "123"},
                          "authors": [{"name": "Author"}]}, {"paperId": "p2", "externalIds": None}],
            })) as get:
                papers = search.semantic_scholar("q", options(limit=500))
            self.assertEqual(get.call_args.kwargs["headers"], expected)
            self.assertEqual(get.call_args.args[1]["limit"], 100)
            self.assertEqual(papers[0]["arxiv_id"], "123")
            self.assertIsNone(papers[1]["doi"])

    def test_untrusted_xml_entities_are_rejected_by_both_xml_backends(self):
        xml = '<!DOCTYPE root [<!ENTITY content "untrusted">]><root>&content;</root>'
        with patch.object(search, "get", return_value=Mock(text=xml)), self.assertRaises(EntitiesForbidden):
            search.arxiv("q", options())
        with patch.object(search, "get", side_effect=[
            Mock(json=lambda: {"esearchresult": {"idlist": ["42"]}}),
            Mock(json=lambda: {"result": {}}), Mock(text=xml),
        ]), self.assertRaises(EntitiesForbidden):
            search.pubmed("q", options())

    def test_cli_envelopes_errors_stubs_and_real_entrypoint(self):
        for backend, response in (("arxiv", Mock(text=ATOM)), ("openalex", Mock(json=lambda: {"meta": {"cost_usd": 0}}))):
            with patch.object(search, "get", return_value=response):
                output = json.loads(run_main(search.main, "--source", backend, "--query", "q", "--no-api-key"))
            self.assertEqual(output["source"], backend)
            self.assertEqual(output["n"], len(output["records"]))
        for backend in ("inspire_hep", "nasa_ads", "repec", "philsci", "chemrxiv"):
            with redirect_stdout(io.StringIO()) as output, patch.object(sys, "argv", ["search", "--source", backend, "--query", "q"]), self.assertRaises(SystemExit):
                search.main()
            self.assertIn("stub", json.loads(output.getvalue())["error"])
        with patch.object(search, "get", side_effect=requests.Timeout("timed out")), patch.object(
            sys, "argv", ["search", "--source", "arxiv", "--query", "q"],
        ), redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit):
            search.main()
        self.assertIn("arxiv search failed", json.loads(output.getvalue())["error"])
        result = subprocess.run([sys.executable, str(ROOT / "skills/callimachus/scripts/search.py"),
                                 "--source", "chemrxiv", "--query", "q"], capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("stub", json.loads(result.stdout)["error"])
