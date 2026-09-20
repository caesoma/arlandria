#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "requests==2.32.*",  # used transitively via _common (polite HTTP); uv builds an isolated env
# ]
# ///
"""Search one bibliographic backend; print lean normalized records as JSON to stdout.

This is the retrieval mouth of the pipeline - the one script that talks to outside databases. Everything downstream (dedupe -> screening -> export) works off the JSON this prints, so its single job is: hit ONE database and translate that database's idiosyncratic response into the project's shared "lean search record" shape. No screening, no ledger writes, no decisions - pure fetch-and- normalize. Keeping all the database-specific quirks isolated here is what lets the rest of the code stay database-agnostic.

Where it sits in the workflow (step 3, Query): the LLM writes several query variants, runs this once per (backend x query) pair, and saves each output to a file; dedupe.py then merges those files into the ledger. One backend per call by design - choosing which databases to fan out across is for the LLM to decide (per SKILL.md); this script just executes the one it was asked for.

How a backend is wired:
  A backend is a function `(query, args) -> [search_record]` registered under a name by the
  `@backend("name")` decorator, which drops it into the BACKENDS dispatch table that `main` looks up. Adding a database is therefore exactly one decorated function that maps that database's fields onto search_record() (defined in _common.py). The backends below are the only database-specific code in the project. The envelope printed to stdout is:
    {"source": <name>, "query": <str>, "n": <count>, "records": [<search_record>, ...], "cost_usd"?}

Backend tiers (which to call is for the LLM to decide, per SKILL.md - this script only runs one):
  - openalex   : the default backbone - a free, cross-disciplinary catalogue of scholarly works. Requires OPENALEX_API_KEY (or --no-api-key for the grace-period keyless pool). Returns closed-access works too; they are screened on the abstract, never dropped here.
  - arxiv / biorxiv / medrxiv : "freshness" backends - the open preprint servers, queried only when a question is recency-sensitive, because OpenAlex lags them by days (--since required).
  - europepmc / pubmed / semantic_scholar : domain / general backends, added when the field fits.
  - inspire_hep / nasa_ads / repec / philsci / chemrxiv : stubs (interface ready; not implemented).

Vocabulary you'll meet below (so the inline comments can stay short):
  - polite pool: sending a contact email (mailto) to NCBI / OpenAlex / etc. earns higher, more reliable rate limits. Wired once in _common.py; no backend has to do it itself.
  - oa_status: an open-access "colour" - open|closed|green|gold|hybrid|bronze. We carry it but never filter on it: a closed paper still has an abstract worth screening.
  - inverted index : OpenAlex ships abstracts as {word: [positions]} (a licensing work-around); _reconstruct_abstract() turns that back into readable prose.
  - referenced_works / snowballing : the works a paper cites; kept only as a seed for later
                     citation-chasing ("snowballing") - this script never follows them.

Usage: search.py --source openalex --query "CRISPR off-target detection" [--limit 50]
       search.py --source openalex --query "..." --filter type:preprint
       search.py --source arxiv --query "..." --since 2026-05-01
"""
import argparse, datetime, json, os, re, sys, xml.etree.ElementTree as ET  # ET: PubMed/arXiv are XML
from _common import get, search_record, die, EMAIL


# --- backend registry: name -> (query, args) -> [search_record] ----------------------------------
# A tiny decorator-based plugin system. `BACKENDS` maps a source name to its function; `@backend(x)`
# registers one. `main` validates --source against the table's keys and dispatches to the match, so
# the CLI choices and the implementations can never drift apart.
BACKENDS = {}


def backend(name):
    def reg(fn):
        BACKENDS[name] = fn
        return fn
    return reg


def _reconstruct_abstract(inv):
    """Rebuild linear abstract text from OpenAlex's inverted index {word: [positions]}.

    OpenAlex usually can't redistribute an abstract as plain prose for licensing reasons, so it ships
    it "inverted" - a map from each word to the position(s) it occupies, e.g.
        {"The": [0], "cell": [1, 4]}  ->  "The cell ... cell"
    We undo that: drop each word into a position->word dict, then read the words back in index order.
    The LLM screens on this reconstructed string, so even closed-access works carry a usable abstract."""
    if not inv:
        return None
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos)) or None


