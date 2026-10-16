---
name: retro
description: Weekly retro for automations: cost and failure deltas, silent misses, cost step changes, and measured effects of past changes, with a shareable Markdown report on request. Use for a weekly review, "how did the week go", or a report for a team.
disable-model-invocation: true
allowed-tools: Read, Bash(python3 *scripts/retro.py*)
---
Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/retro.py" report --days 7`.

Cover, in order: silent cycles (misses with no trace), failed and retried spend, per-automation cost change, any step change (a place to look, not a cause), and the measured effect of changes recorded earlier. If the person made a change this week, offer to record it with `retro.py record-change --automation NAME --note TEXT` so next week shows before and after.

If the person asks for something to share with a team or a customer, run `retro.py report --days 7 --markdown` and hand over that Markdown unchanged; it carries names and numbers only.

Claim savings only from the measured effects. End with an Ops read and at most three proposed changes.
