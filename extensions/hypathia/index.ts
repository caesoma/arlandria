import { existsSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { Type } from "typebox";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { approveGate, finalize, gateFingerprint, loadSnapshot, type Gate, type Snapshot } from "./handoff.js";
import { ContextSchema, parse } from "./schema.js";
import { evidenceDirectory } from "./evidence.js";
import { atomicWrite, hash, inside, json, readJson } from "./storage.js";
import { synthesize } from "./runtime.js";

const RequestSchema = Type.Object({
  status: Type.String(), question: Type.String(),
  reason: Type.Optional(Type.String()), previous_revision: Type.Optional(Type.String()),
});

export function pauseRequest(root: string, question: string) {
  const path = inside(root, ".hypathia/request.json");
  if (existsSync(path) && parse(RequestSchema, readJson(path)).status === "awaiting_callimachus") return;
  atomicWrite(path, json({ status: "paused", question }));
}

export default function hypathia(pi: ExtensionAPI): void {
  const active = new Set<string>();
  const notifyError = (ctx: ExtensionContext, error: unknown) =>
    ctx.ui.notify(error instanceof Error ? error.message : String(error), "error");

  function delegate(root: string, reason: string) {
    pi.sendUserMessage([
      'Load the "literature-review" skill and run Callimachus through ALL nine stages.',
      `Review folder: ${JSON.stringify(root)}. Resume this ledger if it exists; do not duplicate the review.`,
      `Research request / missing evidence: ${JSON.stringify(reason)}.`,
      "Hypathia is waiting. Do not synthesize on its behalf. Do not design queries until the Callimachus criteria gate is released.",
      "Preserve criteria, triage, and final curation human gates. Ask the researcher to use /callimachus-approve at each gate.",
      "The step-8 export is not completion. Finish source acquisition and human curation, prepare sources.json, and ask for /callimachus-approve curation <review folder>.",
      "That command validates/finalizes the review and resumes Hypathia. Never fabricate human approvals.",
    ].join("\n"), { deliverAs: "followUp" });
  }

  async function start(root: string, ctx: ExtensionContext, question = "") {
    root = resolve(root);
    mkdirSync(root, { recursive: true });
    mkdirSync(inside(root, ".hypathia"), { recursive: true });
    if (active.has(root)) throw new Error("This review already has a running Hypathia session");
    const requestPath = inside(root, ".hypathia/request.json");
    let snapshot: Snapshot;
    try {
      snapshot = loadSnapshot(root);
      if (existsSync(requestPath)) {
        const request = parse(RequestSchema, readJson(requestPath));
        if (request.status === "awaiting_callimachus" && request.previous_revision === snapshot.handoff.revision) {
          ctx.ui.notify("Waiting for Callimachus to finish a new revision.", "info");
          return;
        }
      }
    } catch (error) {
      if (existsSync(requestPath)) {
        const request = parse(RequestSchema, readJson(requestPath));
        if (request.status === "awaiting_callimachus") {
          ctx.ui.notify(`Callimachus is still pending: ${error instanceof Error ? error.message : String(error)}. Resume that review and approve final curation.`, "info");
          return;
        }
      }
      atomicWrite(requestPath, json({ status: "awaiting_callimachus", question, reason: question || "Finish the existing review for Hypathia." }));
      delegate(root, question || "Complete or repair this review's completion handoff.");
      return;
    }
    const directory = evidenceDirectory(snapshot);
    const contextPath = inside(directory, "context.json");
    if (!existsSync(contextPath)) {
      if (!ctx.hasUI) throw new Error("Run /hypathia interactively to supply audience and optional research constraints");
      const audience = await ctx.ui.input("Hypathia audience", "Peers and stakeholders");
      if (audience === undefined) return;
      const resources = await ctx.ui.input("Available resources / constraints (optional; separate with semicolons)", "Leave blank if unknown");
      if (resources === undefined) return;
      const context = parse(ContextSchema, {
        audience: audience.trim() || "Peers and stakeholders",
        resources: resources.split(";").map(s => s.trim()).filter(Boolean).map((description, i) => ({ id: `resource-${i + 1}`, description })),
      });
      atomicWrite(contextPath, json(context));
    }
    active.add(root);
    try {
      atomicWrite(requestPath, json({ status: "synthesizing", question: snapshot.ledger.question, revision: snapshot.handoff.revision }));
      const refresh = await synthesize(snapshot, ctx);
      if (refresh) delegate(root, refresh);
      else ctx.ui.notify(`Hypathia delivered. Output details: ${inside(directory, "delivery.json")}`, "info");
    } catch (error) {
      pauseRequest(root, snapshot.ledger.question);
      throw error;
    } finally { active.delete(root); }
  }

  pi.registerCommand("hypathia", {
    description: "Synthesize a completed review: /hypathia <folder> or /hypathia question <research question>",
    handler: async (args, ctx) => {
      try {
        const input = args.trim();
        if (!input) throw new Error("Use /hypathia <review folder> or /hypathia question <research question>");
        if (input.startsWith("question ")) {
          const question = input.slice(9).trim();
          if (!question) throw new Error("A research question is required");
          const root = resolve(ctx.cwd, "reviews", `hypathia-${hash(question.toLowerCase().replace(/\s+/g, " ")).slice(0, 16)}`);
          await start(root, ctx, question);
        } else await start(resolve(ctx.cwd, input), ctx);
      } catch (error) { notifyError(ctx, error); }
    },
  });

  pi.registerCommand("callimachus-approve", {
    description: "Human release of a Callimachus gate: criteria|triage|curation <review folder>",
    handler: async (args, ctx) => {
      try {
        const match = /^(criteria|triage|curation)\s+(.+)$/.exec(args.trim());
        if (!match) throw new Error("Use /callimachus-approve criteria|triage|curation <review folder>");
        if (!ctx.hasUI) throw new Error("Human gate approval requires an interactive UI");
        const gate = match[1] as Gate;
        const root = resolve(ctx.cwd, match[2]);
        const fingerprint = gateFingerprint(root, gate);
        const description = gate === "curation"
          ? "Confirm you reviewed the final human dispositions, source/access limitations and cutoff in sources.json. This completes Callimachus and may resume Hypathia."
          : `Release the ${gate} gate for the current review? Only approve after discussing the current criteria / screened pool.`;
        if (!await ctx.ui.confirm(`Callimachus ${gate}: ${root}`, description)) return;
        approveGate(root, gate, fingerprint);
        if (gate === "curation") {
          const revision = finalize(root);
          ctx.ui.notify(`Callimachus completed: ${revision}`, "info");
          if (existsSync(inside(root, ".hypathia/request.json"))) await start(root, ctx);
        } else {
          pi.sendUserMessage(`The researcher released Callimachus's ${gate} gate for ${JSON.stringify(root)}. Continue its literature-review workflow.`, { deliverAs: "followUp" });
        }
      } catch (error) { notifyError(ctx, error); }
    },
  });

  pi.registerTool({
    name: "hypathia", label: "Run Hypathia",
    description: "Delegate synthesis to an isolated Hypathia session. Accepts an existing review folder only. If incomplete, requests full Callimachus completion first.",
    parameters: Type.Object({ review_folder: Type.String({ minLength: 1 }) }),
    execute: async (_id, params, _signal, _onUpdate, ctx) => {
      await start(resolve(ctx.cwd, params.review_folder), ctx);
      return { content: [{ type: "text", text: "Hypathia request processed. Follow the completion/approval messages; do not synthesize in this parent session." }], details: {} };
    },
  });
}
