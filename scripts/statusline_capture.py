#!/usr/bin/env python3
"""Statusline passthrough: save rate-limit and cost fields to a side file, print a short line.

Claude Code hands the statusline command a JSON blob on stdin. That blob is the only place
the 5-hour and 7-day usage percentages appear, so Otto saves them to ~/.otto/state/statusline.json
(numbers only) for `budget` and the optional guard to read. If you already have a statusline,
set OTTO_CHAIN to its command and Otto will run it and print its output instead.
Never fails: a broken capture must not break your statusline.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    raw = sys.stdin.read()
    try:
        import otto_common as oc
        data = json.loads(raw or "{}")
        rl = data.get("rate_limits") or {}
        keep = {}
        for k in ("five_hour", "seven_day"):
            w = rl.get(k)
            if isinstance(w, dict):
                keep[k] = {"used_percentage": w.get("used_percentage"), "resets_at": w.get("resets_at")}
        cost = (data.get("cost") or {}).get("total_cost_usd")
        side = {"captured_at": int(time.time()), "rate_limits": keep, "session_cost_usd": cost}
        oc.ensure_dirs()
        oc.write_json(oc.state_dir() / "statusline.json", side)
    except Exception:
        pass
    chain = os.environ.get("OTTO_CHAIN")
    if chain:
        try:
            p = subprocess.run(chain, shell=True, input=raw, capture_output=True, text=True, timeout=5)
            sys.stdout.write(p.stdout)
            return 0
        except Exception:
            pass
    try:
        five = keep.get("five_hour", {}).get("used_percentage")
        seven = keep.get("seven_day", {}).get("used_percentage")
        parts = []
        if five is not None:
            parts.append("5h %d%%" % round(five))
        if seven is not None:
            parts.append("7d %d%%" % round(seven))
        print("otto " + " ".join(parts) if parts else "otto")
    except Exception:
        print("otto")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
