---
name: watch
description: Turn on the live watch for this session: a background monitor that polls health and budget every five minutes and speaks only on a change (a new miss, a breaker, a window threshold, a recovery), into the session, as a desktop notification, and into Alerts.md in the vault. Use when asked "tell me if something breaks" or "watch my automations while I work".
disable-model-invocation: true
allowed-tools: Read, Bash(python3 *scripts/watch.py*)
---
Invoking this skill starts the plugin monitor `otto-watch` (monitors/monitors.json), which runs `scripts/watch.py` in the background for the rest of the session. Monitors run only in interactive sessions.

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/watch.py" --once` now so the first tick happens immediately and the baseline line appears. Tell the person: alerts arrive as notifications in this session, as desktop notifications (off with `watch_desktop: false` in ~/.otto/otto.md), and as dated lines in Alerts.md; nothing is repeated; the interval is `watch_interval_s` (default 300). For alerts without a session open, offer the cron line `*/5 * * * * python3 ~/.otto/bin/watch.py --once` and say it writes the same Alerts.md.

When a watch notification arrives later in the session, read it as Otto would: name the automation, the state, and the one check or command that confirms the cause. Do not act on it unless asked.
