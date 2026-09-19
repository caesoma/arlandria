# Review Ledger - schema

One JSON file per review (`<base>/<slug>/ledger.json`) - the durable artifact, reopened across sessions. The single source of truth; `ledger.py` is its only writer. Comments are JSONC for humans; store as plain JSON.

## Search record (the shared backend contract)

Every `search.py` backend normalises its API response onto this **lean** shape and prints
`{"source", "query", "n", "records": [<search record>...], "cost_usd"?}` to stdout. This is pure
retrieval payload - no screening/ledger state. `dedupe.py` maps each search record onto a ledger
entry (`_common.ledger_entry`) before storing it; the two schemas are intentionally distinct.

```jsonc
{
  "doi": "str|null",            // canonical: lowercased, resolver prefix stripped
  "arxiv_id": "str|null",
  "pmid": "str|null",
  "title": "str|null",
  "authors": ["str"],           // [] when unknown
  "year": 2023,                 // int|null
  "venue": "str|null",
  "abstract": "str|null",       // OpenAlex inverted index is reconstructed to plain text here
  "oa_status": "str|null",      // open|closed|green|gold|hybrid|bronze - NEVER filtered at search
  "pdf_url": "str|null",        // best free PDF/landing url known at search time
  "referenced_works": ["str"],  // outbound reference ids - snowballing seed; [] when unknown
  "cited_by_count": 87,         // int|null
  "source_backend": "openalex", // which backend emitted this record
  "raw_id": "str|null"          // backend-native id (openalex W..., s2 paperId, ...)
}
```

Missing fields are `null` (lists default to `[]`). Backends never filter by `is_oa`: closed/paywalled
works are returned so the LLM can screen them on the abstract.

## Ledger entry

```jsonc
{
  "review_id": "str",
  "created": "ISO8601",
  "updated": "ISO8601",
  "question": "the original plain-English question",

  "criteria": {                       // versioned; refined by the clarifying loop
    "version": 3,
    "include": ["str"],
    "exclude": ["str"],
    "history": [ { "version": 1, "at": "ISO8601", "include": [], "exclude": [] } ]
  },

  "queries": [                        // every query run - reproducibility
    { "id": "q1", "round": 1, "source": "pubmed", "query_string": "str",
      "run_at": "ISO8601", "n_returned": 142 }
  ],

  "exchanges": [                      // append-only log of gate-exchange summaries (ledger.py note)
    { "at": "ISO8601", "gate": "criteria",   // criteria (step 2) | triage (step 6)
      "criteria_version": 3,                 // the scope version in effect when noted
      "text": "free-text rationale from the human<->LLM exchange" }
  ],

  "stats": {                          // derived from records on every write (except `found`, which accumulates)
    "found": 0, "deduped": 0,
    "screened_abstract": 0, "included_abstract": 0,
    "screened_fulltext": 0, "included_fulltext": 0, "deferred": 0
  },

  "records": [
    {
      "id": "stable hash (DOI, else normalized title)",
      "doi": "str|null",
      "ids": { "pmid": "...", "arxiv": "...", "openalex": "...", "s2": "..." },

      "title": "str", "abstract": "str|null", "authors": ["str"],
      "year": 2023, "venue": "str|null", "citations": 87,   // citations = search record's cited_by_count
      "referenced_works": ["W123"],        // outbound refs (snowballing); from the search record
      "oa_status": "closed",               // open|closed|green|gold|hybrid|bronze|null
      "sources": ["pubmed", "openalex"],   // which backends surfaced it (= source_backend, dedupe merge)
      "found_by": ["q1", "q4"],            // which query ids hit it

      "status": "active",                  // active | deferred  (orthogonal to decision)

      // is_oa is seeded from oa_status (closed -> false), then confirmed by resolve.py.
      // fulltext == "closed, metadata-only" when resolve found no legal OA copy (record is kept, not dropped).
      "oa": { "is_oa": null, "url": "str|null", "pdf_path": "str|null",
              "fulltext_path": "str|null", "fulltext": "str|null" },

      "screening": {
        "abstract": { "decision": "unscreened",   // unscreened | include | exclude | borderline
                      "reason": "str|null", "at": "ISO8601|null", "criteria_version": 3,
                      "decided_by": "llm",         // llm | human
                      "proposed": null },          // LLM's original, kept when a human overrides
        "fulltext": { "decision": "unscreened",    // unscreened | include | exclude | not_applicable
                      "reason": "str|null", "at": "ISO8601|null", "criteria_version": 3,
                      "decided_by": "llm",
                      "proposed": null }
      },

      "assessment": { "relevance": null,           // high | med | low | null
                      "covers": [], "summary": "str|null",
                      "strength": "str|null", "read_in_full": false },

      "notes": "str|null"
    }
  ]
}
```

## Enums
- `screening.abstract.decision`: `unscreened | include | exclude | borderline`
- `screening.fulltext.decision`: `unscreened | include | exclude | not_applicable`
- `status`: `active | deferred`
- `decided_by`: `llm | human`
- `relevance`: `high | med | low | null`

## Invariants
- Records are never deleted; `exclude` is a decision and `deferred` is a status - both reversible.
- **Exchange log**: `exchanges[]` is an append-only, review-level record of the gate exchanges (written by `ledger.py note`); entries are never overwritten or deleted. It captures *why* the scope is what it is - distinct from a record's per-paper `notes`.
- `ledger.py` is the only writer of `criteria` / `screening` / `status`. No hand-editing. (`resolve.py` writes only `oa.*` and may backfill `abstract`/`venue` from Crossref.)
- **Human decisions are locked**: an LLM re-screen revises only `decided_by:"llm"` records. Overridden LLM calls are retained in `proposed`.
- **Closed access is screened, not dropped**: backends never filter by `is_oa`; a closed work with no OA copy is kept and marked `oa.fulltext = "closed, metadata-only"` by `resolve.py`.
- **Dedupe precedence**: DOI -> arXiv id -> PMID -> normalized(title)+year. A preprint and its version-of-record merge into one entry (VoR metadata preferred, both source ids kept); the stored entry's `id` is stable across the merge.
- **Stats**: `found` is cumulative gross hits across all dedupe runs (it only grows); the other counts (`deduped`, `screened_*`, `included_*`, `deferred`) are recomputed from `records` on every write.
- Effective-include (export): `status==active` and (`fulltext.decision=="include"` or (`fulltext.decision=="unscreened"` and `abstract.decision=="include"`)).
- Filtering and "which cover X best" are reads over `records`. No new search.
