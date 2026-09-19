#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "requests==2.32.*",  # polite HTTP. Library module: imported by the CLI scripts, which each
# ]                       # re-declare this dep (uv runs the entrypoint's metadata, not a sibling's).
# ///
"""Shared helpers imported by every tool script - no CLI of its own.

Four jobs:
  1. Polite HTTP (`get`) with a mailto User-Agent + 429 backoff, `.env` loading, and `die`
     (friendly JSON error to stdout, non-zero exit - so a primitive never spews a stack trace).
  2. The lean search-record contract (`search_record`) every backend normalises onto - the shared
     schema in references/ledger_schema.md - and `ledger_entry`, which maps one lean record into the
     rich ledger entry that dedupe.py stores (search output stays lean; the ledger stays the SoT).
  3. Ledger IO + derived stats (`load_ledger` / `save_ledger` / `recompute_stats`).
  4. Dedupe key normalisation: `norm_title` (lowercase, fold diacritics, strip punctuation) and
     `canonical_doi` (lowercase, drop the resolver prefix).

The ledger schema and its invariants live in references/ledger_schema.md.
"""
import datetime, hashlib, json, os, re, sys, time, unicodedata
from pathlib import Path
import requests  # the only third-party HTTP dependency


def _load_dotenv():
    """Populate os.environ from a .env file (a real exported var wins). No dependency.
    Looks in the package root (where .env.example lives) and the current directory."""
    for root in (Path(__file__).resolve().parents[3], Path.cwd()):
        f = root / ".env"
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()  # so ARLANDRIA_EMAIL / S2_API_KEY can live in .env, not just the shell
EMAIL = os.environ.get("ARLANDRIA_EMAIL", "arlandria@example.org")
# mailto in the User-Agent = the "polite pool": higher rate limits on NCBI / OpenAlex / Unpaywall
UA = {"User-Agent": f"arlandria/0.1 (mailto:{EMAIL})"}
HTTP_TIMEOUT_SECONDS = 30


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def die(msg):
    """Friendly failure: print one JSON error object to stdout and exit non-zero.
    Keeps a primitive's stdout valid JSON instead of letting a traceback escape (spec ss3.2)."""
    json.dump({"error": msg}, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.exit(1)


def get(url, params=None, headers=None, tries=3):
    """One HTTP GET - the single outbound path every backend and resolver shares.

    Sends the polite-pool User-Agent (our mailto, set above) and retries on HTTP 429 ("Too Many
    Requests" - the server asking us to slow down) with exponential backoff: sleep 1s, then 2s, then
    4s before giving up. Any other failing status raises through raise_for_status()."""
    h = dict(UA)
    if headers:
        h.update(headers)  # caller extras (e.g. Semantic Scholar's x-api-key) win
    for i in range(tries):
        r = requests.get(url, params=params, headers=h, timeout=HTTP_TIMEOUT_SECONDS)
        if r.status_code == 429:
            time.sleep(2 ** i)  # 1s, 2s, 4s … then give up and raise
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()


def _stage():
    # blank screening block - one per stage (abstract, fulltext); ledger.py fills it in
    return {"decision": "unscreened", "reason": None, "at": None,
            "criteria_version": None, "decided_by": "llm", "proposed": None}


def canonical_doi(doi):
    # lowercase + drop the resolver prefix so a DOI is a stable dedupe key; "" -> None
    return (doi or "").lower().replace("https://doi.org/", "").replace("http://dx.doi.org/", "") or None


def _to_year(y):
    # normalise year to int across backends (OpenAlex gives int; arXiv/PubMed give "YYYY" strings).
    # Consistent typing matters: the title+year dedupe tier compares years, and "2017" != 2017.
    try:
        return int(str(y)[:4]) if y not in (None, "") else None
    except (ValueError, TypeError):
        return None


def search_record(**kw):
    """One lean search record - the shared schema every backend normalises onto (references/
    ledger_schema.md). Pure retrieval payload: no screening/ledger state lives here (that is added
    later by `ledger_entry`). Missing fields are null; list fields default to []."""
    return {
        "doi": canonical_doi(kw.get("doi")),
        "arxiv_id": kw.get("arxiv_id"),
        "pmid": kw.get("pmid"),
        "title": kw.get("title"),
        "authors": kw.get("authors") or [],
        "year": _to_year(kw.get("year")),
        "venue": kw.get("venue"),
        "abstract": kw.get("abstract"),
        "oa_status": kw.get("oa_status"),          # open|closed|green|gold|hybrid|bronze|null
        "pdf_url": kw.get("pdf_url"),              # best free PDF/landing url known at search time
        "referenced_works": kw.get("referenced_works") or [],  # outbound refs - for snowballing
        "cited_by_count": kw.get("cited_by_count"),
        "source_backend": kw.get("source_backend"),  # which backend emitted this
        "raw_id": kw.get("raw_id"),               # the backend-native id (openalex Wxxx, s2 paperId, ...)
    }


def ledger_entry(rec):
    """Map one lean `search_record` onto the rich ledger entry dedupe.py stores. This is where the
    stable `id`, the cross-backend `ids` map, and the empty screening/assessment blocks are minted -
    the search backends never carry that state, keeping their output a pure retrieval payload."""
    doi = canonical_doi(rec.get("doi"))
    # stable id: the DOI when present, else a hash of the normalized title (t:-prefixed)
    rid = doi or "t:" + hashlib.sha1(norm_title(rec.get("title")).encode()).hexdigest()[:16]
    ids = {}  # cross-backend identifiers, indexed by kind
    if rec.get("arxiv_id"):
        ids["arxiv"] = rec["arxiv_id"]
    if rec.get("pmid"):
        ids["pmid"] = rec["pmid"]
    if rec.get("source_backend") and rec.get("raw_id"):
        ids[rec["source_backend"]] = rec["raw_id"]  # e.g. ids["openalex"] = "W123"
    oa_status = rec.get("oa_status")
    return {
        "id": rid, "doi": doi, "ids": ids,
        "title": rec.get("title"), "abstract": rec.get("abstract"),
        "authors": rec.get("authors") or [], "year": rec.get("year"),
        "venue": rec.get("venue"), "citations": rec.get("cited_by_count"),
        "referenced_works": rec.get("referenced_works") or [],  # snowballing seed
        "oa_status": oa_status,
        "sources": [rec["source_backend"]] if rec.get("source_backend") else [],
        "found_by": [],
        "status": "active",
        # is_oa seeded from oa_status (closed -> False) until resolve.py confirms; fulltext marker
        # carries "closed, metadata-only" when resolve finds no legal OA copy (spec ss2 resolve).
        "oa": {"is_oa": (None if oa_status is None else oa_status != "closed"),
               "url": rec.get("pdf_url"), "pdf_path": None, "fulltext_path": None, "fulltext": None},
        "screening": {"abstract": _stage(), "fulltext": _stage()},
        "assessment": {"relevance": None, "covers": [], "summary": None,
                       "strength": None, "read_in_full": False},
        "notes": None,
    }


def load_ledger(path):
    # open an existing ledger, or mint an empty one whose review_id names the review
    if os.path.exists(path):
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)
    # review_id is the filename stem - but a generic "ledger" (the per-review-folder layout,
    # <base>/<slug>/ledger.json) takes its id from the containing folder name instead, so every
    # review's ledger can share the canonical name `ledger.json` without colliding on "ledger".
    stem = os.path.splitext(os.path.basename(path))[0]
    if stem == "ledger":
        stem = os.path.basename(os.path.dirname(os.path.abspath(path))) or stem
    return {"review_id": stem,
            "created": now(), "updated": now(), "question": None,
            "criteria": {"version": 0, "include": [], "exclude": [], "history": []},
            "queries": [],
            "exchanges": [],  # append-only log of gate-exchange summaries (ledger.py note)
            "stats": {"found": 0, "deduped": 0, "screened_abstract": 0,
                      "included_abstract": 0, "screened_fulltext": 0,
                      "included_fulltext": 0, "deferred": 0},
            "records": []}


def recompute_stats(led):
    # stats are derived, never hand-set - recompute the counts from records on every write
    recs = led["records"]
    def ad(r): return r["screening"]["abstract"]["decision"]
    def fd(r): return r["screening"]["fulltext"]["decision"]
    led["stats"].update(
        deduped=len(recs),
        screened_abstract=sum(1 for r in recs if ad(r) != "unscreened"),
        included_abstract=sum(1 for r in recs if ad(r) == "include"),
        screened_fulltext=sum(1 for r in recs if fd(r) not in ("unscreened", "not_applicable")),
        included_fulltext=sum(1 for r in recs if fd(r) == "include"),
        deferred=sum(1 for r in recs if r.get("status") == "deferred"))


def save_ledger(path, led):
    led["updated"] = now()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)  # create the review folder on first save
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(led, stream, indent=2, ensure_ascii=False)


def norm_title(t):
    # the title dedupe key: fold diacritics (é->e), lowercase, collapse non-alphanumerics to spaces.
    # NFKD splits a letter from its accent; dropping the combining marks folds the diacritic away.
    folded = "".join(c for c in unicodedata.normalize("NFKD", t or "") if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", folded.lower()).strip()
