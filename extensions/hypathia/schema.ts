import { Type, type Static, type TSchema } from "typebox";
import { Check } from "typebox/value";

const text = Type.String({ minLength: 1 });
const id = Type.String({ pattern: "^[a-zA-Z0-9_-]+$" });
const strings = Type.Array(text, { uniqueItems: true });
const choice = <const T extends string[]>(...values: T) => Type.Enum(values);
const object = <T extends Record<string, TSchema>>(fields: T) =>
  Type.Object(fields, { additionalProperties: false });

export function parse<T extends TSchema>(schema: T, value: unknown): Static<T> {
  if (!Check(schema, value)) throw new Error("Invalid data: does not match the required schema");
  return value;
}

const Decision = Type.Object({
  decision: choice("unscreened", "include", "exclude", "borderline", "not_applicable"),
  reason: Type.Union([text, Type.Null()]),
  criteria_version: Type.Union([Type.Integer(), Type.Null()]),
  decided_by: choice("llm", "human"),
});
export const LedgerSchema = Type.Object({
  review_id: text,
  question: text,
  criteria: Type.Object({ version: Type.Integer({ minimum: 1 }), include: strings, exclude: strings }),
  queries: Type.Array(Type.Object({
    id: text, round: Type.Integer({ minimum: 1 }), source: text,
    query_string: text, run_at: text, n_returned: Type.Integer({ minimum: 0 }),
  })),
  records: Type.Array(Type.Object({
    id: text, title: text, abstract: Type.Union([Type.String(), Type.Null()]),
    year: Type.Union([Type.Integer(), Type.Null()]),
    doi: Type.Union([Type.String(), Type.Null()]),
    authors: Type.Array(Type.String()),
    status: choice("active", "deferred"),
    screening: Type.Object({ abstract: Decision, fulltext: Decision }),
  })),
});
export type Ledger = Static<typeof LedgerSchema>;
export const ExtractionSchema = object({
  schema_version: Type.Literal(1),
  pdf_sha256: text,
  extractor: text,
  pages: Type.Array(object({ page: Type.Integer({ minimum: 1 }), text: Type.String() }), { minItems: 1 }),
  warnings: strings,
});
export const SourcesSchema = object({
  cutoff: Type.String({ pattern: "^\\d{4}-\\d{2}-\\d{2}$" }),
  sources: Type.Array(Type.Union([
    object({ record_id: text, kind: Type.Literal("fulltext"), pdf: text, extraction: text }),
    object({ record_id: text, kind: Type.Literal("abstract"), limitation: text }),
  ])),
});
export type Sources = Static<typeof SourcesSchema>;
export const SourceSchema = object({
  record_id: text, kind: choice("fulltext", "abstract"), artifact: text,
  limitation: Type.String(), warnings: strings,
});
export const HandoffSchema = object({
  schema_version: Type.Literal(1),
  producer: Type.Literal("callimachus"),
  status: Type.Literal("completed"),
  run_id: id, review_id: text, revision: id, completed_at: text,
  criteria_version: Type.Integer({ minimum: 1 }), cutoff: text,
  ledger_sha256: text, sources_sha256: text,
  included_ids: strings,
  stages: object({
    question: Type.Literal("completed"), criteria: Type.Literal("completed"),
    query: Type.Literal("completed"), pool: Type.Literal("completed"),
    screen: Type.Literal("completed"), triage: Type.Literal("completed"),
    refine: Type.Literal("completed"), export: Type.Literal("completed"),
    curation: Type.Literal("completed"),
  }),
  gates: object({ criteria: text, triage: text, curation: text }),
  sources: Type.Array(SourceSchema),
  artifacts: Type.Record(Type.String(), text),
  seal: text,
});
export type Handoff = Static<typeof HandoffSchema>;
export const ApprovalSchema = object({
  criteria: Type.Optional(text), triage: Type.Optional(text), curation: Type.Optional(text),
});

export const ClaimSchema = object({
  id, source_id: text, page: Type.Integer({ minimum: 1 }),
  quote: text, statement: text,
  kind: choice("finding", "limitation", "gap", "direction", "context"),
  verification: object({ status: choice("supported", "uncertain", "contradicted"), reason: text }),
  appraisal: text,
  study_id: Type.Union([text, Type.Null()]),
});
export const FindingSchema = object({
  id, statement: text, claim_ids: Type.Array(id, { minItems: 1, uniqueItems: true }),
  disagreements: Type.Array(id, { uniqueItems: true }), strength: text,
});
export const GapSchema = object({
  id, statement: text, claim_ids: Type.Array(id, { minItems: 1, uniqueItems: true }),
  status: choice("open-in-reviewed-corpus", "partly-addressed", "addressed", "unresolved"),
  currency: object({ checked_source_ids: strings, claim_ids: Type.Array(id), rationale: text }),
});
export const OpportunitySchema = object({
  id, gap_id: id, direction_claim_ids: Type.Array(id, { minItems: 1, uniqueItems: true }),
  feasibility: object({
    effort: choice("low", "medium", "high", "unknown"),
    rationale: text, prerequisites: strings, unknowns: strings,
    resource_ids: Type.Array(id, { uniqueItems: true }),
  }),
});
export const EvidenceSchema = object({
  schema_version: Type.Literal(1), handoff_revision: id,
  claims: Type.Array(ClaimSchema), findings: Type.Array(FindingSchema),
  gaps: Type.Array(GapSchema), opportunities: Type.Array(OpportunitySchema),
  source_reviews: Type.Array(object({
    source_id: text, status: choice("reviewed", "unreadable"), note: text,
  })),
});
export type Evidence = Static<typeof EvidenceSchema>;
export type Claim = Static<typeof ClaimSchema>;
export const ContextSchema = object({
  audience: text,
  resources: Type.Array(object({ id, description: text })),
});
export type ResearchContext = Static<typeof ContextSchema>;