@backend("openalex")
def openalex(q, a):
    # OpenAlex (openalex.org) is a free, open catalogue of ~250M scholarly works spanning every
    # field, with citation links - hence our default backbone. The /works endpoint takes a `search`
    # term and returns a page of work objects; we map each onto a lean search_record. The API caps
    # `per-page` at 200.
    params = {"search": q, "per-page": min(a.limit, 200), "mailto": EMAIL}
    # key gate (required since 2026-02-13): read from env, never hardcode. --no-api-key opts into the
    # keyless polite pool (OpenAlex grace period / local testing) instead of failing.
    if not a.no_api_key:
        key = os.environ.get("OPENALEX_API_KEY")
        if not key:
            die("OPENALEX_API_KEY is not set - OpenAlex requires an API key. Add it to the "
                "environment or .env (OPENALEX_API_KEY=...), or pass --no-api-key to use the "
                "keyless polite pool while the grace period lasts.")
        params["api_key"] = key
    # filters: --since adds a publication-date floor; --filter passes arbitrary OpenAlex filters
    # through (e.g. "type:preprint"). NB: we deliberately never add is_oa - closed works must return
    # so they can be screened.
    filters = []
    if a.since:
        filters.append(f"from_publication_date:{a.since}")
    if a.filter:
        filters.append(a.filter)
    if filters:
        params["filter"] = ",".join(filters)
    data = get("https://api.openalex.org/works", params).json()
    out = []
    for w in data.get("results", []):
        oa = w.get("open_access") or {}        # OA truth moved here; top-level oa_status is now null
        loc = w.get("best_oa_location") or {}  # a specific free location, when one exists
        out.append(search_record(
            source_backend="openalex", raw_id=(w.get("id") or "").rsplit("/", 1)[-1] or None,
            doi=w.get("doi"), title=w.get("title"),
            abstract=_reconstruct_abstract(w.get("abstract_inverted_index")),
            authors=[au["author"]["display_name"] for au in w.get("authorships", [])],
            year=w.get("publication_year"),
            venue=((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
            oa_status=oa.get("oa_status"),  # open|closed|green|gold|hybrid|bronze
            # prefer a direct PDF, then a landing page, then OpenAlex's repository url
            pdf_url=loc.get("pdf_url") or loc.get("landing_page_url") or oa.get("oa_url"),
            # short ids (W...) for the works this one cites - snowballing seed
            referenced_works=[r.rsplit("/", 1)[-1] for r in (w.get("referenced_works") or [])],
            cited_by_count=w.get("cited_by_count")))
    # surface OpenAlex's per-call credit cost so the LLM can budget (list ~10 credits, etc.)
    cost = (data.get("meta") or {}).get("cost_usd")
    return out, ({"cost_usd": cost} if cost is not None else {})


@backend("arxiv")
def arxiv(q, a):
    # arXiv (arxiv.org) is the open preprint server for physics, CS, math and quantitative biology.
    # Its API answers with an Atom feed (XML, not JSON); `all:<q>` searches every field. As a
    # freshness backend, with --since we ask for newest-first AND additionally drop anything older
    # than --since client-side, because OpenAlex can lag arXiv's own server by days.
    params = {"search_query": f"all:{q}", "max_results": a.limit}
    if a.since:
        params.update(sortBy="submittedDate", sortOrder="descending")
    feed = get("https://export.arxiv.org/api/query", params).text
    ns = {"a": "http://www.w3.org/2005/Atom"}  # Atom namespace - every findtext needs it
    out = []
    for e in ET.fromstring(feed).findall("a:entry", ns):
        published = (e.findtext("a:published", default="", namespaces=ns) or "")
        if a.since and published[:10] < a.since:  # ISO dates compare lexically
            continue
        # entry id is a URL; its last segment is the arXiv id, which also builds the PDF url below
        aid = (e.findtext("a:id", default="", namespaces=ns) or "").rsplit("/", 1)[-1]
        out.append(search_record(
            source_backend="arxiv", raw_id=aid, arxiv_id=aid,
            title=(e.findtext("a:title", default="", namespaces=ns) or "").strip(),
            abstract=(e.findtext("a:summary", default="", namespaces=ns) or "").strip() or None,
            authors=[au.findtext("a:name", default="", namespaces=ns)
                     for au in e.findall("a:author", ns)],
            year=published[:4] or None, venue="arXiv",
            oa_status="green",  # arXiv preprints are open by definition
            pdf_url=f"https://arxiv.org/pdf/{aid}"))
    return out


def _rxiv(server, q, a):
    # bioRxiv & medRxiv are the biology and health-sciences preprint servers (one shared API). The
    # quirk: there is NO keyword search - you ask for everything posted in a [from, to] date window
    # and page through it. So it's freshness-only (--since required): we sweep recent preprints and
    # keep those whose title/abstract contain ALL the query terms (a cheap client-side AND match).
    if not a.since:
        die(f"{server} is a freshness backend: pass --since YYYY-MM-DD "
            f"(its API is date-range, not keyword search).")
    today = datetime.date.today().isoformat()
    terms = [t for t in re.split(r"\s+", q.lower()) if t]  # AND match keeps the date sweep on-topic
    out, cursor = [], 0
    for _ in range(5):  # scan at most ~500 recent preprints, then stop - bounded cost
        d = get(f"https://api.biorxiv.org/details/{server}/{a.since}/{today}/{cursor}").json()
        coll = d.get("collection", [])
        for p in coll:
            hay = ((p.get("title") or "") + " " + (p.get("abstract") or "")).lower()
            if not all(t in hay for t in terms):
                continue
            doi = p.get("doi")
            out.append(search_record(
                source_backend=server, raw_id=doi, doi=doi, title=p.get("title"),
                abstract=p.get("abstract") or None,
                authors=[x.strip() for x in (p.get("authors") or "").split(";") if x.strip()],
                year=(p.get("date") or "")[:4] or None, venue=server,
                oa_status="green",  # preprints are open
                pdf_url=f"https://www.{server}.org/content/{doi}v1.full.pdf" if doi else None))
            if len(out) >= a.limit:
                return out
        if len(coll) < 100:  # last page
            break
        cursor += 100
    return out


@backend("biorxiv")
def biorxiv(q, a):
    return _rxiv("biorxiv", q, a)


@backend("medrxiv")
def medrxiv(q, a):
    return _rxiv("medrxiv", q, a)


@backend("europepmc")
def europepmc(q, a):
    # Europe PMC (europepmc.org) is a large biomedical / life-sciences corpus (PubMed plus preprints,
    # patents and more). resultType=core returns the abstract and author list inline, so one call
    # suffices. isOpenAccess is a coarse Y/N flag, which we fold into our oa_status colour.
    data = get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
               {"query": q, "format": "json", "pageSize": min(a.limit, 100),
                "resultType": "core"}).json()
    out = []
    for r in data.get("resultList", {}).get("result", []):
        oa = {"Y": "open", "N": "closed"}.get(r.get("isOpenAccess"))  # coarse OA flag -> oa_status
        pdf = next((u.get("url") for u in ((r.get("fullTextUrlList") or {}).get("fullTextUrl") or [])
                    if u.get("documentStyle") == "pdf"), None)
        out.append(search_record(
            source_backend="europepmc", raw_id=r.get("id"),
            doi=r.get("doi"), pmid=r.get("pmid"),
            title=r.get("title"), abstract=r.get("abstractText"),
            authors=[au["fullName"] for au in (r.get("authorList") or {}).get("author", [])],
            year=r.get("pubYear"), venue=r.get("journalTitle"),
            oa_status=oa, pdf_url=pdf, cited_by_count=r.get("citedByCount")))
    return out


@backend("pubmed")
def pubmed(q, a):
    # PubMed via NCBI's E-utilities API. There is no single "search and return everything" call, so
    # it takes three steps:
    #   esearch  -> the PMIDs (PubMed ids) matching the query
    #   esummary -> bibliographic metadata (title, authors, journal, date) for those PMIDs, as JSON
    #   efetch   -> the abstracts, which are only offered as XML, in one batched call
    # We then stitch the per-PMID summary and abstract together below.
    eutils = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    ids = get(f"{eutils}/esearch.fcgi", {"db": "pubmed", "term": q, "retmax": a.limit,
              "retmode": "json", "email": EMAIL}).json()["esearchresult"]["idlist"]
    if not ids:
        return []
    summ = get(f"{eutils}/esummary.fcgi", {"db": "pubmed", "id": ",".join(ids),
               "retmode": "json", "email": EMAIL}).json()["result"]
    # efetch for abstracts (PubMed has no JSON efetch) - one batched XML call.
    xml = get(f"{eutils}/efetch.fcgi", {"db": "pubmed", "id": ",".join(ids),
              "rettype": "abstract", "retmode": "xml", "email": EMAIL}).text
    abs_by_pmid = {}
    # an abstract may arrive as several <AbstractText> chunks (Background/Methods/...) - join them
    for art in ET.fromstring(xml).findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID")
        chunks = [e.text or "" for e in art.findall(".//Abstract/AbstractText")]
        abs_by_pmid[pmid] = " ".join(c.strip() for c in chunks).strip() or None
    out = []
    for pid in ids:
        m = summ.get(pid, {})
        # DOI isn't a top-level field - dig it out of the articleids list
        doi = next((x["value"] for x in m.get("articleids", []) if x["idtype"] == "doi"), None)
        out.append(search_record(
            source_backend="pubmed", raw_id=pid, pmid=pid, doi=doi,
            title=m.get("title"), abstract=abs_by_pmid.get(pid),
            authors=[au["name"] for au in m.get("authors", [])],
            year=(m.get("pubdate", "")[:4] or None), venue=m.get("fulljournalname")))
    return out


@backend("semantic_scholar")
def semantic_scholar(q, a):
    # Semantic Scholar (semanticscholar.org) is an AI-curated corpus with a clean JSON "graph" API.
    # `fields` requests exactly the columns we map. An optional S2_API_KEY lifts the rate limit;
    # without it requests share a slower public pool. DOIs and arXiv ids arrive nested in externalIds.
    h = {"x-api-key": os.environ["S2_API_KEY"]} if os.environ.get("S2_API_KEY") else None
    fields = "title,abstract,year,venue,citationCount,externalIds,authors"  # request all we map
    data = get("https://api.semanticscholar.org/graph/v1/paper/search",
               {"query": q, "limit": min(a.limit, 100), "fields": fields}, headers=h).json()
    out = []
    for p in data.get("data", []):
        ext = p.get("externalIds") or {}  # DOI / ArXiv id live under externalIds
        out.append(search_record(
            source_backend="semantic_scholar", raw_id=p.get("paperId"),
            doi=ext.get("DOI"), arxiv_id=ext.get("ArXiv"),
            title=p.get("title"), abstract=p.get("abstract"),
            authors=[au["name"] for au in p.get("authors", [])],
            year=p.get("year"), venue=p.get("venue"), cited_by_count=p.get("citationCount")))
    return out


def _stub(name, note):
    # register a not-yet-implemented domain backend: the interface (dispatch + CLI choice) is ready;
    # the body just fails friendly, pointing at how to add it. Implement = replace with a @backend.
    @backend(name)
    def _f(q, a, _name=name, _note=note):
        die(f"backend '{_name}' is a stub (interface ready, not implemented): {_note}")
    return _f


_stub("inspire_hep", "HEP - INSPIRE-HEP REST API (literature/?q=); map hits onto search_record()")
_stub("nasa_ads", "astro - NASA ADS API; needs ADS_API_KEY")
_stub("repec", "econ - RePEc / IDEAS")
_stub("philsci", "philosophy - PhilSci-Archive OAI-PMH")
_stub("chemrxiv", "chemistry - ChemRxiv API")


def main():
    # CLI front door: parse args, dispatch to the one chosen backend, wrap its records in the
    # standard envelope, and print. Every error path funnels through die(), so stdout is always
    # valid JSON and never a Python traceback - the LLM reads stdout and shouldn't have to guess.
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, choices=sorted(BACKENDS))
    ap.add_argument("--query", required=True)
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--since", help="ISO date floor YYYY-MM-DD; freshness backends use it as the ""lower bound (required by biorxiv/medrxiv).")
    ap.add_argument("--filter", help="OpenAlex filter passthrough, e.g. 'type:preprint'.")
    ap.add_argument("--no-api-key", action="store_true",
                    help="OpenAlex: use the keyless polite pool instead of requiring OPENALEX_API_KEY "
                         "(grace period / testing).")
    a = ap.parse_args()
    try:
        result = BACKENDS[a.source](a.query, a)  # run the matching backend
    except SystemExit:
        raise  # die() already emitted a friendly JSON error
    except Exception as e:
        die(f"{a.source} search failed: {e}")  # network/parse error -> friendly JSON, not a traceback
    recs, meta = result if isinstance(result, tuple) else (result, {})  # backends may add meta (cost)
    # emit JSON to stdout; the LLM saves it and later passes it to dedupe.py --in
    env = {"source": a.source, "query": a.query, "n": len(recs), "records": recs}
    env.update(meta)
    json.dump(env, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
