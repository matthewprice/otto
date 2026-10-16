---
name: doctor
description: Check Otto's own setup: scripts, config, registry parsing, ledger health, statusline capture, hooks, and the claude binary. Use when Otto's output looks wrong or empty.
disable-model-invocation: true
allowed-tools: Read, Bash(python3 *scripts/health.py*), Bash(python3 *scripts/budget.py*), Bash(python3 *scripts/install.py*), Bash(claude --version)
---
Check and report pass or fail for each, with the fix for any failure:

1. `python3 --version` is 3.9 or newer and `claude --version` runs.
2. ~/.otto exists; ~/.otto/bin matches the plugin version (`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/install.py"` refreshes it).
3. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/health.py" --json` returns without registry problems.
4. ~/.otto/state/statusline.json exists and is fresh (needs the statusline passthrough from onboard).
5. ~/.otto/state/errors.log has no recent entries; if it does, show the last few labels.

Do not change anything except by running install.py when the person agrees.
