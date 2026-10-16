---
name: audit
description: Audit a project's Claude setup (skills, CLAUDE.md, agents, MCP, headless posture) for token waste, with measured findings separated from estimates. Use for "why is Claude using so many tokens in this repo" or before registering a project's automations.
argument-hint: "[project-path]"
allowed-tools: Read, Glob, Grep, Bash(python3 *scripts/audit.py*)
---
Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/audit.py" --project ${ARGUMENTS:-.} --json`. Read references/audit-checks.md only for a check you need explained.

Present findings grouped as MEASURED (from transcripts and the ledger) and ESTIMATE (from file sizes). Each finding gets: what, evidence, the change, the expected saving with its label, and the risk. Lead with the largest measured one. Say how many sessions the measurement rests on; under ten, say it is a small sample.

Never edit the project. Offer to draft the changes as a patch the person can review.
