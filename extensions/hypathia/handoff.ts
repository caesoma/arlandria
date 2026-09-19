import { createHmac, randomBytes, randomUUID, timingSafeEqual } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { ApprovalSchema, ExtractionSchema, HandoffSchema, LedgerSchema, SourcesSchema, parse, type Handoff, type Ledger, type Sources } from "./schema.js";
import { atomicWrite, hash, inside, json, readJson } from "./storage.js";

export type Gate = "criteria" | "triage" | "curation";
const signerDirectory = () => join(homedir(), ".arlandria");

function key(create: boolean): Buffer {
  const directory = signerDirectory();
  const path = join(directory, "completion.key");
  if (create && !existsSync(path)) {
    mkdirSync(directory, { recursive: true, mode: 0o700 });
    try { writeFileSync(path, randomBytes(32), { flag: "wx", mode: 0o600 }); }
    catch (error) { if (!existsSync(path)) throw error; }
  }
  return readFileSync(path);
}

function seal(value: Omit<Handoff, "seal">, create = false): string {
  return createHmac("sha256", key(create)).update(json(value)).digest("hex");
}

export function gateFingerprint(root: string, gate: Gate): string {
  const ledger = parse(LedgerSchema, readJson(join(root, "ledger.json")));
  const criteria = { question: ledger.question, criteria: ledger.criteria };
  if (gate === "criteria") return hash(json(criteria));
  if (gate === "triage") return hash(json({
    ...criteria, queries: ledger.queries,
    records: ledger.records.map(r => ({ id: r.id, status: r.status, abstract: r.screening.abstract })),
  }));
  const registry = parse(SourcesSchema, readJson(join(root, "sources.json")));
  return hash(json({
    ledger: hash(readFileSync(join(root, "ledger.json"))),
    registry: hash(readFileSync(join(root, "sources.json"))),
    artifacts: registry.sources.filter(s => s.kind === "fulltext").map(s => ({
      pdf: hash(readFileSync(inside(root, s.pdf))),
      extraction: hash(readFileSync(inside(root, s.extraction))),
    })),
  }));
}

// Called by the user-facing Callimachus approval command, never a Hypathia tool.
export function approveGate(root: string, gate: Gate, fingerprint: string) {
  if (fingerprint !== gateFingerprint(root, gate)) throw new Error("Review changed during approval; review it again");
  const directory = join(root, ".callimachus");
  mkdirSync(directory, { recursive: true });
  const path = inside(root, ".callimachus/approvals.json");
  const approvals = existsSync(path) ? parse(ApprovalSchema, readJson(path)) : {};
  atomicWrite(path, json({ ...approvals, [gate]: fingerprint }));
}

function completionInputs(root: string) {
  const ledger = parse(LedgerSchema, readJson(join(root, "ledger.json")));
  const registry = parse(SourcesSchema, readJson(join(root, "sources.json")));
  const approvals = parse(ApprovalSchema, readJson(inside(root, ".callimachus/approvals.json")));
  for (const gate of ["criteria", "triage", "curation"] as const)
    if (approvals[gate] !== gateFingerprint(root, gate)) throw new Error(`Pending or stale ${gate} approval`);
  if (!ledger.queries.length) throw new Error("No completed search/pool audit");
  if (new Set(ledger.records.map(r => r.id)).size !== ledger.records.length) throw new Error("Duplicate record IDs");
  for (const record of ledger.records) {
    const { abstract, fulltext } = record.screening;
    if (!["include", "exclude", "borderline"].includes(abstract.decision))
      throw new Error(`Abstract screening incomplete: ${record.id}`);
    if (abstract.criteria_version !== ledger.criteria.version && abstract.decided_by !== "human")
      throw new Error(`Stale abstract decision: ${record.id}`);
    if (record.status === "deferred") continue;
    if (abstract.decision !== "exclude" || fulltext.decision === "include") {
      if (!["include", "exclude"].includes(fulltext.decision) || fulltext.decided_by !== "human" || !fulltext.reason)
        throw new Error(`Human full-text disposition required: ${record.id}`);
    }
  }
  const included = ledger.records.filter(r => r.status === "active" && r.screening.fulltext.decision === "include");
  const ids = included.map(r => r.id).sort();
  if (json(registry.sources.map(s => s.record_id).sort()) !== json(ids))
    throw new Error("Source registry must match the final included set exactly");
  return { ledger, registry, included, approvals };
}

