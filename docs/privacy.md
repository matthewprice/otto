# Privacy

Otto runs locally and makes no network calls. It reads transcripts to count tokens and tools, and keeps only numbers and short labels in `~/.otto/ledger`. Prompt and output text, file contents and command arguments are never stored. The runner's optional `token_cmd` is executed to obtain a login token for the job's environment; the token is never written to disk by Otto.
