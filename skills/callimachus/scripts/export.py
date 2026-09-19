#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []  # stdlib only (argparse, csv, json, os, sys) - no _common, no third-party
# ///
"""Export the effective-include set (spec ss2) as BibTeX or CSV. Re-runnable.

Workflow step 8 (the deliverable) and re-run anytime after: the reading list of currently-included
papers. It never writes the ledger, so it's safe to run repeatedly as decisions evolve. BibTeX (the
.bib citation format that reference managers like Zotero / EndNote import) is the researcher's reading
list; CSV carries the screening trail (decisions, relevance, covers, who decided) for auditing.

By default the deliverable is written into the review's own `exports/` directory (beside the ledger)
and the path is printed - so two reviews never overwrite each other's `references.*`. Pass --out-dir
to choose another directory, or --stdout to stream to stdout for piping.

effective-include = status==active AND
   (fulltext.decision == "include"
    OR (fulltext.decision == "unscreened" AND abstract.decision == "include"))
i.e. a full-text include, or an abstract include not yet overturned at full text; shelved
(deferred) records are excluded.

Usage: export.py --ledger <review>/ledger.json --format bibtex|csv [--out-dir DIR | --stdout]
"""
import argparse, csv, json, os, sys


def effective_include(led):
    # the set a reader actually works from - full-text verdict wins, else the standing abstract call
    out = []
    for r in led["records"]:
        if r.get("status") != "active":
            continue  # skip shelved (deferred) records
        fd = r["screening"]["fulltext"]["decision"]
        ad = r["screening"]["abstract"]["decision"]
        # include if full-text says include, or full text is untouched and the abstract said include
        if fd == "include" or (fd == "unscreened" and ad == "include"):
            out.append(r)
    return out


def bibtex(recs):
    out = []
    for r in recs:
        # cite key: prefer PMID, then DOI, then the record id; "/" is illegal in a key, so swap it
        key = (r.get("ids", {}).get("pmid") or r.get("doi") or r["id"]).replace("/", "_")
        # BibTeX joins multiple authors with " and "
        out.append("@article{%s,\n  title={%s},\n  author={%s},\n  year={%s},\n  journal={%s},\n  doi={%s}\n}" % (
            key, r.get("title") or "", " and ".join(r.get("authors") or []),
            r.get("year") or "", r.get("venue") or "", r.get("doi") or ""))
    return "\n\n".join(out)  # blank line between entries


def write_export(out, fmt, recs):
    # render the chosen format to an open text stream (a file, or stdout under --stdout)
    if fmt == "bibtex":
        out.write(bibtex(recs))
        return
    # CSV carries the audit trail: each paper plus how/why it was decided
    w = csv.writer(out)
    w.writerow(["doi", "title", "year", "venue", "citations",
                "abstract_decision", "fulltext_decision", "relevance", "covers", "decided_by"])
    for r in recs:
        sa, sf = r["screening"]["abstract"], r["screening"]["fulltext"]
        # decided_by reflects the stage that actually settled it: full text if reached, else abstract
        w.writerow([r.get("doi"), r.get("title"), r.get("year"), r.get("venue"),
                    r.get("citations"), sa["decision"], sf["decision"],
                    r["assessment"]["relevance"], "; ".join(r["assessment"]["covers"]),
                    sf["decided_by"] if sf["decision"] != "unscreened" else sa["decided_by"]])


def main():
    ap = argparse.ArgumentParser()  # --ledger, --status (legacy), --format, --out-dir, --stdout
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--status", default="included")  # kept for CLI compatibility
    ap.add_argument("--format", choices=["bibtex", "csv"], default="bibtex")
    ap.add_argument("--out-dir", help="directory to write into (default: <ledger-dir>/exports)")
    ap.add_argument("--stdout", action="store_true",
                    help="stream to stdout instead of writing a file (for piping)")
    a = ap.parse_args()
    with open(a.ledger, encoding="utf-8") as stream:
        led = json.load(stream)
    recs = effective_include(led)

    if a.stdout:  # piping mode: original behavior, nothing written to disk
        write_export(sys.stdout, a.format, recs)
        return
    # default: the review's own exports/ dir, beside the ledger. Namespacing the deliverable by folder
    # is what stops one review's references.bib/.csv from clobbering another's (they used to share a dir).
    out_dir = a.out_dir or os.path.join(os.path.dirname(os.path.abspath(a.ledger)), "exports")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "references." + ("bib" if a.format == "bibtex" else "csv"))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        write_export(fh, a.format, recs)
    print(path)  # report where the deliverable landed


if __name__ == "__main__":
    main()
