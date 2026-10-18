# Security

Otto reads local files under `~/.claude` and `~/.otto` and writes only under `~/.otto` and the registry folder. It makes no network calls.

Report a vulnerability privately through GitHub's "Report a vulnerability" on this repository. Please do not open a public issue. Expect an acknowledgement within a week.

Areas of most interest: anything that could cause prompt or output text to enter the ledger, anything that writes outside `~/.otto`, and the runner's handling of the credential commands (`token_cmd` and `api_key_cmd`).
