# Fixtures

`generate.py --out DIR` builds a synthetic Otto home. Every automation and number is invented. Use `--now 2026-09-24T09:15-05:00` with the scripts to reproduce the planted scenarios. Never quote these numbers as results.

The same home carries a synthetic yield ledger for steward mode (`yield/`, `strategies.json`, `steward-grant.md`, `control.md`, `budget.md`): six fictional strategies over 30 days, one over-performer, one source leak, one triage leak, one judgment leak, one blocked and one with two runs. Try `OTTO_HOME=DIR python3 scripts/steward.py --grant DIR/steward-grant.md --now 2026-09-24T09:15-05:00 run weekly --pool 600 --dry-run`. These numbers are invented too.
