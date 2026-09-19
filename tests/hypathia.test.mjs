import assert from "node:assert/strict";
import { after, test } from "node:test";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, symlinkSync, rmSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { homedir } from "node:os";
import { spawnSync } from "node:child_process";
import { createJiti } from "jiti";
import { AuthStorage, ModelRegistry, createAgentSession } from "@earendil-works/pi-coding-agent";

const sandbox = mkdtempSync(join(homedir(), ".hypathia-tests-"));
// Keep signing keys and SDK discovery isolated from the developer's real home.
const originalHome = process.env.HOME;
process.env.HOME = sandbox;
after(() => { process.env.HOME = originalHome; rmSync(sandbox, { recursive: true }); });
const jiti = createJiti(import.meta.url);
const { approveGate, gateFingerprint, finalize, loadSnapshot } = await jiti.import("../extensions/hypathia/handoff.ts");
const { validateEvidence, saveEvidence, evidenceDirectory, loadEvidence } = await jiti.import("../extensions/hypathia/evidence.ts");
const { render, shortlist } = await jiti.import("../extensions/hypathia/render.ts");
const { restrictedTools, isolatedOptions, toolNames } = await jiti.import("../extensions/hypathia/runtime.ts");
const { hash, json, inside } = await jiti.import("../extensions/hypathia/storage.ts");
const { default: extension } = await jiti.import("../extensions/hypathia/index.ts");

const text = "We found an association, not causation. Rural settings remain untested. Future work should evaluate rural clinics.";
const writeJson = (path, value) => writeFileSync(path, json(value));
const readJson = path => JSON.parse(readFileSync(path, "utf8"));

function fixture({ fulltext = false, completed = true } = {}) {
  const root = mkdtempSync(join(sandbox, "review-"));
  const decision = (decision, by = "llm") => ({
    decision, decided_by: by, reason: "Researcher-approved scope and disposition.",
    criteria_version: 1, at: "2026-09-19", proposed: null,
  });
  const ledger = {
    review_id: "test-review", question: "What is established about this association?",
    criteria: { version: 1, include: ["Relevant evidence"], exclude: [] },
    queries: [{ id: "q1", query: "completed upstream search", at: "2026-09-19" }],
    records: [{
      id: "paper-1", title: "Synthetic fixture, not research evidence", abstract: text,
      year: 2025, doi: null, authors: ["Fixture Author"], status: "active",
      screening: { abstract: decision("include"), fulltext: decision("include", "human") },
      assessment: { relevance: "high", covers: [], read_in_full: fulltext },
    }],
  };
  writeJson(join(root, "ledger.json"), ledger);
  const sources = {
    cutoff: "2026-09-19", sources: fulltext
      ? [{ record_id: "paper-1", kind: "fulltext", pdf: "paper.pdf", extraction: "paper.json" }]
      : [{ record_id: "paper-1", kind: "abstract", limitation: "Researcher approved unavailable full text." }],
  };
  if (fulltext) {
    writeFileSync(join(root, "paper.pdf"), "synthetic source bytes");
    writeJson(join(root, "paper.json"), {
      schema_version: 1, pdf_sha256: hash("synthetic source bytes"), extractor: "test fixture",
      pages: [{ page: 1, text }], warnings: ["Synthetic fixture only"],
    });
  }
  writeJson(join(root, "sources.json"), sources);
  for (const gate of ["criteria", "triage", "curation"])
    approveGate(root, gate, gateFingerprint(root, gate));
  if (!completed) return { root, ledger, sources };
  finalize(root);
  const snapshot = loadSnapshot(root);
  writeJson(join(evidenceDirectory(snapshot), "context.json"), {
    audience: "Research peers", resources: [{ id: "r1", description: "Approved clinic data and analysis expertise." }],
  });
  return { root, ledger, sources, snapshot };
}

