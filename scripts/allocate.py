#!/usr/bin/env python3
"""Tomorrow's allocation: searches, daily cap, cadence and stage models per strategy.

  allocate.py plan --pool N [--settings FILE] [--grant PATH] [--days 30] [--dry-run] [--json]

Reads the yield report, the diagnosis, the grant's bounds and the current settings per strategy.
Settings come from --settings, else OTTO_HOME/strategies.json, else the last run row of each
strategy. The settings file is written by the client:

  {"alpha": {"searches": 120, "daily_cap": 30, "schedule": "daily", "status": "running",
           "stages": {"triage": "haiku", "score": "sonnet"}, "runs_below_median": 0}}

Procedure, in order:
  1. Cadence. 5 consecutive runs below a quarter of the fleet median: alternate days. 10: parked.
     A parked strategy, a blocked one (diagnosis) or one not running or ready gets nothing.
  2. Reserve consumers. A strategy with a steward experiment collecting treatment runs, and a
     newly approved strategy (fewer than 3 runs ever and its first run within 14 days, running or
     ready), are taken out of the softmax pass. Their needs (the grant's searches max for an
     experiment; for a new strategy its exploration floor, the larger of searches.min and the
     exploration share of the pool split evenly) are set aside first.
  3. Shares. A softmax over the smoothed yield of the remaining strategies, each divided by the
     best one's yield first, at the temperature in steward_rules.json.
  4. Clip. Every move is at most the daily shift bound from today's searches, then the value is
     put inside [searches.min, searches.max]: the minimum wins over the shift bound. 0 is emitted
     only for a parked or blocked strategy. A strategy with mode ad-hoc gets no schedule change.
  5. Budget. The regular strategies stay inside the pool minus the set-aside. If their minimums
     alone exceed the pool, the lowest-yield ones are held at no change (searches null, unfunded)
     rather than given a value below searches.min.
  6. Reserve. reserve = pool minus what the regular strategies were allocated. It pays only its
     two consumers, in order: experiments first, then new strategies, each clipped to what is
     left; one that cannot get searches.min is marked unfunded with no change proposed. The rest
     stays unspent. Slack is never redistributed to existing strategies: more
     volume on the same sources is the failure the Steward exists to stop.
  7. Rule 12. Under levers.structural_min_runs runs (7; a grant may lower it) a strategy's
     searches, daily cap and cadence still move, but a model change is listed under `proposed`,
     never in `changes`, and its stages stay as they are. Parking also needs a full sample;
     alternate days may apply earlier.
  8. Models, from the diagnosis only: a judgment leak moves the score stage up one tier, a cost
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
from datetime import timedelta
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_common as xc  # noqa: E402
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


def reserve_consumers(rules: Dict[str, Any]) -> List[str]:
    """The reserve's consumers from steward_rules.json. Only the two known kinds count; a client may
    narrow the list, never add to it."""
    raw = (rules.get("reserve") or {}).get("consumers")
    known = ["experiment", "new-strategy"]
    if not isinstance(raw, list):
        return known
    return [k for k in known if k in [str(x) for x in raw]]


def active_experiment_targets(home: Path) -> set:
    """Strategies with a steward experiment collecting treatment runs (fleet-wide ones excluded)."""
    out = set()
    for _, rec in xc.iter_records(home, "steward"):
        if rec.get("status") in ("collecting", "extended") and rec.get("scope") != "fleet" and rec.get("target"):
            out.add(str(rec["target"]))
    return out


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


def _cadence(cur: str, below: int, g: "steward.Grant", small: bool = False) -> Tuple[str, Optional[str]]:
    r = g.rules
    allowed = g.bounds("cadence") or ["daily", "alternate", "weekly", "parked"]
    park_n, alt_n = int(r.get("park_runs", 10)), int(r.get("demote_alternate_runs", 5))
    if below >= park_n and "parked" in allowed and not small:
        return "parked", "%d consecutive runs below a quarter of the fleet median: park" % below
    if below >= park_n and small and cur == "daily" and "alternate" in allowed:
        return "alternate", "%d consecutive runs below a quarter of the fleet median: alternate days (parking waits for a full sample)" % below
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
    drep = diagnosis or steward.load_script("diagnose").report(home, days, now, g, yrep, settings_path=settings_path)
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
                   "leak": dg.get("leak", "no-data"), "runs_below_median": below, "reasons": [],
                   "mode": str(st.get("mode") or "scheduled")}

    # 1. cadence and who takes part
    takers: List[str] = []
    for n, r in rows.items():
        if r["mode"] == "ad-hoc":
            sched, why = r["schedule_now"], None  # run by hand: the plan never proposes a schedule
        elif r["leak"] in ("blocked", "no-data") or r["status"] not in LIVE:
            sched, why = r["schedule_now"], None  # no yield to judge a cadence by
        else:
            sched, why = _cadence(r["schedule_now"], r["runs_below_median"], g, small=r["sample"] == "small")
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

    # 2. who draws on the reserve instead of the softmax pass
    consumers = reserve_consumers(rules)
    exp_targets = active_experiment_targets(home) if "experiment" in consumers else set()
    exp_draw = [n for n in takers if n in exp_targets]
    # Newly approved: fewer than new_strategy_runs runs over its whole history, and its first run
    # within the last new_strategy_days days. Everything else, small samples included, goes through
    # the normal pass (yield.py's smoothing already damps small samples).
    ylib = steward.load_script("yield")
    rr = rules.get("reserve") or {}
    new_runs, new_days = int(rr.get("new_strategy_runs", 3)), int(rr.get("new_strategy_days", 14))
    clock = now or datetime.now().astimezone()
    for n in takers:
        hist = ylib.read_runs(home, until=clock, strategy=n)
        rows[n]["runs_ever"] = len(hist)
        rows[n]["first_run"] = hist[0]["ts"] if hist else None
    def is_new(n: str) -> bool:
        r = rows[n]
        if r["runs_ever"] >= new_runs:
            return False
        return r["first_run"] is None or oc.parse_when(r["first_run"]) >= clock - timedelta(days=new_days)
    new_draw = [n for n in takers if "new-strategy" in consumers and n not in exp_targets and is_new(n)]
    regular = [n for n in takers if n not in exp_draw and n not in new_draw]
    # The floor never sits below the grant's searches.min, so the client never gets a value it must refuse.
    floor_each = max(float(sb["min"]), explore * pool / len(new_draw)) if new_draw else 0.0
    need = {n: float(sb["max"]) for n in exp_draw}
    need.update({n: min(float(sb["max"]), floor_each) for n in new_draw})
    # The consumers' needs are set aside before the softmax pass, so the regular strategies cannot
    # squeeze them out; the regular pass is still held to its own bounds.
    regular_budget = max(0, pool - int(math.ceil(sum(need.values()))))

    # 3. shares, over the regular strategies only
    # Yields are divided by the best regular strategy's yield, so the softmax sees 0..1 whatever the units.
    filled = {n: (rows[n]["smoothed_yield"] if rows[n]["smoothed_yield"] is not None else (fleet_med or 0.0)) for n in regular}
    scale = max(list(filled.values()) + [0.0]) or 1.0
    sm = softmax([filled[n] / scale for n in regular], float(rules.get("softmax_temperature", 1.0)))
    shares = {n: x for n, x in zip(regular, sm)}

    # 4. clip
    lower: Dict[str, int] = {}
    for n in regular:
        r = rows[n]
        target = shares[n] * regular_budget
        cur = r["searches_now"]
        smin, smax = float(sb["min"]), float(sb["max"])
        lo, hi = smin, smax
        if cur is not None and cur > 0:
            lo = max(lo, cur * (1 - shift))
            hi = min(hi, cur * (1 + shift))
        # Every value lands inside [searches.min, searches.max] after the shift bound: a strategy
        # the bound would leave below the minimum is raised to it, one above the maximum is cut.
        lo, hi = min(max(lo, smin), smax), min(max(hi, smin), smax)
        if lo > hi:
            lo = hi
        v = min(max(target, lo), hi)
        r["share_target"] = round(shares[n], 4)
        r["searches"] = max(int(sb["min"]), int(math.floor(v)))
        lower[n] = max(int(sb["min"]), int(math.ceil(lo)))
        if cur is not None and abs(v - target) > 0.5:
            r["reasons"].append("clipped from %d to %d by the %d%% daily shift bound and the searches bounds" % (round(target), r["searches"], round(shift * 100)))

    # 5. the regular strategies against their budget, then against the pool
    pool_note = None
    total = sum(rows[n]["searches"] for n in regular)
    if total > regular_budget:
        excess = total - regular_budget
        for n in sorted(regular, key=lambda k: -(rows[k]["searches"] - lower[k])):
            if excess <= 0:
                break
            take = min(max(0, rows[n]["searches"] - max(lower[n], 0)), excess)
            if take:
                rows[n]["searches"] -= take
                rows[n]["reasons"].append("trimmed %d to keep the reserve's set-aside whole" % take)
                excess -= take
    total = sum(rows[n]["searches"] for n in regular)
    held: List[str] = []
    if total > pool:
        # The lower limits alone exceed the pool. Scaling everyone below searches.min would hand the
        # client values it must refuse, so the lowest-yield strategies are dropped to their minimum
        # first, then held at no change (searches None) until the rest fits.
        for n in sorted(regular, key=lambda k: (filled.get(k) or 0.0, k)):
            if total <= pool:
                break
            cut = rows[n]["searches"] - int(sb["min"])
            if cut > 0:
                take = min(cut, total - pool)
                rows[n]["searches"] -= take
                total -= take
        for n in sorted(regular, key=lambda k: (filled.get(k) or 0.0, k)):
            if total <= pool:
                break
            total -= rows[n]["searches"]
            rows[n]["searches"] = None
            rows[n]["unfunded"] = True
            rows[n]["reasons"].append("held at no change: the pool cannot cover searches.min %d for every strategy" % int(sb["min"]))
            held.append(n)
        pool_note = "the pool is below the sum of the lower limits; %d strategy%s held at no change" % (len(held), "" if len(held) == 1 else "s")
    allocated = sum(rows[n]["searches"] or 0 for n in regular)

    # 6. the reserve: pool minus what the regular strategies were allocated. Only two consumers may
    # draw on it, in this order: experiment treatment runs, then newly approved strategies. Each is
    # clipped to what is left. The rest is never redistributed.
    reserve = max(0, pool - allocated)
    left = reserve
    drawn = {"experiment": 0, "new-strategy": 0}
    for kind, names_ in (("experiment", exp_draw), ("new-strategy", new_draw)):
        for n in names_:
            r = rows[n]
            want = int(math.ceil(need[n]))
            got = min(want, left)
            r["reserve_consumer"] = kind
            if kind == "new-strategy":
                r["floor_searches"] = want
            if got < int(sb["min"]):
                # Not enough left to fund even searches.min: say so, propose no searches change.
                r["searches"] = None
                r["unfunded"] = True
                r["reasons"].append("%s: the reserve has %d left, below searches.min %d; not funded tonight, no change proposed" % (
                    "experiment collecting" if kind == "experiment" else "new strategy", left, int(sb["min"])))
                continue
            left -= got
            drawn[kind] += got
            r["searches"] = got
            r["funded_from"] = "reserve"
            if kind == "experiment":
                r["reasons"].append("experiment collecting: treatment runs funded from the reserve at searches max %d%s" % (
                    int(sb["max"]), "" if got >= want else ", clipped to %d (reserve short)" % got))
            else:
                r["reasons"].append("new strategy (%d runs ever): funded from the reserve at its exploration floor of %d%s" % (
                    r["runs_ever"], want, "" if got >= want else ", clipped to %d (reserve short)" % got))
    unspent = left
    total = sum(rows[n]["searches"] or 0 for n in rows)

    # daily cap, models, share, change list
    for n, r in rows.items():
        cap = r["daily_cap_now"]
        if r.get("unfunded"):
            r["daily_cap"] = cap
        elif isinstance(cap, (int, float)) and not isinstance(cap, bool) and r["searches_now"] and r["searches"]:
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
        r["share"] = round((r["searches"] or 0) / float(pool), 4) if pool else 0.0
        changes = []
        r["proposed"] = []
        for key, old, new in (("searches", r["searches_now"], r["searches"]), ("daily_cap", r["daily_cap_now"], r["daily_cap"]),
                              ("schedule", r["schedule_now"], r["schedule"]), ("stages", r["stages_now"], r["stages"])):
            if key == "searches" and new is None:
                continue  # unfunded: no searches change proposed
            if old != new:
                lever = LEVER_FOR[key]
                ok, gwhy = g.why_for(lever, r["runs"])
                item = {"field": key, "from": old, "to": new, "lever": lever, "apply": bool(ok and not dry_run),
                        "grant": "dry run" if (ok and dry_run) else gwhy}
                if not ok and gwhy.startswith("tentative:"):
                    # Rule 12: a structural change on a small sample is proposed only, never written
                    # into changes, and the plan keeps the current value.
                    r["proposed"].append(item)
                    r[key] = old
                    r["reasons"].append("%s change proposed only (%s)" % (key, gwhy))
                    continue
                changes.append(item)
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
           "strategies": {n: rows[n] for n in sorted(rows, key=lambda k: (-(rows[k]["searches"] or 0), k))},
           "unfunded": sorted(n for n in rows if rows[n].get("unfunded")),
           "pool_note": pool_note,
           "allocated_regular": allocated, "reserve": reserve, "reserve_drawn": drawn, "reserve_unspent": unspent,
           "reserve_consumers": consumers,
           "reserve_note": ("%d of the reserve stays unspent: slack is never redistributed to existing strategies" % unspent) if unspent else None,
           "label": "ESTIMATE: shares are a rule applied to MEASURED funnel counts and ESTIMATE run-units; nothing here is a result",
           "applies": "nothing; the client applies the changes marked apply: true, one logged commit each"}
    if write:
        oc.write_json(allocation_path(home), out)
    return out


def render(p: Dict[str, Any]) -> str:
    L = ["Allocation for tomorrow (%s%s): %d of %d searches in the pool" % (p["mode"], ", dry run" if p["dry_run"] else "", p["total_searches"], p["pool"])]
    L.append("%-14s %8s %6s %6s %-10s %-9s %s" % ("strategy", "searches", "was", "share", "cadence", "leak", "reason"))
    for n, r in p["strategies"].items():
        L.append("%-14s %8s %6s %5d%% %-10s %-9s %s" % (n[:14], "held" if r["searches"] is None else r["searches"], "-" if r["searches_now"] is None else r["searches_now"],
                                                     round(r["share"] * 100), r["schedule"], r["leak"], r["reason"]))
        for c in r["changes"] + r.get("proposed", []):
            if c["field"] == "stages":
                L.append("    stages %s -> %s [%s]" % (json.dumps(c["from"], sort_keys=True), json.dumps(c["to"], sort_keys=True), "apply" if c["apply"] else "propose: " + c["grant"]))
    if "reserve" in p:
        d = p.get("reserve_drawn") or {}
        L.append("reserve: %d (pool %d minus %d allocated); drawn %d by experiments, %d by new strategies" % (
            p["reserve"], p["pool"], p["allocated_regular"], d.get("experiment", 0), d.get("new-strategy", 0)))
        if p.get("reserve_note"):
            L.append(p["reserve_note"] + ".")
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
