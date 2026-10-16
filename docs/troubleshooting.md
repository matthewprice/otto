# Troubleshooting

- **Empty status:** no registry notes. Run `/otto:register`.
- **Budget windows unavailable:** no statusline capture, or an API-key account. Run `/otto:onboard`.
- **Scheduler job fails with auth:** the scheduler has no access to your login. Set `token_cmd` in `~/.otto/otto.md`.
- **Runner says breaker open:** fix the cause, then `python3 ~/.otto/bin/run.py NAME --reset-breaker`.
- **Skill cannot find scripts:** run `/otto:doctor`.