function evidence(snapshot) {
  const claim = (id, quote, kind) => ({
    id, source_id: "paper-1", page: 1, quote, statement: quote, kind,
    verification: { status: "supported", reason: "The fixture says this verbatim with the stated uncertainty." },
    appraisal: "Synthetic data used only for regression testing.", study_id: null,
  });
  return {
    schema_version: 1, handoff_revision: snapshot.handoff.revision,
    claims: [claim("c1", "We found an association, not causation.", "finding"),
      claim("c2", "Rural settings remain untested.", "gap"),
      claim("c3", "Future work should evaluate rural clinics.", "direction")],
    findings: [{ id: "f1", statement: "The association does not establish causation.", claim_ids: ["c1"], disagreements: [], strength: "Observational only." }],
    gaps: [{ id: "g1", statement: "Rural settings remain untested.", claim_ids: ["c2"], status: "open-in-reviewed-corpus",
      currency: { checked_source_ids: ["paper-1"], claim_ids: [], rationale: "All supplied fixture evidence checked; no subsequent result supplied." } }],
    opportunities: [{ id: "o1", gap_id: "g1", direction_claim_ids: ["c3"],
      feasibility: { effort: "low", rationale: "The researcher supplied necessary fixture resources.", prerequisites: ["Clinic data"],
        unknowns: [], resource_ids: ["r1"] } }],
    source_reviews: [{ source_id: "paper-1", status: "reviewed", note: "Read the complete supplied abstract." }],
  };
}
const context = { audience: "Peers", resources: [{ id: "r1", description: "Approved data" }] };

test("complete handoff, grounded evidence, Markdown and all SVGs share provenance", () => {
  const { root, snapshot } = fixture();
  const document = evidence(snapshot);
  const before = readFileSync(join(root, "ledger.json"));
  saveEvidence(snapshot, document);
  const output = render(snapshot);
  const report = readFileSync(join(output, "report.md"), "utf8");
  assert.match(report, /not causation/);
  assert.match(report, /abstract-only|abstract/);
  assert.match(report, /c1/);
  assert.equal(shortlist(document).length, 1);
  for (const name of ["evidence-matrix.svg", "opportunity-matrix.svg", "gap-directions.svg", "review-flow.svg"]) {
    const svg = readFileSync(join(output, name), "utf8");
    assert.match(svg, /2026-09-19/);
    assert.match(svg, /<desc/);
    assert.doesNotMatch(svg, /<script/);
  }
  assert.equal(render(snapshot), output);
  assert.deepEqual(readFileSync(join(root, "ledger.json")), before);
  assert.equal(readJson(join(output, "provenance.json")).handoff.revision, snapshot.handoff.revision);
});

test("early exports, missing gates, stale criteria, borderlines, and non-human curation are blocked", () => {
  const cases = [
    ledger => { ledger.records[0].screening.fulltext.decision = "unscreened"; },
    ledger => { ledger.records[0].screening.fulltext.decided_by = "llm"; },
    ledger => { ledger.records[0].screening.abstract.decision = "unscreened"; },
    ledger => { ledger.records[0].screening.abstract.criteria_version = 0; },
    ledger => { ledger.records[0].screening.fulltext.decision = "borderline"; },
    ledger => { ledger.queries = []; },
  ];
  for (const mutate of cases) {
    const { root, ledger } = fixture({ completed: false });
    mutate(ledger);
    writeJson(join(root, "ledger.json"), ledger);
    for (const gate of ["criteria", "triage", "curation"]) approveGate(root, gate, gateFingerprint(root, gate));
    assert.throws(() => finalize(root));
    assert.equal(existsSync(join(root, ".callimachus/current.json")), false);
  }
  const { root, ledger } = fixture({ completed: false });
  writeJson(join(root, ".callimachus/approvals.json"), {});
  assert.throws(() => finalize(root), /approval/);
  mkdirSync(join(root, "exports"));
  writeFileSync(join(root, "exports/references.bib"), "early list");
  assert.throws(() => loadSnapshot(root));
  ledger.criteria.version++;
  writeJson(join(root, "ledger.json"), ledger);
  assert.throws(() => finalize(root), /approval/);
});

test("review mutation during human confirmation cannot be approved", () => {
  const { root, ledger } = fixture({ completed: false });
  const fingerprint = gateFingerprint(root, "criteria");
  ledger.question = "Changed question";
  writeJson(join(root, "ledger.json"), ledger);
  assert.throws(() => approveGate(root, "criteria", fingerprint), /changed during approval/);
});

test("forged completion flag/seal and modified snapshot are rejected", () => {
  const { root, snapshot } = fixture();
  const handoffPath = join(snapshot.directory, "handoff.json");
  const original = readFileSync(handoffPath);
  const handoff = readJson(handoffPath);
  handoff.cutoff = "2099-01-01";
  writeJson(handoffPath, handoff);
  assert.throws(() => loadSnapshot(root), /Untrusted/);
  writeFileSync(handoffPath, original);
  writeFileSync(join(snapshot.directory, "source-0.json"), "{}");
  assert.throws(() => loadSnapshot(root), /Modified snapshot/);
});

