#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "requests==2.32.*",  # used transitively via _common; uv builds an isolated env
# ]
# ///
"""Resolve a legal open-access copy for a ledger record.

Workflow step 9 (full-text curation), on request only - run for one record at a time, not in bulk.
Finds a legitimately free copy and records where it lives, so pdf_extract.py (or the researcher) can
fetch it. Legal-OA only: it never attempts to bypass a paywall.

Order (each step fills only what's still missing):
  1. OpenAlex best-OA - a free location OpenAlex already captured on the record at search time.
  2. Unpaywall (unpaywall.org) - a service that, given a DOI, returns the best LEGAL free copy.
  3. Crossref (crossref.org) - the DOI registry; used here only as a metadata / abstract fallback.
If the work is closed and no OA copy turns up, the record is KEPT and marked
`oa.fulltext = "closed, metadata-only"` rather than dropped.

Writes oa.is_oa / oa.url / oa.fulltext (and backfills abstract/venue from Crossref) back to the
ledger. Prints a single JSON object. Usage: resolve.py --ledger <review>/ledger.json --id <record_id>
"""
import argparse, json, re
from _common import load_ledger, save_ledger, get, EMAIL


def _strip_jats(s):
    # Crossref abstracts are JATS XML - strip tags and collapse whitespace to plain text
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip() or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--id", required=True)
    a = ap.parse_args()
    led = load_ledger(a.ledger)
    rec = next((r for r in led["records"] if r["id"] == a.id), None)
    if not rec:
        print(json.dumps({"error": "record not found"}))
        return

    warns = []
    # 1) OpenAlex best-OA: whatever the search already captured on the record (no extra credit spend)
    url = rec["oa"].get("url")
    is_oa = rec["oa"].get("is_oa")
    oa_status = rec.get("oa_status")
    doi = rec.get("doi")

    # 2) Unpaywall: authoritative OA status + best free location for a DOI (email = polite pool)
    if doi:
        try:
            d = get(f"https://api.unpaywall.org/v2/{doi}", {"email": EMAIL}).json()
            is_oa = d.get("is_oa", is_oa)
            if d.get("oa_status"):
                oa_status = d["oa_status"]
            loc = d.get("best_oa_location") or {}
            url = loc.get("url_for_pdf") or loc.get("url") or url  # prefer a direct PDF; keep prior url
        except Exception as e:
            warns.append(f"unpaywall failed: {e}")  # non-fatal: fall back to prior url

    # 3) Crossref: canonical metadata / abstract fallback (never a paywall bypass)
    if doi:
        try:
            m = get(f"https://api.crossref.org/works/{doi}", {"mailto": EMAIL}).json().get("message", {})
            if not rec.get("abstract") and m.get("abstract"):
                rec["abstract"] = _strip_jats(m["abstract"])
            if not rec.get("venue"):
                ct = m.get("container-title") or []
                if ct:
                    rec["venue"] = ct[0]
        except Exception as e:
            warns.append(f"crossref failed: {e}")

    # write resolution back to the ledger
    rec["oa"]["is_oa"], rec["oa"]["url"] = is_oa, url
    if oa_status is not None:
        rec["oa_status"] = oa_status
    # closed + no legal OA copy found -> KEEP the record, mark it metadata-only (don't drop it)
    if not url and (is_oa is False or oa_status == "closed"):
        rec["oa"]["fulltext"] = "closed, metadata-only"
    save_ledger(a.ledger, led)

    out = {"id": a.id, "is_oa": is_oa, "oa_status": oa_status, "url": url,
           "fulltext": rec["oa"].get("fulltext")}
    if warns:
        out["warnings"] = warns
    print(json.dumps(out))


if __name__ == "__main__":
    main()
