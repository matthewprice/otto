#!/usr/bin/env python3
"""Live watch: say something only when the state changes.

  watch.py [--home DIR] [--interval 300] [--once] [--now ISO]

Runs as a Claude Code plugin monitor (monitors/monitors.json), started the first time /otto:watch
is used in a session, or by hand. Every interval it runs health and budget, compares each
automation's status and each window's level with the last tick (state/watch.json), and on a change:
  prints one line (a monitor's stdout reaches the open session as a notification),
  sends a desktop notification if watch_desktop is on (macOS osascript, Linux notify-send),
  appends a dated line to <vault>/Alerts.md.
It never repeats an alert and never prints when nothing changed. --once runs one tick and exits.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import budget  # noqa: E402
import health  # noqa: E402
import otto_common as oc  # noqa: E402

ALERT = {"miss", "fail", "breaker", "late", "drift"}


def snapshot(home: Path, now: datetime) -> Dict[str, Any]:
    h = health.evaluate(home, now)
    b = budget.report(home, now)
    autos = {f["automation"]: {"status": f["status"], "summary": f["summary"]} for f in h["findings"]}
    windows = {w["window"]: w.get("level", "n/a") for w in b["windows"] if w.get("available")}
    credit = (b["spend"].get("api_credit") or {}).get("level")
    return {"ts": oc.iso(now), "automations": autos, "windows": windows, "credit": credit}


def diff(prev: Optional[Dict[str, Any]], cur: Dict[str, Any]) -> List[str]:
    if not prev:
        bad = [n for n, v in cur["automations"].items() if v["status"] in ALERT]
        return ["Otto watch started: %d automations, %d not ok%s" % (len(cur["automations"]), len(bad), (": " + ", ".join(bad)) if bad else "")]
    out: List[str] = []
    for name, v in cur["automations"].items():
        old = (prev.get("automations") or {}).get(name, {}).get("status")
        if old == v["status"]:
            continue
        if v["status"] in ALERT:
            out.append("%s is now %s: %s" % (name, v["status"].upper(), v["summary"]))
        elif old in ALERT and v["status"] in ("ok", "pending"):
            out.append("%s recovered: %s" % (name, v["summary"]))
    for w, level in cur["windows"].items():
        old = (prev.get("windows") or {}).get(w)
        if level != old and level in ("watch", "critical"):
            out.append("%s window is %s" % (w, level))
        elif old in ("watch", "critical") and level == "ok":
            out.append("%s window back to ok" % w)
    if cur.get("credit") != prev.get("credit") and cur.get("credit") in ("watch", "critical"):
        out.append("API credit estimate is %s" % cur["credit"])
    return out


def desktop_notify(message: str) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.run(["osascript", "-e", 'display notification %s with title "Otto"' % json.dumps(message)], timeout=10, check=False, capture_output=True)
        elif shutil.which("notify-send"):
            subprocess.run(["notify-send", "Otto", message], timeout=10, check=False, capture_output=True)
    except Exception:
        pass


def deliver(home: Path, cfg: Dict[str, Any], alerts: List[str], now: datetime, desktop: bool = True) -> None:
    if not alerts:
        return
    vault = oc.vault_dir(cfg, home)
    vault.mkdir(parents=True, exist_ok=True)
    p = vault / "Alerts.md"
    if not p.exists():
        p.write_text("# Alerts\n\nOne line per state change, written by /otto:watch. Newest at the bottom.\n\n", encoding="utf-8")
    with open(p, "a", encoding="utf-8") as fh:
        for a in alerts:
            fh.write("- %s %s\n" % (now.strftime("%Y-%m-%d %H:%M"), a))
    for a in alerts:
        print("Otto: " + a, flush=True)
        if desktop and cfg.get("watch_desktop", True) and not a.startswith("Otto watch started"):
            desktop_notify(a)


def tick(home: Path, now: Optional[datetime] = None, desktop: bool = True) -> List[str]:
    cfg = oc.load_config(home)
    now = now or oc.parse_when(None, oc.get_tz(cfg.get("timezone")))
    path = oc.state_dir(home) / "watch.json"
    prev = oc.read_json(path, None)
    cur = snapshot(home, now)
    alerts = diff(prev, cur)
    oc.write_json(path, cur)
    deliver(home, cfg, alerts, now, desktop)
    return alerts


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home"); ap.add_argument("--interval", type=int); ap.add_argument("--once", action="store_true")
    ap.add_argument("--now", help="testing only"); ap.add_argument("--no-desktop", action="store_true")
    args = ap.parse_args(argv)
    home = Path(args.home).expanduser() if args.home else oc.otto_home()
    oc.ensure_dirs(home)
    cfg = oc.load_config(home)
    interval = args.interval or int(cfg.get("watch_interval_s") or 300)
    while True:
        try:
            tick(home, oc.parse_when(args.now) if args.now else None, not args.no_desktop)
        except Exception as e:  # a watcher must never die on one bad tick
            oc.log_error("watch: %s: %s" % (e.__class__.__name__, str(e)[:120]), home)
        if args.once:
            return 0
        time.sleep(max(60, interval))


if __name__ == "__main__":
    raise SystemExit(main())
