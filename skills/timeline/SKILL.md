---
name: timeline
description: Lay the day out: when each automation runs, against the 5-hour windows, the prompt cache TTL, and the hours you are usually at the keyboard. Finds collisions, cold starts and jobs that compete with you, and proposes moves with the exact scheduler command. Use when asked "when should this run", "why is my window always hot in the morning", or before adding a new scheduled job.
allowed-tools: Read, Bash(python3 *scripts/timeline.py*), Bash(python3 *scripts/units.py*)
---
Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/timeline.py" --json`. It writes Timeline.md in the Otto vault.

Show the grid as-is in a code block. Then the proposals, each with the reason and the `units.py NAME --at HH:MM` command that prints the new unit; offer to run that command so the person can install the unit themselves. Say which figures are measured (durations from the ledger, prefix tokens) and which are estimates or defaults. If there is no statusline history yet, say the hot-window row is empty for that reason and point to /otto:onboard.

Do not apply any move. End with an Ops read: the one move worth making first and what it is expected to change.
