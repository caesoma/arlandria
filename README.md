<p align="center">The open-source semi-automated literature-review agent, built on Pi.</p>

```text
██  ▄█▀             ▀█▄        ▀█▄      ▄▀
██▄█▀     ▄▄▄ ▄▄     ▀█▄        ▀█▄     ▄▄    ▄▄  ▄▄    ▄▄▄ ▄▄ ▄▄      ▄   ▄▄▄▄▄    ▄▄▄▄▄
███▄     ██  ██     ██▀█▄      ██▀█▄    ██    ██  ██   ██  ██   ▀█▄  ▄█▀  ██   ██  ██   ▀▀
██ ▀█▄   ██  ██    ██  ▀█▄    ██  ▀█▄   ██    ██  ██   ██  ██    ▀█▄▄█▀   ██   ██  ▀█▄▄▄▄
██   ██  ▀█▄▄▀█▄  ██    ▀█▄  ██    ▀█▄  ▀█▄▄  ██▀▄█▀▄  ▀█▄▄▀█▄   ▄█▀▀█▄   ▀█▄▄▄█▀       ██
                                              ██                ▄█▀  ▀█▄               ▀▀
                                              ▀▀                ▀      ▀▀

 ██████  █████  ██      ██      ██ ███    ███  █████   ██████ ██   ██ ██    ██ ███████
██      ██   ██ ██      ██      ██ ████  ████ ██   ██ ██      ██   ██ ██    ██ ██
██      ███████ ██      ██      ██ ██ ████ ██ ███████ ██      ███████ ██    ██ ███████
██      ██   ██ ██      ██      ██ ██  ██  ██ ██   ██ ██      ██   ██ ██    ██      ██
 ██████ ██   ██ ███████ ███████ ██ ██      ██ ██   ██  ██████ ██   ██  ██████  ███████
```

---

### What you type → what happens

```
$ cal "review the literature on CRISPR off-target detection"
→ Drafts inclusion criteria with you, searches OpenAlex (+ more when warranted),
  screens every abstract, reports clusters + gaps, and asks you to sharpen scope.

$ "filter the included set to >50 citations, newest first"
→ Reads the ledger; no new search.

$ "which 3 papers cover the in-vivo detection mechanism best?"
→ Answers from the recorded per-paper assessments.
```

### Install

