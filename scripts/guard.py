#!/usr/bin/env python3
"""Opt-in UserPromptSubmit guard. Off unless `guard: warn` or `guard: block` is set in ~/.otto/otto.md.

Reads the statusline side file (one turn stale) and, when the 5-hour or 7-day window is above
your threshold, warns or blocks (exit 2). It always lets through prompts that start with /otto-
and any prompt containing "otto: go ahead", so you can never lock yourself out. Stale or missing
data allows the prompt. Any error allows the prompt.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    try:
        import otto_common as oc
        cfg = oc.load_config()
        mode = str(cfg.get("guard") or "off")
        if mode not in ("warn", "block"):
            return 0
        data = json.loads(sys.stdin.read() or "{}")
        prompt = str(data.get("prompt") or "")
        if prompt.lstrip().startswith(("/otto-", "/otto:")) or "otto: go ahead" in prompt.lower():
            return 0
        side = oc.read_json(oc.state_dir() / "statusline.json", None) or {}
        age = time.time() - float(side.get("captured_at") or 0)
        if age > float(cfg.get("guard_max_age_s") or 900):
            return 0
        rl = side.get("rate_limits") or {}
        hits = []
        for key, lim, label in (("five_hour", cfg.get("guard_5h_percent"), "5-hour"), ("seven_day", cfg.get("guard_7d_percent"), "7-day")):
            used = (rl.get(key) or {}).get("used_percentage")
            if used is not None and lim and float(used) >= float(lim):
                hits.append("%s window at %d%%" % (label, round(float(used))))
        if not hits:
            return 0
        msg = "Otto guard: " + ", ".join(hits) + ". Say 'otto: go ahead' to proceed anyway."
        if mode == "block":
            sys.stderr.write(msg + "\n")
            return 2
        print(json.dumps({"systemMessage": msg}))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
