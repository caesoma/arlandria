# Arlandria — implementation spec

Semi-automated literature-review agent built on the **Pi** coding-agent harness. A researcher poses a question in plain English; **Pi's LLM** turns it into database queries, screens every retrieved paper for relevance, records its decisions to a ledger, and works *with* the researcher — who is the final curator and will read the actual papers, on their own timeline. Primary deliverable: the included set as BibTeX + CSV, **in hand within an hour** of converging on criteria — the review then continues asynchronously over days or weeks.

It runs as a **persistent branded session** (`arlandria`): the review is one workflow inside an ongoing Pi session the researcher can step into, step out of, interrogate, and resume — without leaving `pi`.

This is the complete, settled spec. There are no open design questions. Implementation is delegated (e.g. to Claude Code); this document is the contract.

---

## 1. Architecture

Three actors, with a strict division of labour.

**LLM (Pi).** The orchestrator *and* the decision-maker. It runs the loop in §3, driven by `SKILL.md`. It does all the deciding and interaction itself — drafting criteria, writing queries, reading abstracts and deciding, reporting and asking, refining. Its screening is a **provisional first pass**: a transparent recommendation, never a verdict. It calls the Python scripts only for I/O (fetch, transform, ledger writes, export). It **never blocks on the researcher reading papers**. Its model is whatever Pi is configured with (via pi-ai, local models included); there is no separate model client. The LLM holds no durable state.

**Researcher (human).** The **final curator**. Confirms and shapes criteria, triages clusters, and — having read the papers, over days or weeks — confirms or overturns any of the LLM's calls. Curation (interrogating and overriding) is available on any turn and in any later session, not a separate phase.

**Scripts (Python tools, §4).** Deterministic, JSON in / JSON out, no decisions. They fetch, normalize, dedupe, resolve full text, write to the ledger under a fixed schema, and export. The LLM invokes them via `bash`.

**Ledger (`<base>/<slug>/ledger.json`, §5).** The single source of truth and the durable artifact — a review is a *living document* that outlives any session. Every query, decision (with provenance), reason, assessment, and status lives here. All cross-turn and cross-session state persists in the ledger, never in the LLM's context.

One-line summary: **the LLM orchestrates, calls scripts for I/O, and does the deciding itself — provisionally and without ever waiting on the researcher; the researcher curates, on their own timeline, and has the final say.**

---

## 2. Settled design decisions

- **Query writing is the LLM's job.** It translates plain English into several query variants per database. Non-deterministic is acceptable; reproducibility comes from *logging the queries that were run* (not how they were written) in `ledger.queries`.
- **The researcher is the final curator.** The LLM's screening triages and explains; every decision is a recommendation the researcher can overturn after reading the paper. The LLM assists; the human decides.
- **Gates are interactive — the human closes them.** Steps 2 and 6 are not one-shot checkpoints. At each gate the LLM proposes, then **exchanges and revises across as many turns as the researcher wants**, and advances only on an explicit release signal ("go ahead", "run it"). Free-form questions at a gate are part of the exchange, not instructions to proceed; on an ambiguous reply the LLM asks rather than assumes. At gate #2 the release may be partial and directive ("shelve B, tighten X, then go").
- **Screening reads every retrieved paper.** Each abstract is decided individually against the criteria — no comparison across papers, no embedding rank, no top-N gate. Because decisions are independent, batching is purely a matter of fitting context: the LLM screens the unscreened set in whatever batch size fits, one at a time if need be, until none remain. No silent exclusion.
- **The list comes fast; reading is asynchronous.** The deliverable export happens at abstract-stage convergence (step 8) — within the hour. Full-text reading (step 9) is human-paced, spread over later sessions, and the LLM never waits on it.
- **Export is re-runnable, not terminal.** The BibTeX/CSV is a *snapshot* of the ledger's current effective-include set; it is regenerated any time the review is curated further. There is no "done" — there is the ledger, and a list you regenerate whenever.
- **Deliverable = BibTeX + CSV** of the effective-include set. A PRISMA flow record is a *derived view* over the same ledger — a nice-to-have, implementable later, out of scope now.

### Status & provenance vocabulary

Three axes per record.

- **Relevance decision**, per stage:
  - `screening.abstract.decision` ∈ `unscreened | include | exclude | borderline`
  - `screening.fulltext.decision` ∈ `unscreened | include | exclude | not_applicable`
- **Workflow status**: `status` ∈ `active | deferred`.
- **Decision provenance**: each `screening.<stage>` carries `decided_by` ∈ `llm | human`.

