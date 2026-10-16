---
name: wrap
description: Wrap a local automation in the guarded runner (timeout, turn and budget caps, retry cap, circuit breaker, ledger row) and print the scheduler unit. Use when setting up or hardening a headless claude -p job.
disable-model-invocation: true
argument-hint: "<automation-name>"
allowed-tools: Read, Bash(python3 *scripts/install.py*), Bash(python3 *scripts/run.py*), Bash(python3 *scripts/units.py*)
---
For $ARGUMENTS (must be a registry note with `surface: local-cli` and a `command`):

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/install.py"` so the runner has a stable path in ~/.otto/bin.
2. Run `python3 ~/.otto/bin/run.py $ARGUMENTS --dry-run` and show the command it would run. Point out the caps (turns, budget, timeout) and that prompts are denied rather than left hanging.
3. If a cap is missing from the registry note, propose a value from the run history and ask before writing it into the note.
4. Run `python3 ~/.otto/bin/units.py $ARGUMENTS` and show the unit. Tell the person to install it themselves and where it goes. Do not install it.

Never add `--dangerously-skip-permissions`. If the job needs a tool, list it under `allowed_tools` in the note.
