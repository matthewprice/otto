# Registry note schema

One Markdown note per automation in `<vault>/Automations/NAME.md`. Frontmatter is a small YAML subset: scalars, inline lists `[a, b]`, and dash lists. The body is free text for you.

| Key | Meaning |
|---|---|
| name | Slug. Defaults to the file name |
| surface | local-cli, github-actions, desktop-task, cloud-routine, other |
| days | `daily`, `weekdays`, `weekends`, or a list like `[mon, wed]` |
| expected_by | HH:MM local time the output should exist by |
| timezone | IANA name; defaults to your system zone |
| grace_min | Minutes of slack before a cycle counts as late (default 15) |
| success_file | Path or glob of the output. Tokens: `{date}`, `{yyyy}`, `{mm}`, `{dd}`, `{iso_week}`, `{OTTO_HOME}` |
| success_cwd | Base folder for a relative `success_file` |
| success_min_bytes | Smallest acceptable output size |
| success_pattern | Regex the output must contain |
| registered | Date registered, so history before it is not judged |
| paused | `true` to stop judging it |
| cost_band_usd, turns_band, duration_band_min | `[low, high]` ranges for drift; otherwise inferred from history |
| local-cli only | |
| command | The prompt or slash command passed to `claude -p` |
| cwd | Working directory for the run |
| allowed_tools | Tools the run may use without prompting |
| permission_mode | Default acceptEdits |
| max_turns, max_budget_usd, timeout_min | Hard caps |
| model | Optional model override |
