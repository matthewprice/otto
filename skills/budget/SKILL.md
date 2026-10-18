---
name: budget
description: Show how much of the 5-hour and 7-day windows and the monthly API credit are used and whether you are on pace to run out. Use when asked about limits, usage, "am I going to hit my cap", or credit.
allowed-tools: Read, Bash(python3 *scripts/budget.py*)
---
Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/budget.py" --json`.

Report each pool separately; never merge them. For each window say the percent used, the percent of the window gone, and the projected percent at reset. If a figure is stale (the file shows its age) say how old. The API credit figure is Otto's estimate from the reported cost of his own API-key runs; say so, and point to the Console Billing page as the source of truth, since other keys in the same organization spend that balance too. If runs were not counted because no credential was recorded, say how many and that setting `api_key_cmd` or `token_cmd` fixes it. If a window is unavailable (API-key accounts, or no statusline capture yet), say why in one line and do not guess.

Finish with an Ops read: the pool closest to trouble, when it runs out at the current pace, and the one change that would help most (usually moving or trimming one named automation).