`borderline` is an abstract-stage decision that survives into the full-text pass: the full-text pass pulls **include + borderline**, and at full text `borderline` resolves to `include` or `exclude`.

`deferred` is a triage state, *orthogonal to* the relevance decision — a shelved cluster is parked, not rejected, and can be reactivated. (`deferred` is its own field, not a decision value, so shelving never clobbers a relevance decision and the `decide`/`status` write-verbs own disjoint fields.)

`decided_by` makes curation safe: **human decisions are locked** — the step-7 re-screen revises only `llm`-decided records, never the researcher's. The researcher can re-override their own decisions at any time; the lock binds the LLM, not the human. When a human override replaces an LLM decision, the LLM's original is preserved in a shadow `proposed` object for auditability.

**Effective-include** (the export set): records where `status == active` and (`fulltext.decision == include`, or full text unassessed and `abstract.decision == include`). This definition is identical whether the researcher has read 0 papers or 40 — the early export and every later re-export use it; the list simply sharpens as full-text verdicts arrive.

---

## 3. The loop (`SKILL.md`)

The LLM executes these steps within the session. Two (2, 6) are **interactive gates** the researcher closes; **curation** (interrogate + override) is cross-cutting; full-text reading (9) is **asynchronous** and human-paced. Annotations mark LLM decision-making/interaction vs. script calls.

1. **Question.** Researcher states the topic in plain English. *(input)*
2. **Criteria — interactive gate #1.** LLM drafts inclusion/exclusion criteria and presents them, opening an exchange: the researcher can question them, ask what each would catch or miss, and have the LLM revise — across as many turns as needed. The LLM does **not** search until the researcher explicitly releases the gate. On release it records the agreed criteria. *(LLM + researcher; `ledger.py criteria`)*
3. **Query.** LLM writes several query variants per database and runs `search.py` for each (source × query). *(LLM writes; `search.py` fetches)*
4. **Pool.** LLM runs `dedupe.py` to merge all results into the ledger. *(`dedupe.py`)*
5. **Screen.** LLM reads **every** retrieved abstract and records `include | exclude | borderline` + a reason + an assessment (relevance, `covers` tags) for each. Decided individually; batched only to fit context; nothing ranked or skipped. Decisions are **provisional**, recorded as `decided_by: llm`. *(LLM reads & decides; `ledger.py decide --by llm`)*
6. **Report & triage — interactive gate #2.** LLM reports clusters, gaps, and stage counts, opening an exchange: the researcher can interrogate clusters and individual decisions ("what's in A?", "why exclude X?", "show the borderlines"), shelve clusters, and direct criteria changes. The LLM revises and re-reports as asked, and advances only on an explicit, possibly-directive release. *(LLM + researcher; `ledger.py status`, `decide`, `criteria`)*
7. **Refine.** On release: bump criteria version and re-decide affected records, and/or run new queries. **The re-screen touches only `llm`-decided records — human decisions are locked.** Repeat from step 3 until the researcher converges. *(LLM + researcher; `ledger.py criteria` + `decide`)*
8. **Export — the deliverable, fast.** As soon as abstract screening converges, the LLM exports the current effective-include set (abstract-stage includes + borderlines) to BibTeX + CSV — the reading list, in hand within the hour. **The session can close here.** Export is re-runnable and non-terminal; it is regenerated on every later curation. *(`export.py`)*
9. **Full-text curation — asynchronous.** Over the following days or weeks, in any later session, the researcher reads the papers. On request the LLM fetches a copy (`resolve.py` → `pdf_extract.py`); reading is never a precondition for the list and the LLM never blocks on it. As the researcher reads, they record full-text verdicts (`ledger.py decide --stage fulltext --by human`); `borderline` resolves to include/exclude here. Re-export anytime to refresh the deliverable. *(researcher reads; `resolve.py`/`pdf_extract.py` on request; `ledger.py decide`; `export.py`)*

### Curation (cross-cutting)

Available on any turn and in any later session, all grounded in the ledger:

- **Interrogate (reads):** "what's in cluster A?", "why was Verkuijl-2023 excluded?", "show me the borderlines", "what does this paper cover?" — answered from the recorded decisions, reasons, and `covers` tags. No new search.
- **Override (writes):** flip a decision, change relevance, re-tag `covers` (which reshapes clusters), un-defer a cluster. Recorded as `decided_by: human`; the human's call replaces the LLM's, is preserved-with-shadow for audit, and is locked against future re-screens. The researcher may re-override their own calls at will.

