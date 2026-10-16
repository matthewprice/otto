---
name: otto-audit
description: Audit a project's Claude setup (skills, CLAUDE.md, agents, plugins, MCP servers, headless posture) for context cost and token waste, with measured findings kept apart from estimates. Use for "why is Claude using so many tokens in this repo", "is my CLAUDE.md too long", "which skills are never used", or before scheduling a project's automations. Proposes changes; never edits the project.
license: MIT
metadata:
  author: Matt Price
  version: 0.1.0
  source: https://github.com/matthewprice/otto
---

# Otto audit

This is Otto's context-tax audit, packaged on its own so it can run anywhere a skill can run a Python script. Everything it needs is inside this folder; Python 3.9 or newer and the standard library are the only requirements.

## Run it

From this skill's folder:

```
python3 scripts/audit.py --project <path-to-project> --json
```

`<path-to-project>` is the folder the person named. If they named none, use the current working directory. Add `--days N` to change the 30-day transcript sample.

The script reads, in this order:

- The project's `.claude/` folder (skills, agents, settings), its `CLAUDE.md` files, and any `.mcp.json`.
- The person's user-level `~/.claude/` setup (personal skills, installed plugins) when it is reachable.
- Transcripts under `~/.claude/projects/` for this project, when they exist. These are what make a finding MEASURED.

It never edits anything and never sends anything anywhere.

## Present the findings

Group them as **MEASURED** (from transcripts and run data) and **ESTIMATE** (from file sizes and caps). For each finding give: what, the evidence, the change, the expected saving with its label, and the risk. Lead with the largest measured one.

Say how many sessions the measurement rests on. Under ten, say it is a small sample. If `sessions_sampled` is zero, say plainly that every finding is an estimate and why: in a sandbox or on a machine with no transcripts for this project, the script only sees file sizes and structure.

Read `references/audit-checks.md` only when a check needs explaining.

## Rules

- Never edit the project. Offer to draft the changes as a patch the person can review.
- Never claim a saving that has not been measured with a before and after.
- Quote counts, sizes and names. Do not quote prompt or output text from transcripts.
- End with an Ops read: two to five sentences on the one change worth making first and what it is expected to save.
