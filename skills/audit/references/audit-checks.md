# Audit checks

MEASURED means the number came from files or usage Claude Code recorded. ESTIMATE means tokens were derived from characters divided by four.

| Check | Basis | What it flags |
|---|---|---|
| description-over-cap | MEASURED | A skill description longer than the 1,536 character listing cap, which is truncated |
| description-over-spec | MEASURED | Longer than the 1,024 characters the portable spec allows |
| claude-md-long | MEASURED | A CLAUDE.md over 200 lines |
| skill-body-long | MEASURED | A skill body over 500 lines |
| listing-cost | ESTIMATE | Total skill descriptions loaded in every session |
| batch-skill-model-invocable | MEASURED | A skill used only by scheduled jobs that the model can also invoke, so its description is loaded for nothing |
| agent-model-unpinned | MEASURED | An agent with no model set |
| unused-skills, unused-mcp-servers | MEASURED | Installed but not used in the sampled sessions |
| usage-sample-small | MEASURED | Fewer than ten sessions sampled, so conclusions are weak |
| measured-prefix | MEASURED | Median tokens in the first request of sampled sessions |
| wrapper-posture | MEASURED | Headless jobs missing caps, a timeout, or JSON output, or using the bypass flag |
| cold-start, hidden-user-context | ESTIMATE | User-level files that load in headless runs too |
