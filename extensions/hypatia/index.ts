import { join, resolve } from "node:path";
import { Type } from "typebox";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { evidenceDirectory, loadSnapshot, pauseRequest, python, type Gate, type Request, type Snapshot } from "./bridge.js";
import { synthesize } from "./runtime.js";

export { pauseRequest } from "./bridge.js";

export default function hypatia(pi: ExtensionAPI): void {
  const active = new Set<string>();
  const notifyError = (ctx: ExtensionContext, error: unknown) =>
    ctx.ui.notify(error instanceof Error ? error.message : String(error), "error");

  function delegate(root: string, reason: string) {
    pi.sendUserMessage([
      'Load the "callimachus" skill and run Callimachus through ALL nine stages.',
      `Review folder: ${JSON.stringify(root)}. Resume this ledger if it exists; do not duplicate the review.`,
      `Research request / missing evidence: ${JSON.stringify(reason)}.`,
      "Hypatia is waiting. Do not synthesize on its behalf. Do not design queries until the Callimachus criteria gate is released.",
      "Preserve criteria, triage, and final curation human gates. Ask the researcher to use /callimachus-approve at each gate.",
      "The step-8 export is not completion. Finish source acquisition and human curation, prepare sources.json, and ask for /callimachus-approve curation <review folder>.",
      "That command validates/finalizes the review and resumes Hypatia. Never fabricate human approvals.",
    ].join("\n"), { deliverAs: "followUp" });
  }

  async function start(root: string, ctx: ExtensionContext, question = "") {
    root = python<string>("prepare", root);
    if (active.has(root)) throw new Error("This review already has a running Hypatia session");
    const request = python<Request | null>("request-read", root);
    let snapshot: Snapshot;
    try {
      snapshot = loadSnapshot(root);
      if (request) {
        if (request.status === "awaiting_callimachus" && request.previous_revision === snapshot.handoff.revision) {
          ctx.ui.notify("Waiting for Callimachus to finish a new revision.", "info");
          return;
        }
      }
    } catch (error) {
      if (request) {
        if (request.status === "awaiting_callimachus") {
          ctx.ui.notify(`Callimachus is still pending: ${error instanceof Error ? error.message : String(error)}. Resume that review and approve final curation.`, "info");
          return;
        }
      }
      python("request-write", root, { status: "awaiting_callimachus", question, reason: question || "Finish the existing review for Hypatia." });
      delegate(root, question || "Complete or repair this review's completion handoff.");
      return;
    }
    const directory = evidenceDirectory(snapshot);
    if (!python("context", root, {}, snapshot.handoff.revision)) {
      if (!ctx.hasUI) throw new Error("Run /hypatia interactively to supply audience and optional research constraints");
      const audience = await ctx.ui.input("Hypatia audience", "Peers and stakeholders");
      if (audience === undefined) return;
      const resources = await ctx.ui.input("Available resources / constraints (optional; separate with semicolons)", "Leave blank if unknown");
      if (resources === undefined) return;
      python("context-save", root, {
        audience: audience.trim() || "Peers and stakeholders",
        resources: resources.split(";").map(s => s.trim()).filter(Boolean).map((description, i) => ({ id: `resource-${i + 1}`, description })),
      }, snapshot.handoff.revision);
    }
    active.add(root);
    try {
      python("request-write", root, { status: "synthesizing", question: snapshot.ledger.question, revision: snapshot.handoff.revision });
      const refresh = await synthesize(snapshot, ctx);
      if (refresh) delegate(root, refresh);
      else ctx.ui.notify(`Hypatia delivered. Output details: ${join(directory, "delivery.json")}`, "info");
    } catch (error) {
      pauseRequest(root, snapshot.ledger.question);
      throw error;
    } finally { active.delete(root); }
  }

  pi.registerCommand("hypatia", {
    description: "Synthesize a completed review: /hypatia <folder> or /hypatia question <research question>",
    handler: async (args, ctx) => {
      try {
        const input = args.trim();
        if (!input) throw new Error("Use /hypatia <review folder> or /hypatia question <research question>");
        if (input === "question" || input.startsWith("question ")) {
          const question = input.slice("question".length).trim();
          if (!question) throw new Error("A research question is required");
          const root = python<string>("prepare", ctx.cwd, { question });
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
        const fingerprint = python<string>("gate-fingerprint", root, { gate });
        const description = gate === "curation"
          ? "Confirm you reviewed the final human dispositions, source/access limitations and cutoff in sources.json. This completes Callimachus and may resume Hypatia."
          : `Release the ${gate} gate for the current review? Only approve after discussing the current criteria / screened pool.`;
        if (!await ctx.ui.confirm(`Callimachus ${gate}: ${root}`, description)) return;
        python("approve-gate", root, { gate, fingerprint });
        if (gate === "curation") {
          const revision = python<string>("finalize", root);
          ctx.ui.notify(`Callimachus completed: ${revision}`, "info");
          if (python("request-read", root)) await start(root, ctx);
        } else {
          pi.sendUserMessage(`The researcher released Callimachus's ${gate} gate for ${JSON.stringify(root)}. Continue its literature-review workflow.`, { deliverAs: "followUp" });
        }
      } catch (error) { notifyError(ctx, error); }
    },
  });

  pi.registerTool({
    name: "hypatia", label: "Run Hypatia",
    description: "Delegate synthesis to an isolated Hypatia session. Accepts an existing review folder only. If incomplete, requests full Callimachus completion first.",
    parameters: Type.Object({ review_folder: Type.String({ minLength: 1 }) }),
    execute: async (_id, params, _signal, _onUpdate, ctx) => {
      await start(resolve(ctx.cwd, params.review_folder), ctx);
      return { content: [{ type: "text", text: "Hypatia request processed. Follow the completion/approval messages; do not synthesize in this parent session." }], details: {} };
    },
  });
}
