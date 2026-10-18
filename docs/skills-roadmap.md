# Skills roadmap: the next five

Designed with Matt on 2026-10-15 from eight candidates. Three were folded into existing skills: `estimate` is the "before" half of `experiment`, `migrate` is a set of recipes inside `wrap`, and `report` is a shareable format on `retro`. Build order: discover, verify, timeline, experiment, watch.

Rules that apply to all five, unchanged from the rest of Otto: Otto writes only his own registry notes and `~/.otto`; every other change is printed for the person to apply. Optimised for one person with a handful of scheduled jobs on a subscription. Standard library only. Every figure labelled MEASURED or ESTIMATE.

## 1. discover

**Problem.** Registering automations by hand is the biggest onboarding chore, and the registry drifts the moment you edit a cron line and forget the note.

**Looks in**, on the first pass:

| Source | How | What it yields |
|---|---|---|
| crontab | `crontab -l` | lines that call `claude` or Otto's runner: schedule, command, cwd |
| launchd | `~/Library/LaunchAgents/*.plist` | `ProgramArguments` with `claude` or the runner; `StartCalendarInterval` or `StartInterval` |
| systemd user timers | `~/.config/systemd/user/*.timer` and the matching `.service` | `OnCalendar`, `ExecStart` |
| Desktop scheduled tasks | `~/.claude/scheduled-tasks/*/SKILL.md` | name and description only; the schedule lives in the app and is asked for |
| In-session saved tasks | `.claude/scheduled_tasks.json` in the project | cron and prompt |
| GitHub Actions | `.github/workflows/*.yml` in the project | `schedule:` cron on workflows that run Claude |
| Transcript history | first line of each transcript under `~/.claude/projects` | headless sessions recurring at the same hour on three or more days: inferred, labelled as such |
| Cloud routines | `/schedule list` is in-session only, so the skill asks the person to run it and paste the names | name and cadence |

**Does with it.** Prints a table of candidates with surface, schedule and command, matched against the registry by command and by name. For each unmatched candidate it asks, then writes a registry note with `expected_by` set from the schedule plus a margin, the success check pre-filled with a guess at the output path, and `registered` set to today. For each matched candidate whose live schedule or command differs from the note, it reports the drift and proposes the note update.

**Script.** `discover.py scan [--project DIR] [--json]` and `discover.py draft ID [--name N] [--expected-by HH:MM] [--success-file P]`.

## 2. verify

**Problem.** An expectation that was never tested catches nothing. People register a success file path and never learn it was wrong until the first real miss, which they then cannot tell from a false one.

**Plain run.** `/otto:verify NAME` validates the note (schedule parses, surface known, cwd exists, caps present on a local job, command non-empty, a success file set) and runs the registered success check against the current cycle right now, reporting pass or fail with the evidence and the next due time.

**Drill.** `/otto:verify NAME --drill miss|auth|budget|timeout` copies the registry, ledger and state into a scratch home, injects the failure there (removes the cycle's evidence, or appends failed rows and opens the breaker), runs health against the copy, and shows what tomorrow's `/otto:status` would say. The real ledger is never touched; the scratch home is deleted afterwards.

**Script.** `verify.py NAME [--drill KIND] [--now ISO] [--json]`.

## 3. timeline

**Problem.** Jobs collide with each other, with the hours you need the window yourself, and with the prompt cache's TTL, and nothing shows the day as a whole.

**Lays out**, on a 24-hour grid with one row per automation:

- expected-by times and typical duration (median from the ledger, else the registered band, else ten minutes)
- 5-hour window boundaries as they actually rolled over the last seven days, from a bounded history the statusline capture now keeps
- cold-cache starts: runs that began more than the cache TTL after the previous Claude activity, with the measured prefix tokens they re-paid
- interactive hours: when you tend to be at the keyboard, from transcript timestamps over the last 14 days

**Output.** A monospace grid in the terminal, then proposed moves, each with the reason and the exact cron or launchd line (via `units.py --at`). Writes `vault/Timeline.md`. Nothing is applied.

**Script.** `timeline.py [--days 14] [--ttl-min 5] [--json]`.

## 4. experiment

**Problem.** People apply a recommendation and hope. A saving exists only once it has been measured.

**Before.** `experiment.py estimate NAME [--model M] [--cadence C] [--max-turns N]` projects the cost of a change from the job's own token mix in the ledger and the dated list-price table in `scripts/prices.json`. Labelled ESTIMATE, with the price table's date printed. Offers a dry run when history is thin.

**Start.** `experiment.py start NAME --change "shorter description" [--kind model|effort|description|cap|other] [--runs 3]` records the hypothesis and a baseline of the last passing runs (medians of cost, duration, tokens), writes `~/.otto/experiments/<id>.json`, records the change with `retro.py record-change` so the weekly retro sees it, and prints the change for the person to apply.

**Status.** `experiment.py status [ID]` collects passing runs after the start; at three on each side it reports medians, the delta, and a verdict (pays, does not pay, inconclusive), with the small-sample caveat under seven runs total. Results feed HONEST-NUMBERS.md.

## 5. watch

**Problem.** The morning read is a day late for a breaker that opened at 02:06.

**How.** A plugin monitor (`monitors/monitors.json`) that starts the first time `/otto:watch` runs in a session and then polls `health` and `budget` every five minutes. It keeps the last state in `~/.otto/state/watch.json` and speaks only on a change: a new miss, a breaker opening, a window or credit crossing a threshold, a recovery. It never repeats.

**Speaks** through all of: a line to stdout (which Claude Code delivers into the open session as a notification), a desktop notification (macOS `osascript`, Linux `notify-send`), and a dated line appended to `vault/Alerts.md`, which the morning read links to. Monitors only run in interactive sessions, so the vault note is the record when no session is open.

**Script.** `watch.py [--interval 300] [--once]`. `--once` runs a single tick, for tests and for cron users who want the same alerts without a session.

## Folded in

- **wrap recipes** (`skills/wrap/references/migrate.md`): moving a job between surfaces with caps, auth path and registry note carried across: cron to routine, Desktop task to wrapped `claude -p`, `/loop` to cron.
- **retro share** (`retro.py report --markdown`): the weekly numbers as a Markdown report for a team or a customer, names and numbers only.
- **estimate** lives inside `experiment`.

## Steward mode (0.2.0)

Designed with Matt on 2026-10-17 for a fleet of discovery strategies. Opt-in: these four skills apply nothing unless a steward grant names the lever, and even then the client applies the plan, one logged commit per change. The design is in [steward.md](steward.md).

| Skill | Script | What it does |
|---|---|---|
| `yield` | `yield.py report` | The funnel per strategy, points per 100 searches and per run-unit, smoothed yield, small-sample flags |
| `allocate` | `allocate.py plan --pool N` | Tomorrow's searches, daily cap, cadence and stage models within the grant's bounds and the pool |
| `evolve` | `evolve.py propose\|start\|status\|verdict` | One-change experiments with a measured baseline and a keep, revert or extend verdict |
| `steward` | `steward.py run nightly\|weekly` | The mode runner: grant and pause check, then the scripts in order, ending with an Ops read |

`diagnose.py` has no skill of its own; `evolve` and `steward` call it.

## Not in this round

A `report` skill with its own format catalog, `migrate` as a skill that reads the source surface's definition, and watch on non-interactive surfaces (a launchd unit that runs `watch.py --once`, which the install guide can document).
