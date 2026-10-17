# Scope

Otto watches and advises. He does not run your work, except through the optional runner for `claude -p` jobs, and he does not change it, except for the levers an opt-in steward grant names.

## In scope
- Registry, ledger, silence detection, drift detection
- Budget pacing from data Claude Code exposes
- Context-tax audit with measured and estimated findings kept apart
- A guarded runner for headless jobs and scheduler units printed for you to install
- Weekly retro with measured before and after
- In scope under an explicit grant: applying changes to the levers a steward grant names (budget, cadence, model, gates, method, skills), each as one logged, revertible commit (`docs/steward.md`)

## Out of scope
- Applying changes to a user's automations or settings without a steward grant, or to anything a grant does not name (`.out-of-scope/auto-apply.md`)
- Creating or deleting a strategy, raising a pool, or editing a rubric, kill list or archive, with or without a grant
- Dashboards served over a network, accounts, or telemetry
- Reading or storing prompt and output text
- Exact token counts; Otto reports what Claude Code reported and labels estimates
- Windows support in 0.1
- Anything that bypasses permissions

Proposals that fit the "in scope" list are welcome. See CONTRIBUTING.md.
