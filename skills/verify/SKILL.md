---
name: verify
description: Prove a registry note before you need it. Lints the note and runs its success check right now, or stages a drill (miss, auth, budget, timeout) in a scratch copy to show what tomorrow's status would say. Use after registering an automation, when a status looks wrong, or when asked "would Otto catch it if this broke".
disable-model-invocation: true
argument-hint: "<automation-name> [--drill miss|auth|budget|timeout]"
allowed-tools: Read, Bash(python3 *scripts/verify.py*)
---
Plain check: run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify.py" NAME --json`. Report the lint findings first (each one is a reason a real miss could be missed or faked), then the success check with its evidence, then the status as of now and the next expected time. If the verdict is `no-check`, say plainly that this automation is unobservable until it has a success file, and offer a line for its prompt that writes a small marker file.

Drill: run `verify.py NAME --drill KIND --json`. Say what was injected into the scratch copy and what the next /otto:status would report. If it was not caught, explain which registry field would make it catchable. State that the real ledger was not touched.

Never edit the note or the automation. Propose the change and the command.
