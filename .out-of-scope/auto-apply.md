# Auto-applying changes

Asked for often, declined by default. An ops tool that edits the thing it watches is hard to trust to watch it. So Otto drafts a patch or a command, and you review and run it. If you want a different tool to apply Otto's proposals, the retro's `record-change` command lets you log what you did so the effect is measured.

The one opt-in exception is steward mode. You write a grant (`config/steward.template.md`, explained in `docs/steward.md`) that names the levers Otto may apply and the bounds he must stay inside. Under it, each applied change is one commit, logged with its revert command, and experiments revert themselves when they do not pay. Anything the grant does not name stays a proposal. Creating or deleting a strategy, raising a pool, and editing a rubric, kill list or archive are never applied, with or without a grant.
