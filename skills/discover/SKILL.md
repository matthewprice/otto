---
name: discover
description: Find the automations already on this machine (crontab, launchd, systemd timers, Desktop scheduled tasks, saved session tasks, GitHub workflows, recurring headless sessions) and draft a registry note for each one you confirm. Also reports registry drift when a live schedule no longer matches its note. Use at onboarding, after changing a cron line, or when asked "what do I have scheduled".
disable-model-invocation: true
argument-hint: "[project-path]"
allowed-tools: Read, Bash(python3 *scripts/discover.py*), Bash(python3 *scripts/health.py*)
---
Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/discover.py" scan --project ${ARGUMENTS:-.} --json`.

Show a table: id, surface, source, schedule, command, and whether it is NEW, already registered, or registered with DRIFT. Candidates from `transcripts` are inferred from recurring headless sessions; say so.

Then, one candidate at a time, for each NEW one: ask whether to register it, and for the expected-by time (default: 30 minutes after it starts) and the file it leaves when it succeeds. Run `discover.py draft ID --name NAME --expected-by HH:MM --success-file PATTERN` for each yes. Desktop tasks have no schedule on disk; ask for it. Cloud routines cannot be scanned: ask the person to run `/schedule list` and paste the names and cadences, then register those with /otto:register.

For each DRIFT, show the live schedule beside the note and propose the exact frontmatter change. Do not edit the note unless they say so; the note is Otto's file, the scheduler is theirs and stays untouched.

Finish with `health.py --json` so the new notes are seen parsing, and an Ops read: how many were found, how many are now observable, and which one still has no success file.
