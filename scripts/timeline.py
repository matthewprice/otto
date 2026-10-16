#!/usr/bin/env python3
"""Lay the day out: when each automation runs, against the windows, the cache and your own hours.

  timeline.py [--home DIR] [--now ISO] [--days 14] [--json]

Rows: one per automation, from its run_at (or expected_by minus 30 minutes) for its typical
duration (median from the ledger, else the registered band, else ten minutes).
Overlays:
  keyboard   hours you tend to be in a session, from interactive ledger rows and transcript
             timestamps over the last --days days
  5h hot     hours that sat inside a 5-hour window that reached the first alert threshold, replayed
             from the statusline history the capture keeps
  cold       runs that started more than cache_ttl_min after the previous Claude activity and so
             paid their full prefix again (MEASURED when prefix_tokens is in the ledger)
Then proposed moves: collisions, runs inside your keyboard hours, and cold starts that could cluster.
Each proposal names the exact units.py command. Nothing is applied. Writes <vault>/Timeline.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import health  # noqa: E402
import ledger  # noqa: E402
import otto_common as oc  # noqa: E402


def _hhmm_to_min(s: Any) -> int:
    h, m = oc.parse_hhmm(s)
    return h * 60 + m


def _min_to_hhmm(x: int) -> str:
    x %= 1440
    return "%02d:%02d" % (x // 60, x % 60)


def rows_for(home: Path, cfg: Dict[str, Any], autos: List[Dict[str, Any]], runs: List[Dict[str, Any]], tz) -> List[Dict[str, Any]]:
    out = []
    for a in autos:
        if a.get("paused") is True:
            continue
        try:
            exp = _hhmm_to_min(a.get("expected_by"))
        except ValueError:
            continue
        mine = [r for r in runs if r.get("automation") == a["name"] and health.row_outcome(r) == "pass"]
        durs = [r["duration_ms"] / 60000.0 for r in mine[-14:] if r.get("duration_ms")]
        if durs:
            dur, basis = float(oc.median(durs) or 10), "MEASURED (median of %d runs)" % len(durs)
        elif health._band(a.get("duration_min")):
            lo, hi = health._band(a.get("duration_min"))
            dur, basis = (lo + hi) / 2.0, "ESTIMATE (registered band)"
        else:
            dur, basis = 10.0, "ESTIMATE (default 10 min)"
        start = _hhmm_to_min(a["run_at"]) if a.get("run_at") else exp - 30
        if mine:
            starts = [oc.parse_when(r["ts"], tz).hour * 60 + oc.parse_when(r["ts"], tz).minute for r in mine[-14:]]
            start = int(oc.median(starts) or start)
        out.append({"automation": a["name"], "surface": a.get("surface", "other"), "days": health.normalize_days(a.get("days")),
                    "start_min": start, "end_min": start + int(round(dur)), "expected_by_min": exp, "duration_min": round(dur, 1),
                    "duration_basis": basis, "local_cli": a.get("surface") == "local-cli",
                    "cwd": os.path.expanduser(str(a.get("cwd") or ""))})
    return out


def keyboard_hours(home: Path, runs: List[Dict[str, Any]], tz, now: datetime, days: int, claude_home: Optional[Path] = None) -> Dict[str, Any]:
    hist: Counter = Counter()
    since = now - timedelta(days=days)
    for r in runs:
        if r.get("surface") == "interactive":
            t = oc.parse_when(r.get("ts"), tz)
            if t >= since:
                hist[t.hour] += 1
    root = (claude_home or (Path.home() / ".claude")) / "projects"
    seen = 0
    for proj in root.iterdir() if root.is_dir() else []:
        for t in proj.glob("*.jsonl") if proj.is_dir() else []:
            try:
                mt = datetime.fromtimestamp(t.stat().st_mtime, tz=tz)
            except OSError:
                continue
            if mt < since:
                continue
            try:
                with open(t, encoding="utf-8", errors="replace") as fh:
                    head = [fh.readline() for _ in range(4)]
            except OSError:
                continue
            ts, ep = None, ""
            for line in head:
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if isinstance(o, dict):
                    if o.get("timestamp") and ts is None:
                        ts = oc.parse_epoch_or_iso(o["timestamp"])
                    if o.get("entrypoint"):
                        ep = str(o["entrypoint"])
            if ts and "sdk" not in ep.lower():
                hist[ts.astimezone(tz).hour] += 1
                seen += 1
    if not hist:
        return {"hours": [], "basis": "no interactive sessions found in the last %d days" % days}
    peak = max(hist.values())
    busy = sorted(h for h, c in hist.items() if c >= max(2, 0.3 * peak))
    return {"hours": busy, "sessions": sum(hist.values()), "basis": "hours with at least 30%% of your busiest hour's sessions, %d sessions over %d days" % (sum(hist.values()), days)}


def hot_window_hours(home: Path, cfg: Dict[str, Any], tz, now: datetime) -> Dict[str, Any]:
    p = oc.state_dir(home) / "statusline-history.jsonl"
    alerts = [int(x) for x in (cfg.get("alert_percents") or [50, 75, 90])]
    if not p.exists():
        return {"hours": [], "windows": 0, "basis": "no statusline history yet; the capture writes one once onboarding installs it"}
    since = now - timedelta(days=7)
    windows: Dict[str, float] = {}
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            o = json.loads(line)
        except ValueError:
            continue
        cap = oc.parse_epoch_or_iso(o.get("captured_at"))
        if not cap or cap < since:
            continue
        w = (o.get("rate_limits") or {}).get("five_hour") or {}
        if w.get("resets_at") is None or w.get("used_percentage") is None:
            continue
        key = str(w["resets_at"])
        windows[key] = max(windows.get(key, 0.0), float(w["used_percentage"]))
    hot: Counter = Counter()
    for resets, used in windows.items():
        if used < alerts[0]:
            continue
        end = oc.parse_epoch_or_iso(resets)
        if not end:
            continue
        start = end - timedelta(hours=5)
        t = start.astimezone(tz)
        while t < end.astimezone(tz):
            hot[t.hour] += 1
            t += timedelta(hours=1)
    return {"hours": sorted(hot), "windows": len(windows), "hot_windows": sum(1 for u in windows.values() if u >= alerts[0]),
            "basis": "%d five-hour windows seen in 7 days, %d of them past %d%%" % (len(windows), sum(1 for u in windows.values() if u >= alerts[0]), alerts[0])}


def cold_starts(rows: List[Dict[str, Any]], runs: List[Dict[str, Any]], tz, ttl_min: int) -> Dict[str, Dict[str, Any]]:
    stamps = []
    for r in runs:
        try:
            stamps.append((oc.parse_when(r.get("ts"), tz), oc.parse_when(r.get("end_ts") or r.get("ts"), tz)))
        except ValueError:
            continue
    stamps.sort()
    ends = [e for _, e in stamps]
    out: Dict[str, Dict[str, Any]] = {}
    ttl = timedelta(minutes=ttl_min)
    for row in rows:
        mine = [r for r in runs if r.get("automation") == row["automation"] and health.row_outcome(r) == "pass"][-14:]
        if not mine:
            continue
        cold, prefix = 0, []
        for r in mine:
            t = oc.parse_when(r.get("ts"), tz)
            prev_end = max((e for e in ends if e < t - timedelta(seconds=1)), default=None)
            if prev_end is None or t - prev_end > ttl:
                cold += 1
                if r.get("prefix_tokens"):
                    prefix.append(int(r["prefix_tokens"]))
        out[row["automation"]] = {"runs": len(mine), "cold": cold, "cold_fraction": round(cold / len(mine), 2),
                                  "prefix_tokens_median": int(oc.median(prefix)) if prefix else None,
                                  "basis": "MEASURED prefix tokens from %d runs" % len(prefix) if prefix else "prefix tokens not in the ledger for these runs"}
    return out


def _overlap(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return bool(set(a["days"]) & set(b["days"])) and a["start_min"] < b["end_min"] and b["start_min"] < a["end_min"]


def proposals(rows: List[Dict[str, Any]], kb: List[int], cold: Dict[str, Dict[str, Any]], ttl_min: int) -> List[Dict[str, Any]]:
    """One proposal per automation, by priority: a collision, then keyboard hours, then a cold start."""
    out: Dict[str, Dict[str, Any]] = {}
    busy = set(kb)

    def quiet(m: int) -> bool:
        return (m // 60) % 24 not in busy

    def fits(row: Dict[str, Any], to_min: int) -> bool:
        return 0 <= to_min and to_min + (row["end_min"] - row["start_min"]) <= row["expected_by_min"]

    def move(row: Dict[str, Any], to_min: int, reason: str, kind: str) -> None:
        if row["automation"] in out or not fits(row, to_min):
            return
        how = ("python3 ~/.otto/bin/units.py %s --at %s" % (row["automation"], _min_to_hhmm(to_min)) if row["local_cli"]
               else "this surface is not scheduled by Otto; change its schedule in the app or workflow")
        out[row["automation"]] = {"automation": row["automation"], "kind": kind, "reason": reason,
                                  "from": _min_to_hhmm(row["start_min"]), "to": _min_to_hhmm(to_min), "how": how}

    ordered = sorted(rows, key=lambda r: r["start_min"])
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if _overlap(a, b):
                move(b, a["end_min"] + 1, "overlaps %s (%s to %s); one at a time keeps a stall or a rate limit from taking both" % (
                    a["automation"], _min_to_hhmm(a["start_min"]), _min_to_hhmm(a["end_min"])), "collision")
    for r in rows:
        if not quiet(r["start_min"]):
            for back in range(30, 24 * 60, 30):
                m = r["start_min"] - back
                if m >= 0 and quiet(m) and quiet(m + (r["end_min"] - r["start_min"])):
                    move(r, m, "starts inside your keyboard hours and competes with you for the 5-hour window", "keyboard")
                    break
    for r in rows:
        c = cold.get(r["automation"])
        if not c or c["cold_fraction"] < 0.5 or not r["local_cli"]:
            continue
        # Only a local job in the same working directory shares enough prefix for the cache to matter.
        neighbours = [o for o in rows if o is not r and o["local_cli"] and o["cwd"] == r["cwd"]
                      and set(o["days"]) & set(r["days"]) and 0 < r["start_min"] - o["end_min"] <= 90]
        if neighbours:
            n = max(neighbours, key=lambda o: o["end_min"])
            saved = ("about %s prefix tokens per run" % format(c["prefix_tokens_median"], ",")) if c.get("prefix_tokens_median") else "its prefix tokens (not measured yet)"
            move(r, n["end_min"] + 1, "starts cold %d of %d runs; within %d min of %s (same project) it would reuse the cache and save %s" % (
                c["cold"], c["runs"], ttl_min, n["automation"], saved), "cold")
    return list(out.values())


def grid(rows: List[Dict[str, Any]], kb: List[int], hot: List[int]) -> str:
    hdr = "%-18s %s" % ("", "".join(str(h % 10) for h in range(24)))
    tens = "%-18s %s" % ("hour", "".join(str(h // 10) if h % 10 == 0 else " " for h in range(24)))
    L = [tens, hdr]
    L.append("%-18s %s" % ("keyboard", "".join("▒" if h in kb else "." for h in range(24))))
    L.append("%-18s %s" % ("5h hot", "".join("!" if h in hot else "." for h in range(24))))
    for r in sorted(rows, key=lambda r: r["start_min"]):
        cells = []
        for h in range(24):
            lo, hi = h * 60, h * 60 + 60
            mark = "."
            if r["start_min"] < hi and r["end_min"] > lo:
                mark = "#"
            if lo <= r["expected_by_min"] < hi:
                mark = "|" if mark == "." else "#"
            cells.append(mark)
        L.append("%-18s %s  %s %s %s" % (r["automation"][:18], "".join(cells), _min_to_hhmm(r["start_min"]),
                                         "%g min" % r["duration_min"], "" if r["local_cli"] else "(%s)" % r["surface"]))
    L.append("# run, | expected_by, ▒ keyboard hours, ! inside a hot 5-hour window")
    return "\n".join(L)


def report(home: Path, now: Optional[datetime] = None, days: int = 14, claude_home: Optional[Path] = None) -> Dict[str, Any]:
    cfg = oc.load_config(home)
    tz = oc.get_tz(cfg.get("timezone"))
    now = (now or oc.parse_when(None, tz)).astimezone(tz)
    autos, problems = health.load_registry(home, cfg)
    runs = ledger.read_rows(home, since=now - timedelta(days=max(days, 30)), kind="run")
    rows = rows_for(home, cfg, autos, runs, tz)
    kb = keyboard_hours(home, runs, tz, now, days, claude_home)
    hot = hot_window_hours(home, cfg, tz, now)
    ttl = int(cfg.get("cache_ttl_min") or 5)
    cold = cold_starts(rows, runs, tz, ttl)
    props = proposals(rows, kb["hours"], cold, ttl)
    rep = {"generated_at": oc.iso(now), "rows": rows, "keyboard": kb, "hot_windows": hot, "cold_starts": cold,
           "cache_ttl_min": ttl, "proposals": props, "registry_problems": problems,
           "basis": "Durations are medians of reported runs where the ledger has them. Proposals are printed, never applied."}
    rep["grid"] = grid(rows, kb["hours"], hot["hours"])
    return rep


def render_markdown(rep: Dict[str, Any]) -> str:
    L = ["# Timeline", "", "Generated %s by Otto. Nothing here has been applied." % rep["generated_at"][:16], "",
         "```", rep["grid"], "```", "",
         "Keyboard hours: %s. Hot windows: %s. Cache TTL assumed: %d min." % (rep["keyboard"]["basis"], rep["hot_windows"]["basis"], rep["cache_ttl_min"]), ""]
    if rep["proposals"]:
        L += ["## Proposed moves", ""]
        for p in rep["proposals"]:
            L.append("- **%s** %s to %s (%s): %s. How: `%s`" % (p["automation"], p["from"], p["to"], p["kind"], p["reason"], p["how"]))
    else:
        L += ["## Proposed moves", "", "None. Nothing overlaps, nothing runs in your keyboard hours, nothing starts cold often."]
    cold = [(n, c) for n, c in rep["cold_starts"].items() if c["cold"]]
    if cold:
        L += ["", "## Cold starts", ""]
        for n, c in cold:
            L.append("- %s: %d of %d runs started cold (%s)" % (n, c["cold"], c["runs"], c["basis"]))
    L += ["", "_%s_" % rep["basis"]]
    return "\n".join(L) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home"); ap.add_argument("--now"); ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--json", action="store_true"); ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)
    home = Path(args.home).expanduser() if args.home else oc.otto_home()
    rep = report(home, oc.parse_when(args.now) if args.now else None, args.days)
    if not args.no_write:
        cfg = oc.load_config(home)
        p = oc.vault_dir(cfg, home) / "Timeline.md"
        oc.atomic_write(p, render_markdown(rep))
        rep["written"] = str(p)
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print(render_markdown(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
