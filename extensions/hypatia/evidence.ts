import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { Type } from "typebox";
import { ContextSchema, EvidenceSchema, parse, type Evidence, type ResearchContext } from "./schema.js";
import { loadSnapshot, type Snapshot } from "./handoff.js";
import { atomicWrite, hash, inside, json, readJson } from "./storage.js";

const Pages = Type.Object({ pages: Type.Array(Type.Object({ page: Type.Integer(), text: Type.String() })) });

export function sourcePages(snapshot: Snapshot, sourceId: string) {
  const source = snapshot.handoff.sources.find(s => s.record_id === sourceId);
  if (!source) throw new Error("Source is not in the completed Callimachus result");
  return parse(Pages, readJson(inside(snapshot.directory, source.artifact))).pages;
}

export function validateEvidence(snapshot: Snapshot, input: unknown, context: ResearchContext): Evidence {
  const evidence = parse(EvidenceSchema, input);
  if (evidence.handoff_revision !== snapshot.handoff.revision) throw new Error("Evidence references a different revision");
  const seen = new Set<string>();
  for (const item of [...evidence.claims, ...evidence.findings, ...evidence.gaps, ...evidence.opportunities]) {
    if (seen.has(item.id)) throw new Error(`Duplicate evidence ID: ${item.id}`);
    seen.add(item.id);
  }
  const claims = new Map(evidence.claims.map(c => [c.id, c]));
  const supported = (ids: string[]) => ids.map(id => {
    const claim = claims.get(id);
    if (!claim || claim.verification.status !== "supported") throw new Error(`Unsupported claim: ${id}`);
    return claim;
  });
  for (const claim of evidence.claims) {
    const page = sourcePages(snapshot, claim.source_id).find(p => p.page === claim.page);
    if (!page?.text.includes(claim.quote)) throw new Error(`Quote not found on cited page: ${claim.id}`);
  }
  for (const finding of evidence.findings) {
    supported(finding.claim_ids);
    for (const id of finding.disagreements)
      if (!claims.has(id)) throw new Error(`Missing disagreement evidence: ${id}`);
  }
  for (const gap of evidence.gaps) {
    if (supported(gap.claim_ids).some(c => c.kind !== "gap" && c.kind !== "limitation"))
      throw new Error(`Gap requires author-stated gap/limitation evidence: ${gap.id}`);
    supported(gap.currency.claim_ids);
    const checked = gap.currency.checked_source_ids;
    if (checked.some(id => !snapshot.handoff.included_ids.includes(id))) throw new Error("Currency check cites an external source");
    if (gap.status !== "unresolved" &&
        json([...checked].sort()) !== json([...snapshot.handoff.included_ids].sort()))
      throw new Error(`Currency check must cover the completed corpus: ${gap.id}`);
    if (["addressed", "partly-addressed"].includes(gap.status) && !gap.currency.claim_ids.length)
      throw new Error("Addressed gaps require supporting claims");
  }
  for (const opportunity of evidence.opportunities) {
    const gap = evidence.gaps.find(g => g.id === opportunity.gap_id);
    if (!gap) throw new Error("Opportunity references a missing gap");
    if (supported(opportunity.direction_claim_ids).some(c => c.kind !== "direction"))
      throw new Error("An opportunity requires an explicit author-proposed direction");
    const { feasibility } = opportunity;
    if (feasibility.resource_ids.some(id => !context.resources.some(r => r.id === id)))
      throw new Error("Feasibility references a resource the researcher did not supply");
    if (feasibility.effort === "low" && (
      !["open-in-reviewed-corpus", "partly-addressed"].includes(gap.status) ||
      feasibility.unknowns.length || !feasibility.resource_ids.length || !feasibility.prerequisites.length))
      throw new Error("Low effort requires current gap, known prerequisites, and researcher resources");
  }
  const reviewed = evidence.source_reviews.map(r => r.source_id);
  if (new Set(reviewed).size !== reviewed.length || reviewed.some(id => !snapshot.handoff.included_ids.includes(id)))
    throw new Error("Invalid source review coverage");
  return evidence;
}

export function validateDelivery(snapshot: Snapshot, evidence: Evidence) {
  const reviewed = evidence.source_reviews.map(r => r.source_id).sort();
  if (json(reviewed) !== json([...snapshot.handoff.included_ids].sort()))
    throw new Error("Every included source needs a review or unreadable disposition before delivery");
  for (const claim of evidence.claims) {
    const review = evidence.source_reviews.find(r => r.source_id === claim.source_id);
    if (review?.status === "unreadable" && claim.verification.status === "supported")
      throw new Error("Unreadable sources cannot support verified claims");
  }
}

export function evidenceDirectory(snapshot: Snapshot): string {
  const root = inside(snapshot.root, ".hypatia");
  mkdirSync(root, { recursive: true });
  const directory = inside(snapshot.root, `.hypatia/${snapshot.handoff.revision}`);
  mkdirSync(directory, { recursive: true });
  return directory;
}

export function loadContext(snapshot: Snapshot): ResearchContext {
  return parse(ContextSchema, readJson(inside(evidenceDirectory(snapshot), "context.json")));
}

export function loadEvidence(snapshot: Snapshot): Evidence {
  const file = inside(evidenceDirectory(snapshot), "evidence.json");
  return existsSync(file) ? validateEvidence(snapshot, readJson(file), loadContext(snapshot)) : {
    schema_version: 1, handoff_revision: snapshot.handoff.revision,
    claims: [], findings: [], gaps: [], opportunities: [], source_reviews: [],
  };
}

export function saveEvidence(snapshot: Snapshot, input: unknown): string {
  loadSnapshot(snapshot.root, snapshot.handoff.revision);
  const context = loadContext(snapshot);
  const evidence = validateEvidence(snapshot, input, context);
  const directory = evidenceDirectory(snapshot);
  const digest = hash(json(evidence));
  const history = inside(directory, "history");
  mkdirSync(history, { recursive: true });
  const file = inside(directory, `history/${digest}.json`);
  if (!existsSync(file)) atomicWrite(file, json(evidence));
  atomicWrite(inside(directory, "evidence.json"), json(evidence));
  return digest;
}

export function evidenceDigest(snapshot: Snapshot): string {
  return hash(readFileSync(inside(evidenceDirectory(snapshot), "evidence.json")) +
    "\n" + readFileSync(inside(evidenceDirectory(snapshot), "context.json")));
}
