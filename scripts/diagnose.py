#!/usr/bin/env python3
"""Where each strategy leaks, and which lever matches the leak.

  diagnose.py report [--days 30] [--grant PATH] [--json]

The funnel says where a strategy loses opportunities. Each stage maps to one lever:

  blocked   most runs blocked by network or fetch     no lever; a Sentinel exception, excluded from yield
  source    examined high, candidates low; or drops   method: swap or add sources, narrow the cursor
            repeat the kill list and overlap           (weekly). After two failed method experiments:
                                                       propose a new strategy to the person
  triage    candidates high, prescreen pass near      gates: triage questions and the triage threshold
            zero, drops cluster on one filter          (weekly). Revenue-timing drops are surfaced
  judgment  passes and scores, but almost nothing     model: score stage up one tier (nightly);
            reaches the persona floor                  gates: tighten evidence (weekly)
  review    reaches the floor, then is killed at      skills: the reviewing persona's wording, as one
            review most of the time                    fleet-wide experiment (weekly)
  cost      yield at or above the fleet median,       model: stages down one tier; budget: searches
            run-units well above it                    down (nightly)
  healthy   none of the above                         none

Thresholds live in steward_rules.json under `diagnosis`. Under seven runs a strategy is a small
sample; the leak is still named, marked tentative. Exit code 0 always.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_common as xc  # noqa: E402
import otto_common as oc  # noqa: E402
import steward  # noqa: E402

LEVER_OF = {"blocked": [], "source": [("method", "weekly")], "triage": [("gates", "weekly")],
            "judgment": [("model", "nightly"), ("gates", "weekly")], "review": [("skills", "weekly")],
            "cost": [("model", "nightly"), ("budget", "nightly")], "healthy": [], "no-data": []}

CHANGE_OF = {
    ("source", "method"): "swap or add sources, or narrow the cursor",
    ("triage", "gates"): "rewrite the triage questions or move the triage threshold",
    ("judgment", "model"): "score stage up one model tier for two weeks",
    ("judgment", "gates"): "tighten the evidence gate",
    ("review", "skills"): "add a reference of the patterns the reviewer keeps killing, or sharpen its anchors",
    ("cost", "model"): "every non-volume stage down one model tier",
    ("cost", "budget"): "searches down by the daily shift bound",
}


def _rate(a: float, b: float) -> Optional[float]:
    return round(a / b, 4) if b else None


def failed_method_experiments(home: Path, target: str) -> int:
    return len(xc.records_where(home, "steward", lambda r: r.get("target") == target and r.get("lever") == "method"
                                and r.get("verdict") == "revert"))


def classify(s: Dict[str, Any], fleet: Dict[str, Any], rules: Dict[str, Any]) -> Dict[str, Any]:
    """One strategy's leak from its yield-report entry. Pure; the thresholds come from rules."""
    th = rules.get("diagnosis") or {}
    f = s["funnel"]
    n, total = s["runs"], s["runs_total"]
    drops = s.get("dropped") or {}
    drop_total = sum(drops.values())
    ev: Dict[str, Any] = {"runs": n, "blocked_runs": s["blocked_runs"]}
    if total and s["blocked_runs"] / float(total) >= th.get("blocked_share", 0.5):
        ev["blocked_share"] = round(s["blocked_runs"] / float(total), 3)
        return {"leak": "blocked", "evidence": ev, "why": "%d of %d runs blocked by network or fetch" % (s["blocked_runs"], total)}
    if n == 0:
        return {"leak": "no-data", "evidence": ev, "why": "no passing runs in the window"}
    ex_pr = f["examined"] / float(n)
    cand_rate = _rate(f["candidates"], f["examined"])
    pass_rate = _rate(f["prescreen_pass"], f["candidates"])
    floor_rate = _rate(f["at_floor"], f["scored"])
    kill_share = _rate(f["kill"], f["at_floor"])
    repeat = sum(drops.get(k, 0) for k in th.get("source_repeat_keys", ["overlap", "kill_list"]))
    repeat_share = _rate(repeat, drop_total)
    top_drop = max(drops.items(), key=lambda kv: (kv[1], kv[0])) if drops else (None, 0)
    cluster_share = _rate(top_drop[1], drop_total)
    ev.update({"examined_per_run": round(ex_pr, 2), "candidate_rate": cand_rate, "prescreen_pass_rate": pass_rate,
               "at_floor_rate": floor_rate, "kill_share": kill_share, "repeat_drop_share": repeat_share,
               "top_drop": top_drop[0], "top_drop_share": cluster_share})
    # source
    if (ex_pr >= th.get("source_min_examined_per_run", 20) and cand_rate is not None and cand_rate <= th.get("source_max_candidate_rate", 0.1)) or \
       (repeat_share is not None and repeat_share >= th.get("source_repeat_drop_share", 0.5) and drop_total >= 3):
        why = ("%.0f examined per run, %s of them become candidates" % (ex_pr, _pct(cand_rate))) if (cand_rate is not None and cand_rate <= th.get("source_max_candidate_rate", 0.1)) \
            else ("%s of drops repeat the kill list or overlap" % _pct(repeat_share))
        return {"leak": "source", "evidence": ev, "why": why}
    # triage
    if f["candidates"] / float(n) >= th.get("triage_min_candidates_per_run", 5) and pass_rate is not None and pass_rate <= th.get("triage_max_pass_rate", 0.1):
        out = {"leak": "triage", "evidence": ev, "why": "%s of candidates pass the prescreen; %s of drops on %s" % (_pct(pass_rate), _pct(cluster_share), top_drop[0])}
        if cluster_share is not None and cluster_share >= th.get("triage_cluster_share", 0.5) and top_drop[0] == th.get("seasonality_filter", "filter3"):
            out["surface"] = "revenue-timing drops dominate (%s); tell the person, it may be a seasonality pattern" % top_drop[0]
        return out
    # review (checked before judgment: a strategy that reaches the floor is not a judgment leak)
    if f["at_floor"] >= th.get("review_min_at_floor", 3) and f["kill"] >= th.get("review_min_kills", 2) and kill_share is not None and kill_share >= th.get("review_kill_share", 0.67):
        return {"leak": "review", "evidence": ev, "why": "%d reached the floor, %d killed at review" % (f["at_floor"], f["kill"])}
    # judgment
    if pass_rate is not None and pass_rate >= th.get("judgment_min_pass_rate", 0.1) and f["scored"] >= th.get("judgment_min_scored", 3) \
       and floor_rate is not None and floor_rate <= th.get("judgment_max_floor_rate", 0.1):
        return {"leak": "judgment", "evidence": ev, "why": "%d scored, %d at the floor" % (f["scored"], f["at_floor"])}
    # cost
    med_y, med_u = fleet.get("median_yield"), fleet.get("median_units_per_run")
    upr = (s["run_units"] / float(n)) if n else None
    ev["run_units_per_run"] = round(upr, 3) if upr is not None else None
    if med_y is not None and med_u and s.get("yield_per_unit") is not None and upr is not None:
        if s["yield_per_unit"] >= med_y and upr >= th.get("cost_units_ratio", 1.5) * med_u:
            return {"leak": "cost", "evidence": ev, "why": "yield at or above median at %.1fx the median run-units" % (upr / med_u)}
    return {"leak": "healthy", "evidence": ev, "why": "no stage stands out"}


