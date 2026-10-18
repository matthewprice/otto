# Privacy

Otto runs locally and makes no network calls. It reads transcripts to count tokens and tools, and keeps only numbers and short labels in `~/.otto/ledger`. Prompt and output text, file contents and command arguments are never stored. The runner's optional `token_cmd` or `api_key_cmd` is executed to obtain a login token or API key for the job's environment; neither is ever written to disk by Otto.