### Resume — returning days or weeks later

The ledger persists everything, so reopening `arlandria` and pointing at an existing review supports three distinct modes:

1. **Curate (same ledger).** Record full-text verdicts on papers now read, override earlier calls, then re-export. This is the ongoing tail of step 9.
2. **Refine / expand (same ledger).** Re-enter the loop at step 2 (change criteria → re-screen) or step 3 (add query variants → widen coverage) against the existing ledger. Prior `human` decisions stay locked throughout; only `llm` decisions are revisited.
3. **Contextualize a new search (new ledger, referencing an old one).** Start a fresh review whose pool can reference a prior ledger — seed criteria from it (the LLM reads the prior `criteria` and proposes them at gate #1) and/or skip papers already screened there (`dedupe.py --exclude-known`), so a new angle doesn't re-litigate old ground.

Modes 1–2 are the same ledger; mode 3 is a new ledger that references an old one — the only cross-review capability, and it is additive.

**Follow-ups** — "filter to >50 citations, newest first", "which 3 cover X best" — are LLM reads over the ledger (a facet of Curate). No new search unless the researcher asks to broaden scope.

---

## 4. Tools (deterministic Python)

All print JSON to stdout and never make judgments. Reads (filtering, "which cover X best", interrogating clusters) are **not** scripts — they are the LLM parsing the ledger.

| Tool | Invocation | Behaviour |
|------|-----------|-----------|
| `search.py` | `--source <db> --query "…" [--limit N]` | Search one database; emit normalized records (the §5 record contract). `db` ∈ `pubmed, openalex, semantic_scholar, europepmc, arxiv`. |
| `dedupe.py` | `--ledger L --in r1.json [r2.json …] [--exclude-known OTHER.json]` | Merge result files into the ledger: match on DOI, then normalized title; union source provenance; backfill a missing abstract. With `--exclude-known`, drop records already screened in another ledger (mode-3 cross-review search). Update `found` / `deduped`. |
| `ledger.py` | *(write-tool — three verbs)* | The only writer of decisions/criteria/status. Schema-safe so the LLM never hand-edits JSON. |
| `resolve.py` | `--ledger L --id ID` | Resolve a **legal** open-access copy: OpenAlex best-OA (cached on the record) → Unpaywall (by DOI) → Crossref (canonical metadata/abstract). Write `oa.is_oa` / `oa.url` / `oa.fulltext`; a closed work with no OA copy is kept and marked `metadata-only`, not dropped. On request only (step 9). Paywalled sources are out of scope. |
| `pdf_extract.py` | `--pdf path [--out file]` | Extract plain text from a PDF for the researcher/LLM to read. On request only. (Optionally back this with `pi-docparser` for layout-aware / scanned PDFs.) |
| `export.py` | `--ledger L --format bibtex\|csv [--out-dir D \| --stdout]` | Emit the **effective-include** set (§2) as BibTeX or CSV into the review's `exports/` (prints the path; `--stdout` to pipe). The deliverable — re-runnable, non-terminal. |

### `ledger.py` verbs

- `criteria --ledger L --include "…" […] --exclude "…" […]`
  Bump `criteria.version`, append a `{version, at, include, exclude}` entry to `criteria.history`. (Steps 2, 7.)
- `decide --ledger L --id ID --stage abstract|fulltext --decision include|exclude|borderline --by llm|human [--relevance high|med|low] [--covers tag …] [--reason "…"]`
  Write the decision into `screening.<stage>` with `reason`, current timestamp, current `criteria_version`, and `decided_by`; mirror `relevance` / `covers` into `assessment`. At `fulltext`, decision is `include|exclude` only. A `human` write replaces an existing decision, moving the LLM's prior call into the `proposed` shadow field. **`human` decisions are locked against the step-7 re-screen.** (Steps 5, 7, 9; curation.)
- `status --ledger L --status active|deferred --id ID [ID …]`
  Set `record.status` on the listed ids. (Step 6/7 cluster triage; clusters are re-selectable later via `assessment.covers`, so no separate cluster field is needed.)
- `note --ledger L --gate criteria|triage --text "…"`
  Append `{at, gate, criteria_version, text}` to the review-level `exchanges` log — a free-text summary of the human↔LLM gate exchange and the rationale it reached. Append-only; never overwritten. (Steps 2, 6.)

Every write recomputes the derived `stats` counts.

---

## 5. Ledger schema

One JSON file per review (`<base>/<slug>/ledger.json`) — the durable artifact, reopened across sessions. Comments are JSONC for humans; store as plain JSON.

```jsonc
{
  "review_id": "str",
  "created": "ISO8601",
  "updated": "ISO8601",
  "question": "the original plain-English question",

  // Versioned; the clarifying loop refines these and re-screens under the new version.
  "criteria": {
    "version": 3,
    "include": ["str", "…"],
    "exclude": ["str", "…"],
    "history": [ { "version": 1, "at": "ISO8601", "include": [], "exclude": [] } ]
  },

  // Every query run — for reproducibility (the queries, not how they were written).
  "queries": [
    { "id": "q1", "round": 1, "source": "pubmed", "query_string": "str",
      "run_at": "ISO8601", "n_returned": 142 }
  ],

  // Append-only log of gate-exchange summaries (ledger.py note) — the rationale, not just the outcome.
  "exchanges": [
    { "at": "ISO8601", "gate": "criteria", "criteria_version": 3,
      "text": "free-text summary of the human↔LLM exchange at this gate" }
  ],

  // Derived stage counts (recomputed on every write).
  "stats": {
    "found": 0, "deduped": 0,
    "screened_abstract": 0, "included_abstract": 0,
    "screened_fulltext": 0, "included_fulltext": 0,
    "deferred": 0
  },

  "records": [
    {
      "id": "stable hash (DOI, else normalized title)",
      "doi": "str|null",
      "ids": { "pmid": "…", "arxiv": "…", "openalex": "…", "s2": "…" },

      // bibliographic + filter fields
      "title": "str", "abstract": "str|null", "authors": ["str"],
      "year": 2023, "venue": "str|null", "citations": 87,
      "sources": ["pubmed", "openalex"],   // which DBs surfaced it (dedupe merge)
      "found_by": ["q1", "q4"],            // which query ids hit it

      // workflow status — orthogonal to the relevance decision; non-destructive shelving
      "status": "active",                  // active | deferred

      // legal open-access resolution (resolve.py / pdf_extract.py) — populated on request in step 9
      "oa": { "is_oa": null, "url": "str|null", "pdf_path": "str|null", "fulltext_path": "str|null" },

      // two-stage relevance decision — the science. decision + reason + provenance + criteria version
      "screening": {
        "abstract": { "decision": "unscreened",   // unscreened | include | exclude | borderline
                      "reason": "str|null", "at": "ISO8601|null", "criteria_version": 3,
                      "decided_by": "llm",         // llm | human
                      "proposed": null },          // LLM's original call, kept when a human overrides
        "fulltext": { "decision": "unscreened",    // unscreened | include | exclude | not_applicable
                      "reason": "str|null", "at": "ISO8601|null", "criteria_version": 3,
                      "decided_by": "llm",
                      "proposed": null }
      },

      // assessment memory — powers "which papers cover X best?" without re-search
      "assessment": { "relevance": null,            // high | med | low | null
                      "covers": [], "summary": "str|null",
                      "strength": "str|null", "read_in_full": false },

      "notes": "str|null"
    }
  ]
}
```

**Invariants.**
- Records are never deleted. `exclude` is a recorded decision; `deferred` is a parked status — both reversible, neither a removal.
- `ledger.py` is the only writer of `criteria`, `screening`, `status`. No hand-editing.
- **Human decisions (`decided_by: "human"`) are locked**: the step-7 re-screen revises only `llm`-decided records. The researcher can re-override at any time; the lock binds the LLM, not the human. Overridden LLM calls are retained in `proposed`.
- The ledger is the durable artifact: a review is resumable indefinitely; exports are disposable snapshots regenerated from it.
- Filtering and "which cover X best" are reads over `records` (by `year` / `citations` / `venue` / `covers` / decision / status). No new search.
- Re-screening on a criteria bump rewrites `llm`-decided `screening.*` and updates `criteria_version`; `criteria.history` preserves the definition each decision was made under.

---

## 6. Package delta

<<<<<<< HEAD
The repo is a Feynman-style **pi-package**: `arlandria` lettering (`logo.mjs`), `package.json` wiring `skills/` + `prompts/` into Pi via the `"pi"` field, a branded `bin` (`arlandria`, alias `cal`), `.arlandria/` config, and `scripts/install/`. The current contents diverge from this spec; the delta to reconcile:

**Entry point — `cal` is a persistent branded session.**
- `bin/arlandria.js` launches the **interactive** Pi REPL with the skill preloaded and the banner printed — and **stays** in the session. It does **not** run a single task and exit. The review is the `/litreview` workflow invoked *within* the running session; between review turns the researcher can do any other Pi work and can interrogate/override the ledger at any point.
- The skill remains usable from a plain `pi` (install the package as a Pi package: `"packages": ["npm:arlandria"]`), but the shipped surface is the persistent `cal` session.
=======
The repo is a Feynman-style **pi-package**: `callimachus` lettering (`logo.mjs`), `package.json` wiring `skills/` + `prompts/` into Pi via the `"pi"` field, a branded `bin` (`arlandria`), `.arlandria/` config, and `scripts/install/`. The current contents diverge from this spec; the delta to reconcile:

**Entry point — `arlandria` is a persistent branded session.**
- `bin/arlandria.js` launches the **interactive** Pi REPL with the skills preloaded and the banner printed — and **stays** in the session. It does **not** run a single task and exit. The review is the `/callimachus` workflow invoked *within* the running session; between review turns the researcher can do any other Pi work and can interrogate/override the ledger at any point.
- The skills remain usable from a plain `pi` (install the package as a Pi package: `"packages": ["npm:arlandria"]`), but the shipped surface is the persistent `arlandria` session.
>>>>>>> devin/1789827103-hypathia

**Delete** (rejected architecture — a competing deterministic orchestrator + a redundant scorer):
- `skills/callimachus/scripts/review.py`
- `skills/callimachus/scripts/assess.mjs`

**Add:**
- `skills/callimachus/scripts/ledger.py` — the write-tool, three verbs (§4), including `decide --by llm|human` and the locking/shadow behaviour.

**Keep / extend** (the deterministic primitives):
- `search.py`, `resolve.py`, `pdf_extract.py`, `export.py`
- `dedupe.py` — add the `--exclude-known OTHER.json` option (mode-3 cross-review search).
- `skills/callimachus/references/ledger_schema.md` (update to the §5 schema: `status`, `borderline`, `decided_by` + `proposed`, `deferred` in `stats`).

**Rewrite:**
- `skills/callimachus/SKILL.md` — the 9-step loop (§3) as **LLM instructions**: orchestrate, call scripts for I/O and ledger writes, do the criteria-drafting, abstract-reading, reporting/asking, and refining yourself. Encode the **interactive gates** (propose → exchange → revise → advance only on explicit release), **curation** (interrogate + override on any turn; record overrides as `human`), the **export-then-async-read** ordering (export at step 8, never block on reading), and the three **Resume** modes. No script driver.
<<<<<<< HEAD
- `prompts/litreview.md` — align to the same loop; `/litreview` is the in-session entry.
=======
- `prompts/callimachus.md` — align to the same loop; `/callimachus` is the in-session entry.
>>>>>>> devin/1789827103-hypathia

**Configuration cleanup** (consequences of deleting `assess.mjs`):
- Drop the `@mariozechner/pi-ai` (or `@earendil-works/pi-ai`) **dependency** from `package.json`. It was only for the scorer; the LLM's model comes from Pi itself (`pi-coding-agent`), which remains the harness.
- Drop the `ARLANDRIA_MODEL` / `ARLANDRIA_MODEL_BASEURL` env vars (also scorer-only). Keep `ARLANDRIA_EMAIL` (polite-pool identity for `search.py` / `resolve.py`).
- `pi-docparser` (full-text extraction) and `pi-subagents` (optional screening sub-agents for large batches) remain optional Pi packages, not required by this spec.

---

## 7. Non-goals

Explicitly out of scope, to prevent reintroduction:
- No deterministic Python loop driving the review (the LLM orchestrates).
- No separate LLM scorer / Node assess step (the LLM is the decision-maker; pi-ai is already its model).
- No embedding ranker or top-N prefilter that decides which abstracts are read — every retrieved paper is screened.
- No silent exclusions — any shortcut is the researcher's explicit choice and is visible.
- No one-shot gates — the LLM must not advance past an interactive gate on an ambiguous reply; it advances only on an explicit release.
- No overwriting human curation — the re-screen never revises `decided_by: human` records.
- **No blocking on the researcher's reading** — the deliverable export (step 8) precedes full-text reading; the LLM never waits on step 9, and export is re-runnable, not terminal.
- No synthesis prose and no PRISMA artifact in v1 — deliverable is BibTeX + CSV; PRISMA is a later derived view.
- `arlandria` does not run-and-exit — it is a persistent interactive session.
