---
name: budget
description: Show how much of the 5-hour, 7-day and Agent SDK credit limits are used and whether you are on pace to run out. Use when asked about limits, usage, "am I going to hit my cap", or credit.
allowed-tools: Read, Bash(python3 *scripts/budget.py*)
---
Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/budget.py" --json`.

Report each pool separately; never merge them. For each window say the percent used, the percent of the window gone, and the projected percent at reset. If a figure is stale (the file shows its age) say how old. The SDK credit figure is Otto's estimate from reported run cost; say so and point to the usage page as the source of truth. If a window is unavailable (API-key accounts, or no statusline capture yet), say why in one line and do not guess.

Finish with an Ops read: the pool closest to trouble, when it runs out at the current pace, and the one change that would help most (usually moving or trimming one named automation).
