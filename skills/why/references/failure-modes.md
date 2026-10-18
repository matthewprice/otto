# Failure modes

Labels the runner and hooks record, and the usual cause of each. These are starting points: confirm with the one check listed before changing anything.

| Label | Usual cause | Confirm with |
|---|---|---|
| auth | Expired or revoked login or token; the job runs from a scheduler that has no keychain access | Run `claude -p "hi"` in the same environment the scheduler uses |
| rate_limit | A 5-hour or 7-day window was already spent when the job started | `/otto:budget`, then check what else ran in that window |
| budget | Console credit balance exhausted ("credit balance is too low") on an API-key run, or a `--max-budget-usd` cap reached | Console Billing page; the run's reported cost against its cap |
| max_turns | Prompt grew, a tool loops, or the cap is too low for the task | Turns in recent runs against the cap |
| timeout | A tool hung, a network call stalled, or the cap is too low | Duration of recent passing runs against the timeout |
| permission | The job needed a tool that is not in `allowed_tools` and prompts are denied | The registry's allowed tools against what the prompt asks for |
| error | Anything else the CLI reported; the exit code and subtype are in the ledger row | Run the command by hand with the same flags |
| miss | Scheduler did not fire (machine asleep, cloud skip, paused routine) | Scheduler log; the machine's sleep history |
| breaker | Three failures in a row stopped the job on purpose | Fix the cause, then `run.py NAME --reset-breaker` |
| drift | Cost, turns or duration outside the automation's usual band | `/otto:why NAME`, then what changed in its skill, model or inputs that day |

## Silent causes worth ruling out

- A cloud routine skipped because a connector credential decayed.
- A laptop asleep at the scheduled time (cron does not catch up; launchd runs missed jobs on wake).
- A monthly credit pool that ran out partway through the month.
- Retries that each cost a full run. Check the retry cost in `/otto:retro`.
