#!/usr/bin/env python3
"""Pace spend against the limits that actually gate you.

Three pools, kept apart on purpose:
  1. The subscription windows (5-hour and 7-day), from the statusline side file. Pro and Max only,
     and only as fresh as the last statusline refresh, so the age is always reported.
  2. The monthly Agent SDK credit for unattended runs, if you set sdk_credit_usd. Otto estimates
     consumption from the cost Claude Code reported for your headless runs. The official figure
     is on your usage page; this is a pacing aid, not a bill.
  3. Optional soft budgets you set in otto.md.

Usage: budget.py [--home DIR] [--now ISO] [--json | --table]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ledger  # noqa: E402
import otto_common as oc  # noqa: E402

WINDOWS = (("five_hour", timedelta(hours=5), "5-hour"), ("seven_day", timedelta(days=7), "7-day"))
HEADLESS_SURFACES = {"local-cli", "github-actions"}


def read_side(home: Path) -> Optional[Dict[str, Any]]:
    return oc.read_json(oc.state_dir(home) / "statusline.json", None)


def window_report(side: Optional[Dict[str, Any]], now: datetime, alerts: List[int]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not side:
        return [{"window": w[2], "available": False,
                 "reason": "no statusline capture yet. Run /otto:onboard to install it. API-key users have no subscription windows."} for w in WINDOWS]
    cap = oc.parse_epoch_or_iso(side.get("captured_at"))
    age = (now - cap).total_seconds() if cap else None
    rl = side.get("rate_limits") or {}
    for key, size, label in WINDOWS:
        w = rl.get(key)
        if not isinstance(w, dict) or w.get("used_percentage") is None:
            out.append({"window": label, "available": False,
                        "reason": "no %s figure in the last capture (Pro and Max only, and only after the first response of a session)" % label})
            continue
        used = float(w["used_percentage"])
        resets = oc.parse_epoch_or_iso(w.get("resets_at"))
        rec: Dict[str, Any] = {"window": label, "available": True, "used_percent": round(used, 1),
                               "age_seconds": int(age) if age is not None else None,
                               "resets_at": oc.iso(resets.astimezone(now.tzinfo)) if resets else None}
        if resets is None:
            rec["note"] = "no reset time in the capture"
        elif resets <= now:
            rec["stale"] = True
            rec["note"] = "that window has already reset; the figure is from before the reset"
        else:
            start = resets - size
            elapsed = max(0.0, min(1.0, (now - start) / size))
            rec["elapsed_percent"] = round(elapsed * 100, 1)
            if elapsed >= 0.02 and used > 0:
                rate = used / ((now - start).total_seconds())  # percent per second
                proj = used / elapsed
                rec["projected_percent_at_reset"] = round(proj, 1)
                if proj >= 100:
                    rec["exhausted_at"] = oc.iso((now + timedelta(seconds=(100 - used) / rate)).astimezone(now.tzinfo))
            level = "ok"
            if used >= alerts[-1] or (rec.get("projected_percent_at_reset", 0) >= 110):
                level = "critical"
            elif used >= alerts[0] or rec.get("projected_percent_at_reset", 0) >= 90:
                level = "watch"
            rec["level"] = level
        if age is not None and age > 900:
            rec["stale"] = True
        out.append(rec)
    return out


def period_start(now: datetime, reset_day: int) -> datetime:
    day = max(1, min(28, int(reset_day or 1)))
    d = now.date()
    if d.day < day:
        d = (d.replace(day=1) - timedelta(days=1)).replace(day=day)
    else:
        d = d.replace(day=day)
    return datetime.combine(d, time(0, 0), tzinfo=now.tzinfo)


def next_period(start: datetime) -> datetime:
    nxt = (start.date().replace(day=1) + timedelta(days=32)).replace(day=start.day)
    return datetime.combine(nxt, time(0, 0), tzinfo=start.tzinfo)


def spend_report(home: Path, cfg: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    rows = [r for r in ledger.read_rows(home, since=now - timedelta(days=70), kind="run")]
    midnight = datetime.combine(now.date(), time(0, 0), tzinfo=now.tzinfo)
    week_start = midnight - timedelta(days=now.weekday())
    credit_start = period_start(now, cfg.get("sdk_credit_reset_day") or 1)

    def ts(r: Dict[str, Any]) -> datetime:
        return oc.parse_when(r.get("ts"), now.tzinfo)

    def cost(rs: List[Dict[str, Any]]) -> float:
        return round(sum(r.get("cost_usd") or 0.0 for r in rs), 2)

    def headless(r: Dict[str, Any]) -> bool:
        return r.get("surface") in HEADLESS_SURFACES or str(r.get("entrypoint", "")).startswith("sdk")

    today = [r for r in rows if ts(r) >= midnight]
    week = [r for r in rows if ts(r) >= week_start]
    period = [r for r in rows if ts(r) >= credit_start and headless(r)]
    by: Dict[str, Dict[str, Any]] = {}
    for r in week:
        k = r.get("automation") or "(interactive)"
        b = by.setdefault(k, {"runs": 0, "failed": 0, "cost_usd": 0.0, "failed_cost_usd": 0.0, "runs_without_cost": 0, "tokens": 0})
        b["runs"] += 1
        c = r.get("cost_usd")
        if c is None:
            b["runs_without_cost"] += 1
        else:
            b["cost_usd"] += c
        failed = r.get("outcome") == "fail"
        if failed:
            b["failed"] += 1
            b["failed_cost_usd"] += c or 0.0
        b["tokens"] += sum((r.get("tokens") or {}).values())
    for b in by.values():
        b["cost_usd"] = round(b["cost_usd"], 2)
        b["failed_cost_usd"] = round(b["failed_cost_usd"], 2)
        b["avg_cost_usd"] = round(b["cost_usd"] / max(1, b["runs"] - b["runs_without_cost"]), 2)
    rep: Dict[str, Any] = {
        "today_usd": cost(today), "week_usd": cost(week), "week_start": oc.iso(week_start),
        "week_failed_usd": round(sum(b["failed_cost_usd"] for b in by.values()), 2),
        "by_automation_this_week": dict(sorted(by.items(), key=lambda kv: -kv[1]["cost_usd"])),
        "basis": "cost Claude Code reported per run (client-side estimate at list price), not billing data",
    }
    alerts = [int(x) for x in (cfg.get("alert_percents") or [50, 75, 90])]
    wk = cfg.get("budget_weekly_usd")
    if wk:
        rep["weekly_budget_usd"] = float(wk)
        rep["weekly_used_percent"] = round(rep["week_usd"] / float(wk) * 100, 1)
    daily = cfg.get("budget_daily_usd")
    if daily:
        rep["daily_budget_usd"] = float(daily)
        rep["daily_used_percent"] = round(rep["today_usd"] / float(daily) * 100, 1)
    credit = cfg.get("sdk_credit_usd")
    if credit:
        credit = float(credit)
        end = next_period(credit_start)
        used = cost(period)
        elapsed = max(0.0, min(1.0, (now - credit_start) / (end - credit_start)))
        c: Dict[str, Any] = {"credit_usd": credit, "estimated_used_usd": used, "estimated_used_percent": round(used / credit * 100, 1),
                             "period_start": oc.iso(credit_start), "refreshes_at": oc.iso(end),
                             "elapsed_percent": round(elapsed * 100, 1), "runs_in_period": len(period),
                             "note": "Estimate from reported run cost. Your usage page is the source of truth."}
        if elapsed >= 0.05 and used > 0:
            proj = used / elapsed
            c["projected_usd_at_refresh"] = round(proj, 2)
            if proj >= credit:
                rate = used / (now - credit_start).total_seconds()
                c["exhausted_at"] = oc.iso((now + timedelta(seconds=(credit - used) / rate)).astimezone(now.tzinfo))
        pct = c["estimated_used_percent"]
        proj_pct = c.get("projected_usd_at_refresh", 0.0) / credit * 100
        if pct >= alerts[-1] or proj_pct >= 105:
            c["level"] = "critical"
        elif pct >= alerts[0] or proj_pct >= 90:
            c["level"] = "watch"
        else:
            c["level"] = "ok"
        c["alerts_crossed"] = [a for a in alerts if pct >= a]
        rep["sdk_credit"] = c
    return rep


def report(home: Path, now: datetime) -> Dict[str, Any]:
    cfg = oc.load_config(home)
    alerts = [int(x) for x in (cfg.get("alert_percents") or [50, 75, 90])]
    return {"generated_at": oc.iso(now), "plan": cfg.get("plan") or None,
            "windows": window_report(read_side(home), now, alerts), "spend": spend_report(home, cfg, now)}


def render_table(rep: Dict[str, Any]) -> str:
    L = ["Otto budget at %s" % rep["generated_at"]]
    for w in rep["windows"]:
        if not w.get("available"):
            L.append("%-8s unavailable: %s" % (w["window"], w["reason"]))
            continue
        extra = ""
        if "projected_percent_at_reset" in w:
            extra = ", on pace for %s%% at reset" % w["projected_percent_at_reset"]
        L.append("%-8s %5.1f%% used, %s%% of the window elapsed%s [%s]%s" % (
            w["window"], w["used_percent"], w.get("elapsed_percent", "?"), extra, w.get("level", "?"),
            " (stale: %s)" % w.get("note", "capture older than 15 min") if w.get("stale") else ""))
    s = rep["spend"]
    L.append("spend    today $%.2f, this week $%.2f (failed runs: $%.2f)" % (s["today_usd"], s["week_usd"], s["week_failed_usd"]))
    if "sdk_credit" in s:
        c = s["sdk_credit"]
        L.append("credit   ~%.1f%% of $%g used (estimate), %s%% of the period gone [%s]" % (c["estimated_used_percent"], c["credit_usd"], c["elapsed_percent"], c["level"]))
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home"); ap.add_argument("--now")
    g = ap.add_mutually_exclusive_group(); g.add_argument("--json", action="store_true"); g.add_argument("--table", action="store_true")
    a = ap.parse_args(argv)
    home = Path(a.home).expanduser() if a.home else oc.otto_home()
    cfg = oc.load_config(home)
    now = oc.parse_when(a.now, oc.get_tz(cfg.get("timezone")))
    rep = report(home, now)
    print(render_table(rep) if a.table else json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
