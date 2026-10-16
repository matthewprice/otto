# Moving a job between surfaces

Recipes for carrying an automation from one surface to another with its caps, auth path and registry note intact. Otto prints the steps; you run them. After any move, update the note's `surface` and run /otto:verify.

## cron or launchd to a cloud routine

Why: the laptop sleeps, the job needs to run anyway. Cost: the routine cannot see local files; Otto can only observe it by what it writes to a repo.

1. Put the prompt (the note's `command`) and any skill it uses into a repository the routine will clone.
2. In a session, `/schedule <cadence> <prompt>` and pick the repo and environment. Set the model there; caps are the routine's own.
3. Make the routine write its output to the repo (a dated file) and register that path as `success_file` on a clone you keep locally, or point `success_file` at a path a sync job updates.
4. In the note: `surface: cloud-routine`, remove `command`, `cwd` and the runner caps, keep `expected_by` (routines on the hour start late; add 10 minutes).
5. Remove the local unit (`launchctl unload` or delete the crontab line). Keep the note's history.

## Desktop scheduled task to a wrapped claude -p

Why: a Desktop task leaves no ledger row and no cost; the runner gives you both plus caps and a breaker.

1. Copy the prompt from `~/.claude/scheduled-tasks/<name>/SKILL.md` into the note's `command` (as a slash command if it is a skill, else the text).
2. Set `surface: local-cli`, `cwd`, `allowed_tools`, `max_turns`, `max_budget_usd`, `timeout_min`.
3. `/otto:wrap NAME` prints the runner command and the unit. Install the unit. Run `python3 ~/.otto/bin/run.py NAME --dry-run` first.
4. Pause the Desktop task in the app (keep it until the first wrapped run passes), then delete it.

## /loop to cron

Why: a loop dies with the session and expires after seven days.

1. The loop's prompt becomes the note's `command`; its interval becomes `days` and `run_at` (cron has no sub-hour cadence worth running unattended; if it was `/loop 5m`, it is a monitor, not an automation).
2. Same as the Desktop recipe from step 2.

## Subscription login under a scheduler

`claude -p` under cron or launchd does not see your interactive login. Run `claude setup-token` once and set `token_cmd` in `~/.otto/otto.md` to a command that prints it (a keychain or password-manager read). The runner exports it per run and never writes it to disk. If runs start failing with `auth`, the token expired: run `setup-token` again, then `run.py NAME --reset-breaker`.
