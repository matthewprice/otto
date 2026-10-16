<p align="center"><img src="assets/otto.svg" width="120" alt="Otto the otter"></p>

# Otto

**The ops manager for your Claude automations.** Otto tells you which scheduled runs happened, which ones quietly did not, what they cost, and what to change. He proposes. He never edits your setup.

[![ci](https://github.com/matthewprice/otto/actions/workflows/ci.yml/badge.svg)](https://github.com/matthewprice/otto/actions/workflows/ci.yml)
[![license](https://img.shields.io/github/license/matthewprice/otto)](LICENSE)
[![release](https://img.shields.io/github/v/release/matthewprice/otto?include_prereleases)](https://github.com/matthewprice/otto/releases)

## Install

**Claude Code** (terminal), inside a session:

```
/plugin marketplace add matthewprice/otto
/plugin install otto@otto
/otto:demo
```

**Claude app or Cowork:** Settings, Plugins, Add marketplace, paste `matthewprice/otto`. Syncs to Cowork and to Claude Code on the same account.

**Claude app, one skill as a file:** download `otto-audit.skill` or `otto.skill` from the [latest release](https://github.com/matthewprice/otto/releases/latest) and drop it into Settings, Skills, Upload a skill.

**Other agents:** `npx skills add matthewprice/otto`

Every path, what it writes where, and how to uninstall: [docs/install.md](docs/install.md).

## The gap

Claude Code can run on a schedule now: cron and launchd jobs, GitHub Actions, desktop tasks, cloud routines. When one of them stops, it usually stops silently. A login expires, a laptop sleeps, a monthly credit pool runs dry, a retry loop burns a day of budget, and the first sign is a report that never arrived.

Claude Code shows you a session. Nothing shows you the fleet. Otto does one job: it compares what should have happened with what the evidence says happened, and says so in plain numbers.

## What you get

Ten skills, one agent, five hooks. Skills marked *you* are run by you; the rest Otto can also reach for on his own when a question fits.

| Command | Who | What it does |
|---|---|---|
| `/otto:status` | both | Per-automation status: ok, miss, fail, late, drift, breaker, unobservable |
| `/otto:why NAME` | both | The evidence behind a failure or a cost jump, and the one check that confirms it |
| `/otto:budget` | both | 5-hour, 7-day and Agent SDK credit pacing, kept as separate pools |
| `/otto:audit [path]` | both | Context-tax audit of a project, measured findings apart from estimates |
| `/otto:retro` | you | Weekly deltas, silent misses, cost step changes, measured effect of past changes |
| `/otto:wrap NAME` | you | Guarded runner for a headless job, plus a scheduler unit you install yourself |
| `/otto:register NAME` | you | Describe one automation: surface, cadence, what success looks like, caps |
| `/otto:onboard` | you | Ten-minute setup interview; writes `~/.otto/otto.md` |
| `/otto:doctor` | you | Health of Otto itself: versions, capture, registry |
| `/otto:demo` | you | A tour on a synthetic month of data |

Every report ends with an **Ops read**: two to five sentences on what matters most and what Otto would do.

Two skills also ship as standalone `.skill` files for the Claude app: `otto-audit` (the audit with its scripts bundled) and `otto` (the persona and playbook). Sources are under [`portable/`](portable/); `scripts/bundle.py` builds them.

## How it works

- **Registry.** One Markdown note per automation: schedule, where its output should appear, caps.
- **Ledger.** One JSON line per run in `~/.otto/ledger`. Numbers and short labels only.
- **Health.** Replays every expected cycle against the ledger and the output file. A due run with no trace is a `miss`.
- **Runner.** Optional wrapper for `claude -p` jobs: turn, budget and time caps, prompts denied, retry cap, circuit breaker.
- **Budget and audit.** Pacing from the statusline's rate-limit data and reported run cost; audit of skills, CLAUDE.md, agents and headless posture.

See [docs/architecture.md](docs/architecture.md). The persona is in [docs/persona.md](docs/persona.md) and the numbered playbook Otto cites is [config/ops_playbook.md](config/ops_playbook.md).

## What Otto never does

- Edit your automations, skills, settings or schedules. He proposes; you apply.
- Store prompts, outputs or file contents. The ledger is an allowlist of numbers and enums.
- Send anything anywhere. No network calls, no telemetry.
- Use `--dangerously-skip-permissions`.
- Claim a saving he has not measured.

## Honest numbers

Cost figures are what Claude Code reported per run, a client-side estimate at list price, not billing data. The audit separates MEASURED from ESTIMATE. The demo data is synthetic and says so. Otto's measured results on real setups will be published in [HONEST-NUMBERS.md](HONEST-NUMBERS.md) with the method, once collected; until then the file holds no results.

Context cost of installing Otto: `claude plugin details otto` estimated about 740 tokens always-on across all ten skills and the agent when last checked. Run it yourself; that figure is Claude Code's estimate, not an exact count.

## Optional pieces

- **Statusline passthrough** (via `/otto:onboard`) enables the 5-hour and 7-day figures. Pro and Max plans only.
- **Guard** (`guard: warn` or `block` in `~/.otto/otto.md`) warns or blocks prompts near a limit. Off by default. `/otto:` commands and the phrase `otto: go ahead` always pass.

## What Claude Code does natively

Otto reads Claude Code's own primitives and recommends Claude Code's own tools. The list of what is native, and therefore not Otto's job, is kept current in [docs/what-claude-code-does-natively.md](docs/what-claude-code-does-natively.md).

## Requirements

Claude Code, Python 3.9 or newer, macOS or Linux. No dependencies beyond the standard library.

## Status

Version 0.1.0, early. See [SCOPE.md](SCOPE.md) for what is in and out, [BUILD.md](BUILD.md) for the plan, [CONTRIBUTING.md](CONTRIBUTING.md) to help, [SECURITY.md](SECURITY.md) to report a problem.

## Troubleshooting

Run `/otto:doctor`. Common causes of an empty report: no registry notes yet, no statusline capture, or `~/.otto/bin` older than the plugin (re-run `/otto:onboard`). More in [docs/troubleshooting.md](docs/troubleshooting.md).

MIT licensed.
