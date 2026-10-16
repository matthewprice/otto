---
name: demo
description: Try Otto on synthetic data without touching your own setup. Use right after install, or to see what a report looks like.
disable-model-invocation: true
allowed-tools: Read, Bash(python3 *fixtures/generate.py*), Bash(python3 *scripts/health.py*), Bash(python3 *scripts/budget.py*), Bash(python3 *scripts/retro.py*)
---
Generate a throwaway home: `python3 "${CLAUDE_PLUGIN_ROOT}/fixtures/generate.py" --out /tmp/otto-demo`. Then run health, budget and retro with `--home /tmp/otto-demo --now 2026-09-24T09:15-05:00`.

Say at the top that every automation and number is synthetic and made up to show the format. Show the status table, one failure traced with its evidence, and the Ops read Otto would write. Never mix demo numbers with the person's own, and never quote them as results.
