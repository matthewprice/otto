---
name: status
description: Show whether each registered automation ran, left its output, and cost what it should. Use when asked "did my automations run", "what happened overnight", or "anything broken".
allowed-tools: Read, Bash(python3 *scripts/health.py*), Bash(python3 *scripts/budget.py*)
---
Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/health.py" --json` and `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/budget.py" --json`.

Report one line per automation: name, status, and the evidence (last good run, what is missing). Put anything not `ok` first. Statuses mean: miss (due, no trace), fail, breaker (stopped after repeated failures), late, drift (cost or duration outside its normal band), unobservable (cloud or desktop surface with no output file to check), config (registry note is incomplete), pending (not due yet), paused, new.

End with an Ops read of two to five sentences. Use only numbers from the scripts. If the registry is empty, say so and point to /otto:onboard. Do not edit anything.
