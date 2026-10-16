---
name: my-automation
surface: local-cli
days: weekdays
expected_by: "08:00"
timezone: "America/Chicago"
success_file: "~/reports/{date}.md"
success_min_bytes: 200
command: "/my-skill"
cwd: "~/projects/my-project"
allowed_tools: [Read, Write]
max_turns: 12
max_budget_usd: 1.5
timeout_min: 20
registered: "2026-10-15"
---
What this automation does and what success looks like.
