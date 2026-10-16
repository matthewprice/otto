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


def _append_history(oc, side) -> None:
    """One line per five minutes or per window change, capped, so timeline.py can replay the week."""
    try:
        p = oc.state_dir() / "statusline-history.jsonl"
        last = None
        if p.exists():
            with open(p, "rb") as fh:
                try:
                    fh.seek(-2048, 2)
                except OSError:
                    fh.seek(0)
                tail = fh.read().decode("utf-8", "replace").strip().splitlines()
                if tail:
                    last = json.loads(tail[-1])
        rl = side.get("rate_limits") or {}
        if last and side["captured_at"] - int(last.get("captured_at") or 0) < 300 and last.get("rate_limits") == rl:
            return
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"captured_at": side["captured_at"], "rate_limits": rl}) + "\n")
        if p.stat().st_size > 512 * 1024:
            keep = p.read_text(encoding="utf-8").splitlines()[-2000:]
            p.write_text("\n".join(keep) + "\n", encoding="utf-8")
    except Exception:
        pass


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
        _append_history(oc, side)
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
