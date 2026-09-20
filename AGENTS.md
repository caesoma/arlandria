# Repo guidance for agents

This package has exactly two skills: `callimachus` and `hypatia`. Do not add other skill definitions.

Callimachus owns the literature review. Its workflow lives in `skills/callimachus/SKILL.md` and the `/callimachus` prompt. Review state lives in a per-review folder's `ledger.json` (alongside `exports/`, `searches/`, `pdfs/`); its schema is in `skills/callimachus/references/ledger_schema.md`. Records are never deleted.

Hypatia synthesizes only completed Callimachus results. Its workflow lives in `skills/hypatia/SKILL.md`; `/hypatia` delegates missing or incomplete research to Callimachus. It never searches independently.
