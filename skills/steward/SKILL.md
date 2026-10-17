---
name: steward
description: Run Otto's steward mode, the nightly or weekly yield loop for a fleet of discovery strategies. Reads the grant, then the yield report, diagnosis, allocation plan, experiment status and verdicts, and on the weekly pass the experiment proposals. Proposes by default; applies only what the grant names, through the client.
disable-model-invocation: true
argument-hint: "nightly|weekly --pool N [--grant PATH] [--settings FILE] [--dry-run]"
allowed-tools: Read, Bash(python3 *scripts/steward.py*)
---
Script: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/steward.py"`. OTTO_HOME comes from the environment; pass `--grant PATH` for a repo-hosted grant.

1. `show --json`. If the mode is `paused`, say so and stop. If it is `propose`, say every step below only proposes.
2. `run nightly|weekly --pool N --json` with `--settings FILE` if the person has one, and `--dry-run` on a first night or when asked. The script runs the steps in order and writes only `allocation.json` and its own experiment records.
3. Report in this order: anything blocked, tomorrow's allocation (one line per strategy: share, cadence, model, why), experiments in flight with runs remaining, verdicts with their git commands, and on the weekly pass the proposed experiments and any new-strategy proposal for the person.

Counts are MEASURED, run-units and shares are ESTIMATE. Never create or delete a strategy, raise a pool, or edit a rubric, kill list or archive. End with an Ops read.
