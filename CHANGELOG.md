# Changelog

## 0.2.0 (unreleased)
- Steward mode, opt-in and off by default: a grant (`config/steward.template.md`, in `~/.otto/otto.md` or a repo file passed as `--grant`) names the levers Otto may apply; everything else stays a proposal (docs/steward.md)
- `yield.py`: a yield ledger of strategy runs and outcomes in `OTTO_HOME/yield/`, an allowlist of numbers and short labels, with a funnel report, points per 100 searches and per run-unit, smoothing, and small-sample flags
- `allocate.py`: tomorrow's searches, daily cap, cadence and stage models within the grant's bounds and the pool; writes only `allocation.json`. Pool slack is an explicit reserve that funds only experiments in progress and newly approved strategies; the rest stays unspent
- `diagnose.py`: the leak per strategy (source, triage, judgment, review, cost, blocked) and the matching lever
- `evolve.py`: one-change experiments with a yield or review-quality metric, keep, revert or extend verdicts, and the exact git command; never runs git
- `steward.py`: the grant loader, pause check and nightly or weekly runner; `steward_rules.json` holds the points table and thresholds
- Four skills: `/otto:yield`, `/otto:allocate`, `/otto:evolve`, `/otto:steward`; the Otto agent says when steward mode is on
- `experiment.py` shares its baseline and median helpers with `evolve.py` through `exp_common.py`; its CLI is unchanged
- Fixtures gain a synthetic yield month for six strategies; `tests/test_steward.py`
- The "Agent SDK credit" pool is now the monthly API credit that Max and Team plans include, matching Anthropic's documentation: it pays for `claude -p` and Agent SDK runs only when they use an API key from the linked Console organization. **Breaking:** `sdk_credit_usd` and `sdk_credit_reset_day` are renamed `api_credit_usd` and `api_credit_reset_day`; the old keys are ignored
- Ledger run rows gain a `credential` enum (`api_key` or `subscription`), set by the runner and the Stop hook; the credit counts only API-key headless runs and reports the rest as not counted
- Runner: `api_key_cmd` supplies `ANTHROPIC_API_KEY` the way `token_cmd` supplies the OAuth token; each removes the other credential from the job's environment, and setting both is refused
- README: API-key accounts, a per-surface visibility table, and the "What you cannot do" table checked against Anthropic's docs; `docs/what-claude-code-does-natively.md` rewritten

## 0.1.0 (unreleased)
- Registry, ledger, health, budget, retro, audit scripts
- Guarded runner with breaker, attempt cap and idempotency
- Fifteen skills and the Otto agent, namespaced `/otto:`
- discover, verify, timeline, experiment and watch (see docs/skills-roadmap.md); a plugin monitor for watch; `retro.py report --markdown` for a shareable report; surface migration recipes in wrap; the statusline capture keeps a bounded history for timeline
- Hooks: Stop, StopFailure, Notification, SessionStart, opt-in guard
- Portable `.skill` bundles for the Claude app: `otto` (persona) and `otto-audit`, built by `scripts/bundle.py` and attached to GitHub releases
- Install guide covering Claude Code, the Claude app, Cowork, and other agents
- Pixel-sprite mascot set on the Clawd body, generated from `assets/make_sprites.py`
- Synthetic fixtures and tests; CI on Python 3.9 to 3.13
