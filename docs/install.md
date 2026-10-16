# Installing Otto

Three ways in, depending on where you use Claude. Pick one; they do not conflict.

| You use | Install path | What you get |
|---|---|---|
| Claude Code in a terminal | Marketplace, two commands | The whole plugin: ten skills, the Otto agent, hooks, runner |
| The Claude app (desktop or web) or Cowork | Add marketplace in app settings | The whole plugin, synced to Cowork and to Claude Code signed into the same account |
| The Claude app, one skill at a time | Upload a `.skill` file | `otto-audit` or the `otto` persona, nothing else needed |
| Another agent (Codex, Cursor, Gemini CLI, and so on) | `npx skills add` | The skill folders; only `audit` works fully outside Claude Code |

## 1. Claude Code (terminal)

Inside a Claude Code session:

```
/plugin marketplace add matthewprice/otto
/plugin install otto@otto
/otto:onboard
```

Or from the shell:

```
claude plugin marketplace add matthewprice/otto
claude plugin install otto@otto
```

`/otto:onboard` is a short interview that writes `~/.otto/otto.md` and copies the scripts to `~/.otto/bin` so cron and launchd have a stable path. It shows you any change to `~/.claude/settings.json` (the optional statusline capture) and asks before applying it. Nothing outside `~/.claude/plugins/` and `~/.otto/` is written without that confirmation.

Try it with synthetic data first: `/otto:demo`.

Update later with `claude plugin update otto`, then re-run `/otto:onboard` so `~/.otto/bin` matches the plugin version. `/otto:doctor` tells you when they differ.

Uninstall: `claude plugin uninstall otto`, then `rm -rf ~/.otto` if you also want the ledger gone.

## 2. The Claude app and Cowork (whole plugin)

In the Claude app, open Settings, then Plugins (under Customize), choose **Add marketplace**, and paste:

```
matthewprice/otto
```

Then install `otto` from that marketplace. Plugins added this way sync to Cowork and to any Claude Code session signed into the same account. The skills that read local files and transcripts (`status`, `why`, `budget`, `retro`, `wrap`) need a machine with Claude Code on it, which Cowork has and claude.ai chat does not.

## 3. The Claude app (one skill as a file)

This is the path in the app's **Upload a skill** dialog: a `.zip` or `.skill` file that contains a `SKILL.md`. Two of Otto's skills are packaged this way because they work without the plugin's ledger and hooks:

| File | What it does in the app |
|---|---|
| `otto-audit.skill` | Audits a project folder's Claude setup for context cost. Measured findings need transcripts on the machine; otherwise every finding is labelled an estimate. |
| `otto.skill` | The dispatcher persona and playbook. Give Otto your run histories, schedules and cost figures and get the Ops read. |

Get the files from the latest GitHub release (`.skill` and `.zip` are the same archive under two names), or build them from a clone:

```
python3 scripts/bundle.py        # writes dist/otto.skill, dist/otto-audit.skill, and SHA256SUMS
```

Then in the app: Settings, Skills, **Upload a skill**, drag the file in, and wait for the security scan. Each file is one skill; you can drop both at once.

The upload dialog accepts only the six portable frontmatter keys. The files under `portable/` are the sources; `scripts/bundle.py --check` enforces the rules and runs in CI.

## 4. Other agents

```
npx skills add matthewprice/otto
```

Installs the `skills/` folders into whichever agents the installer supports. `audit` works anywhere Python 3.9+ can run. The other nine read Claude Code's transcripts, statusline and result JSON, so outside Claude Code they load but find nothing to read. The portable `.skill` bundles above are the better choice for a non-Claude agent that can read a zip.

## 5. From a clone (development)

```
git clone https://github.com/matthewprice/otto && cd otto
claude --plugin-dir .
```

Loads the plugin for that session without a marketplace. Before a release: `python3 -m unittest discover -s tests`, `python3 scripts/bundle.py --check`, and `claude plugin validate --strict .`.

## Checking the install

- `/otto:doctor` reports the plugin version, `~/.otto/bin` version, whether the statusline capture is present, and whether any registry notes exist.
- `claude plugin details otto` lists the components and Claude Code's estimate of the always-on context cost.

## Requirements

Claude Code (any recent version; the plugin was validated on 2.1.301), Python 3.9 or newer, macOS or Linux. No dependencies beyond the standard library. Windows is not supported in 0.1.
