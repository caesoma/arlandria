---
name: callimachus
description: Semi-automated literature review. Turns a plain-English research question into multi-query searches over OpenAlex (the default backbone) plus freshness backends (arXiv, bioRxiv/medRxiv) and domain backends (Europe PMC, PubMed, and others) when the field or recency warrants; screens EVERY retrieved abstract for relevance against the question (closed-access works included); records every decision, reason, and assessment to a review ledger; and works interactively with the researcher, who is the final curator. The LLM's screening is a provisional first pass the researcher can override after reading the papers. Use for systematic or scoping literature search where recall and auditability matter.
---

# Callimachus

You (the LLM) orchestrate the review and do all the deciding and interaction yourself. The Python scripts are deterministic I/O tools you call via `bash`; they never make decisions. The review ledger (`<review-folder>/ledger.json`) is the single source of truth and persists across sessions. Your screening is a **provisional first pass** - the researcher reads the papers and has the final say.

## Setup (once)

```bash
cp .env.example .env   # then set:
#   ARLANDRIA_EMAIL  - polite-pool identity for NCBI / OpenAlex / Unpaywall / Crossref
#   OPENALEX_API_KEY   - REQUIRED for OpenAlex searches (the default backbone) since 2026-02-13
#   ARLANDRIA_HOME   - fallback base for new review folders (default ~/arlandria-reviews);
#                        you ask the researcher where to save at creation, so this is only the default
```

