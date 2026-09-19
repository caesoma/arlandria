# Repo guidance for agents

This package adds a `literature-review` skill to Pi. The workflow lives in `skills/literature-review/SKILL.md` and the `/litreview` prompt. The review state lives in a per-review folder's `ledger.json` (the ledger; the folder also holds `exports/`, `searches/`, `pdfs/`) — its schema is in `skills/literature-review/references/ledger_schema.md`. Records are never deleted.
