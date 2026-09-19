import assert from "node:assert/strict";
import { after, test } from "node:test";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, symlinkSync, rmSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { homedir } from "node:os";
import { spawnSync } from "node:child_process";
import { createJiti } from "jiti";
import { createAssistantMessageEventStream, InMemoryCredentialStore } from "@earendil-works/pi-ai";
import {
  AgentSession, DefaultResourceLoader, ModelRegistry, ModelRuntime,
  SettingsManager, createAgentSession, loadSkillsFromDir,
} from "@earendil-works/pi-coding-agent";

const sandbox = mkdtempSync(join(homedir(), ".hypatia-tests-"));
// Keep signing keys and SDK discovery isolated from the developer's real home.
const originalHome = process.env.HOME;
process.env.HOME = sandbox;
after(() => { process.env.HOME = originalHome; rmSync(sandbox, { recursive: true }); });
const jiti = createJiti(import.meta.url);
const { approveGate, gateFingerprint, finalize, loadSnapshot } = await jiti.import("../extensions/hypatia/handoff.ts");
const { validateEvidence, saveEvidence, evidenceDirectory, loadEvidence } = await jiti.import("../extensions/hypatia/evidence.ts");
const { render, shortlist } = await jiti.import("../extensions/hypatia/render.ts");
const { restrictedTools, isolatedOptions, hypatiaModelRuntime, toolNames } = await jiti.import("../extensions/hypatia/runtime.ts");
const { hash, json, inside } = await jiti.import("../extensions/hypatia/storage.ts");
const { default: extension, pauseRequest } = await jiti.import("../extensions/hypatia/index.ts");
const { default: callimachus } = await jiti.import("../extensions/callimachus/index.ts");

const text = "We found an association, not causation. Rural settings remain untested. Future work should evaluate rural clinics.";
const writeJson = (path, value) => writeFileSync(path, json(value));
const readJson = path => JSON.parse(readFileSync(path, "utf8"));

async function modelFixture(auth, credentials = new InMemoryCredentialStore()) {
  const model = {
    id: "fixture", name: "Fixture model", provider: "hypatia-fixture", api: "openai-completions",
    baseUrl: "https://fixture.invalid", reasoning: false, input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 8192, maxTokens: 512,
  };
  const requests = [];
  const stream = (selected, context, options) => {
    requests.push({ model: selected, context, options });
    const events = createAssistantMessageEventStream();
    events.push({ type: "done", reason: "stop", message: {
      role: "assistant", content: [{ type: "text", text: "Fixture response." }],
      api: selected.api, provider: selected.provider, model: selected.id, stopReason: "stop", timestamp: Date.now(),
      usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
    } });
    events.end();
    return events;
  };
  const runtime = await ModelRuntime.create({ credentials, modelsPath: null, refreshOnCreate: false });
  runtime.registerNativeProvider({
    id: model.provider, name: "Fixture provider", auth, getModels: () => [model], stream, streamSimple: stream,
  });
  await runtime.refresh({ allowNetwork: false, providers: [model.provider] });
  return { runtime, model, modelRegistry: new ModelRegistry(runtime), requests };
}

test("Pi discovers exactly Callimachus and Hypatia with their commands and prompt", async () => {
  const loader = new DefaultResourceLoader({
    cwd: sandbox, agentDir: sandbox,
    settingsManager: SettingsManager.inMemory({ packages: [resolve(".")] }),
    noContextFiles: true, noThemes: true,
  });
  await loader.reload();
  const discovered = loader.getSkills();
  assert.deepEqual(discovered.diagnostics, []);
  assert.deepEqual(discovered.skills.map(s => s.name).sort(), ["callimachus", "hypatia"]);
  const allSkills = loadSkillsFromDir({ dir: resolve("skills"), source: "test" });
  assert.deepEqual(allSkills.diagnostics, []);
  assert.deepEqual(allSkills.skills.map(s => s.name).sort(), ["callimachus", "hypatia"]);
  assert.deepEqual(loader.getExtensions().errors, []);
  assert.deepEqual(loader.getExtensions().extensions.flatMap(e => [...e.commands.keys()]).sort(),
    ["callimachus", "callimachus-approve", "hypatia"]);
  assert.deepEqual(loader.getPrompts().prompts.map(p => p.name), ["callimachus"]);

  const commands = new Map();
  const messages = [];
  callimachus({
    registerCommand: (name, value) => commands.set(name, value),
    sendUserMessage: message => messages.push(message),
  });
  await commands.get("callimachus").handler("A research question");
  assert.match(messages[0], /Load the "callimachus" skill/);
  assert.match(messages[0], /A research question/);
});

