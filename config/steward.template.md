---
# Steward grant. Off by default: without this block, or with enabled: false, every Steward command
# runs in propose mode and prints what it would have done.
# Local install: paste the steward: block into ~/.otto/otto.md, beside your other settings.
# Repo-hosted fleet: save this file in the repo (for example ops/steward.md), set OTTO_HOME to a
# folder in the repo (for example ops/.otto) and pass --grant ops/steward.md to every script.
steward:
  # true turns steward mode on for the levers below. Anything else is propose mode.
  enabled: false
  # The levers Otto may apply. Any subset; a lever left out is proposed, never applied.
  #   budget   searches and daily cap per strategy
  #   cadence  daily, alternate days, weekly, parked
  #   model    the model per stage (never above the ceiling in bounds.models)
  #   gates    triage questions and gate thresholds, as a measured experiment
  #   method   a strategy's sources and method, as a measured experiment
  #   skills   persona and runner skill wording, as a fleet-wide measured experiment
  levers: [budget, cadence, model]
  # Always the person's call. No grant can remove these; you may add to the list.
  requires-approval: [create-strategy, delete-strategy, raise-pool]
  bounds:
    # Searches per strategy per run, and the largest move in one night (percent of today's value).
    searches: {min: 50, max: 200, max-daily-shift: 20%}
    # Daily cap per strategy.
    daily-cap: {min: 10, max: 60}
    # The cadences Otto may choose from. Leave parked out to forbid parking.
    cadence: [daily, alternate, weekly, parked]
    # Allowed models, lowest first. The last is the ceiling. fable is never used, whatever this says.
    models: [haiku, sonnet, opus]
    # Share of the pool held for strategies with fewer than 7 runs. Never squeezed below this.
    exploration-share: 15%
  experiment:
    # Passing runs before the change that form the baseline, and after it that form the treatment.
    baseline-runs: 3
    treatment-runs: 3
    # yield-per-run-unit for strategy changes; persona skill changes use review-quality.
    metric: yield-per-run-unit
    # Keep the change only when this holds; otherwise revert (or extend once at equal cost).
    keep-if: "delta > +10% and survivors not fewer"
    on-fail: revert
    # At most this many experiments collecting at once. A fleet-wide one pauses strategy ones.
    max-active: {per-strategy: 1, fleet-wide: 1}
  # Optional: runs a strategy needs before model, gates, method or skills changes apply to it
  # (default 7, playbook rule 12). Budget and cadence move on any sample.
  # structural-min-runs: 7
  # Optional: override the yield points table in scripts/steward_rules.json.
  # metric-points:
  #   archived: 0
  # Hard caps the Steward reads and can never raise. Relative paths resolve from where you run.
  pools: ops/budget.md
  # Where the client appends one row per applied change, with its revert command.
  log: ops/steward-log.md
  # The Steward stops while this file says paused: true, or a PAUSE file sits beside it.
  pause: ops/control.md
---
Steward grant template for Otto. Read docs/steward.md before turning it on.
