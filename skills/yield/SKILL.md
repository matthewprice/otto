---
name: yield
description: The yield funnel for discovery strategies in Otto's steward mode. Per strategy, examined, candidates, prescreen passes, scored, at the persona floor, top 20, Keep and Kill, with points per 100 searches and per run-unit, smoothed yield and a small-sample flag. Use for "which strategy is producing", "show the funnel", or before an allocation.
allowed-tools: Read, Bash(python3 *scripts/yield.py*)
---
Script: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/yield.py"`. Pass `--grant PATH` when the person's grant lives in a repo; OTTO_HOME comes from the environment.

- `report [--days 30] --json`: one line per strategy in the script's ranked order: runs, the funnel, points, points per 100 searches, points per run-unit and smoothed yield. Counts are MEASURED; run-units are ESTIMATE unless the row says MEASURED. Say "small sample" for every strategy the script flags, and do not infer a trend from it. Report blocked runs apart: they are a Sentinel matter, not a yield one.
- `ingest FILE`, `outcomes FILE`, `reviews FILE`: only when the person or their adapter hands you a JSONL file. Report the added, updated and skipped counts.

Call candidates "opportunities" in what you write. End with an Ops read. Do not edit anything.
