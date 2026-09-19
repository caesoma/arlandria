# Completion, evidence, and output contracts

## Callimachus completion

Callimachus continues to support early reading-list exports. Hypathia additionally
requires human approval of three gates through the extension:

```
/callimachus-approve criteria /path/to/review
/callimachus-approve triage /path/to/review
/callimachus-approve curation /path/to/review
```

Criteria approval is tied to the question and criteria version. Triage approval
is tied to the criteria, query audit, abstract decisions, and record status.
Curation approval is tied to the final ledger, source registry, and source bytes.
An edit invalidates the affected approvals. Pending human decisions cannot be
released by a model tool. Commands present a confirmation dialog to the user.

Before approving curation, Callimachus must:

1. Screen every abstract under current criteria (existing human decisions remain
   locked). Resolve active included/borderline records with a human full-text
   include/exclude disposition and reason.
2. For each final included publication, prepare page-located text with:
   `uv run skills/literature-review/scripts/pdf_extract.py --pdf paper.pdf --structured --out paper.json`.
3. Write `sources.json` in the review folder. Paths are relative to that folder;
   absolute paths, traversal, and symlinks are rejected:

```json
{
  "cutoff": "2026-09-19",
  "sources": [
    {
      "record_id": "10.example/paper",
      "kind": "fulltext",
      "pdf": "pdfs/paper.pdf",
      "extraction": "pdfs/paper.json"
    },
    {
      "record_id": "10.example/unavailable",
      "kind": "abstract",
      "limitation": "No legal full text was available; researcher approved terminal abstract-only inclusion."
    }
  ]
}
```

The source list must exactly match active full-text includes. An abstract-only
entry is a terminal, explicitly approved access limitation, not permission to
skip curation. Callimachus records the human disposition with `ledger.py decide
--stage fulltext --by human`, with the access limitation in the reason.
Neither `not_applicable` nor `unscreened` qualifies for an active inclusion.

The curation command validates prerequisites, re-exports BibTeX/CSV, copies
source artifacts and the ledger into `.callimachus/completed/<revision>/`, and
publishes `.callimachus/current.json` only after success. The sealed `handoff.json`
includes stage outcomes, gate fingerprints, cutoff, final IDs, and artifact hashes.

The seal uses a host-owned key at `~/.arlandria/completion.key`. Hypathia cannot
read the key or invoke the finalizer. Hashes establish integrity; the seal
establishes the local Callimachus producer. This is a local agent capability
boundary, not protection against a user or process that already controls the
machine. Moving a review to another machine requires fresh gate approval and
finalization there. Keep the original completion directory for historical audit.

## Evidence

The executable schemas are in `extensions/hypathia/schema.ts`. Example:

```json
{
  "schema_version": 1,
  "handoff_revision": "revision-from-the-handoff",
  "claims": [{
    "id": "c1", "source_id": "10.example/paper", "page": 5,
    "quote": "Future work should evaluate this approach in rural clinics.",
    "statement": "The authors propose evaluating the approach in rural clinics.",
    "kind": "direction",
    "verification": {"status": "supported", "reason": "Explicit author proposal; not a demonstrated result."},
    "appraisal": "A proposal, with no feasibility estimate.",
    "study_id": null
  }],
  "findings": [],
  "gaps": [],
  "opportunities": [],
  "source_reviews": [{
    "source_id": "10.example/paper",
    "status": "reviewed",
    "note": "Read all supplied pages; no explicit gap claim beyond the proposed setting."
  }]
}
```

Quote verification is exact, scoped to the source and page. Semantic verification
is an explicit agent assessment, not a deterministic entailment guarantee.
Findings may use only supported claims. Gaps require gap/limitation claims.
Opportunities require direction claims; a limitation alone cannot become an
action. A non-unresolved gap requires a currency check covering the entire
included set. Addressed/partly-addressed statuses also require evidence.

Low effort requires known prerequisites, no declared material unknowns, researcher
resource IDs supplied outside the synthesis model, and a gap that remains open
or partly addressed within the corpus. Resource descriptions are constraints,
not a fabricated cost model. Unknowns are never scored as zero effort.

## Storage and delivery

Hypathia writes only `.hypathia/` under the selected review:

```
request.json
<callimachus-revision>/
  context.json
  evidence.json
  history/<evidence-hash>.json
  delivery.json
  exports/<evidence-and-context-hash>/
    report.md
    brief.md
    evidence-matrix.svg
    opportunity-matrix.svg
    gap-directions.svg
    review-flow.svg
    evidence.json
    context.json
    references.bib
    references.csv
    provenance.json
```

Writes use atomic replacement; evidence versions and deliveries retain history.
All sources need a reviewed/unreadable disposition before rendering. Changing
the ledger, source registry, extraction, PDF, or completion revision blocks tool
calls until Callimachus completes again. No previously generated report is
silently reused against a new revision.

`/hypathia question <question>` uses a stable review folder keyed by normalized
question under the working directory's `reviews/`. Reuse that folder rather than
starting another review. If a matching review already lives elsewhere, supply its
folder explicitly. Resume Callimachus in the same folder after a session restart.
