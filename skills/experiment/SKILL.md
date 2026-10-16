---
name: experiment
description: Measure one change to one automation instead of hoping. Estimates the cost of a model, cadence or turn-cap change from the job's own ledger before you make it, records a baseline when you start, and reports the measured before and after with a verdict once enough runs are in. Use for "would Haiku be cheaper here", "did trimming the description help", or before quoting any saving.
disable-model-invocation: true
argument-hint: "estimate NAME [--model M] | start NAME --change TEXT | status [ID]"
allowed-tools: Read, Bash(python3 *scripts/experiment.py*)
---
Script: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/experiment.py"`.

- `estimate NAME [--model M] [--cadence C] [--max-turns N] --json`: present the projection with its ESTIMATE label, the price table date, the sample size, and the assumptions the script names. Under three passing runs, say a dry run would measure what this only guesses.
- `start NAME --change "..." [--kind model|effort|description|cap] [--runs 3]`: show the baseline it recorded, then tell the person exactly what to change and where. Otto does not apply it. The change is also recorded for the weekly retro.
- `status [ID] --json`: while collecting, say how many runs remain. When done, give the medians before and after, the delta, the verdict, and the small-sample caveat when the script sets it. A saving exists only here, never in the estimate.

End with an Ops read. If a result is worth publishing, point to the method in HONEST-NUMBERS.md.
