# Architecture — how Arlandria is plumbed together

Arlandria is a [Pi](https://pi.dev) package that adds the semi-automated `callimachus` skill.
This document is the map: what the pieces are, how they connect, and how a request flows from a typed
question to a BibTeX file.

## The one principle everything follows

**The LLM decides; the scripts do deterministic I/O.** Pi's LLM is the orchestrator — it drafts
criteria, decides on every abstract, and talks to the researcher. The bundled Python scripts make *no
decisions*: they search a database, merge results, write a schema-safe ledger, resolve a PDF, export
a list. Each prints JSON to stdout and exits. The durable state lives in one place — the **review
ledger**, `<base>/<slug>/ledger.json` (one self-contained folder per review) — which persists across sessions and is the single source of truth.

```
research question
      │
      ▼
  Pi's LLM ──reads──▶ skills/callimachus/SKILL.md   (the 9-step workflow)
      │
      │ calls via `bash`
      ▼
  scripts/*.py  ──read/write──▶  <base>/<slug>/ledger.json  (the ledger)
      │
      ▼
  BibTeX / CSV  (the deliverable)
```

## How it plugs into Pi

The package declares its Pi contributions in [`package.json`](../package.json) under the `"pi"` key:

```json
"pi": { "skills": ["./skills"], "prompts": ["./prompts"], "extensions": ["./extensions"] }
```

When Pi loads `arlandria` as a package (`{ "packages": ["npm:arlandria"] }` in the user's Pi
settings), it auto-discovers the skill, the `/litreview` prompt, and the slash-command extension.

There are two ways to run it:

- **As a Pi package** — add it to Pi settings; then just talk to `pi`.
- **As a branded CLI** — the `cal` / `arlandria` launcher
  ([`bin/arlandria.js`](../bin/arlandria.js)) prints the banner and spawns Pi with the skill and extension already on the path:

  ```
  pi -e extensions/litreview/index.ts --skill skills/callimachus  …
  ```

  It prefers the Pi binary bundled as a dependency and falls back to a global `pi`.

The `.arlandria/` directory (`SYSTEM.md` + `settings.json`) is the rebranded Pi config dir — Pi's normal `.pi/` settings under the Arlandria name. `SYSTEM.md` is the standing system instruction ("you are a callimachus assistant…"); `settings.json` holds Pi harness settings (`packages`, `quietStartup`, `collapseChangelog`).

## The moving parts

| Piece | Path | Role |
|------|------|------|
| Launcher | [`bin/arlandria.js`](../bin/arlandria.js) | Branded entry point (`cal`); banner, then hands off to Pi. |
| Extension | [`extensions/litreview/index.ts`](../extensions/litreview/index.ts) | Registers the `/litreview` and `/literature-review` slash commands; kicks the LLM into the skill's workflow. |
| Prompt | [`prompts/litreview.md`](../prompts/litreview.md) | The `/litreview` slash-command body — disciplines + handoff to the skill. |
| Skill | [`skills/callimachus/SKILL.md`](../skills/callimachus/SKILL.md) | **The workflow** the LLM follows: the 9-step loop, the interactive gates, the screening discipline. |
| Tools | [`skills/callimachus/scripts/`](../skills/callimachus/scripts/) | The deterministic Python I/O scripts (below). |
| Schema | [`skills/callimachus/references/ledger_schema.md`](../skills/callimachus/references/ledger_schema.md) | The ledger's JSON contract + invariants. |
| Ledger | `<base>/<slug>/ledger.json` (runtime) | Durable per-review state in one self-contained folder; the single source of truth. |

The extension is the only TypeScript; Pi loads it directly via `jiti`, so there is no build step.

## The scripts (deterministic tools, called via `bash`)

All live in `skills/callimachus/scripts/` and share [`_common.py`](../skills/callimachus/scripts/_common.py).
They are **self-bootstrapping**: each carries its dependencies inline (PEP 723) and is run with
`uv run <script>`, which provisions a cached per-script environment — there is no `pip install` and no
venv. The LLM always invokes them as `uv run scripts/X.py …`; a bare `python` run has no deps and
fails. `uv` is the only host prerequisite besides Node/Pi (the launcher preflights for it).

| Script | Does |
|--------|------|
| `_common.py` | Shared helpers: polite HTTP (`get` + friendly `die`), the lean `search_record()` contract every backend maps onto plus `ledger_entry()` (search record → ledger entry), ledger load/save/stat helpers, and `.env` loading. Imported by all the others. |
| `search.py` | Search one pluggable backend → lean normalized records as JSON on stdout. OpenAlex is the default backbone (requires `OPENALEX_API_KEY`); freshness backends (arXiv, bioRxiv/medRxiv) are gated on `--since`; domain backends (Europe PMC, PubMed, …) plug into the same registry. Closed-access works are returned, never filtered. |
| `dedupe.py` | Map lean records → ledger entries and merge into the ledger (DOI → arXiv → PMID → title+year; preprint/VoR collapse to one entry); log the queries; optionally skip records already screened in another ledger. |
| `ledger.py` | The **only** writer of criteria / screening decisions / status. Schema-safe; enforces the human-decision lock. |
| `resolve.py` | Resolve a legal open-access copy (OpenAlex best-OA → Unpaywall → Crossref); write `oa.*` back; mark closed-with-no-OA records `metadata-only` instead of dropping them. |
| `pdf_extract.py` | Extract plain text from a PDF so the LLM can read the full paper. |
| `export.py` | Export the effective-include set as BibTeX or CSV into the review's `exports/` (or `--stdout`). Re-runnable, non-terminal. |

## Control flow (the 9-step loop, abridged)

1. Researcher states a question (chat, or `/litreview <question>`).
2. **Criteria gate** — LLM drafts include/exclude criteria and exchanges with the researcher; on release, `ledger.py criteria`.
3. **Query** — LLM writes query variants; runs `search.py --source … --query …` per (source × query).
4. **Pool** — `dedupe.py` merges every result file into the ledger.
5. **Screen** — LLM reads *every* abstract and records `ledger.py decide --stage abstract --by llm`.
6. **Report gate** — LLM reports clusters/gaps; researcher shelves clusters / directs criteria changes.
7. **Refine** — `ledger.py criteria` (bump version) + re-decide llm-decided records; loop to 3.
8. **Export** — `export.py` (BibTeX + CSV) as soon as abstract screening converges. The deliverable.
9. **Full-text curation** — asynchronously, `resolve.py` → `pdf_extract.py`; researcher verdicts via
   `ledger.py decide --stage fulltext --by human`.

The two **gates** (steps 2 and 6) never advance without an explicit human release. Steps 8–9 are
deliberately decoupled: the list ships fast; reading happens later and never blocks.

## Data contracts

- **Lean search record** — `_common.search_record()` returns one flat dict shape (doi, arxiv_id,
  pmid, title, authors, year, venue, abstract, oa_status, pdf_url, referenced_works, cited_by_count,
  source_backend, raw_id); every backend maps its response onto it, so downstream scripts never care
  which database a paper came from. `dedupe.py` then promotes each lean record to a **ledger entry**
  via `_common.ledger_entry()`, minting the stable `id` (lowercased DOI, else a title hash) and the
  empty screening/assessment blocks. Search output stays lean; screening state lives only in the ledger.
- **The ledger** — `<base>/<slug>/ledger.json`. Full schema and invariants in
  [`references/ledger_schema.md`](../skills/callimachus/references/ledger_schema.md). Key rules:
  records are never deleted; `ledger.py` is the only writer of `criteria`/`screening`/`status`;
  **human decisions are locked** against LLM re-screens (the LLM's overridden call is retained in
  `proposed`); `stats` is derived and recomputed on every write. A review-level `exchanges[]` log
  (written by `ledger.py note`) keeps an append-only summary of the gate exchanges — the
  rationale, not just the outcome.
- **stdout JSON** — every script prints JSON (or, for `export.py` / `pdf_extract.py`, the artifact
  text) and exits. The LLM reads stdout; nothing is hidden in side effects except the ledger write.

## Configuration & external services

- **`.env` / `ARLANDRIA_EMAIL`** — the polite-pool identity (higher rate limits on NCBI, OpenAlex,
  Unpaywall). Loaded by `_common._load_dotenv()` from the package root or cwd; a real exported
  environment variable overrides the file. `ARLANDRIA_EMAIL` is *not* a Pi `settings.json` key —
  Pi's settings have no env block (see [`.env.example`](../.env.example)).
- **`OPENALEX_API_KEY`** (required) — OpenAlex (the default search backbone) requires an API key
  since 2026-02-13. `search.py --source openalex` reads it from the environment and fails friendly if
  unset; `--no-api-key` falls back to the keyless polite pool for the grace period.
- **`S2_API_KEY`** (optional) — Semantic Scholar key for higher `search.py` rate limits.
- **`ARLANDRIA_HOME`** (optional) — fallback base directory for new review folders (default
  `~/arlandria-reviews`). At creation the LLM asks where to save: the current dir, a path the
  researcher gives, or this default.
- **Data sources** — OpenAlex (backbone) + freshness backends arXiv / bioRxiv / medRxiv (gated on
  `--since`) + domain/general backends Europe PMC, PubMed (NCBI E-utilities), Semantic Scholar, with
  registry stubs for INSPIRE-HEP, NASA ADS, RePEc, PhilSci, ChemRxiv.
- **OA resolution** — `resolve.py` tries OpenAlex's best-OA location (already on the record), then
  Unpaywall (by DOI), then Crossref (canonical metadata/abstract). Open access only; it never touches
  paywalled sources, and marks closed-with-no-OA records `metadata-only` rather than dropping them.

## State & what ships

- Each review is one self-contained folder (`ledger.json` + `exports/` + `searches/` + `pdfs/`) at a
  user-chosen base — the current dir, a given path, or `$ARLANDRIA_HOME` / `~/arlandria-reviews`,
  external to the repo by default. The legacy in-package `reviews/` and `outputs/` stay **gitignored** —
  a review is a living document you resume, not something committed.
- The npm package ships only what's in the `files` list in [`package.json`](../package.json):
  `bin/`, `skills/`, `prompts/`, `extensions/`, the two `.arlandria/` files, the logo, install
  scripts, and the docs/examples. Personal config (`.env`) is never shipped.
