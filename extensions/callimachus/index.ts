import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

// `/callimachus` starts the workflow in skills/callimachus/SKILL.md.

function kickoff(args: string): string {
  const q = args.trim();
  return [
    'Load the "callimachus" skill (read its SKILL.md) and follow its 9-step workflow.',
    q
      ? `Research question / instruction: ${q}`
      : "If I have not given a research question yet, ask me for one before doing anything else.",
    "",
    "Honor these disciplines:",
    "- Interactive gates (steps 2 and 6): propose, then discuss and revise across as many turns as I want; advance only on my explicit release.",
    "- Screen every retrieved abstract individually; nothing ranked or skipped. Your screening is a provisional first pass, recorded with `ledger.py decide --by llm`.",
    "- I am the final curator: record my overrides with `--by human`, and never overwrite a human decision.",
    "- Export the list as soon as abstract screening converges (step 8); full-text reading is asynchronous (step 9) - never block on it.",
    "- Follow-ups (filter, which-papers-cover-X-best, resume) are reads over the ledger, not new searches.",
  ].join("\n");
}

export default function callimachus(pi: ExtensionAPI): void {
  const definition = {
    description: "Start or resume a semi-automated literature review (Callimachus)",
    handler: async (args: string) => {
      pi.sendUserMessage(kickoff(args), { deliverAs: "followUp" });
    },
  };
  pi.registerCommand("callimachus", definition);
}
