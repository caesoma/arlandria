# Changelog

## 0.2.0
- Reworked to the LLM-orchestrated design: Pi's LLM runs the 9-step loop and does all the deciding and screening; the Python primitives are deterministic JSON I/O only.
- Added `ledger.py`, the schema-safe write-tool (`criteria` / `decide` / `status`) with the human-decision lock and `proposed` shadow; the ledger is the single source of truth, resumable across sessions.
- Removed the deterministic `review.py` driver and the `assess.mjs` scorer, and dropped the `pi-ai` dependency and `CALLIMACHUS_MODEL*` vars (the LLM's model is Pi's).
- Search: OpenAlex is the default backbone and now requires `OPENALEX_API_KEY`; added freshness backends arXiv / bioRxiv / medRxiv (`--since`) and domain backends Europe PMC / PubMed / Semantic Scholar. Closed-access works are screened, not dropped.
- Self-bootstrapping primitives via `uv` + PEP 723 (no pip / venv); the `cal` launcher preflights for `uv`.
- `dedupe.py --exclude-known` for cross-review search; export (BibTeX + CSV) of the effective-include set at abstract convergence, re-runnable.
- Each review is now one self-contained folder (`<base>/<slug>/ledger.json` + `exports/` + `searches/` + `pdfs/`) at a user-chosen location (asked for at creation; default `$CALLIMACHUS_HOME`, else `~/callimachus-reviews`). `export.py` writes into the review's `exports/` (with `--out-dir` / `--stdout`), so reviews no longer share a directory or overwrite each other's `references.*`.
- Added `ledger.py note --gate criteria|triage --text "…"`: an append-only, review-level `exchanges` log that captures the rationale from the human↔LLM gate exchanges (steps 2/6), recoverable on resume. Distinct from a record's per-paper `notes`.

## 0.1.0
- Initial scaffold: literature-review skill, ledger, multi-database search (PubMed, OpenAlex, Semantic Scholar, Europe PMC, arXiv).
