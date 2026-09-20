# Architecture — Callimachus and Hypatia

Arlandria is a [Pi](https://pi.dev) package with exactly two skills:
`callimachus` for the literature review and `hypatia` for synthesis of its completed results.
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
"pi": { "skills": ["./skills/callimachus", "./skills/hypatia"], "prompts": ["./prompts"], "extensions": ["./extensions"] }
```

When Pi loads `arlandria` as a package (`{ "packages": ["npm:arlandria"] }` in the user's Pi
settings), it loads both skills, the `/callimachus` prompt, and their command extensions.

There are two ways to run it:

- **As a Pi package** — add it to Pi settings; then just talk to `pi`.
- **As a branded CLI** — the `arlandria` launcher
  ([`bin/arlandria.js`](../bin/arlandria.js)) prints the banner and spawns Pi with both skills and
  extensions already on the path:

  ```
  pi -e extensions/callimachus/index.ts -e extensions/hypatia/index.ts --skill skills/callimachus --skill skills/hypatia …
  ```

  It prefers the Pi binary bundled as a dependency and falls back to a global `pi`.

The `.arlandria/` directory (`SYSTEM.md` + `settings.json`) is the rebranded Pi config dir — Pi's
normal `.pi/` settings under the Callimachus name. `SYSTEM.md` is the standing system instruction
("you are a literature-review assistant…"); `settings.json` holds Pi harness settings (`packages`,
`quietStartup`, `collapseChangelog`).

## The moving parts

| Piece | Path | Role |
|------|------|------|
| Launcher | [`bin/arlandria.js`](../bin/arlandria.js) | Branded entry point (`arlandria`); banner, then hands off to Pi. |
| Callimachus extension | [`extensions/callimachus/index.ts`](../extensions/callimachus/index.ts) | Registers `/callimachus`; kicks the LLM into the review workflow. |
| Hypatia extension | [`extensions/hypatia/index.ts`](../extensions/hypatia/index.ts) | Registers `/hypatia` and `/callimachus-approve`; enforces the completed-review prerequisite. |
| Prompt | [`prompts/callimachus.md`](../prompts/callimachus.md) | The `/callimachus` slash-command body — disciplines + handoff to the skill. |
| Callimachus skill | [`skills/callimachus/SKILL.md`](../skills/callimachus/SKILL.md) | The 9-step loop, interactive gates, and screening discipline. |
| Hypatia skill | [`skills/hypatia/SKILL.md`](../skills/hypatia/SKILL.md) | Findings, gaps, and literature-backed opportunities from completed reviews. |
| Tools | [`skills/callimachus/scripts/`](../skills/callimachus/scripts/) | The deterministic Python I/O scripts (below). |
| Schema | [`skills/callimachus/references/ledger_schema.md`](../skills/callimachus/references/ledger_schema.md) | The ledger's JSON contract + invariants. |
| Ledger | `<base>/<slug>/ledger.json` (runtime) | Durable per-review state in one self-contained folder; the single source of truth. |

Pi loads the TypeScript extensions directly via `jiti`, so there is no build step.

## Hypatia downstream boundary

The Arlandria launcher also loads `extensions/hypatia/index.ts` and
`skills/hypatia/`. Callimachus still owns every research stage, including
full-text acquisition and human curation:

```text
Callimachus ledger + sources.json + human gate approvals
    → finalizer → .callimachus/completed/<revision>/handoff.json
    → isolated Hypatia session → validated evidence → Markdown / SVG / Beamer / audit
```

The early step-8 export is non-terminal. `/callimachus-approve curation` checks
criteria/triage approvals, search audit entries, screening, and final human
dispositions before publishing a sealed, versioned snapshot with source hashes.
Changing upstream evidence invalidates the handoff until Callimachus completes
again.

`/hypatia <folder>` starts a Pi SDK session with only five mediated tools:
snapshot read, page read, evidence save, render, and request Callimachus. Its
resource loader inherits no extensions, skills, prompts, or project context.
The tool allowlist has no shell, arbitrary file access, search, downloader, or
upstream writer. The parent session retains Callimachus's normal capabilities.

Evidence is stored separately under `.hypatia/<revision>/`, with historical
digests. Quotes are checked against their page, while semantic support remains
an explicit assessment. Author gap/limitation claims support gaps; author
direction claims support opportunities; researcher-provided resources constrain
feasibility. Reports and visuals use the same validated evidence and context.
Refresh requests suspend synthesis until a new completed revision exists.
See [the contracts](../skills/hypatia/references/contracts.md) for schemas,
approval commands, access limitations, and local trust assumptions.

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

1. Researcher states a question (chat, or `/callimachus <question>`).
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

- **`.env` / `CALLIMACHUS_EMAIL`** — the polite-pool identity (higher rate limits on NCBI, OpenAlex,
  Unpaywall). Loaded by `_common._load_dotenv()` from the package root or cwd; a real exported
  environment variable overrides the file. `CALLIMACHUS_EMAIL` is *not* a Pi `settings.json` key —
  Pi's settings have no env block (see [`.env.example`](../.env.example)).
- **`OPENALEX_API_KEY`** (required) — OpenAlex (the default search backbone) requires an API key
  since 2026-02-13. `search.py --source openalex` reads it from the environment and fails friendly if
  unset; `--no-api-key` falls back to the keyless polite pool for the grace period.
- **`S2_API_KEY`** (optional) — Semantic Scholar key for higher `search.py` rate limits.
- **`CALLIMACHUS_HOME`** (optional) — fallback base directory for new review folders (default
  `~/callimachus-reviews`). At creation the LLM asks where to save: the current dir, a path the
  researcher gives, or this default.
- **Data sources** — OpenAlex (backbone) + freshness backends arXiv / bioRxiv / medRxiv (gated on
  `--since`) + domain/general backends Europe PMC, PubMed (NCBI E-utilities), Semantic Scholar, with
  registry stubs for INSPIRE-HEP, NASA ADS, RePEc, PhilSci, ChemRxiv.
- **OA resolution** — `resolve.py` tries OpenAlex's best-OA location (already on the record), then
  Unpaywall (by DOI), then Crossref (canonical metadata/abstract). Open access only; it never touches
  paywalled sources, and marks closed-with-no-OA records `metadata-only` rather than dropping them.

## State & what ships

- Each review is one self-contained folder (`ledger.json` + `exports/` + `searches/` + `pdfs/`) at a
  user-chosen base — the current dir, a given path, or `$CALLIMACHUS_HOME` / `~/callimachus-reviews`,
  external to the repo by default. The legacy in-package `reviews/` and `outputs/` stay **gitignored** —
  a review is a living document you resume, not something committed.
- The npm package ships only what's in the `files` list in [`package.json`](../package.json):
  `bin/`, `skills/`, `prompts/`, `extensions/`, the two `.callimachus/` files, the logo, install
  scripts, and the docs/examples. Personal config (`.env`) is never shipped.
