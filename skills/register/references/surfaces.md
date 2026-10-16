# Surfaces

Where an automation runs decides what Otto can see.

| Surface | What Otto sees | What it cannot see |
|---|---|---|
| local-cli | Everything: the runner writes a ledger row per run, hooks add session detail | Nothing material |
| github-actions | Output files you commit or upload, if you point `success_file` at a local path | Run cost, unless the workflow posts it |
| desktop-task | The output file the task leaves, if any | Whether it ran, its cost, its failure reason |
| cloud-routine | The output file or message it leaves, if you can reach it | The same as desktop-task |
| other | Whatever file you name | Everything else |

For anything except local-cli, a success file is the only evidence. Without one the status is `unobservable`, which is honest and not an error.
