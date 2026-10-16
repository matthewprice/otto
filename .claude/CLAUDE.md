# Agent instructions

Otto is a Claude Code plugin with Python standard-library scripts. Read SCOPE.md and docs/architecture.md first.

- Test: `python3 -m unittest discover -s tests -v`
- Validate: `claude plugin validate . --strict`
- Bundles: `python3 scripts/bundle.py --check` (portable sources under `portable/` use only the six agentskills.io frontmatter keys)
- Never add network calls, third-party dependencies, or text fields to the ledger.
- Observers must fail open. Only guard.py may exit 2.
- Do not write em dashes in prose. Do not quote fixture numbers as results.
