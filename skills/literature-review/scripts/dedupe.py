#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "requests==2.32.*",  # used transitively via _common; uv builds an isolated env
# ]
# ///
"""Merge search-result JSON files into the ledger; log the queries that were run.

Workflow step 4 (Pool): takes the saved outputs of several search.py runs (lean search records) and
folds them into one ledger of rich entries, collapsing duplicates that surfaced from more than one
backend. Each lean record is first mapped to a ledger entry (`ledger_entry`), then matched against
what's already in the ledger by this precedence:

  DOI  ->  arXiv id  ->  PMID  ->  normalized(title) + year

A duplicate is *merged* (union sources + ids, backfill missing fields), never re-added - so a
screening decision is never overwritten or duplicated. A preprint and its version-of-record collapse
into one entry (VoR = the final peer-reviewed published article; a preprint is its earlier, un-reviewed
form): when an incoming record carries a DOI and the stored one did not (preprint -> VoR),
we upgrade to the VoR's metadata while keeping BOTH source ids. The stored entry's stable `id` does
not change. Each input file is recorded in the ledger's query log with an incrementing round number.

--exclude-known OTHER.json drops records already screened in another ledger
(mode-3 cross-review search), so a new review doesn't re-litigate old ground.

Prints {found_this_run, skipped_known, deduped_total}.

Usage: dedupe.py --ledger <review>/ledger.json --in <review>/searches/*.json [--exclude-known prior/ledger.json]
"""
import argparse, json
from _common import load_ledger, save_ledger, recompute_stats, ledger_entry, norm_title, now


def _ty(r):
    # the title+year dedupe key (last tier): normalized title paired with the publication year
    return (norm_title(r.get("title")), r.get("year"))


def index(r, by_doi, by_arxiv, by_pmid, by_ty):
    # register a stored entry under every key it has, so later inputs dedupe against it too
    if r.get("doi"):
        by_doi[r["doi"]] = r
    if r.get("ids", {}).get("arxiv"):
        by_arxiv[r["ids"]["arxiv"]] = r
    if r.get("ids", {}).get("pmid"):
        by_pmid[r["ids"]["pmid"]] = r
    if r.get("title"):
        by_ty[_ty(r)] = r


def merge(ex, le):
    """Fold incoming ledger entry `le` into the already-stored `ex` in place. Preserves ex's id and
    its screening decision; unions provenance; upgrades to version-of-record metadata when warranted."""
    for s in le["sources"]:
        if s not in ex["sources"]:
            ex["sources"].append(s)  # union the backends that surfaced it
    for k, v in le["ids"].items():
        ex["ids"].setdefault(k, v)   # keep both source ids (preprint arXiv id + VoR native id)
    # version-of-record upgrade: incoming has a DOI, stored one didn't -> prefer the VoR metadata
    if le.get("doi") and not ex.get("doi"):
        ex["doi"] = le["doi"]
        for f in ("title", "venue", "year", "oa_status"):
            if le.get(f):
                ex[f] = le[f]
        if le.get("citations") is not None:
            ex["citations"] = le["citations"]
        if le.get("referenced_works"):
            ex["referenced_works"] = le["referenced_works"]
        if le["oa"].get("url"):
            ex["oa"]["url"] = le["oa"]["url"]
        if le.get("oa_status") is not None:
            ex["oa"]["is_oa"] = le["oa_status"] != "closed"
    # backfill anything still missing on the stored entry from the incoming one
    if not ex.get("abstract") and le.get("abstract"):
        ex["abstract"] = le["abstract"]
    if not ex.get("year") and le.get("year"):
        ex["year"] = le["year"]
    if not ex.get("venue") and le.get("venue"):
        ex["venue"] = le["venue"]
    if ex.get("citations") is None and le.get("citations") is not None:
        ex["citations"] = le["citations"]
    if ex.get("oa_status") is None and le.get("oa_status"):
        ex["oa_status"] = le["oa_status"]
    if not ex.get("referenced_works") and le.get("referenced_works"):
        ex["referenced_works"] = le["referenced_works"]
    if not ex["oa"].get("url") and le["oa"].get("url"):
        ex["oa"]["url"] = le["oa"]["url"]


def known_keys(path):
    # collect id/doi/arxiv/pmid + (title, year) keys of already-screened records (--exclude-known)
    led = json.load(open(path))
    ids, titles = set(), set()
    for r in led["records"]:
        if r["screening"]["abstract"]["decision"] != "unscreened":  # only already-decided papers
            ids.add(r["id"])
            if r.get("doi"):
                ids.add(r["doi"])
            for k in ("arxiv", "pmid"):
                v = r.get("ids", {}).get(k)
                if v:
                    ids.add(v)
            if r.get("title"):
                titles.add(_ty(r))
    return ids, titles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--in", dest="inputs", nargs="+", required=True)
    ap.add_argument("--exclude-known")
    a = ap.parse_args()

    led = load_ledger(a.ledger)
    # build lookup indexes over what's already in the ledger - one per match tier
    by_doi, by_arxiv, by_pmid, by_ty = {}, {}, {}, {}
    for r in led["records"]:
        index(r, by_doi, by_arxiv, by_pmid, by_ty)
    skip_ids, skip_titles = known_keys(a.exclude_known) if a.exclude_known else (set(), set())

    # this merge is one "round" - one past the highest round already logged
    rnd = max([q.get("round", 0) for q in led["queries"]], default=0) + 1
    found = skipped = 0
    for path in a.inputs:
        p = json.load(open(path))
        # log the query that produced this file (source, string, count) for reproducibility
        led["queries"].append({"id": f"q{len(led['queries']) + 1}", "round": rnd,
                               "source": p.get("source"), "query_string": p.get("query"),
                               "run_at": now(), "n_returned": p.get("n")})
        for rec in p["records"]:
            found += 1
            le = ledger_entry(rec)  # lean search record -> rich ledger entry
            # cross-review skip: already screened elsewhere (by any id, or by title+year)
            le_keys = {le["id"], le.get("doi"), le["ids"].get("arxiv"), le["ids"].get("pmid")}
            if (le_keys & skip_ids) or (_ty(le) in skip_titles):
                skipped += 1
                continue
            # already in this ledger? match by DOI, then arXiv id, then PMID, then title+year
            ex = (le.get("doi") and by_doi.get(le["doi"])) \
                or (le["ids"].get("arxiv") and by_arxiv.get(le["ids"]["arxiv"])) \
                or (le["ids"].get("pmid") and by_pmid.get(le["ids"]["pmid"])) \
                or by_ty.get(_ty(le))
            if ex:
                merge(ex, le)            # duplicate: fold in, don't re-add (preserves its decision)
                index(ex, by_doi, by_arxiv, by_pmid, by_ty)  # re-index any keys it just gained
            else:
                led["records"].append(le)  # genuinely new
                index(le, by_doi, by_arxiv, by_pmid, by_ty)

    led["stats"]["found"] = led["stats"].get("found", 0) + found  # cumulative gross hits
    recompute_stats(led)  # refresh derived counts (deduped, screened, ...)
    save_ledger(a.ledger, led)
    print(json.dumps({"found_this_run": found, "skipped_known": skipped,
                      "deduped_total": len(led["records"])}))


if __name__ == "__main__":
    main()
