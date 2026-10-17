# Steward mode

Otto proposes by default. Steward mode is the one place he may apply changes himself, and only the ones you grant. It is built for a fleet of scheduled discovery jobs, called strategies here, that each search for opportunities and pass the best ones to review. The Steward closes the loop between what each strategy costs and what it produces.

It is off until you write a grant. With no grant, or with `enabled: false`, every command below runs in propose mode and prints what it would have done.

## What it does

1. **Measures** every strategy run as a funnel: opportunities examined, candidates, prescreen passes, scored, at or above the review floor, entered the top 20, survived the hardest review. Later outcomes are credited back to the strategy that found the opportunity, so a find that survives a review weeks later still counts.
2. **Allocates** each night: moves searches, daily cap, cadence and model per stage toward the strategies producing survivors per unit of cost, inside bounds you set and never above your pools.
3. **Diagnoses** where each strategy leaks (sources, triage, judgment, review, cost) and picks the lever that matches the leak.
4. **Evolves** weekly: changes one strategy's method, sources, triage questions or gates, or one persona or runner skill, as a measured experiment that reverts itself when it does not pay.
5. **Proposes** new strategies to you, with the evidence, when a strategy's sources are exhausted or one hunting ground is far ahead of the rest. You design and approve every new strategy. The Steward never creates one.

Every change it applies is one git commit, logged with the command that reverts it.

## The grant

A local install keeps the grant in `~/.otto/otto.md`. A fleet whose state lives in a repo keeps it in its own file (for example `ops/steward.md`), sets `OTTO_HOME` to a folder in the repo (for example `ops/.otto`) so all state is tracked, and passes `--grant ops/steward.md` to every script. The commented template is [config/steward.template.md](../config/steward.template.md).

```yaml
---
steward:
  enabled: true
  levers: [budget, cadence, model, gates, method, skills]   # any subset; absent = propose only
  requires-approval: [create-strategy, delete-strategy, raise-pool]
  bounds:
    searches: {min: 50, max: 200, max-daily-shift: 20%}     # per strategy per run
    daily-cap: {min: 10, max: 60}
    cadence: [daily, alternate, weekly, parked]
    models: [haiku, sonnet, opus]                            # the last is the ceiling
    exploration-share: 15%                                   # never squeezed below this
  experiment:
    baseline-runs: 3
    treatment-runs: 3
    metric: yield-per-run-unit
    keep-if: "delta > +10% and survivors not fewer"
    on-fail: revert
    max-active: {per-strategy: 1, fleet-wide: 1}
  pools: ops/budget.md                                       # hard caps the Steward cannot raise
  log: ops/steward-log.md
  pause: ops/control.md
---
```

`python3 scripts/steward.py show` prints the grant as Otto reads it. `steward.py check LEVER` says whether a lever is applied or only proposed, and why.

Rules no grant can override: the Steward never raises a pool, never uses a model above the ceiling (and never `fable`, whatever the list says), never edits the rubric, kill list, recommendation or archive, never queues a persona review, never creates or deletes a strategy, and stops entirely while the pause file says `paused: true` or a `PAUSE` file sits beside it.

## The yield ledger

One JSON line per strategy run in `OTTO_HOME/yield/YYYY-MM.jsonl`, written by `yield.py ingest`. Numbers and short labels only, in the same allowlist tradition as Otto's run ledger: free text is dropped except a 120-character `notes` field and the strategy and opportunity slugs.

```json
{"ts": "2026-10-16T13:11:00Z", "strategy": "S08", "run": 2, "model": "opus", "stages": {"triage": "haiku"},
 "searches": 148, "run_units": 4.5, "run_units_label": "ESTIMATE",
 "examined": 30, "candidates": 14, "prescreen_pass": 0,
 "dropped": {"filter1": 0, "filter2": 1, "filter3": 4, "overlap": 2},
 "scored": 0, "at_floor": 0, "best_score": null, "slugs": [], "blocked": false, "notes": "cursor: grossing chart"}
```

Later events per opportunity (`scored`, `at_floor`, `top20`, `keep`, `kill`, `archived`) go to `OTTO_HOME/yield/outcomes.jsonl` through `yield.py outcomes`. Both are keyed, so a client can rebuild them from its own records every night and nothing is counted twice. Building the rows is the client's job; the math is Otto's.

## The yield metric

| Event | Points | Why |
|---|---|---|
| Cleared the hard filters and was scored | 1 | The funnel's first real signal |
| Scored at or above the review floor | +3 | Earned a review |
| Entered the top 20 after review | +8 | A real contender |
| Survived the hardest review | +20 | The gate that matters most |
| Killed after a full review | -2 | A false positive that cost review budget |
| Archived by the person | -1 | Not what they want more of |

The table is in `scripts/steward_rules.json`; a grant can override any value with a `metric-points:` block.

