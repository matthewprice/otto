# Architecture

```
registry notes ──┐
output files  ───┼─> health.py ──> status, why
ledger (JSONL) ──┤                 
                 ├─> budget.py ──> budget
statusline file ─┘                 
ledger ──────────────> retro.py ─> retro
~/.claude, project ──> audit.py ─> audit
runner (run.py) ──writes──> ledger      hooks ──write──> ledger
```

State lives in `~/.otto`: `ledger/YYYY-MM.jsonl`, `state/` (statusline capture, breaker, changes, errors), `vault/Automations/` (registry), `bin/` (stable copy of the scripts for schedulers), `otto.md` (settings).

Ledger rows are upserted by session id. When two sources report the same session, the wrapper outranks a manual entry, which outranks a hook. Rows hold numbers and enums from an allowlist; text fields are dropped.

Health replays each expected cycle: given the schedule, the registered date, the ledger and the output file, a cycle is ok, miss, fail, late, drift or unobservable. The runner targets the latest cycle if it lacks evidence and was due within 12 hours, else the next one, and skips if the cycle already has a pass.
