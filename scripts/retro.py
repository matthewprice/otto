#!/usr/bin/env python3
"""The numbers behind the weekly retro, and the record of changes you applied.

  retro.py report [--days 7] [--now ISO] [--json]
  retro.py record-change --automation NAME --note TEXT [--date ISO] [--kind KIND]
  retro.py effects [--json]

`report` compares this period with the one before it, counts silent misses by replaying
past cycles, finds step changes in per-run cost, and totals what failed runs and retries
cost. `record-change` writes down a change you made (for example "trimmed the skill
description") so that `effects` can later show the measured before and after for that
automation. Savings are only claimed from measurements, never from the audit's estimate.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import health  # noqa: E402
import ledger  # noqa: E402
import otto_common as oc  # noqa: E402


def _ts(r: Dict[str, Any], tz) -> datetime:
    return oc.parse_when(r.get("ts"), tz)


def _stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    ok = [r for r in rows if health.row_outcome(r) == "pass"]
    bad = [r for r in rows if health.row_outcome(r) == "fail"]
    costs = [r["cost_usd"] for r in ok if r.get("cost_usd") is not None]
    return {
        "runs": len(rows), "failed": len(bad),
        "cost_usd": round(sum(r.get("cost_usd") or 0.0 for r in rows), 2),
        "failed_cost_usd": round(sum(r.get("cost_usd") or 0.0 for r in bad), 2),
        "retry_runs": sum(1 for r in rows if (r.get("attempt") or 1) > 1),
        "retry_cost_usd": round(sum(r.get("cost_usd") or 0.0 for r in rows if (r.get("attempt") or 1) > 1), 2),
        "median_cost_usd": round(oc.median(costs), 3) if costs else None,
    }


def step_change(rows: List[Dict[str, Any]], tz, min_side: int = 4) -> Optional[Dict[str, Any]]:
    """Largest shift in median per-run cost between the runs before and after a split point."""
    ok = [r for r in rows if health.row_outcome(r) == "pass" and r.get("cost_usd") is not None]
    if len(ok) < 2 * min_side:
        return None
    best = None
    for i in range(min_side, len(ok) - min_side + 1):
        before = oc.median([r["cost_usd"] for r in ok[max(0, i - 7):i]])
        after = oc.median([r["cost_usd"] for r in ok[i:i + 7]])
        if not before or after is None:
            continue
        ratio = after / before
        score = abs(ratio - 1)
        if best is None or score > best[0]:
            best = (score, i, before, after, ratio)
    if not best or best[0] < 0.25 or abs(best[3] - best[2]) < 0.10:
        return None
    _, i, before, after, ratio = best
    return {"at": oc.iso(_ts(ok[i], tz)), "median_before_usd": round(before, 3), "median_after_usd": round(after, 3),
            "change_percent": round((ratio - 1) * 100), "runs_before": min(7, i), "runs_after": min(7, len(ok) - i),
            "caveat": "A step is a place to look, not a cause. Check what changed in the skill, the model, or the inputs that day."}


def report(home: Path, days: int, now: datetime) -> Dict[str, Any]:
    cfg = oc.load_config(home)
    tz = now.tzinfo
    rows = [r for r in ledger.read_rows(home, since=now - timedelta(days=days * 2 + 30), kind="run") if r.get("automation")]
    cur_start, prev_start = now - timedelta(days=days), now - timedelta(days=days * 2)
    cur = [r for r in rows if _ts(r, tz) >= cur_start]
    prev = [r for r in rows if prev_start <= _ts(r, tz) < cur_start]
    names = sorted({r["automation"] for r in rows})
    per = {}
    for n in names:
        c = _stats([r for r in cur if r["automation"] == n])
        p = _stats([r for r in prev if r["automation"] == n])
        entry: Dict[str, Any] = {"this_period": c, "previous_period": p}
        if p["cost_usd"] > 0:
            entry["cost_change_percent"] = round((c["cost_usd"] / p["cost_usd"] - 1) * 100)
        sc = step_change([r for r in rows if r["automation"] == n], tz)
        if sc:
            entry["step_change"] = sc
        per[n] = entry
    hist = health.history(home, days, now)
    events = [e for e in ledger.read_rows(home, since=cur_start, kind="event")]
    kinds: Dict[str, int] = {}
    for e in events:
        k = e.get("detail") or e.get("event") or "event"
        kinds[k] = kinds.get(k, 0) + 1
    return {
        "generated_at": oc.iso(now), "days": days,
        "totals": {"this_period": _stats(cur), "previous_period": _stats(prev)},
        "silent_cycles": hist["totals"], "cycles": {k: [c for c in v if c["status"] not in ("ok", "new")] for k, v in hist["cycles"].items()},
        "by_automation": per, "event_counts": kinds,
        "changes": effects(home, now),
        "basis": "Run cost is what Claude Code reported (client-side estimate). Silent cycles are replayed from the registry and the ledger.",
    }


# --------------------------------------------------------------------------- applied changes

def changes_path(home: Path) -> Path:
    return oc.state_dir(home) / "changes.json"


def record_change(home: Path, automation: str, note: str, when: Optional[str], kind: str = "other") -> Dict[str, Any]:
    oc.ensure_dirs(home)
    entry = {"automation": oc.slug(automation), "note": oc.short(note, 200), "kind": oc.short(kind, 32),
             "date": oc.iso(oc.parse_when(when))}
    with oc.file_lock(oc.state_dir(home) / "changes.lock"):
        data = oc.read_json(changes_path(home), []) or []
        data.append(entry)
        oc.write_json(changes_path(home), data)
    return entry


def effects(home: Path, now: datetime, window: int = 7) -> List[Dict[str, Any]]:
    out = []
    for ch in oc.read_json(changes_path(home), []) or []:
        when = oc.parse_when(ch["date"], now.tzinfo)
        rows = [r for r in ledger.read_rows(home, kind="run", automation=ch["automation"])
                if health.row_outcome(r) == "pass" and r.get("cost_usd") is not None]
        before = [r["cost_usd"] for r in rows if _ts(r, now.tzinfo) < when][-window:]
        after = [r["cost_usd"] for r in rows if _ts(r, now.tzinfo) >= when][:window]
        rec = dict(ch)
        rec["runs_before"], rec["runs_after"] = len(before), len(after)
        if len(before) >= 3 and len(after) >= 3:
            b, a = oc.median(before), oc.median(after)
            rec.update({"median_before_usd": round(b, 3), "median_after_usd": round(a, 3),
                        "change_percent": round((a / b - 1) * 100) if b else None, "measured": True})
        else:
            rec.update({"measured": False, "reason": "needs at least 3 passing runs on each side of the change"})
        out.append(rec)
    return out


def render_markdown(rep: Dict[str, Any]) -> str:
    """A report someone else can read: names and numbers only, no prompt or output text."""
    t, p = rep["totals"]["this_period"], rep["totals"]["previous_period"]
    L = ["# Automations: the last %d days" % rep["days"], "",
         "Generated %s by Otto. Cost is what Claude Code reported per run (a client-side estimate at list price), not billing data." % rep["generated_at"][:16], "",
         "| | This period | Previous |", "|---|---|---|",
         "| Runs | %d | %d |" % (t["runs"], p["runs"]),
         "| Failed runs | %d | %d |" % (t["failed"], p["failed"]),
         "| Reported cost | $%.2f | $%.2f |" % (t["cost_usd"], p["cost_usd"]),
         "| Cost of failed runs | $%.2f | $%.2f |" % (t["failed_cost_usd"], p["failed_cost_usd"]),
         "| Retry runs | %d | %d |" % (t["retry_runs"], p["retry_runs"]), ""]
    sc = rep.get("silent_cycles") or {}
    if sc:
        L += ["## Cycles by outcome", "", ", ".join("%s %d" % (k, v) for k, v in sorted(sc.items())), ""]
    L += ["## By automation", "", "| Automation | Runs | Failed | Cost | Change | Median per run |", "|---|---|---|---|---|---|"]
    for name, e in sorted(rep["by_automation"].items()):
        c = e["this_period"]
        ch = e.get("cost_change_percent")
        L.append("| %s | %d | %d | $%.2f | %s | %s |" % (name, c["runs"], c["failed"], c["cost_usd"],
                 ("%+d%%" % ch) if ch is not None else "n/a", ("$%.3f" % c["median_cost_usd"]) if c.get("median_cost_usd") is not None else "n/a"))
    steps = [(n, e["step_change"]) for n, e in rep["by_automation"].items() if e.get("step_change")]
    if steps:
        L += ["", "## Step changes (places to look, not causes)", ""]
        for n, s_ in steps:
            L.append("- %s: median $%.3f to $%.3f (%+d%%) around %s" % (n, s_["median_before_usd"], s_["median_after_usd"], s_["change_percent"], s_["at"][:10]))
    ch = rep.get("changes") or []
    if ch:
        L += ["", "## Changes and their measured effect", ""]
        for c in ch:
            if c.get("measured"):
                L.append("- %s, %s (%s): median $%.3f before, $%.3f after (%+d%%) over %d and %d runs" % (
                    c["automation"], c["note"], c["date"][:10], c["median_before_usd"], c["median_after_usd"], c["change_percent"] or 0, c["runs_before"], c["runs_after"]))
            else:
                L.append("- %s, %s (%s): not yet measured, %s" % (c["automation"], c["note"], c["date"][:10], c.get("reason", "")))
    L += ["", "_%s_" % rep["basis"]]
    return "\n".join(L) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report"); r.add_argument("--days", type=int, default=7); r.add_argument("--now")
    r.add_argument("--markdown", action="store_true", help="a shareable Markdown report instead of JSON")
    c = sub.add_parser("record-change")
    c.add_argument("--automation", required=True); c.add_argument("--note", required=True)
    c.add_argument("--date"); c.add_argument("--kind", default="other")
    e = sub.add_parser("effects"); e.add_argument("--now")
    args = ap.parse_args(argv)
    home = Path(args.home).expanduser() if args.home else oc.otto_home()
    cfg = oc.load_config(home)
    tz = oc.get_tz(cfg.get("timezone"))
    if args.cmd == "report":
        rep = report(home, args.days, oc.parse_when(args.now, tz))
        print(render_markdown(rep) if args.markdown else json.dumps(rep, indent=2))
    elif args.cmd == "record-change":
        print(json.dumps(record_change(home, args.automation, args.note, args.date, args.kind)))
    elif args.cmd == "effects":
        print(json.dumps(effects(home, oc.parse_when(args.now, tz)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
