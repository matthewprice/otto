---
name: why
description: Explain why one automation failed, was late, or got more expensive. Use when asked "why did X fail", "why was X slow", or "why did X cost more".
argument-hint: "<automation-name>"
allowed-tools: Read, Bash(python3 *scripts/health.py*), Bash(python3 *scripts/ledger.py*), Bash(python3 *scripts/retro.py*)
---
Investigate $ARGUMENTS.

1. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/health.py" --automation $ARGUMENTS --json`.
2. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py" query --automation $ARGUMENTS --since 14d --json` for its recent runs.
3. Read its registry note for what success is meant to look like.

Work from the evidence in this order: did it run at all, did it exit cleanly, did it leave its output, did cost or turns change, did anything change on that date (`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/retro.py" effects`). Read references/failure-modes.md for the usual causes of each failure label.

Name the most likely cause and the single check that would confirm it. If the evidence does not decide between two causes, say which two and what would separate them. Propose a fix; do not apply it.
