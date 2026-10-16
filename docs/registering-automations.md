# Registering automations

Run `/otto:register NAME`, or copy `config/automation.template.md` into `~/.otto/vault/Automations/`. Keys are in `skills/register/references/registry-schema.md`.

A success file is what turns "it ran" into "it worked". For cloud or desktop surfaces it is the only evidence Otto has, so have the automation write a small output file or marker.

## Recipe: a daily skill run
Surface `local-cli`, `command: "/my-skill"`, caps set, then `/otto:wrap NAME` to get the runner command and a scheduler unit to install.