function fixture({ fulltext = false, completed = true } = {}) {
  const root = mkdtempSync(join(sandbox, "review-"));
  const decision = (decision, by = "llm") => ({
    decision, decided_by: by, reason: "Researcher-approved scope and disposition.",
    criteria_version: 1, at: "2026-09-19", proposed: null,
  });
  const ledger = {
    review_id: "test-review", question: "What is established about this association?",
    criteria: { version: 1, include: ["Relevant evidence"], exclude: [] },
    queries: [{ id: "q1", round: 1, source: "fixture", query_string: "completed upstream search",
      run_at: "2026-09-19", n_returned: 1 }],
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
  const modelRuntime = await ModelRuntime.create({
    credentials: new InMemoryCredentialStore(), modelsPath: null, refreshOnCreate: false,
  });
  const { session } = await createAgentSession({
    ...options, modelRuntime,
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

test("child SDK requests inherit changing parent keys, headers, endpoints and provider env", async () => {
  const parent = await modelFixture({ apiKey: {
    name: "Fixture key",
    resolve: async ({ credential }) => credential?.key ? {
      auth: { apiKey: credential.key, headers: { "x-project": "fixture" }, baseUrl: "https://request.invalid" },
      env: { FIXTURE_REGION: "local" },
    } : undefined,
  } });
  await parent.runtime.setRuntimeApiKey(parent.model.provider, "first-test-key");
  const modelRuntime = await hypatiaModelRuntime(parent);
  const { snapshot } = fixture();
  const { session } = await createAgentSession({
    ...await isolatedOptions(snapshot), model: parent.model, modelRuntime,
    customTools: restrictedTools(snapshot, () => {}),
  });
  try {
    await session.prompt("Respond using the fixture provider.");
    await parent.runtime.setRuntimeApiKey(parent.model.provider, "second-test-key");
    await session.prompt("Respond again.");
    assert.equal(session.agent.state.errorMessage, undefined);
    assert.deepEqual(parent.requests.map(r => r.options.apiKey), ["first-test-key", "second-test-key"]);
    for (const request of parent.requests) {
      assert.equal(request.options.headers["x-project"], "fixture");
      assert.equal(request.options.env.FIXTURE_REGION, "local");
      assert.equal(request.model.baseUrl, "https://request.invalid");
      assert.deepEqual(request.context.tools.map(t => t.name).sort(), [...toolNames].sort());
    }
    assert.deepEqual(await modelRuntime.listCredentials(), []);
  } finally { session.dispose(); }
});

test("child auth refreshes OAuth through the parent store without retaining tokens", async () => {
  const credentials = new InMemoryCredentialStore();
  await credentials.modify("hypatia-fixture", async () => ({
    type: "oauth", access: "expired-test-token", refresh: "test-refresh-token", expires: 0,
  }));
  let refreshes = 0;
  const parent = await modelFixture({ oauth: {
    name: "Fixture OAuth",
    login: async () => { throw new Error("Login must remain in the parent"); },
    refresh: async credential => ({
      ...credential, access: `refreshed-test-token-${++refreshes}`, expires: Date.now() + 3600000,
    }),
    toAuth: async credential => ({ apiKey: credential.access, headers: { "x-oauth": "fixture" } }),
  } }, credentials);
  const runtime = await hypatiaModelRuntime(parent);
  const first = await runtime.getAuth(parent.model);
  assert.equal(first.auth.apiKey, "refreshed-test-token-1");
  assert.equal(first.auth.headers["x-oauth"], "fixture");
  await credentials.modify(parent.model.provider, async credential => ({ ...credential, expires: 0 }));
  assert.equal((await runtime.getAuth(parent.model)).auth.apiKey, "refreshed-test-token-2");
  assert.equal((await credentials.read(parent.model.provider)).access, "refreshed-test-token-2");
  assert.deepEqual(await runtime.listCredentials(), []);
  await credentials.delete(parent.model.provider);
  await assert.rejects(runtime.getAuth(parent.model), /No API key found/);
});

test("child auth preserves configured model headers for a keyless custom provider", async () => {
  const parent = await modelFixture({ apiKey: { name: "Local", resolve: async () => ({ auth: {} }) } });
  const provider = parent.modelRegistry.getProvider(parent.model.provider);
  parent.runtime.registerProvider(parent.model.provider, {
    api: parent.model.api, baseUrl: parent.model.baseUrl, authHeader: false,
    headers: { "x-provider": "configured" },
    models: [{ ...parent.model, headers: { "x-model": "selected" } }],
    streamSimple: provider.streamSimple.bind(provider),
  });
  const runtime = await hypatiaModelRuntime(parent);
  const auth = await runtime.getAuth(parent.model);
  assert.equal(auth.auth.apiKey, undefined);
  assert.equal(auth.auth.headers["x-provider"], "configured");
  assert.equal(auth.auth.headers["x-model"], "selected");
  await runtime.completeSimple(parent.model, { messages: [] });
  assert.equal(parent.requests.length, 1);
  assert.equal(parent.requests[0].options.headers["x-model"], "selected");
});

test("child auth cancels pending parent resolution and never falls back after failure", async t => {
  const parent = await modelFixture({ apiKey: {
    name: "Fixture", resolve: async () => ({ auth: { apiKey: "fixture-test-key" } }),
  } });
  const runtime = await hypatiaModelRuntime(parent);
  t.mock.method(parent.modelRegistry, "getApiKeyAndHeaders", async () => ({ ok: false, error: "Parent auth failed" }));
  await assert.rejects(runtime.getAuth(parent.model), /Parent auth failed/);
  let started;
  const pending = new Promise(resolve => { started = resolve; });
  t.mock.method(parent.modelRegistry, "getApiKeyAndHeaders", () => {
    started();
    return new Promise(() => {});
  });
  const controller = new AbortController();
  const request = runtime.getAuth(parent.model, { signal: controller.signal });
  await pending;
  controller.abort();
  await assert.rejects(request, /abort/i);
});

test("refresh request suspends every synthesis tool; no shell, search, or upstream writer exists", async () => {
  const { snapshot } = fixture();
  let reason;
  const tools = restrictedTools(snapshot, value => { reason = value; });
  assert.deepEqual(tools.map(t => t.name).sort(), [...toolNames].sort());
  await tools.find(t => t.name === "request_callimachus").execute("1", { reason: "Need an updated completed review." });
  assert.match(reason, /updated/);
  await assert.rejects(tools.find(t => t.name === "hypatia_snapshot").execute("2", {}), /Awaiting/);
  await assert.rejects(tools.find(t => t.name === "hypatia_save").execute("3", evidence(snapshot)), /Awaiting/);
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
  await commands.get("hypatia").handler("question A new research question", ctx);
  assert.equal(messages.length, 1);
  assert.match(messages[0], /Load the "callimachus" skill/);
  assert.match(messages[0], /ALL nine stages/);
  assert.match(messages[0], /step-8 export is not completion/);
  await commands.get("hypatia").handler("question A new research question", ctx);
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

test("interrupted synthesis preserves its upstream refresh requirement across sessions", async () => {
  const { root, snapshot } = fixture();
  const path = join(root, ".hypatia/request.json");
  const pending = { status: "awaiting_callimachus", question: snapshot.ledger.question,
    reason: "Update the evidence", previous_revision: snapshot.handoff.revision };
  writeJson(path, pending);
  pauseRequest(root, snapshot.ledger.question);
  assert.deepEqual(readJson(path), pending);
  const commands = new Map();
  const notices = [];
  extension({ registerCommand: (name, value) => commands.set(name, value), registerTool: () => {}, sendUserMessage: () => {} });
  await commands.get("hypatia").handler(root, {
    cwd: sandbox, hasUI: false, ui: { notify: message => notices.push(message) },
  });
  assert.deepEqual(notices, ["Waiting for Callimachus to finish a new revision."]);
  writeJson(path, { status: "synthesizing", question: snapshot.ledger.question });
  pauseRequest(root, snapshot.ledger.question);
  assert.equal(readJson(path).status, "paused");
});

test("bundled CLI launches outside the repository without a global pi or npm PATH", () => {
  const result = spawnSync(process.execPath, [resolve("bin/arlandria.js"), "--offline", "--version"], {
    cwd: sandbox, encoding: "utf8",
    env: { ...process.env, PATH: "/usr/bin:/bin", CALLIMACHUS_SKIP_UV_CHECK: "1", CALLIMACHUS_QUIET: "1" },
  });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout + result.stderr, /^\d+\.\d+\.\d+\s*$/);
});

test("transport failure after a refresh tool call never releases the old snapshot", async t => {
  const { root, snapshot } = fixture();
  t.mock.method(AgentSession.prototype, "prompt", async function () {
    const refresh = this.agent.state.tools.find(tool => tool.name === "request_callimachus");
    await refresh.execute("refresh", { reason: "An upstream update is necessary." });
    throw new Error("Synthetic connection interrupted");
  });
  const commands = new Map();
  const notices = [];
  const modelRuntime = await ModelRuntime.create({
    credentials: new InMemoryCredentialStore(), modelsPath: null, refreshOnCreate: false,
  });
  const modelRegistry = new ModelRegistry(modelRuntime);
  extension({ registerCommand: (name, value) => commands.set(name, value), registerTool: () => {}, sendUserMessage: () => {} });
  const ctx = { cwd: sandbox, hasUI: false, modelRegistry, model: modelRegistry.getAll()[0],
    ui: { notify: message => notices.push(message), setStatus: () => {} } };
  await commands.get("hypatia").handler(root, ctx);
  const request = readJson(join(root, ".hypatia/request.json"));
  assert.equal(request.status, "awaiting_callimachus");
  assert.equal(request.previous_revision, snapshot.handoff.revision);
  assert.match(notices[0], /Synthetic connection interrupted/);
  await commands.get("hypatia").handler(root, ctx);
  assert.match(notices[1], /Waiting for Callimachus/);
});

test("cached report selections update the delivery pointer when evidence is restored", () => {
  const { snapshot } = fixture();
  const document = evidence(snapshot);
  saveEvidence(snapshot, document);
  const first = render(snapshot);
  const second = structuredClone(document);
  second.findings[0].strength = "An updated appraisal of the same source.";
  saveEvidence(snapshot, second);
  assert.notEqual(render(snapshot), first);
  saveEvidence(snapshot, document);
  assert.equal(render(snapshot), first);
  assert.equal(readJson(join(evidenceDirectory(snapshot), "delivery.json")).directory, first);
});

test("failed and cancelled handoffs and malformed search audits cannot complete", () => {
  const { root, snapshot } = fixture();
  const path = join(snapshot.directory, "handoff.json");
  for (const status of ["failed", "cancelled", "pending"]) {
    writeJson(path, { ...snapshot.handoff, status });
    assert.throws(() => loadSnapshot(root), /Invalid data/);
  }
  const incomplete = fixture({ completed: false });
  incomplete.ledger.queries = [{}];
  writeJson(join(incomplete.root, "ledger.json"), incomplete.ledger);
  assert.throws(() => finalize(incomplete.root), /Invalid data/);
});

test("PDF extractor retains plain-text CLI behavior and emits page hashes/warnings", () => {
  const root = mkdtempSync(join(sandbox, "pdf-"));
  const pdf = join(root, "blank.pdf");
  const make = spawnSync("uv", ["run", "--python", "3.11", "--with", "pypdf==4.3.1", "python", "-c",
    "from pypdf import PdfWriter; import sys; w=PdfWriter(); w.add_blank_page(width=72,height=72); w.write(sys.argv[1])", pdf], { encoding: "utf8" });
  assert.equal(make.status, 0, make.stderr);
  const script = resolve("skills/callimachus/scripts/pdf_extract.py");
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