There is **no `pip install`**. The primitives are self-bootstrapping via [`uv`](https://docs.astral.sh/uv/):
each script carries its dependencies inline (PEP 723), and `uv run <script>` provisions them into a
cached per-script environment on first call. **Always invoke a primitive with `uv run <script>`;
never call `python`/`python3` directly** - a bare `python` run has no dependencies installed and will
fail with `ImportError`. (`uv` is the only host prerequisite besides Node/Pi.)

The scripts load `.env` from the package root automatically. A real `export ARLANDRIA_EMAIL=...`
in the shell overrides it. OpenAlex now **requires** an API key: `search.py --source openalex` reads
`OPENALEX_API_KEY` from the environment and fails with a clear message if it is unset (pass
`--no-api-key` to use the keyless polite pool only while the grace period lasts). OpenAlex is
credit-metered, so prefer one filtered list call over many singletons; `search.py` echoes the call's
`cost_usd`.

The model is whatever Pi is configured with - you are the decision-maker; there is no separate scorer.

## Where a review lives

Each review is one self-contained folder you can keep anywhere (including outside this package):

```
<base>/<slug>/
  ledger.json     # the single source of truth
  exports/        # references.bib, references.csv (the deliverable)
  searches/       # raw search.py outputs, fed to dedupe.py
  pdfs/           # resolved OA PDFs (step 9)
```

You choose `<base>` interactively when the review is created (step 2): the current folder, a path the
researcher gives, or the default (`$ARLANDRIA_HOME`, else `~/arlandria-reviews`). `<slug>` is a
short keyword name for the topic. Paths stored in the ledger are relative to the folder, so the whole
review can be moved or renamed freely (e.g. to sharpen the slug once the first search lands).

## Tools (call via bash with `uv run`; script paths relative to this skill, review paths under `<base>/<slug>/`)

| Tool | Use |
|------|-----|
| `uv run scripts/search.py --source <backend> --query "..."` | Search one backend -> lean records as JSON. **`openalex` is the default backbone** (needs `OPENALEX_API_KEY`); add `--filter type:preprint` or arbitrary OpenAlex filters. Freshness (use only when recency matters): `arxiv`, `biorxiv`, `medrxiv` with `--since YYYY-MM-DD`. Domain/general: `europepmc`, `pubmed`, `semantic_scholar`. Stubs (interface ready): `inspire_hep`, `nasa_ads`, `repec`, `philsci`, `chemrxiv`. |
| `uv run scripts/dedupe.py --ledger L --in r1.json ... [--exclude-known OTHER.json]` | Merge results into the ledger (DOI -> arXiv -> PMID -> title+year; preprint/VoR collapse to one); log the queries. `--exclude-known` skips papers already screened in another review. |
| `uv run scripts/ledger.py criteria\|decide\|status ...` | The ONLY writer of criteria / decisions / status (schema-safe). See below. |
| `uv run scripts/resolve.py --ledger L --id ID` | Resolve a legal open-access copy (OpenAlex best-OA -> Unpaywall -> Crossref). Closed + no OA -> kept and marked `metadata-only`. On request only. |
| `uv run scripts/pdf_extract.py --pdf p.pdf` | Extract full text for reading. On request only. |
| `uv run scripts/export.py --ledger L --format bibtex\|csv` | Export the effective-include set into the review's `exports/` (prints the path written). `--stdout` to pipe instead; `--out-dir` to redirect. Re-runnable, non-terminal. |

`ledger.py` verbs:
- `criteria --ledger L --include "..." [...] --exclude "..." [...] [--question "..."]` - bumps version, appends history; `--question` records the original question (pass it on the first call).
- `decide --ledger L --id ID --stage abstract|fulltext --decision include|exclude|borderline --by llm|human [--relevance high|med|low] [--covers tag ...] [--reason "..."] [--summary "..."]` - records a decision with provenance. `--reason` is why you decided; `--summary` is what the paper covers (distinct fields). Your screening writes `--by llm`; researcher overrides are `--by human`. **A `--by llm` write cannot overwrite a `human` decision (locked); a `human` write wins and keeps your original in `proposed`.**
- `status --ledger L --status active|deferred --id ID [...]` - shelve / un-shelve records.
- `note --ledger L --gate criteria|triage --text "..."` - append a short summary of the gate exchange (the rationale you and the researcher reached). Append-only, review-level, never overwritten - read it back on resume to recover *why* the scope is what it is. Distinct from a record's per-paper `notes`.

The ledger schema is in `references/ledger_schema.md`. Records are never deleted.

## Workflow (the 9-step loop)

1. **Question.** The researcher states the topic in plain English.
2. **Criteria - interactive gate.** Draft include/exclude criteria and present them. Then *exchange*: answer questions, show what each criterion would catch or miss, revise. Stay here across as many turns as needed. **Do not run any search until the researcher explicitly releases the gate** ("go ahead", "run it"). On an ambiguous reply, ask - do not assume. On release, set up the review's home, then record criteria:
   - **Ask where to save it:** "Save this review in the current folder (`<pwd>`)? [Y/n]" - if no: "Enter a folder to save it in, or press Enter for the default (`$ARLANDRIA_HOME`, else `~/arlandria-reviews`):". Create `<base>/<slug>/` plus `exports/ searches/ pdfs/`; `<slug>` is a short keyword name for the topic.
   - `ledger.py criteria --ledger <base>/<slug>/ledger.json --question "<the original question>"` - records the question on this first call (`ledger.json` derives its review_id from the folder name).
   - `ledger.py note --gate criteria --text "<2-3 sentences: what was debated and why the criteria landed here>"` - capture the rationale while it is fresh.
3. **Query.** Write several query variants and run `search.py` for each (backend x query), saving each output into the review's `searches/` (`mkdir -p <folder>/searches`, then redirect `> <folder>/searches/r1.json`). **Hit OpenAlex by default** (the backbone; it returns closed works too - screen them). Add a **freshness** backend (`arxiv`/`biorxiv`/`medrxiv` with `--since`) only when the question is recency-sensitive (OpenAlex lags the source servers by days). Add **one** domain backend when the field clearly fits (e.g. `europepmc` for biomed) - not all of them. One backend per call; you fan out.
4. **Pool.** `dedupe.py --ledger <folder>/ledger.json --in <folder>/searches/*.json` to merge all outputs into the ledger; report found -> deduped. If a sharper keyword slug is now obvious, you may rename the review folder here (paths are relative; just re-point `--ledger` afterwards).
5. **Screen.** Read EVERY retrieved abstract. Decide on each one individually against the criteria - no comparison across papers, no ranking, nothing skipped. Batch only to fit context (one at a time is fine). For each, `ledger.py decide --stage abstract --by llm` with decision (`include|exclude|borderline`), `--reason`, `--relevance`, `--covers`. These are provisional.
6. **Report & triage - interactive gate.** Report clusters (from `covers` tags), gaps, and counts. Then *exchange*: answer "what's in A?", "why exclude X?", "show the borderlines"; let the researcher shelve clusters (`ledger.py status --status deferred`) and direct criteria changes. Advance only on an explicit, possibly-directive release ("shelve B, tighten X, then go"). On release, record the triage rationale: `ledger.py note --gate triage --text "<what was shelved or changed, and why>"`.
7. **Refine.** On release: `ledger.py criteria` (bump version) and re-decide affected records, and/or new queries. **Re-decide only `llm`-decided records - human decisions are locked.** Loop back to step 3 until the researcher converges.
8. **Export - the deliverable, fast.** As soon as abstract screening converges, run `export.py` (bibtex + csv); it writes `references.bib`/`.csv` into the review's `exports/` and prints each path. This is the reading list, in hand within the hour. The session can end here. Export is re-runnable.
9. **Full-text curation - asynchronous.** Over later sessions, the researcher reads the papers. On request, fetch a copy: `resolve.py` finds a legal OA url, download it into the review's `pdfs/`, then `pdf_extract.py --pdf <folder>/pdfs/<id>.pdf` to read it. **Never block on their reading.** As they read, record verdicts with `ledger.py decide --stage fulltext --by human`; `borderline` resolves to include/exclude here. Re-export anytime.

## Curation (any turn, any session)

- **Interrogate** (reads over the ledger): clusters, why a paper was decided a certain way, borderlines, what a paper covers. No new search.
- **Override** (writes): flip a decision, change relevance, re-tag `covers` (reshapes clusters), un-defer a cluster - always `--by human`. Your prior call is kept in `proposed`; the researcher's call is locked against future re-screens.

## Resume (returning days or weeks later)

Point at an existing review folder's `ledger.json`. Skim its `exchanges` log and `criteria.history` to recover *why* the scope is what it is, then do one of:
1. **Curate** - record full-text verdicts on papers now read; re-export.
2. **Refine / expand** - change criteria (re-screen) or add queries (widen) on the same ledger; human decisions stay locked.
3. **New contextualized search** - start a new ledger; seed criteria by reading the prior one, and/or `dedupe.py --exclude-known prior.json` to skip already-screened papers.
