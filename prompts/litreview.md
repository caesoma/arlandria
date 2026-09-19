---
description: Start or resume a semi-automated literature review in this session (interactive gates, per-paper screening, fast export, asynchronous full-text curation).
args: <research question, or "resume <review>">
section: Research Workflows
topLevelCli: true
---
## Tool Discipline (Read First)

Tool names are literal; use only tools visible in the current tool set. Run the Python primitives through `bash` with `uv run <script>` (never `python` directly - uv provisions their dependencies automatically). To ask the researcher something, write plain chat text and wait for their reply - never advance an interactive gate on an ambiguous answer.

## Task

Load the `literature-review` skill and follow its 9-step workflow for: $@

Key disciplines:
- **Interactive gates (steps 2, 6):** propose, then exchange and revise across as many turns as the researcher wants; proceed only on an explicit release.
- **Screen every retrieved abstract** individually; nothing ranked or skipped. Your decisions are a provisional first pass (`--by llm`).
- **The researcher is the final curator.** Record their overrides `--by human`; never overwrite a human decision.
- **List first, reading later:** export (step 8) as soon as abstracts converge - within the hour - then full-text curation (step 9) proceeds asynchronously over later sessions. Never block on the researcher's reading.
- Follow-ups ("filter by citations", "which cover X best", "resume") are reads/curation over the review folder's `ledger.json` - no new search unless asked to broaden.
