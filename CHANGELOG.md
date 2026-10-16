# Changelog

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
