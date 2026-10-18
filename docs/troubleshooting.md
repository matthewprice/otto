# Troubleshooting

- **Empty status:** no registry notes. Run `/otto:register`.
- **Budget windows unavailable:** no statusline capture, or an API-key account. Run `/otto:onboard`. API-key accounts have no subscription windows; use `budget_daily_usd` or `budget_weekly_usd` instead (README, "API-key accounts").
- **Scheduled job fails with "invalid api key" on an API-key account:** the scheduler does not see `ANTHROPIC_API_KEY`. Set `api_key_cmd` in `~/.otto/otto.md`.
- **Runner says to set token_cmd or api_key_cmd, not both:** pick the account the job should bill and remove the other key.
- **Scheduler job fails with auth:** the scheduler has no access to your login. Set `token_cmd` (subscription) or `api_key_cmd` (API key) in `~/.otto/otto.md`.
- **Runner says breaker open:** fix the cause, then `python3 ~/.otto/bin/run.py NAME --reset-breaker`.
- **Skill cannot find scripts:** run `/otto:doctor`.
