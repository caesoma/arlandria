#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pypdf==4.*",  # embedded-text PDF reader
# ]
# ///
"""Extract plain text from a PDF so the LLM can read the full paper.

Workflow step 9, on request only: turns a resolved PDF into text the LLM can read to record a full-text verdict. With --out it writes a sidecar .txt and prints the path; otherwise it streams the text to stdout. Embedded-text only: it reads the real text layer of a born-digital PDF; a scanned (image-only) PDF has no such layer and yields empty text - that case would need OCR (see note below).

Usage: pdf_extract.py --pdf path/to/paper.pdf [--out paper.txt]
NOTE: starting point. For scanned PDFs add OCR; consider the pi-docparser
package for layout-aware extraction across formats.
"""
import argparse, sys
from pypdf import PdfReader  # third-party PDF reader (declared in the PEP 723 block above)


def main():
    ap = argparse.ArgumentParser()  # --pdf (input), --out (optional sidecar path)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    # pull each page's embedded text (None -> "") and join with blank lines between pages
    text = "\n\n".join((p.extract_text() or "") for p in PdfReader(a.pdf).pages)
    if a.out:
        open(a.out, "w").write(text)  # persist to the sidecar file and report its path
        print(a.out)
    else:
        sys.stdout.write(text)  # otherwise stream the full text to stdout


if __name__ == "__main__":
    main()