`yield.py report` gives points per 100 searches and points per run-unit. A run-unit is whatever the scarce resource is, usually a share of a weekly allowance, and is labelled ESTIMATE unless the client measured it. Allocation uses points per run-unit.

Smoothing: a strategy with fewer than 3 runs is blended with the fleet median, weighted by its runs, so one lucky or unlucky night cannot move the allocation much. Under 7 runs a strategy is flagged as a small sample and no trend is inferred. A blocked run (network policy, a failed fetch) is excluded from yield and counted separately; it is a missed run, not a bad one.

## Diagnosis: which lever for which leak

The funnel says where a strategy loses opportunities, and each stage maps to one lever. Without this step, "optimise the strategy" becomes random edits.

| Leak | Signal | Lever | When |
|---|---|---|---|
| Source | Many examined, few candidates; or drops that repeat the kill list and overlaps | Method: swap or add sources, narrow the cursor. After two failed method experiments, propose a new strategy to the person | Weekly |
| Triage | Many candidates, almost none pass the prescreen, drops cluster on one filter | Triage questions and the triage threshold. Revenue-timing drops are surfaced to the person as a possible seasonality pattern | Weekly |
| Judgment | Passes and scores fine, but almost nothing reaches the review floor | Score stage up one model tier for two weeks; tighten the evidence gate | Nightly (model), weekly (gates) |
| Review | Reaches the floor, then dies at the same reviewer most of the time | That reviewer's skill wording, as one fleet-wide experiment | Weekly |
| Cost | Yield fine, run-units well above the fleet | Non-volume stages down one tier, searches down | Nightly |
| Blocked | Runs blocked by network or fetch | None; reported as a missed run and excluded from yield | Sentinel |

`diagnose.py report` prints the leak, the evidence numbers, the lever, whether the grant lets it apply, and whether it is a nightly or weekly action. The thresholds are in `steward_rules.json`.

## Nightly allocation

`allocate.py plan --pool N` reads the yield report, the diagnosis, the grant's bounds and the current settings per strategy (a JSON file the client writes), and produces tomorrow's plan:

1. Cadence: 5 consecutive runs below a quarter of the fleet median moves a strategy to alternate days; 10 parks it. A parked or blocked strategy gets nothing.
2. Shares: a softmax over smoothed yield.
3. Exploration floor: the exploration share of the pool is split across strategies with fewer than 7 runs, and none of them gets less than its part.
4. Clip: every other move is at most the daily shift bound and inside the searches bounds.
5. Pool: the total never exceeds the pool.
6. Models: changed only by the diagnosis, never above the ceiling. Volume stages never leave the lowest tier.

It writes `OTTO_HOME/allocation.json` and prints the plan, with each change marked `apply` only when the grant names its lever and this is not a dry run. Otto applies nothing himself; the client applies the plan, one commit per change.

## Weekly experiments

`evolve.py` extends Otto's experiment pattern for strategies. Each experiment is one change to one target, with a baseline from the last 3 passing runs and a treatment of the next 3:

- `propose` ranks candidates from the diagnosis, at most one per target, within `max-active`.
- `start --target --lever --hypothesis --commit` records the baseline and the revert command after the client has committed the change.
- `status` counts treatment runs.
- `verdict` applies `keep-if`: keep, revert (with the exact `git revert` command and any counter to restore), or extend once by 2 runs when the result is inconclusive at equal cost.

One experiment per strategy and one fleet-wide at a time, because a fleet-wide change (a reviewer's skill, a runner prompt) confounds every strategy's treatment; strategy runs during a fleet-wide experiment are not counted. Skill experiments use a review metric instead of yield: the share of high ratings backed by a sourced fact, the reversal rate at later full review, and searches per job. Keep only if quality rose and searches did not.

`evolve.py` never runs git. It prints the command.

## The runner

`steward.py run nightly|weekly --pool N` runs the steps in order: control check, yield report, diagnosis, allocation, experiment status and verdicts, and on the weekly pass the experiment proposals. `/otto:steward` wraps it. The first night should be `--dry-run`.

## Rails, in one place

- Hard caps live in the pools file and only the person changes them.
- The pause file, or a `PAUSE` file, stops the Steward entirely.
- `enabled: false` drops every command to propose mode.
- One commit per applied change, always revertible, always logged with its revert command.
- At most one experiment per strategy and one fleet-wide; at most two open strategy proposals.
- Never: create or delete a strategy, raise a pool, exceed the model ceiling, touch the rubric, kill list, recommendation, index or archive, queue a review, or send anything outside the repo.
- Small samples are named as such; no allocation move larger than the daily shift bound; no park before 10 runs below the line.
- Every figure is labelled: funnel counts are MEASURED, run-units and shares are ESTIMATE.
