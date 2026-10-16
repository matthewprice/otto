---
name: register
description: Create or update the registry note for one automation, with its schedule, success check and caps. Use when adding a new automation to Otto.
disable-model-invocation: true
argument-hint: "<automation-name>"
allowed-tools: Read, Write, Edit, Glob, Bash(python3 *scripts/health.py*)
---
Create the note `Automations/$ARGUMENTS.md` in the Otto vault (default ~/.otto/vault). Read references/registry-schema.md for every key and references/surfaces.md for what each surface can and cannot be observed doing.

Ask only for what you cannot infer: the surface, the schedule, and the file the automation leaves when it succeeds. A success file is what makes the status real, so push for one. If there is none, say the automation will show as unobservable and offer to add a line to its prompt that writes a small marker file.

After writing, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/health.py" --json` and show that the note parses and what its status is. Do not edit the automation itself.