test("fulltext artifacts, source changes and new revisions invalidate synthesis", () => {
  const { root, snapshot } = fixture({ fulltext: true });
  assert.equal(snapshot.handoff.sources[0].kind, "fulltext");
  writeFileSync(join(root, "paper.pdf"), "changed");
  assert.throws(() => loadSnapshot(root));
  assert.throws(() => finalize(root), /approval/);
  const second = fixture();
  finalize(second.root);
  assert.throws(() => loadSnapshot(second.root, second.snapshot.handoff.revision), /newer/);
});

test("absolute paths, traversal and symlinks never expose external artifacts", () => {
  const { root } = fixture({ completed: false });
  assert.throws(() => inside(root, "../secret"), /escapes/);
  assert.throws(() => inside(root, "/etc/passwd"), /relative/);
  symlinkSync(sandbox, join(root, "outside"));
  assert.throws(() => inside(root, "outside/secret"), /Symlinks/);
});

test("unsupported claims, incorrect locators, invented directions and stale gap status fail validation", () => {
  const { snapshot } = fixture();
  const mutations = [
    d => { d.claims[0].quote = "Proven causation."; },
    d => { d.claims[0].page = 2; },
    d => { d.claims[0].source_id = "external"; },
    d => { d.claims[0].verification.status = "uncertain"; },
    d => { d.opportunities[0].direction_claim_ids = ["c2"]; },
    d => { d.gaps[0].currency.checked_source_ids = []; },
    d => { d.gaps[0].status = "addressed"; },
    d => { d.opportunities[0].feasibility.unknowns = ["Data availability"]; },
    d => { d.opportunities[0].feasibility.resource_ids = ["invented"]; },
    d => { d.handoff_revision = "different"; },
  ];
  for (const mutate of mutations) {
    const document = evidence(snapshot);
    mutate(document);
    assert.throws(() => validateEvidence(snapshot, document, context));
  }
});

test("unresolved gaps and unknown feasibility are retained without a fabricated shortlist", () => {
  const { snapshot } = fixture();
  const document = evidence(snapshot);
  document.gaps[0].status = "unresolved";
  document.gaps[0].currency.checked_source_ids = [];
  document.opportunities[0].feasibility.effort = "unknown";
  document.opportunities[0].feasibility.resource_ids = [];
  document.opportunities[0].feasibility.unknowns = ["Data access"];
  saveEvidence(snapshot, document);
  assert.equal(shortlist(document).length, 0);
  assert.match(readFileSync(join(render(snapshot), "report.md"), "utf8"), /No directions can currently be shortlisted/);
});

test("evidence history preserves corrections; unreviewed sources block delivery", () => {
  const { snapshot } = fixture();
  const document = evidence(snapshot);
  const first = saveEvidence(snapshot, document);
  document.claims[0].verification.reason = "Rechecked the quoted negation and context.";
  const second = saveEvidence(snapshot, document);
  assert.notEqual(first, second);
  for (const digest of [first, second])
    assert.ok(existsSync(join(evidenceDirectory(snapshot), "history", `${digest}.json`)));
  document.source_reviews = [];
  saveEvidence(snapshot, document);
  assert.throws(() => render(snapshot), /Every included source/);
});

test("SVG and Markdown escape source markup rather than interpreting it", () => {
  const { snapshot } = fixture();
  const document = evidence(snapshot);
  document.findings[0].statement = "<script>alert('x')</script>";
  document.opportunities[0].feasibility.unknowns = ["<script>x</script>"];
  document.opportunities[0].feasibility.effort = "unknown";
  saveEvidence(snapshot, document);
  const output = render(snapshot);
  assert.doesNotMatch(readFileSync(join(output, "opportunity-matrix.svg"), "utf8"), /<script>/);
  assert.match(readFileSync(join(output, "report.md"), "utf8"), /\\<script\\>/);
});

test("actual Pi SDK session exposes only mediated tools and loads no ambient resources", async () => {
  const { snapshot } = fixture();
  const cwd = evidenceDirectory(snapshot);
  writeFileSync(join(cwd, "AGENTS.md"), "UNTRUSTED ambient instructions");
  mkdirSync(join(cwd, ".pi/extensions"), { recursive: true });
  writeFileSync(join(cwd, ".pi/extensions/injected.js"), "throw new Error('must not load')");
  const options = await isolatedOptions(snapshot);
  const authStorage = AuthStorage.inMemory();
  const { session } = await createAgentSession({
    ...options, authStorage, modelRegistry: ModelRegistry.inMemory(authStorage),
    customTools: restrictedTools(snapshot, () => {}),
  });
  try {
    assert.deepEqual(session.agent.state.tools.map(t => t.name).sort(), [...toolNames].sort());
    assert.doesNotMatch(session.agent.state.systemPrompt, /UNTRUSTED ambient/);
    assert.equal(options.resourceLoader.getExtensions().extensions.length, 0);
    assert.equal(options.resourceLoader.getSkills().skills.length, 0);
    assert.equal(options.resourceLoader.getAgentsFiles().agentsFiles.length, 0);
  } finally { session.dispose(); }
});

