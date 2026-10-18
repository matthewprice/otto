---
name: evolve
description: Steward experiments on discovery strategies and persona skills, one change at a time with a measured baseline and an automatic keep or revert verdict. Proposes candidates from the diagnosis, records a start with the change's commit, reports runs remaining, and prints the verdict with the exact git command.
disable-model-invocation: true
argument-hint: "propose | start --target T --lever L --hypothesis TEXT --commit HASH | status [ID] | verdict [ID]"
allowed-tools: Read, Bash(python3 *scripts/evolve.py*), Bash(python3 *scripts/diagnose.py*)
---
Script: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/evolve.py"`, with `--grant PATH` when the grant lives in a repo. Run `diagnose.py report --json` first if the person asks why.

- `propose --json`: the ranked candidates, at most one per target, and what is held back by max-active. `expected_gain` is an ESTIMATE for ranking only. Proposals for a new strategy are for the person to design; say so.
- `start ...`: only after the change is committed. Show the baseline and the revert command. If the script refuses (max-active, no hash), say why.
- `status [ID] --json`: runs collected and remaining per experiment.
- `verdict [ID] --json`: keep, revert or extend, the measured deltas, the small-sample caveat, and the `git` line to run for a revert plus any counter to restore. Otto prints that command; he does not run it.

End with an Ops read.