def _pct(x: Optional[float]) -> str:
    return "-" if x is None else "%d%%" % round(x * 100)


def report(home: Path, days: int = 30, now: Optional[datetime] = None, g: Optional["steward.Grant"] = None,
           yield_report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    g = g or steward.grant(None, home)
    rules = g.rules
    th = rules.get("diagnosis") or {}
    y = yield_report or steward.load_script("yield").report(home, days, now, rules)
    strats = y["strategies"]
    upr = [s["run_units"] / float(s["runs"]) for s in strats.values() if s["runs"] and s["run_units"]]
    fleet = {"median_yield": y.get("fleet_median_yield_per_unit"), "median_units_per_run": oc.median(upr) if upr else None}
    out: Dict[str, Any] = {}
    for name, s in strats.items():
        c = classify(s, fleet, rules)
        acts = []
        for lever, when in LEVER_OF.get(c["leak"], []):
            ok, why = g.why(lever)
            acts.append({"lever": lever, "when": when, "change": CHANGE_OF.get((c["leak"], lever), ""),
                         "scope": "fleet" if lever == "skills" else "strategy", "allowed": ok, "grant": why})
        if c["leak"] == "source":
            failed = failed_method_experiments(home, name)
            c["evidence"]["failed_method_experiments"] = failed
            if failed >= th.get("propose_after_failed_method", 2):
                acts = [{"lever": "propose-strategy", "when": "weekly", "scope": "fleet", "allowed": False,
                         "grant": "the person designs and approves every new strategy",
                         "change": "%d method experiments failed; propose a new hunting ground to the person" % failed}]
        if c["leak"] == "blocked":
            acts = [{"lever": "none", "when": "sentinel", "scope": "strategy", "allowed": False,
                     "grant": "no lever applies", "change": "report as a Sentinel miss; excluded from yield"}]
        signals = []
        med = fleet["median_yield"]
        if med and s.get("smoothed_yield") is not None and s["sample"] == "ok" and s["funnel"]["top20"] >= th.get("over_performer_min_top20", 1) \
                and s["smoothed_yield"] >= th.get("over_performer_ratio", 2.0) * med:
            signals.append("over-performer")
            acts.append({"lever": "propose-strategy", "when": "weekly", "scope": "fleet", "allowed": False,
                         "grant": "the person designs and approves every new strategy",
                         "change": "yield %.1fx the fleet median; propose a sibling strategy on the same hunting ground" % (s["smoothed_yield"] / med)})
        out[name] = {"strategy": name, "leak": c["leak"], "why": c["why"], "evidence": c["evidence"], "actions": acts,
                     "tentative": s["sample"] == "small", "signals": signals}
        if c.get("surface"):
            out[name]["surface"] = c["surface"]
    return {"now": y.get("now"), "window_days": days, "mode": g.mode, "fleet": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in fleet.items()},
            "strategies": out, "order": y["ranked"],
            "basis": "Leaks are read from MEASURED funnel counts against the thresholds in steward_rules.json. A tentative leak rests on fewer than 7 runs."}


def render(rep: Dict[str, Any]) -> str:
    L = ["Diagnosis (%s mode, last %d days)" % (rep["mode"], rep["window_days"])]
    for name in rep["order"]:
        d = rep["strategies"][name]
        line = "%-16s %-9s %s%s" % (name[:16], d["leak"], d["why"], " (tentative: small sample)" if d["tentative"] else "")
        L.append(line)
        for a in d["actions"]:
            L.append("    %s, %s: %s [%s]" % (a["lever"], a["when"], a["change"], "apply" if a["allowed"] else "propose"))
        if d.get("surface"):
            L.append("    surface: " + d["surface"])
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    common = steward.common_flags()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", parents=[common]); r.add_argument("--days", type=int, default=30)
    args = steward.parse_args(ap, argv)
    if args is None:
        return 0
    try:
        home = Path(args.home).expanduser() if args.home else oc.otto_home()
        g = steward.grant(args.grant, home)
        now = oc.parse_when(args.now) if args.now else None
        rep = report(home, args.days, now, g)
        print(json.dumps(rep, indent=2) if args.json else render(rep))
    except Exception as e:  # fail open
        oc.log_error("diagnose: %s" % e)
        oc.eprint("diagnose: %s (logged)" % oc.short(e, 200))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
