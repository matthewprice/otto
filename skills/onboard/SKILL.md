---
name: onboard
description: First-run setup for Otto: create ~/.otto, install the runner, add the statusline passthrough, and register the first automation. Use once after installing the plugin.
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash(python3 *scripts/install.py*), Bash(python3 *scripts/health.py*), Bash(claude --version)
---
1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/install.py"`. Tell the person what it created and that everything stays under ~/.otto.
2. Offer the statusline passthrough, which is what makes 5-hour and 7-day figures available: it sets `statusLine` in their settings to `python3 ~/.otto/bin/statusline_capture.py`. Show the exact edit and make it only if they say yes. If they already have a statusline, set OTTO_CHAIN to it instead of replacing it.
3. Ask which automation worries them most and run /otto:register for it.
4. Explain the optional guard (`guard: warn` in ~/.otto/otto.md) in one sentence and leave it off.
5. Run /otto:status and show the result.

State plainly what Otto does not do: it does not read prompts or outputs, it does not change automations, and it sends nothing anywhere.
