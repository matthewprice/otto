#!/usr/bin/env python3
"""Tomorrow's allocation: searches, daily cap, cadence and stage models per strategy.

  allocate.py plan --pool N [--settings FILE] [--grant PATH] [--days 30] [--dry-run] [--json]

Reads the yield report, the diagnosis, the grant's bounds and the current settings per strategy.
Settings come from --settings, else OTTO_HOME/strategies.json, else the last run row of each
strategy. The settings file is written by the client:

  {"S01": {"searches": 120, "daily_cap": 30, "schedule": "daily", "status": "running",
           "stages": {"triage": "haiku", "score": "sonnet"}, "runs_below_median": 0}}

Procedure, in order:
  1. Cadence. 5 consecutive runs below a quarter of the fleet median: alternate days. 10: parked.
     A parked strategy, a blocked one (diagnosis) or one not running or ready gets nothing.
  2. Shares. A softmax over smoothed yield, each divided by the best live strategy's yield first,
     at the temperature in steward_rules.json.
  3. Exploration floor. The exploration share of the pool is split evenly across live strategies
     with fewer than 7 runs; none of them is given less than its part.
  4. Clip. Every move is at most the daily shift bound from today's searches, and inside the
     grant's searches bounds. The exploration floor outranks the shift bound: a small-sample
     strategy is lifted to its floor in one step, and never below it, up to the searches maximum.
  5. Pool. The total never exceeds --pool. If the clipped plan is over, the excess comes off the
     strategies with room above their lower limits, largest first.
  6. Models, from the diagnosis only: a judgment leak moves the score stage up one tier, a cost
     leak moves the non-volume stages down one. Volume stages never leave the lowest tier, and no
     stage is ever above the grant's model ceiling.

Writes OTTO_HOME/allocation.json and prints the plan. Applies nothing: each change carries
`apply: true` only when the grant names its lever and this is not a dry run, and the client does
the applying. Exit code 0 always.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import otto_common as oc  # noqa: E402
import steward  # noqa: E402

LIVE = ("running", "ready")
LEVER_FOR = {"searches": "budget", "daily_cap": "budget", "schedule": "cadence", "stages": "model"}


def allocation_path(home: Path) -> Path:
    return home / "allocation.json"


def load_settings(home: Path, path: Optional[str], yrep: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], str]:
    p = Path(path).expanduser() if path else home / "strategies.json"
    data = oc.read_json(p, None)
    if isinstance(data, dict) and data:
        return {steward.ident(k): (v if isinstance(v, dict) else {}) for k, v in data.items()}, str(p)
    # fall back to the last run row of each strategy
    y = steward.load_script("yield")
    out: Dict[str, Dict[str, Any]] = {}
    for name in yrep["strategies"]:
        rows = y.read_runs(home, strategy=name)
        last = rows[-1] if rows else {}
        out[name] = {"searches": last.get("searches"), "daily_cap": None, "schedule": "daily", "status": "running",
                     "stages": dict(last.get("stages") or {})}
    return out, "derived from the last run rows (no settings file)"


def softmax(xs: List[float], temperature: float = 1.0) -> List[float]:
    if not xs:
        return []
    t = temperature if temperature > 0 else 1.0
    m = max(xs)
    ex = [math.exp((x - m) / t) for x in xs]
    s = sum(ex)
    return [e / s for e in ex]


def apply_floor(shares: Dict[str, float], floors: Dict[str, float]) -> Dict[str, float]:
    """Raise every floored share to its floor and take the difference from the rest, pro rata."""
    out = dict(shares)
    fixed: Dict[str, float] = {}
    for _ in range(len(out) + 1):
        need = {k: f for k, f in floors.items() if k in out and k not in fixed and out[k] < f}
        if not need:
            break
        fixed.update(need)
        rest = [k for k in out if k not in fixed]
        left = max(0.0, 1.0 - sum(fixed.values()))
        tot = sum(shares[k] for k in rest)
        for k in rest:
            out[k] = (shares[k] / tot * left) if tot else (left / len(rest))
        out.update(fixed)
    return out


def _tier_shift(model: str, tiers: List[str], step: int, ceiling: Optional[str]) -> str:
    if model not in tiers:
        return model
    i = tiers.index(model) + step
    top = tiers.index(ceiling) if ceiling in tiers else len(tiers) - 1
    return tiers[max(0, min(i, top))]


def plan_models(stages: Dict[str, str], leak: str, g: "steward.Grant") -> Tuple[Dict[str, str], List[str]]:
    rules = g.rules
    tiers = [m for m in (rules.get("model_tiers") or ["haiku", "sonnet", "opus"])]
    allowed = g.bounds("models") or tiers[:1]
    ceiling = allowed[-1]
    floor_model = allowed[0]
    volume = set(rules.get("volume_stages") or [])
    judge = rules.get("judgment_stage", "score")
    new = dict(stages)
    why: List[str] = []
    for st, m in stages.items():
        m = str(m).lower()
        if m in (rules.get("banned_models") or []) or (m in tiers and tiers.index(m) > tiers.index(ceiling)):
            new[st] = ceiling
            why.append("%s %s is above the ceiling, down to %s" % (st, m, ceiling))
        if st in volume and new[st] != floor_model and new[st] in tiers:
            new[st] = floor_model
            why.append("%s is a volume stage and stays %s" % (st, floor_model))
    if leak == "judgment":
        cur = new.get(judge)
        if cur:
            up = _tier_shift(cur, tiers, +1, ceiling)
            if up != cur:
                new[judge] = up
                why.append("judgment leak: %s %s to %s for %d days" % (judge, cur, up, int(rules.get("judgment_hold_days", 14))))
            else:
                why.append("judgment leak but %s is already at the ceiling (%s)" % (judge, cur))
    elif leak == "cost":
        for st, m in list(new.items()):
            if st in volume:
                continue
            down = _tier_shift(m, tiers, -1, ceiling)
            if down != m:
                new[st] = down
                why.append("cost leak: %s %s to %s" % (st, m, down))
    return new, why


def _cadence(cur: str, below: int, g: "steward.Grant") -> Tuple[str, Optional[str]]:
    r = g.rules
    allowed = g.bounds("cadence") or ["daily", "alternate", "weekly", "parked"]
    park_n, alt_n = int(r.get("park_runs", 10)), int(r.get("demote_alternate_runs", 5))
    if below >= park_n and "parked" in allowed:
        return "parked", "%d consecutive runs below a quarter of the fleet median: park" % below
    if below >= alt_n and cur == "daily" and "alternate" in allowed:
        return "alternate", "%d consecutive runs below a quarter of the fleet median: alternate days" % below
    if below == 0 and cur == "alternate" and "daily" in allowed:
        return "daily", "back above the line: daily again"
    return cur, None


def plan(home: Path, pool: int, g: Optional["steward.Grant"] = None, settings_path: Optional[str] = None,
         dry_run: bool = False, now: Optional[datetime] = None, days: int = 30,
         yield_report: Optional[Dict[str, Any]] = None, diagnosis: Optional[Dict[str, Any]] = None,
         write: bool = True) -> Dict[str, Any]:
    g = g or steward.grant(None, home)
    rules = g.rules
    yrep = yield_report or steward.load_script("yield").report(home, days, now, rules)
    drep = diagnosis or steward.load_script("diagnose").report(home, days, now, g, yrep)
    settings, settings_src = load_settings(home, settings_path, yrep)
    sb = g.bounds("searches")
    cb = g.bounds("daily-cap")
    shift = sb["max-daily-shift"] or 0.0
    explore = g.bounds("exploration-share") or 0.0
    small_n = int(rules.get("small_sample_runs", 7))
    fleet_med = yrep.get("fleet_median_yield_per_unit")
    pool = max(0, int(pool))

    names = sorted(set(settings) | set(yrep["strategies"]))
    rows: Dict[str, Dict[str, Any]] = {}
    for n in names:
        st = settings.get(n, {})
        ys = yrep["strategies"].get(n) or {}
        dg = (drep.get("strategies") or {}).get(n) or {}
        cur_searches = st.get("searches")
        cur_searches = int(cur_searches) if isinstance(cur_searches, (int, float)) and not isinstance(cur_searches, bool) else None
        below = st.get("runs_below_median")
        below = int(below) if isinstance(below, int) and not isinstance(below, bool) else int(ys.get("runs_below_median") or 0)
        rows[n] = {"strategy": n, "status": str(st.get("status") or "running"), "schedule_now": str(st.get("schedule") or "daily"),
                   "searches_now": cur_searches, "daily_cap_now": st.get("daily_cap"),
                   "stages_now": dict(st.get("stages") or {}), "runs": int(ys.get("runs") or 0),
                   "smoothed_yield": ys.get("smoothed_yield"), "sample": ys.get("sample", "small"),
                   "leak": dg.get("leak", "no-data"), "runs_below_median": below, "reasons": []}

    # 1. cadence and who takes part
    takers: List[str] = []
    for n, r in rows.items():
        if r["leak"] in ("blocked", "no-data") or r["status"] not in LIVE:
            sched, why = r["schedule_now"], None  # no yield to judge a cadence by
        else:
            sched, why = _cadence(r["schedule_now"], r["runs_below_median"], g)
        r["schedule"] = sched
        if why:
            r["reasons"].append(why)
        if r["status"] not in LIVE:
            r["exclude"] = "status %s" % r["status"]
        elif r["leak"] == "blocked":
            r["exclude"] = "blocked runs: nothing allocated until the Sentinel clears it"
        elif sched == "parked":
            r["exclude"] = "parked"
        if r.get("exclude"):
            r["searches"] = 0
            r["share"] = 0.0
            if r["exclude"] != "parked" or not why:
                r["reasons"].append(r["exclude"])
        else:
            takers.append(n)

    # 2. shares
    # Yields are divided by the best taker's yield, so the softmax sees 0..1 whatever the units.
    filled = {n: (rows[n]["smoothed_yield"] if rows[n]["smoothed_yield"] is not None else (fleet_med or 0.0)) for n in takers}
    scale = max(list(filled.values()) + [0.0]) or 1.0
    ys_ = [filled[n] / scale for n in takers]
    sm = softmax(ys_, float(rules.get("softmax_temperature", 1.0)))
    shares = {n: s for n, s in zip(takers, sm)}
    # 3. exploration floor
    smalls = [n for n in takers if rows[n]["runs"] < small_n]
    floors = {n: explore / len(smalls) for n in smalls} if smalls else {}
    shares = apply_floor(shares, floors) if floors else shares

    # 4. clip
    lower: Dict[str, int] = {}
    for n in takers:
        r = rows[n]
        target = shares[n] * pool
        cur = r["searches_now"]
        lo, hi = float(sb["min"]), float(sb["max"])
        if cur is not None and cur > 0:
            lo = max(lo, cur * (1 - shift))
            hi = min(hi, cur * (1 + shift))
        floor_s = floors.get(n, 0.0) * pool
        lo = min(lo, hi)
        if n in floors:
            # The exploration floor is a guarantee: it outranks the shift bound (a new strategy may
            # jump to its floor in one night) but never the grant's searches maximum.
            lo = max(lo, min(floor_s, float(sb["max"])))
            hi = max(hi, lo)
        v = min(max(target, lo), hi)
        r["share_target"] = round(shares[n], 4)
        r["searches"] = int(math.ceil(v)) if n in floors else int(math.floor(v))
        lower[n] = int(math.ceil(lo))
        if n in floors:
            r["floor_searches"] = int(math.ceil(floor_s))
            r["reasons"].append("small sample (%d runs): held at or above its exploration floor of %d" % (r["runs"], math.ceil(floor_s)))
        if cur is not None and abs(v - target) > 0.5:
            r["reasons"].append("clipped from %d to %d by the %d%% daily shift bound and the searches bounds" % (round(target), r["searches"], round(shift * 100)))

    # 5. pool
    total = sum(rows[n]["searches"] for n in takers)
    pool_note = None
    if total > pool:
        excess = total - pool
        for n in sorted(takers, key=lambda k: -(rows[k]["searches"] - lower[k])):
            if excess <= 0:
                break
            room = max(0, rows[n]["searches"] - max(lower[n], 0))
            take = min(room, excess)
            if take:
                rows[n]["searches"] -= take
                rows[n]["reasons"].append("trimmed %d to keep the total inside the pool" % take)
                excess -= take
        if excess > 0:  # the lower limits alone exceed the pool: the pool wins, pro rata
            tot = sum(rows[n]["searches"] for n in takers)
            for n in takers:
                rows[n]["searches"] = int(math.floor(rows[n]["searches"] * pool / float(tot))) if tot else 0
            pool_note = "the pool is below the sum of the lower limits; every strategy was scaled down pro rata and some bounds do not hold"
    total = sum(rows[n]["searches"] for n in rows)

    # daily cap, models, share, change list
    for n, r in rows.items():
        cap = r["daily_cap_now"]
        if isinstance(cap, (int, float)) and not isinstance(cap, bool) and r["searches_now"] and r["searches"]:
            v = cap * r["searches"] / float(r["searches_now"])
            v = min(max(v, cap * (1 - shift)), cap * (1 + shift))
            r["daily_cap"] = int(min(max(round(v), cb["min"]), cb["max"]))
        elif r["searches"] == 0:
            r["daily_cap"] = cap
        else:
            r["daily_cap"] = cap
        stages, why = plan_models(r["stages_now"], r["leak"], g) if not r.get("exclude") else (dict(r["stages_now"]), [])
        r["stages"] = stages
        r["reasons"].extend(why)
        r["share"] = round(r["searches"] / float(pool), 4) if pool else 0.0
        changes = []
        for key, old, new in (("searches", r["searches_now"], r["searches"]), ("daily_cap", r["daily_cap_now"], r["daily_cap"]),
                              ("schedule", r["schedule_now"], r["schedule"]), ("stages", r["stages_now"], r["stages"])):
            if old != new:
                lever = LEVER_FOR[key]
                ok, gwhy = g.why(lever)
                changes.append({"field": key, "from": old, "to": new, "lever": lever, "apply": bool(ok and not dry_run),
                                "grant": "dry run" if (ok and dry_run) else gwhy})
        r["changes"] = changes
        if not r["reasons"]:
            r["reasons"].append("share follows yield" if not r.get("exclude") else r["exclude"])
        r["reason"] = "; ".join(r["reasons"])
        r.pop("reasons", None)
        r.pop("exclude", None)

    out = {"generated": oc.iso(now or datetime.now().astimezone()), "pool": pool, "total_searches": total,
           "within_pool": total <= pool, "dry_run": bool(dry_run), "mode": g.mode,
           "bounds": {"searches": sb, "daily-cap": cb, "exploration-share": explore, "models": g.bounds("models")},
           "settings_source": settings_src, "fleet_median_yield_per_unit": fleet_med,
           "strategies": {n: rows[n] for n in sorted(rows, key=lambda k: (-rows[k]["searches"], k))},
           "pool_note": pool_note,
           "label": "ESTIMATE: shares are a rule applied to MEASURED funnel counts and ESTIMATE run-units; nothing here is a result",
           "applies": "nothing; the client applies the changes marked apply: true, one logged commit each"}
    if write:
        oc.write_json(allocation_path(home), out)
    return out


def render(p: Dict[str, Any]) -> str:
    L = ["Allocation for tomorrow (%s%s): %d of %d searches in the pool" % (p["mode"], ", dry run" if p["dry_run"] else "", p["total_searches"], p["pool"])]
    L.append("%-14s %8s %6s %6s %-10s %-9s %s" % ("strategy", "searches", "was", "share", "cadence", "leak", "reason"))
    for n, r in p["strategies"].items():
        L.append("%-14s %8d %6s %5d%% %-10s %-9s %s" % (n[:14], r["searches"], "-" if r["searches_now"] is None else r["searches_now"],
                                                     round(r["share"] * 100), r["schedule"], r["leak"], r["reason"]))
        for c in r["changes"]:
            if c["field"] == "stages":
                L.append("    stages %s -> %s [%s]" % (json.dumps(c["from"], sort_keys=True), json.dumps(c["to"], sort_keys=True), "apply" if c["apply"] else "propose: " + c["grant"]))
    if p.get("pool_note"):
        L.append("note: " + p["pool_note"])
    L.append(p["label"])
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    common = steward.common_flags()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("plan", parents=[common])
    pp.add_argument("--pool", type=int, required=True); pp.add_argument("--settings"); pp.add_argument("--days", type=int, default=30)
    pp.add_argument("--dry-run", action="store_true")
    args = steward.parse_args(ap, argv)
    if args is None:
        return 0
    try:
        home = Path(args.home).expanduser() if args.home else oc.otto_home()
        g = steward.grant(args.grant, home)
        now = oc.parse_when(args.now) if args.now else None
        p = plan(home, args.pool, g, args.settings, args.dry_run, now, args.days)
        print(json.dumps(p, indent=2) if args.json else render(p))
    except Exception as e:  # fail open
        oc.log_error("allocate: %s" % e)
        oc.eprint("allocate: %s (logged; nothing was changed)" % oc.short(e, 200))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