test("refresh request suspends every synthesis tool; no shell, search, or upstream writer exists", async () => {
  const { snapshot } = fixture();
  let reason;
  const tools = restrictedTools(snapshot, value => { reason = value; });
  assert.deepEqual(tools.map(t => t.name).sort(), [...toolNames].sort());
  await tools.find(t => t.name === "request_callimachus").execute("1", { reason: "Need an updated completed review." });
  assert.match(reason, /updated/);
  await assert.rejects(tools.find(t => t.name === "hypathia_snapshot").execute("2", {}), /Awaiting/);
  await assert.rejects(tools.find(t => t.name === "hypathia_save").execute("3", evidence(snapshot)), /Awaiting/);
});

test("question-only dispatch delegates the complete Callimachus workflow and reuses its review", async () => {
  const commands = new Map();
  const messages = [];
  extension({
    registerCommand: (name, value) => commands.set(name, value),
    registerTool: () => {},
    sendUserMessage: message => messages.push(message),
  });
  const ctx = { cwd: sandbox, ui: { notify: () => {} }, hasUI: false };
  await commands.get("hypathia").handler("question A new research question", ctx);
  assert.equal(messages.length, 1);
  assert.match(messages[0], /ALL nine stages/);
  assert.match(messages[0], /step-8 export is not completion/);
  await commands.get("hypathia").handler("question A new research question", ctx);
  assert.equal(messages.length, 1);
});

test("declining curation never finalizes or synthesizes", async () => {
  const { root } = fixture({ completed: false });
  const commands = new Map();
  extension({ registerCommand: (name, value) => commands.set(name, value), registerTool: () => {}, sendUserMessage: () => {} });
  await commands.get("callimachus-approve").handler(`curation ${root}`, {
    cwd: sandbox, hasUI: true, ui: { confirm: async () => false, notify: () => {} },
  });
  assert.equal(existsSync(join(root, ".callimachus/current.json")), false);
});

test("PDF extractor retains plain-text CLI behavior and emits page hashes/warnings", () => {
  const root = mkdtempSync(join(sandbox, "pdf-"));
  const pdf = join(root, "blank.pdf");
  const make = spawnSync("uv", ["run", "--python", "3.11", "--with", "pypdf==4.3.1", "python", "-c",
    "from pypdf import PdfWriter; import sys; w=PdfWriter(); w.add_blank_page(width=72,height=72); w.write(sys.argv[1])", pdf], { encoding: "utf8" });
  assert.equal(make.status, 0, make.stderr);
  const script = resolve("skills/literature-review/scripts/pdf_extract.py");
  const plain = spawnSync("uv", ["run", script, "--pdf", pdf], { encoding: "utf8" });
  assert.equal(plain.status, 0, plain.stderr);
  assert.equal(plain.stdout, "");
  const structured = spawnSync("uv", ["run", script, "--pdf", pdf, "--structured"], { encoding: "utf8" });
  assert.equal(structured.status, 0, structured.stderr);
  const result = JSON.parse(structured.stdout);
  assert.equal(result.pdf_sha256, hash(readFileSync(pdf)));
  assert.deepEqual(result.pages, [{ page: 1, text: "" }]);
  assert.match(result.warnings.join(" "), /OCR/);
});

test("source-free completed reviews produce a truthful empty report", () => {
  const { root, ledger, sources } = fixture({ completed: false });
  ledger.records[0].screening.abstract.decision = "exclude";
  ledger.records[0].screening.fulltext.decision = "unscreened";
  sources.sources = [];
  writeJson(join(root, "ledger.json"), ledger);
  writeJson(join(root, "sources.json"), sources);
  for (const gate of ["criteria", "triage", "curation"]) approveGate(root, gate, gateFingerprint(root, gate));
  finalize(root);
  const snapshot = loadSnapshot(root);
  writeJson(join(evidenceDirectory(snapshot), "context.json"), context);
  saveEvidence(snapshot, loadEvidence(snapshot));
  assert.match(readFileSync(join(render(snapshot), "report.md"), "utf8"), /No supported findings/);
});
