# Build plan

Built so far (v0.1.0 scaffold): all scripts, ten skills, agent, hooks, fixtures, tests, the portable `.skill` bundles (`scripts/bundle.py`), the install guide, and the CI and release workflows.

| Milestone | Goal | Status |
|---|---|---|
| M0 | Install from a clean machine; confirm `${CLAUDE_PLUGIN_ROOT}` expands inside skill text; run `/otto:demo` | to verify |
| M1 | Run the runner against one real job for a week; compare ledger to the usage page | to do |
| M2 | Real `audit` on three projects; publish only measured results in HONEST-NUMBERS.md | to do |
| M3 | Statusline passthrough tested with a chained existing statusline | to do |
| M4 | Evals under `evals/` for the Ops read and the proposal-only rule | to do |
| M5 | Cloud routine and Actions recipes in docs | to do |
| M6 | Launch kit (docs/launch-kit.md): post, short screen recording, a screenshot of the app's Add marketplace and Upload a skill dialogs for docs/install.md | to do |
| M8 | The five roadmap skills (discover, verify, timeline, experiment, watch) built with tests; verify the monitor starts from `/otto:watch` in a real session and that `discover` reads a real crontab and LaunchAgent | built, to verify live |
| M7 | Deferred: PreCompact check, Windows | later |

Known gaps: the guard reads a statusline capture that is one turn stale; SDK credit figures are an estimate; the name `otto` is used by other AI products (ottoai on PyPI, otto8-ai/otto8, Ask Otto), so the repo and plugin are `matthewprice/otto` and the character stays Otto; the `plugin-validate` CI job is continue-on-error until seen green once.