**Prerequisites.** Node/Pi, plus [`uv`](https://docs.astral.sh/uv/) — the Python primitives
self-bootstrap through it, so it is the only extra host requirement (no `pip`, no venv):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

The branded launcher checks for `uv` on start and prints this hint if it is missing.

**As a pi-based, standalone CLI.**

```bash
curl -fsSL <your-host>/install | bash    # or: npm install -g callimachus
```

`cal` (alias of `callimachus`) prints the banner and launches Pi with the literature-review skill on the path.


**As a Pi package.** If you don't want to perform an installation of the package, Callimachis can be added to a standard Pi harness as a skill package.
Add to your Pi settings so the skill is auto-discovered:

```json
{ "packages": ["npm:callimachus"] }
```

Then just talk to `pi` about a research question.


### Configure

Copy the example env file and set two values:

```bash
cp .env.example .env
#   CALLIMACHUS_EMAIL  - polite-pool identity (higher rate limits on NCBI / OpenAlex / Unpaywall / Crossref)
#   OPENALEX_API_KEY   - REQUIRED for OpenAlex, the default search backbone (since 2026-02-13)
```

The scripts load `.env` automatically; a shell `export` overrides it. Without `OPENALEX_API_KEY`,
OpenAlex searches fail with a clear message (pass `--no-api-key` to use the keyless polite pool
while the grace period lasts).

Each review is saved as its own self-contained folder. At creation the LLM asks where: the current
directory, a path you give, or a default base (`CALLIMACHUS_HOME`, else `~/callimachus-reviews`) — so
your reviews can live anywhere, including outside this package.

The model is whatever your `pi` is configured with (local models included) - the LLM is the decision-maker.

### How it works

Pi's LLM is the orchestrator and the only decision-maker — it makes every decision and does all interaction itself. The Python files under [`skills/literature-review/scripts/`](skills/literature-review/scripts/) are **deterministic primitives**: JSON in, JSON out, no decisions. The LLM calls them via `bash` with `uv run`, and each script declares its dependencies inline (PEP 723), so `uv` builds a cached per-script environment on first call — no `pip install`, no venv. Everything they read and write lives in one self-contained folder per review — the **review ledger** at `<base>/<slug>/ledger.json`, alongside its `exports/`, `searches/`, and `pdfs/` — which persists across sessions.

**The primitives** (`scripts/`):

- **`search.py`** — one backend per call. A `@backend("name")` decorator registers each source into a `BACKENDS` dispatch table that `main()` looks up by `--source`; the backend's body normalizes that API's quirks (OpenAlex's inverted-index abstracts, arXiv's Atom XML, PubMed's three-call E-utilities sequence) into a uniform **lean search record**. Every error path funnels through `die()`, so stdout is always valid JSON. Freshness backends take `--since`; OpenAlex reads `OPENALEX_API_KEY` and echoes the call's `cost_usd`.
- **`dedupe.py`** — folds those lean records into the ledger as rich entries (`ledger_entry()` mints a stable id plus empty screening/assessment blocks), collapsing duplicates by **DOI → arXiv id → PMID → normalized(title)+year**. A duplicate is *merged* (union sources + ids, backfill missing fields, upgrade a preprint to its version-of-record while keeping both ids), never re-added — so an existing screening decision is never lost. It logs every query; `--exclude-known` skips papers already screened in another ledger.
- **`ledger.py`** — the **only** writer of criteria, decisions, and status, so the schema and safety rules live in one place. Its `decide` verb enforces the **human-decision lock**: a `--by llm` write cannot overwrite a `decided_by: human` decision, and a `--by human` override stashes the LLM's prior call into a `proposed` shadow field for audit. No-op writes (a locked decision, a missing record) leave the file untouched.
- **`resolve.py`** — finds a **legal** open-access copy, never bypassing a paywall: OpenAlex best-OA (already cached on the record) → Unpaywall (by DOI) → Crossref (metadata fallback). A closed work with no OA copy is *kept* and marked `metadata-only`, not dropped.
- **`pdf_extract.py`** — pulls the embedded text layer of a resolved PDF (via `pypdf`) so the LLM can read the full paper; a scanned, image-only PDF has no text layer and would need OCR.
- **`export.py`** — read-only. Emits the **effective-include** set (below) as BibTeX (the reading list) or CSV (the screening audit trail: decisions, relevance, `covers` tags, who decided).
- **`_common.py`** — the shared spine the others import rather than invoke: the polite-pool HTTP `get()` with exponential backoff on HTTP 429, the `.env` loader, ledger load/save, `recompute_stats()`, and `norm_title()`.

**The ledger** is the single source of truth. Each record carries a stable id, metadata, `screening.{abstract,fulltext}` blocks, an `assessment`, `oa` info, and an active/deferred `status`; derived counts are recomputed on every write, and records are never deleted. A review-level `exchanges` log (written via `ledger.py note`) keeps the rationale from the gate exchanges, so *why* the scope is what it is survives a session close. Two rules are enforced in the code rather than left to the LLM — the human-decision lock above, and the **effective-include** rule that defines the export set:

```
effective-include = status == active
  AND ( fulltext.decision == include
        OR (fulltext unscreened AND abstract.decision == include) )
```

i.e. a full-text include, or an abstract include not yet overturned at full text.

For how the pieces fit together end to end, see [docs/architecture.md](docs/architecture.md); the LLM-facing workflow is [skills/literature-review/SKILL.md](skills/literature-review/SKILL.md).

### The 9-step loop

Two steps are **interactive gates** — the LLM proposes, then exchanges and revises with you across as many turns as you want, and advances only on your explicit release.

1. **Question** — you state the topic in plain English.
2. **Criteria** *(gate)* — draft include/exclude criteria, exchange, and revise; no search runs until you release the gate.
3. **Query** — several query variants across backends (OpenAlex by default; add freshness/domain backends when warranted).
4. **Pool** — `dedupe.py` merges all results into the ledger (reports found → deduped).
5. **Screen** — read *every* retrieved abstract and record a provisional include/exclude/borderline with a reason.
6. **Report & triage** *(gate)* — present clusters, gaps, and counts; you shelve clusters and direct criteria changes.
7. **Refine** — bump criteria and re-decide llm-decided records (your human decisions stay locked); loop back to step 3 until you converge.
8. **Export** — BibTeX + CSV of the included set, as soon as abstract screening converges (in hand within the hour). Re-runnable.
9. **Full-text curation** — asynchronously over later sessions, fetch and read papers and record final verdicts with `--by human`. Never blocks.

### Layout

```
callimachus/
├── logo.mjs                      # the lettering
├── package.json                  # pi-package: ships skills/ + prompts/ + extensions/ via the "pi" field
├── bin/callimachus.js            # branded launcher (alias: cal): banner, then hands off to Pi
├── extensions/litreview/         # registers the /litreview + /literature-review slash commands
├── prompts/litreview.md          # the /litreview prompt workflow
├── skills/literature-review/
│   ├── SKILL.md                  # the 9-step workflow the LLM follows
│   ├── references/ledger_schema.md
│   └── scripts/                  # search · dedupe · ledger (write-tool)
│                                  #  · resolve · pdf_extract · export
├── docs/                         # architecture.md · callimachus-spec.md
├── .callimachus/                 # settings.json + SYSTEM.md
└── scripts/install/              # install.sh · install.ps1
```
