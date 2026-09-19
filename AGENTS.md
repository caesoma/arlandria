# Repo guidance for agents

This package has exactly two skills: `callimachus` and `hypatia`. Do not add other skill definitions.

Callimachus owns the literature review. Its workflow lives in `skills/callimachus/SKILL.md` and the `/callimachus` prompt. Review state lives in a per-review folder's `ledger.json` (alongside `exports/`, `searches/`, `pdfs/`); its schema is in `skills/callimachus/references/ledger_schema.md`. Records are never deleted.

Hypatia synthesizes only completed Callimachus results. Its workflow lives in `skills/hypatia/SKILL.md`; `/hypatia` delegates missing or incomplete research to Callimachus. It never searches independently.

Standalone skill logic belongs in Python under the owning skill's `scripts/` directory. This includes rendering, validation, evidence processing, persistence, and completion artifacts. TypeScript is reserved for Pi harness integration: registering commands/tools, UI interactions, session/model setup, and invoking the Python scripts. Do not add standalone TypeScript skill implementations without a specific reason.
