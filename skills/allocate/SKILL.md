---
name: allocate
description: Tomorrow's searches, daily cap, cadence and stage models per strategy in Otto's steward mode, within the grant's bounds and never above the pool. Use for "what would the Steward change tonight" or a dry run of the nightly allocation.
disable-model-invocation: true
argument-hint: "--pool N [--settings FILE] [--dry-run]"
allowed-tools: Read, Bash(python3 *scripts/allocate.py*)
---
Script: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/allocate.py" plan --pool N --json`, with `--settings FILE` and `--grant PATH` when the person has them, and `--dry-run` unless they asked for a live plan.

Report one line per strategy: searches now and tomorrow, share, cadence, the leak, and the script's reason. List model changes separately. Say for each change whether it is marked `apply` (the grant names its lever) or propose only. Shares are an ESTIMATE produced by a rule; never call one a result.

The script writes only `allocation.json` in OTTO_HOME. It applies nothing; the person's client does. If the total is below the pool, say so; it is not a shortfall. End with an Ops read.