export function finalize(root: string): string {
  root = resolve(root);
  const { ledger, registry, included, approvals } = completionInputs(root);
  const revision = randomUUID();
  const base = inside(root, ".callimachus/completed");
  mkdirSync(base, { recursive: true });
  const pending = inside(root, `.callimachus/completed/${revision}.partial`);
  mkdirSync(pending);
  const artifacts: Record<string, string> = {};
  const write = (name: string, data: Buffer | string) => {
    writeFileSync(join(pending, name), data, { flag: "wx" });
    artifacts[name] = hash(data);
  };
  write("ledger.json", readFileSync(join(root, "ledger.json")));
  write("sources.json", json(registry));
  const sources: Handoff["sources"] = [];
  for (const [index, entry] of registry.sources.entries()) {
    const record = included.find(r => r.id === entry.record_id)!;
    const artifact = `source-${index}.json`;
    if (entry.kind === "fulltext") {
      const extraction = parse(ExtractionSchema, readJson(inside(root, entry.extraction)));
      const pdf = readFileSync(inside(root, entry.pdf));
      if (hash(pdf) !== extraction.pdf_sha256) throw new Error(`PDF/extraction mismatch: ${record.id}`);
      if (!extraction.pages.some(p => p.text.trim())) throw new Error(`Empty extraction: ${record.id}`);
      if (extraction.pages.some((p, i) => p.page !== i + 1)) throw new Error("Invalid page sequence");
      write(`source-${index}.pdf`, pdf);
      write(artifact, json(extraction));
      sources.push({ record_id: record.id, kind: "fulltext", artifact, limitation: "", warnings: extraction.warnings });
    } else {
      if (!record.abstract?.trim()) throw new Error(`No usable abstract: ${record.id}`);
      write(artifact, json({ pages: [{ page: 1, text: record.abstract }] }));
      sources.push({ record_id: record.id, kind: "abstract", artifact, limitation: entry.limitation, warnings: [] });
    }
  }
  const exporter = fileURLToPath(new URL("../../skills/literature-review/scripts/export.py", import.meta.url));
  for (const format of ["bibtex", "csv"]) {
    const result = spawnSync("uv", ["run", exporter, "--ledger", join(pending, "ledger.json"), "--format", format, "--stdout"], { encoding: "utf8" });
    if (result.error || result.status !== 0) throw new Error(`Final export failed: ${result.error?.message ?? result.stderr}`);
    write(format === "bibtex" ? "references.bib" : "references.csv", result.stdout);
  }
  const unsigned: Omit<Handoff, "seal"> = {
    schema_version: 1, producer: "callimachus", status: "completed", run_id: revision,
    review_id: ledger.review_id, revision, completed_at: new Date().toISOString(),
    criteria_version: ledger.criteria.version, cutoff: registry.cutoff,
    ledger_sha256: hash(readFileSync(join(root, "ledger.json"))),
    sources_sha256: hash(readFileSync(join(root, "sources.json"))),
    included_ids: included.map(r => r.id),
    stages: { question: "completed", criteria: "completed", query: "completed", pool: "completed",
      screen: "completed", triage: "completed", refine: "completed", export: "completed", curation: "completed" },
    gates: { criteria: approvals.criteria!, triage: approvals.triage!, curation: approvals.curation! },
    sources, artifacts,
  };
  const handoff = { ...unsigned, seal: seal(unsigned, true) };
  writeFileSync(join(pending, "handoff.json"), json(handoff), { flag: "wx" });
  completionInputs(root);
  if (unsigned.ledger_sha256 !== hash(readFileSync(join(root, "ledger.json"))) ||
      unsigned.sources_sha256 !== hash(readFileSync(join(root, "sources.json"))))
    throw new Error("Review changed during finalization");
  const final = join(base, revision);
  renameSync(pending, final);
  atomicWrite(inside(root, ".callimachus/current.json"), json({ revision }));
  return revision;
}

export interface Snapshot {
  root: string;
  directory: string;
  handoff: Handoff;
  ledger: Ledger;
  registry: Sources;
}

export function loadSnapshot(root: string, revision?: string): Snapshot {
  root = resolve(root);
  const current = readJson(inside(root, ".callimachus/current.json"));
  if (typeof current !== "object" || current === null || !("revision" in current) ||
      typeof current.revision !== "string" || !/^[\w-]+$/.test(current.revision))
    throw new Error("Invalid completion pointer");
  if (revision && revision !== current.revision) throw new Error("A newer Callimachus revision requires a new synthesis");
  const directory = inside(root, `.callimachus/completed/${current.revision}`);
  const handoff = parse(HandoffSchema, readJson(inside(directory, "handoff.json")));
  const { seal: signature, ...unsigned } = handoff;
  const expected = seal(unsigned);
  if (!/^[a-f0-9]{64}$/.test(signature) || !timingSafeEqual(Buffer.from(signature), Buffer.from(expected)))
    throw new Error("Untrusted Callimachus completion record");
  if (handoff.revision !== current.revision) throw new Error("Revision mismatch");
  for (const [name, digest] of Object.entries(handoff.artifacts))
    if (hash(readFileSync(inside(directory, name))) !== digest) throw new Error(`Modified snapshot artifact: ${name}`);
  if (hash(readFileSync(join(root, "ledger.json"))) !== handoff.ledger_sha256 ||
      hash(readFileSync(join(root, "sources.json"))) !== handoff.sources_sha256)
    throw new Error("Callimachus has changed; complete its workflow before continuing Hypathia");
  const { ledger, registry } = completionInputs(root);
  for (const entry of registry.sources) {
    if (entry.kind !== "fulltext") continue;
    const source = handoff.sources.find(s => s.record_id === entry.record_id)!;
    if (hash(json(parse(ExtractionSchema, readJson(inside(root, entry.extraction))))) !== handoff.artifacts[source.artifact] ||
        hash(readFileSync(inside(root, entry.pdf))) !== parse(ExtractionSchema, readJson(inside(directory, source.artifact))).pdf_sha256)
      throw new Error(`Upstream source changed: ${entry.record_id}`);
  }
  return { root, directory, handoff, ledger, registry };
}
