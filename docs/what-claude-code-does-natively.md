# What Claude Code already does

Otto fills gaps, so use the native feature where it covers you. When a native feature covers something Otto does, Otto reads that feature's data instead of computing his own. Checked against Anthropic's documentation in October 2026; open an issue when this drifts.

## Native features Otto reads

- **Statusline `rate_limits`.** The only live source of the 5-hour and 7-day window percentages (`used_percentage`, `resets_at`), Pro and Max only, after the first response of a session. Plugins cannot ship a statusline, so onboarding installs a small capture that saves it to `~/.otto/state/statusline.json`. Otto reads it; he does not replace it. [Source](https://code.claude.com/docs/en/statusline).
- **`claude -p --output-format json`.** Reported cost, tokens per model, turns, duration and stop reason for each headless run. The runner stores these numbers in the ledger. [Source](https://code.claude.com/docs/en/headless).
- **Session transcripts.** Token usage per message and the session's reported cost. The Stop hook summarizes them into one ledger row.
- **`StopFailure` hook.** Fires when a turn ends on an API error, with an error type such as `rate_limit`, `billing_error` or `authentication_failed`. Otto records the label. [Source](https://code.claude.com/docs/en/hooks).
- **`SessionStart` on resume.** Claude Code passes `estimated_cache_write_usd`; Otto warns when resuming a cold session costs more than your threshold. [Source](https://code.claude.com/docs/en/hooks).

## Native features to use directly

- **`/usage` and the usage page.** Authoritative limits. `/usage` also attributes spend to skills, subagents, plugins, MCP servers and loops over 24 hours or 7 days, for one machine. [Source](https://code.claude.com/docs/en/costs).
- **Console Billing and Cost pages (API keys).** Authoritative spend and credit balance, including the monthly API credit that Max and Team plans include. Otto's credit figure is an estimate from his own runs; other keys in the same organization spend the same balance. [Source](https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers).
- **Workspace spend limits (API keys).** A hard monthly cap with alert thresholds per workspace. If you need a hard stop on API spend, set one; Otto's soft budgets only report. [Source](https://platform.claude.com/docs/en/manage-claude/workspaces).
- **`--max-turns` and `--max-budget-usd`.** Native caps for a single `claude -p` run. The runner passes them through and adds what works across runs: attempt caps, the breaker and the idempotency check. [Source](https://code.claude.com/docs/en/cli-reference).
- **`claude plugin details`.** Projected always-on and on-invoke token cost of each installed plugin. [Source](https://code.claude.com/docs/en/plugins/cli-reference).
- **Routine run history.** `/schedule list` and the routines page show each cloud routine's runs. A green status means the session started and exited cleanly, not that the task succeeded, which is why Otto checks the output file. [Source](https://code.claude.com/docs/en/routines).
- **OpenTelemetry export.** `claude_code.cost.usage` and `claude_code.token.usage` metrics, if you run a backend and want history beyond the 30 days of local session data. Otto keeps his own months-deep ledger in a file so you do not need one. [Source](https://code.claude.com/docs/en/monitoring-usage).

## What none of these do

Notice a run that did not happen, judge a run by its output, keep cost per workflow across surfaces and months, stop a workflow after repeated failures, or measure what a change saved. That is Otto's job.
