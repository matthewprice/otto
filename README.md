<p align="center"><img src="assets/banner.svg" width="100%" alt="Otto. Put every token to work. The ops layer for the agentic workflows that run without you. He proposes. You run the command."></p>

<p align="center">
  <a href="https://github.com/matthewprice/otto/actions/workflows/ci.yml"><img src="https://github.com/matthewprice/otto/actions/workflows/ci.yml/badge.svg" alt="ci"></a>
  <a href="https://github.com/matthewprice/otto/releases"><img src="https://img.shields.io/github/v/release/matthewprice/otto?include_prereleases&color=f7b32b" alt="release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/matthewprice/otto?color=d97757" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/python-3.9%2B-1f3c56" alt="Python 3.9 or newer">
  <img src="https://img.shields.io/badge/dependencies-none-2f8f5b" alt="no dependencies">
</p>

**Put every token to work.** Your agentic workflows are supposed to turn tokens into finished work while you are elsewhere. On a Claude subscription, those tokens are a budget that refills every five hours and every week, whether you use it or not. On an API key, every token is billed, including the ones a failed run burns. Either way, Otto is the operations layer that makes sure the tokens land. He keeps a registry of what should run, proves what did, counts what it cost, and paces spend against the limits that actually gate you. He also audits the context tax of everything you have installed and measures every change, so next week's work costs less than this week's. He runs inside Claude Code and the Claude app on the account you already have, subscription or [API key](#api-key-accounts). He proposes. He never changes anything without being told.

```
/plugin marketplace add matthewprice/otto
/plugin install otto@otto
/otto:demo
```

Then, on your own setup: `/otto:onboard` (a ten-minute interview), `/otto:discover` (finds the workflows already on the machine and registers the ones you confirm), and `/otto:status` (what ran, what did not, what it cost).

Claude app or Cowork: Settings, Plugins, Add marketplace, paste `matthewprice/otto`. One skill as a file: drop `otto-audit.skill` or `otto.skill` from the [latest release](https://github.com/matthewprice/otto/releases/latest) into Settings, Skills, Upload a skill. Other agents: `npx skills add matthewprice/otto`. Every path, what it writes where, and how to uninstall: [docs/install.md](docs/install.md).

---

## Who this is for

Otto is for people who run Claude as infrastructure rather than as a chat window: agentic workflows on a schedule, in CI, or in the background, and someone who has to answer three questions about them every week. Did it run? What did it cost? What should change? Otto calls each workflow he tracks an automation.

- **On a Pro or Max plan:** you want the windows you already pay for filled with work instead of expiring unused.
- **On an API key:** you pay per token, so you want every run capped, every repeated failure stopped early, and spend tracked per workflow, not per invoice.

Five ways Otto puts tokens back to work. The first is for subscriptions; the other four apply to both.

1. **Fill the windows you already pay for.** A workflow that lands in a quiet window costs nothing extra; the same workflow during your keyboard hours competes with you for the limit. `/otto:timeline` shows the day and proposes the move.
2. **Stop paying for runs that produce nothing.** Retries, turn-limit failures, expired logins that fail three nights in a row, routines that silently skip. `/otto:status` reports the miss first; the runner's breaker stops the bleeding.
3. **Cut the context tax.** Over-cap descriptions, bloated CLAUDE.md files, never-used MCP servers and skills, workflows that start cold and re-pay their prefix every run. `/otto:audit` measures it; `/otto:timeline` clusters the cold starts.
4. **Right-size each workflow.** The digest does not need the model the refactor needs. `/otto:experiment estimate` projects the change from the workflow's own token mix; `start` and `status` measure whether it paid.
5. **Keep the proof.** Months of ledger, a weekly retro, and a shareable report, so the number you quote is one you measured.

---

## What you cannot do in Claude today

As of October 2026, Claude can run on a schedule in several first-party places: `/loop` in a session, Desktop scheduled tasks, cloud routines, and Managed Agents scheduled deployments (beta). Add Claude in GitHub Actions and any `claude -p` workflow you put under cron or launchd. Each is good at running. None of them does the following, and Otto exists for this list.

| | Without Otto | With Otto |
|---|---|---|
| **Notice silence** | Nothing reports a run that did not happen. A skipped routine, a laptop that slept through cron, an expired login under launchd: the first sign is the report that never arrived. Routines and Desktop tasks share a run list; `/loop`, cron, GitHub Actions and Managed Agents each keep their own. | One registry of every workflow on every surface, with its cadence and what success looks like. A run that was due and left no trace is a `miss`, reported before anything that succeeded. |
| **Judge success by output** | Anthropic's routines docs say a green status means the session started and exited without an infrastructure error, not that the task in your prompt succeeded. | Every run is judged against its registered expectation: the file exists, is recent, matches its pattern, and cost and duration sit inside their bands. |
| **Keep months of cost history** | `/usage` attributes spend to skills, plugins, MCP servers and loops, over 24 hours or 7 days, for one machine. Local session data is deleted after 30 days by default. Longer history means running an OpenTelemetry backend. | A ledger of every run, months deep, in a file you own, with no backend to run. Cost per workflow per week, step changes dated, retries counted as the full runs they are. |
| **Pace every limit at once** | On a subscription, the 5-hour and 7-day windows gate interactive and `claude -p` use alike, and only the statusline reads them live. Max and Team plans also include a monthly API credit that pays only for API-key runs, shown on the Console Billing page; when it runs out with no purchased credits, API requests stop until it refreshes. On an API key, the Console shows spend by workspace and model, not by workflow. | One read: each limit, percent used against percent of the period elapsed, projected exhaustion, spend per workflow, and which workflows to defer. |
| **Stop repeat failures** | `--max-turns` and `--max-budget-usd` cap a single `claude -p` run. Nothing native caps attempts per day, stops a workflow after its third failure in a row, or skips a run whose output already exists. | A guarded runner for `claude -p` workflows: turn, budget and time caps, prompts denied rather than left hanging, an attempt cap per day, a circuit breaker after repeated failures, and an idempotency check. |
| **Hold the line in a session** | No setting or hook can stop a turn because your 5-hour window is at 92 percent. Hooks never receive the window percentages, and `autoContinueAtUsageLimit` only waits for the reset. | An opt-in guard that reads the statusline's rate-limit data and warns or blocks at the threshold you set. Off by default. |
| **Audit context cost with real numbers** | `claude plugin details` projects each plugin's always-on token cost, and `/usage` attributes spend to skills and MCP servers. Neither checks your CLAUDE.md files, finds the MCP servers and skills you never use, or shows which workflows start with a cold cache. | Every skill, agent, plugin, MCP server and CLAUDE.md measured against the real caps, with findings from transcripts labelled MEASURED and findings from file sizes labelled ESTIMATE. |
| **Know what a change saved** | You apply a recommendation and hope. | `/otto:experiment` records a baseline, you apply the change, and the verdict comes from three passing runs on each side. A saving exists only once it has been measured. |

Otto only builds what Claude does not already do. When Claude Code ships a feature that covers one of these rows, Otto switches to reading that feature's data and retires his own version. [What Claude Code already does](docs/what-claude-code-does-natively.md) lists what is native today and which native features Otto reads.

---

## Meet Otto

<table>
  <tr>
    <td align="center" width="16%"><img src="assets/otto-driver.svg" width="110" alt="Otto the Driver"><br><sub><b>The Driver</b><br>Knows what left the depot</sub></td>
    <td align="center" width="16%"><img src="assets/otto-captain.svg" width="110" alt="Otto the Transit Captain"><br><sub><b>Transit Captain</b><br>The registry</sub></td>
    <td align="center" width="16%"><img src="assets/otto-stoparm.svg" width="110" alt="Otto with the stop arm out"><br><sub><b>The Stop Arm</b><br>The circuit breaker</sub></td>
    <td align="center" width="16%"><img src="assets/otto-wheel.svg" width="110" alt="Otto behind the wheel"><br><sub><b>Behind the Wheel</b><br>The runner</sub></td>
    <td align="center" width="16%"><img src="assets/otto-later.svg" width="110" alt="Otto in shades, hand raised"><br><sub><b>Later, Dudes</b><br>The Ops read</sub></td>
    <td align="center" width="16%"><img src="assets/otto-window.svg" width="110" alt="Otto in the window seat"><br><sub><b>Window Seat</b><br>The avatar</sub></td>
  </tr>
</table>

Otto is a dispatcher: the person in the depot who knows what is scheduled, notices what did not come back, and tells you in plain words what it cost. Calm, dry, specific. Short sentences. He names the automation, the time, and the number. He does not cheer and he does not apologise. He reports the miss before the success, says "reported cost" rather than "bill", and tells you when a sample is too small to mean anything.

Every report ends with an **Ops read**: two to five sentences on what matters most, the one thing to change this week, and what will hit a limit next. This is what `/otto:demo` prints on its synthetic month. Every name and number below is made up to show the shape.

```
Otto status  Thu 24 Sep 09:15                                  (synthetic demo data)

MISS     repo-watch      routine       due 06:30; no ledger row, no file work/repo-watch/2026-09-24.md
BREAKER  nightly-sync    local-cli     open since Tue 02:06; authentication_failed three runs in a row
FAIL     weekly-brief    local-cli     08:29, exit 1 (error_max_turns); no file work/briefs/2026-W39.md
DRIFT    inbox-triage    local-cli     ran ok, but 19.0 min (band 2 to 12) and $2.94 (band $0.30 to $1.50)
OK       desktop-notes   desktop-task  output found, 1,704 bytes; no ledger row, so cost is unknown
OK       morning-digest  local-cli     07:04, $1.28

Windows  5-hour 31%, resets 12:05        7-day 58% with 68% of the week elapsed, on pace for 86%  watch
Credit   API credit about 61% used with 78% of the month elapsed; on pace for $78 of $100     watch
Week     $28.85 reported; $10.18 of it on runs that failed (weekly-brief, twice)

Ops read. Two of six automations did not deliver and a third is stopped. nightly-sync is a login that
expired on Sunday; nothing told you until now, and the fix is one `claude setup-token` and a breaker
reset. weekly-brief has spent $10.14 on two turn-limit failures, all of it from the API credit; raise
max_turns from 8 to 12 before Monday or it fails a third time. The credit is on pace to hold this
month. I have not changed anything.
```

---

## Otto's virtues

The fifteen rules in [config/ops_playbook.md](config/ops_playbook.md), numbered so a report can cite them. They are the product; the scripts just do the arithmetic.

1. **Evidence over exit codes.** A run succeeded when its output exists, is recent, and passes its checks. An exit code of zero is a claim, not evidence.
2. **Silence is a finding.** An automation that was due and left no trace is a `miss`, and it is reported first.
3. **Numbers only.** Reports use the numbers the scripts produced. If one is missing, Otto says what is missing rather than filling the gap.
4. **Measured and estimated stay apart.** Every figure is labelled MEASURED or ESTIMATE. An estimate is never presented as a saving.
5. **Propose, never apply.** Otto writes his own registry notes and `~/.otto`. He never edits your automation, skill, settings or schedule unless you tell him to in the current conversation.
6. **Reported cost is not a bill.** Cost is what Claude Code reported, a client-side estimate at list price. Your usage page is the source of truth.
7. **Three pools, never merged.** Subscription windows, the monthly API credit (Max and Team, API-key runs only), and your own soft budgets are separate limits, reported separately.
8. **Cap every headless job.** Turns, budget, timeout, and an allowlist of tools. Prompts are denied, not left waiting for someone who is asleep.
9. **Retries are runs.** A retry costs a full run. Attempts are capped per day and stopped after repeated failures.
10. **Fail open, except the guard.** Observers never block your work. Only the opt-in guard may block, and it always lets `/otto:` commands and the phrase `otto: go ahead` through.
11. **Privacy by construction.** The ledger holds numbers and short labels. No prompts, no outputs, no file contents, no paths beyond names, no network calls.
12. **Small samples are small.** Under ten sessions, he says so. No trend is inferred from fewer than seven runs.
13. **Steps are places to look.** A step change in cost points at a date. It does not name a cause.
14. **Ask before cost.** Anything that spends money or changes a schedule is confirmed first.
15. **Always end with the Ops read.** Two to five sentences: what matters most, and what Otto would do.

---

## What you get

Fifteen thin skills (nineteen with steward mode), one agent, five hooks, one background monitor, and a set of Python scripts with no dependencies beyond the standard library. Skills marked *you* only run when you invoke them; the rest Otto can also reach for on his own when a question fits.

| Command | Who | What it does |
|---|---|---|
| `/otto:status` | both | Per-automation status: ok, miss, fail, late, drift, breaker, unobservable |
| `/otto:why NAME` | both | The evidence behind a failure or a cost jump, and the one check that confirms it |
| `/otto:budget` | both | 5-hour and 7-day windows, the monthly API credit, and soft budgets, kept as separate pools |
| `/otto:audit [path]` | both | Context-tax audit of a project, measured findings apart from estimates |
| `/otto:retro` | you | Weekly deltas, silent misses, cost step changes, measured effect of the changes you logged |
| `/otto:wrap NAME` | you | The guarded runner for a headless job, plus a launchd, cron or systemd unit you install yourself |
| `/otto:register NAME` | you | Describe one automation: surface, cadence, what success looks like, caps |
| `/otto:onboard` | you | A ten-minute setup interview; writes `~/.otto/otto.md` and asks before touching anything else |
| `/otto:doctor` | you | Health of Otto himself: versions, statusline capture, registry |
| `/otto:demo` | you | A tour on a synthetic month of data, before you register anything of your own |
| `/otto:discover [path]` | you | Finds the automations already on the machine (crontab, launchd, systemd, Desktop tasks, workflows, recurring headless sessions), drafts a note for each you confirm, reports registry drift |
| `/otto:verify NAME` | you | Lints a note and runs its success check right now; `--drill miss\|auth\|budget\|timeout` stages the failure in a scratch copy and shows what tomorrow's status would say |
| `/otto:timeline` | both | The day on a grid: runs against the 5-hour windows, the cache TTL and your keyboard hours, with proposed moves and the exact unit command |
| `/otto:experiment` | you | Estimate a model, cadence or cap change from the job's own ledger, record a baseline, and get a measured before-and-after verdict |
| `/otto:watch` | you | A live monitor for the session: speaks only when an automation misses, fails, trips its breaker, recovers, or a window crosses a threshold |

**Hooks** (shipped, observe-only, fail open): `Stop` appends the per-session ledger row, `StopFailure` records rate-limit, billing and authentication failures with a timestamp, `Notification` records background-agent completions, `SessionStart` on resume reports the estimated cache-write cost before you continue a stale session, and the optional `UserPromptSubmit` guard described above. The **monitor** (`otto-watch`) starts the first time `/otto:watch` runs in a session and polls every five minutes; it also writes `Alerts.md` in the vault and can run from cron with `watch.py --once` when no session is open.

**Portable bundles.** Two skills also ship as standalone `.skill` files for the Claude app's upload dialog: `otto-audit` (the audit with its scripts inside) and `otto` (the persona and playbook, for giving Otto your run histories by hand). Sources are under [`portable/`](portable/); `python3 scripts/bundle.py` builds them and CI attaches them to every tagged release.

### Steward mode (opt-in)

Off by default. If you run a fleet of scheduled discovery jobs and want Otto to move budget toward the ones that produce, you can grant him named levers: budget, cadence, model per stage, gates, a strategy's method, or a persona skill's wording. He then measures every run as a funnel, plans tomorrow's searches and cadence inside bounds you set and never above your pools, diagnoses where each strategy leaks, and runs one change at a time as a measured experiment that reverts itself when it does not pay.

Unused pool is never handed to the strategies already running, since more volume on the same sources is exactly the failure he exists to stop. It is kept as a reserve that funds only experiments in progress and newly approved strategies, and whatever they do not need stays unspent.

He applies only what the grant names. Everything else stays a proposal. With or without a grant he never creates or deletes a strategy, raises a pool, uses a model above the grant's ceiling, edits the rubric, kill list, recommendation, index or archive, or queues a persona review (the full list is in [the Rails section of docs/steward.md](docs/steward.md#rails-in-one-place)). Every applied change is one commit, logged with the command that reverts it. A pause file stops him outright. Four skills drive it: `/otto:yield`, `/otto:allocate`, `/otto:evolve` and `/otto:steward`. The grant template is [config/steward.template.md](config/steward.template.md) and the design is [docs/steward.md](docs/steward.md).

---

## How it works

Everything Otto does is reading, with two exceptions: the ledger he writes and the optional guard.

- **Registry.** One Markdown note per automation under `~/.otto/vault/Automations/`, with YAML frontmatter the scripts can parse and you can edit by hand: surface, schedule, where the output should appear, cost and duration bands, caps.
- **Ledger.** One JSON line per run in `~/.otto/ledger/`. Numbers and short labels only, deduplicated by session. Months of a busy user are a few megabytes.
- **Health.** Replays every expected cycle against the ledger and the output file. Due with no trace is `miss`; exit zero with no output is `fail`; outside the band is `drift`.
- **Runner.** Optional wrapper for `claude -p` jobs: turn, budget and time caps, prompts denied, an attempt cap, a circuit breaker, an idempotency check, and the ledger write at exit. It never uses `--dangerously-skip-permissions`.
- **Budget.** Pacing from the statusline's rate-limit data (persisted to a side file by a capture you install through onboarding, since plugins cannot ship a statusline) and from reported run cost.
- **Audit.** Skills, agents, plugins, MCP servers and CLAUDE.md measured against the real caps, with transcript-backed findings labelled MEASURED.

### What Otto can see on each surface

| Surface | What Otto reads | What he cannot see |
|---|---|---|
| `claude -p` on your machine, through the runner | Everything: outcome, cost, tokens, turns, duration, which account it billed, and the output file | Nothing in the run itself |
| `claude -p` or a session on your machine, without the runner | Cost, tokens and duration from the Stop hook, and the output file | Attempts, caps and the breaker, which only the runner applies |
| `/loop` in a session | The session's cost through the hooks, and each iteration's output file | The cost of one iteration on its own |
| Desktop scheduled tasks, cloud routines, Cowork, GitHub Actions, Managed Agents | The output file the workflow leaves when it succeeds | Cost and tokens. A workflow with no success file shows as `unobservable` |

How the pieces fit is in [docs/architecture.md](docs/architecture.md). The persona is in [docs/persona.md](docs/persona.md).

### What Otto costs to run

The morning status is a Sonnet run over a few kilobytes of ledger and registry; the audit is weekly and announced with its own cost. The agent runs at `model: sonnet`, `effort: medium`. `claude plugin details otto` estimated about 1,340 tokens always-on for version 0.1.0 (fifteen skills and the agent) in October 2026, before steward mode added four more; run it yourself, since that figure is Claude Code's estimate and will move as the skills change.

---

## What Otto never does

- Edit your automations, skills, settings or schedules. He proposes; you apply. The one exception is steward mode, and only for the levers your grant names.
- Store prompts, outputs or file contents. The ledger is an allowlist of numbers and enums.
- Send anything anywhere. No network calls, no telemetry, no accounts.
- Use `--dangerously-skip-permissions`, or suggest it.
- Claim a saving he has not measured.
- Pretend to be a HUD, a proxy, a gateway, a scheduler for cloud routines, or a multi-agent framework. Those exist, some are good, and [SCOPE.md](SCOPE.md) names what Otto recommends instead.

---

## Honest numbers

Cost figures are what Claude Code reported per run, a client-side estimate at list price, not billing data. The audit separates MEASURED from ESTIMATE. The demo data is synthetic and says so on every screen. Otto's measured results on real setups will be published in [HONEST-NUMBERS.md](HONEST-NUMBERS.md) with the method, once collected; until then the file holds the method and no results. If you run Otto for a week and want your numbers in that file, open a pull request with the method followed.

## Requirements

Claude Code (validated on 2.1.301), Python 3.9 or newer, macOS or Linux. The statusline passthrough that enables the 5-hour and 7-day figures needs a Pro or Max plan. Windows is not supported in 0.1.

### API-key accounts

Otto also works when Claude Code is signed in with an Anthropic API key instead of a subscription. The registry, ledger, status, why, timeline, audit and retro read what Claude Code records for each session, which is the same on either account.

- **Runner:** a scheduler does not load your shell profile, so set `api_key_cmd` in `~/.otto/otto.md` to a command that prints the key (a keychain or password-manager read). The runner exports it as `ANTHROPIC_API_KEY` for that run only and never writes it to disk. Set `api_key_cmd` or `token_cmd`, not both: each one also removes the other credential from the job's environment, so a run bills exactly the account you chose. With neither set, the job inherits whatever its environment holds.
- **Not applicable:** the 5-hour and 7-day windows (`/otto:budget` reports them as unavailable) and the guard (it acts only on those windows, so it always allows).
- **The monthly API credit:** if your key belongs to the Console organization linked to a Max or Team plan, your API-key runs draw on that plan's monthly credit. Set `api_credit_usd` and `api_credit_reset_day` (the day your billing cycle starts) and Otto paces it. Otherwise leave them empty.
- **Use instead:** `budget_daily_usd` and `budget_weekly_usd` in `~/.otto/otto.md`. Reported cost is still a client-side estimate at list price, but on an API key that is the price you pay, so the soft budgets track your bill more closely than they do on a subscription.

## Status

Version 0.2.0, early. The scripts, skills, hooks, monitor and tests are built, including the five skills designed in [docs/skills-roadmap.md](docs/skills-roadmap.md) and the opt-in steward mode; a real week of runner data and the measured audit results are still to come. [SCOPE.md](SCOPE.md) says what is in and out, [BUILD.md](BUILD.md) has the plan, [docs/troubleshooting.md](docs/troubleshooting.md) has the common causes of an empty report. Start with `/otto:doctor` when something looks wrong.

---

## Feedback and contributing

Otto is young and opinionated, and he is only as good as the evidence he reads. Tell him where he is wrong.

- **Ran him for a week?** Open an issue and say what he missed, what he got wrong, and what the Ops read should have said. A screenshot of a real Ops read, with the numbers you are happy to share, is the most useful thing you can send.
- **Found a bug?** Use the [bug template](.github/ISSUE_TEMPLATE/bug.md). `/otto:doctor` output contains no prompt text and is safe to paste.
- **Want a check, a skill or a surface?** Use the [proposal template](.github/ISSUE_TEMPLATE/proposal.md): the problem, why it fits [SCOPE.md](SCOPE.md), and how it would be measured.
- **Security concern?** [SECURITY.md](SECURITY.md) explains private reporting. Anything that could put prompt text in the ledger or write outside `~/.otto` is top priority.

Contributions most wanted right now:

1. **Registration templates** for popular automations (a daily digest, a repo watch, an inbox triage), so `/otto:register` can start from one.
2. **Surface recipes** in `docs/` for desktop scheduled tasks, cloud routines and GitHub Actions: how each exposes its run history and what Otto should treat as a miss.
3. **Measured results** for HONEST-NUMBERS.md, following its method.
4. **Audit checks** with tests, where you have seen a real pattern waste real tokens.
5. **Windows support** for the runner and the units.

The bar, from [CONTRIBUTING.md](CONTRIBUTING.md): standard library only, Python 3.9 compatible, observers fail open, the ledger stays an allowlist, every figure labelled, fixtures stay synthetic, skills stay thin with the logic in tested scripts. Small pull requests with one concern each, saying what you verified and what you did not. Everyone here follows the [code of conduct](CODE_OF_CONDUCT.md).

---

## License

Otto is open source under the [MIT License](LICENSE), copyright 2026 Matt Price. In plain terms:

- You may use, copy, modify, merge, publish, distribute, sublicense and sell copies of this software, for any purpose, including commercial use and inside closed-source products.
- The only condition is that the copyright notice and the permission notice in [LICENSE](LICENSE) stay with any copy or substantial portion of the software.
- It is provided as is, without warranty of any kind. The authors are not liable for anything that happens as a result of using it, including a scheduled job you cap, a breaker that opens, or a number Otto estimated.

Contributions are accepted under the same license.

**On the mascot.** Otto is drawn on the Clawd sprite. Clawd belongs to Anthropic, redrawn here with affection and no affiliation; the driver styling is the archetype (hair, cap, headphones, a stop arm) and not a copy of any other character. The pixel data and the generator in [`assets/make_sprites.py`](assets/make_sprites.py) are MIT like the rest of the repo, but that grant cannot cover the Clawd character itself, which is not ours to license. Otto is an independent project and is not affiliated with, endorsed by, or supported by Anthropic. Claude is a trademark of Anthropic, PBC.
