#!/usr/bin/env python3
"""Steward experiments: one change to one target, measured against its own baseline, kept or reverted.

  evolve.py propose [--days 30] [--grant PATH] [--json]
      Candidate experiments from the diagnosis, ranked by expected gain, at most one per target,
      within max-active. Strategy experiments wait while a fleet-wide one collects.
  evolve.py start --target alpha --lever method --hypothesis TEXT --commit HASH
                  [--metric yield-per-run-unit|review-quality] [--empty-runs N] [--by-person] [--grant PATH]
      Record the baseline (the last passing runs) and the revert command. Refused when max-active
      would be exceeded, or when the target is a small sample (fewer than
      levers.structural_min_runs runs) unless --by-person says the person made the change. The
      change itself is made and committed by the client before this runs.
  evolve.py status [ID] [--json]
      Treatment runs collected so far, and runs remaining.
  evolve.py verdict [ID] [--dry-run] [--json]
      For each experiment with its treatment runs in: keep, revert or extend, by the grant's
      keep-if rule, and the exact git command. evolve.py never runs git; the client does.

Metrics:
  yield-per-run-unit   points per run-unit (yield.py), survivors = opportunities scored after the
                       five hard filters. Keep if the delta clears keep-if and survivors are not fewer.
  review-quality       for a persona or runner skill change: share of high ratings backed by a
                       sourced fact, reversal rate at later full review, searches per job, from
                       OTTO_HOME/yield/reviews.jsonl. Keep if quality rose and searches did not.

Records share OTTO_HOME/experiments/ with experiment.py and carry family "steward". Exit code 0 always.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_common as xc  # noqa: E402
import otto_common as oc  # noqa: E402
import steward  # noqa: E402

FAMILY = "steward"
ACTIVE = ("collecting", "extended")
EXPERIMENT_LEVERS = ("method", "gates", "skills")
METRICS = ("yield-per-run-unit", "review-quality")
FLEET_TARGET = "fleet"
LEAK_WEIGHT = {"source": 1.0, "triage": 0.8, "judgment": 0.6, "review": 0.7}


def _y():
    return steward.load_script("yield")


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now().astimezone()


def records(home: Path) -> List[Tuple[Path, Dict[str, Any]]]:
    return list(xc.iter_records(home, FAMILY))


def active(home: Path) -> List[Dict[str, Any]]:
    return [r for _, r in records(home) if r.get("status") in ACTIVE]


def _is_fleet(rec: Dict[str, Any]) -> bool:
    return rec.get("scope") == "fleet"


def _settings(g: "steward.Grant") -> Dict[str, Any]:
    r = g.rules.get("experiment") or {}
    keep_if = str(g.experiment("keep-if", "") or "")
    m = re.search(r"delta\s*>\s*\+?\s*(\d+(?:\.\d+)?)\s*%", keep_if)
    keep_delta = float(m.group(1)) if m else float(r.get("keep_delta_percent", 10))
    survivors = ("survivors not fewer" in keep_if) if keep_if else bool(r.get("survivors_not_fewer", True))
    def num(key: str, default: int) -> int:
        try:
            return max(1, int(g.experiment(key, default)))
        except (TypeError, ValueError):
            return default
    return {"baseline_runs": num("baseline-runs", int(r.get("baseline_runs", 3))),
            "treatment_runs": num("treatment-runs", int(r.get("treatment_runs", 3))),
            "keep_delta_percent": keep_delta, "survivors_not_fewer": survivors,
            "higher_cost_percent": float(r.get("higher_cost_percent", 10)), "extend_runs": int(r.get("extend_runs", 2)),
            "on_fail": str(g.experiment("on-fail", "revert") or "revert"), "keep_if": keep_if or "delta > +%g%% and survivors not fewer" % keep_delta}


# --------------------------------------------------------------------------- measuring

def _passing_runs(home: Path, target: str, since: Optional[datetime] = None, until: Optional[datetime] = None) -> List[Dict[str, Any]]:
    rows = _y().read_runs(home, since=since, until=until, strategy=target)
    return [r for r in rows if not r.get("blocked")]


def _fleet_windows(home: Path, rec: Dict[str, Any], now: datetime) -> List[Tuple[datetime, datetime]]:
    """Windows in which a fleet-wide experiment was collecting, after this one started. Strategy
    treatment runs inside them are confounded and not counted."""
    out = []
    if _is_fleet(rec):
        return out
    st = oc.parse_when(rec["started"])
    for _, r in records(home):
        if not _is_fleet(r) or r["id"] == rec["id"]:
            continue
        a = oc.parse_when(r["started"])
        b = oc.parse_when(r["closed"]) if r.get("closed") else now
        if b > st:
            out.append((max(a, st), b))
    return out


def measure_yield(rows: List[Dict[str, Any]], outcomes: List[Dict[str, Any]], pts: Dict[str, Any]) -> Dict[str, Any]:
    """Yield per run-unit, survivors and run-units per run over a set of passing runs."""
    y = _y()
    slugs = {s: r.get("run") for r in rows for s in (r.get("slugs") or [])}
    pts_total = sum(y.row_points(r, pts) for r in rows)
    pts_total += sum(pts.get(e["event"], 0) for e in outcomes if e["slug"] in slugs and e["event"] not in ("scored", "at_floor"))
    units = sum(r.get("run_units") or 0 for r in rows)
    n = len(rows)
    return {"runs": n, "points": round(pts_total, 4), "run_units": round(units, 4),
            "yield_per_unit": round(pts_total / units, 4) if units else None,
            "survivors": sum(r.get("scored") or 0 for r in rows),
            "run_units_per_run": round(units / n, 4) if n else None,
            "first": rows[0]["ts"] if rows else None, "last": rows[-1]["ts"] if rows else None}


def measure_reviews(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    hi = sum(r.get("ratings_high") or 0 for r in rows)
    src = sum(r.get("ratings_high_sourced") or 0 for r in rows)
    rev = [r for r in rows if r.get("reversed") is not None]
    searches = [r["searches"] for r in rows if r.get("searches") is not None]
    return {"runs": len(rows), "sourced_share": round(src / float(hi), 4) if hi else None,
            "reversal_rate": round(sum(1 for r in rev if r["reversed"]) / float(len(rev)), 4) if rev else None,
            "searches_per_job": oc.median(searches) if searches else None,
            "first": rows[0]["ts"] if rows else None, "last": rows[-1]["ts"] if rows else None}


def _baseline(home: Path, target: str, metric: str, n: int, now: datetime, pts: Dict[str, Any]) -> Dict[str, Any]:
    if metric == "review-quality":
        rows = [r for r in _y().read_reviews(home) if oc.parse_when(r["ts"]) <= now]
        if target != FLEET_TARGET:
            rows = [r for r in rows if r.get("persona") == oc.slug(target)] or rows
        return measure_reviews(xc.last_n(rows, n))
    rows = xc.last_n(_passing_runs(home, target, until=now), n)
    return measure_yield(rows, _y().read_outcomes(home), pts)


def _treatment(home: Path, rec: Dict[str, Any], now: datetime, pts: Dict[str, Any]) -> Dict[str, Any]:
    st = oc.parse_when(rec["started"])
    need = rec["treatment"]["needed"]
    if rec["metric"] == "review-quality":
        rows = [r for r in _y().read_reviews(home, since=st) if oc.parse_when(r["ts"]) > st and oc.parse_when(r["ts"]) <= now]
        if rec["target"] != FLEET_TARGET:
            rows = [r for r in rows if r.get("persona") == rec["target"]] or rows
        m = measure_reviews(rows[:need])
    else:
        rows = [r for r in _passing_runs(home, rec["target"], until=now) if oc.parse_when(r["ts"]) > st]
        wins = _fleet_windows(home, rec, now)
        kept = [r for r in rows if not any(a <= oc.parse_when(r["ts"]) <= b for a, b in wins)]
        m = measure_yield(kept[:need], _y().read_outcomes(home), pts)
        m["confounded_runs_skipped"] = len(rows) - len(kept)
    m["needed"] = need
    return m


# --------------------------------------------------------------------------- verdict logic

def decide(rec: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """keep, revert or extend for an experiment whose treatment is complete. Pure."""
    b, t = rec["baseline"], rec["treatment"]
    ext_used = bool(rec.get("extended"))
    if rec["metric"] == "review-quality":
        ds = (t.get("sourced_share") or 0) - (b.get("sourced_share") or 0) if t.get("sourced_share") is not None and b.get("sourced_share") is not None else None
        dr = (b.get("reversal_rate") or 0) - (t.get("reversal_rate") or 0) if t.get("reversal_rate") is not None and b.get("reversal_rate") is not None else None
        sc = xc.change_percent(b.get("searches_per_job"), t.get("searches_per_job"))
        rose = any(x is not None and x > 0 for x in (ds, dr)) and not any(x is not None and x < 0 for x in (ds, dr))
        fell = any(x is not None and x < 0 for x in (ds, dr)) and not any(x is not None and x > 0 for x in (ds, dr))
        searches_up = sc is not None and sc > cfg["higher_cost_percent"]
        res = {"sourced_share_delta": None if ds is None else round(ds, 4), "reversal_rate_drop": None if dr is None else round(dr, 4),
               "searches_change_percent": sc}
        if rose and not searches_up:
            return dict(res, verdict="keep", why="review quality rose and searches per job did not")
        if fell or searches_up:
            return dict(res, verdict="revert", why="review quality fell" if fell else "searches per job rose %s%%" % sc)
        if not ext_used:
            return dict(res, verdict="extend", why="no clear change at equal cost; extend by %d jobs once" % cfg["extend_runs"])
        return dict(res, verdict="revert", why="still inconclusive after the extension")
    by, ty = b.get("yield_per_unit"), t.get("yield_per_unit")
    if by in (None, 0):
        delta = None if (ty in (None, 0)) else float("inf")
    else:
        delta = xc.change_percent(by, ty if ty is not None else 0.0)
    cost = xc.change_percent(b.get("run_units_per_run"), t.get("run_units_per_run"))
    fewer = (t.get("survivors") or 0) < (b.get("survivors") or 0)
    res = {"delta_percent": None if delta is None else ("+inf" if delta == float("inf") else delta),
           "cost_change_percent": cost, "survivors": {"before": b.get("survivors"), "after": t.get("survivors")}}
    surv_ok = not (cfg["survivors_not_fewer"] and fewer)
    if delta is not None and delta > cfg["keep_delta_percent"] and surv_ok:
        return dict(res, verdict="keep", why="yield per run-unit %s and survivors not fewer" % ("rose from zero" if delta == float("inf") else "up %s%%" % delta))
    if (delta is not None and delta <= -cfg["keep_delta_percent"]) or not surv_ok:
        return dict(res, verdict="revert", why="survivors fell" if not surv_ok else "yield per run-unit down %s%%" % abs(delta))
    if cost is not None and cost > cfg["higher_cost_percent"]:
        return dict(res, verdict="revert", why="inconclusive at %s%% higher run-units" % cost)
    if not ext_used:
        return dict(res, verdict="extend", why="inconclusive at equal cost; extend by %d runs once" % cfg["extend_runs"])
    return dict(res, verdict="revert", why="still inconclusive after the extension")


def git_command(rec: Dict[str, Any], verdict: str) -> Optional[str]:
    return rec.get("revert") if verdict == "revert" else None


# --------------------------------------------------------------------------- commands

def start(home: Path, g: "steward.Grant", target: str, lever: str, hypothesis: str, commit: str,
          metric: Optional[str] = None, empty_runs: Optional[int] = None, now: Optional[datetime] = None,
          by_person: bool = False, days: int = 30) -> Dict[str, Any]:
    now = _now(now)
    cfg = _settings(g)
    lever = str(lever)
    if lever not in EXPERIMENT_LEVERS:
        return {"error": "lever %r is not an experiment lever (%s); nightly levers go through allocate.py" % (lever, ", ".join(EXPERIMENT_LEVERS))}
    commit = re.sub(r"[^0-9a-fA-F]", "", str(commit or ""))[:40]
    if len(commit) < 7:
        return {"error": "--commit must be the hash of the commit that made the change (at least 7 hex characters)"}
    fleet = lever == "skills" or steward.ident(target).lower() == FLEET_TARGET
    target_s = FLEET_TARGET if (fleet and steward.ident(target).lower() in ("", FLEET_TARGET)) else steward.ident(target)
    metric = metric or ("review-quality" if lever == "skills" else "yield-per-run-unit")
    if metric not in METRICS:
        return {"error": "unknown metric %r (known: %s)" % (metric, ", ".join(METRICS))}
    blocked = max_active_violation(home, g, target_s, fleet)
    if blocked:
        return {"error": blocked}
    tentative = None
    if not fleet:
        # Rule 12: the same test the diagnosis uses. A small sample takes a structural change only
        # when the person made it.
        yrep = _y().report(home, days, now, g.rules)
        runs = int(((yrep["strategies"].get(target_s) or {}).get("runs")) or 0)
        ok_s, why_s = g.why_for(lever, runs)
        if not ok_s and why_s.startswith("tentative:"):
            if not by_person:
                return {"error": "%s for %s; pass --by-person if the person made this change" % (why_s, target_s)}
            tentative = why_s
    eid = xc.next_id(home, "exp-%s-%s" % (oc.slug(target_s), lever), now.strftime("%Y-%m-%d"))
    ok, why = g.why(lever)
    rec = {"id": eid, "family": FAMILY, "target": target_s, "lever": lever, "scope": "fleet" if fleet else "strategy",
           "metric": metric, "hypothesis": oc.short(hypothesis, 200), "change_commit": commit,
           "revert": "git revert --no-edit %s" % commit, "started": oc.iso(now), "status": "collecting",
           "baseline": _baseline(home, target_s, metric, cfg["baseline_runs"], now, g.rules.get("points") or {}),
           "treatment": {"runs": 0, "needed": cfg["treatment_runs"]}, "keep_if": cfg["keep_if"],
           "applied_under": "the person (--by-person)" if by_person else ("grant" if ok else "the person (%s)" % why)}
    if tentative:
        rec["tentative"] = tentative
    if not fleet:
        rec["funding"] = ("treatment runs are funded from the allocation reserve at the grant's searches max (%d per run), "
                          "not from other strategies" % g.bounds("searches")["max"])
    if isinstance(empty_runs, int):
        rec["restore"] = {"empty-runs-so-far": empty_runs}
    if rec["baseline"]["runs"] < cfg["baseline_runs"]:
        rec["warning"] = "only %d baseline runs of %d; the baseline is thin" % (rec["baseline"]["runs"], cfg["baseline_runs"])
    oc.write_json(xc.exp_dir(home) / (eid + ".json"), rec)
    return rec


def max_active_violation(home: Path, g: "steward.Grant", target: str, fleet: bool) -> Optional[str]:
    lim = g.max_active()
    act = active(home)
    if fleet:
        n = sum(1 for r in act if _is_fleet(r))
        if n >= lim["fleet-wide"]:
            return "max-active: %d fleet-wide experiment%s already collecting (limit %d)" % (n, "" if n == 1 else "s", lim["fleet-wide"])
        return None
    n = sum(1 for r in act if not _is_fleet(r) and r.get("target") == target)
    if n >= lim["per-strategy"]:
        return "max-active: %s already has %d experiment%s collecting (limit %d)" % (target, n, "" if n == 1 else "s", lim["per-strategy"])
    if any(_is_fleet(r) for r in act):
        return "a fleet-wide experiment is collecting; strategy experiments wait until it closes"
    return None


def status(home: Path, g: Optional["steward.Grant"] = None, eid: Optional[str] = None, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    g = g or steward.grant(None, home)
    now = _now(now)
    pts = g.rules.get("points") or {}
    fleet_on = any(_is_fleet(r) for r in active(home))
    out = []
    for _, rec in records(home):
        if eid and rec.get("id") != eid:
            continue
        if rec.get("status") in ACTIVE:
            rec = dict(rec)
            rec["treatment"] = _treatment(home, rec, now, pts)
            rec["remaining"] = max(0, rec["treatment"]["needed"] - rec["treatment"]["runs"])
            if not _is_fleet(rec) and fleet_on:
                rec["paused"] = "a fleet-wide experiment is collecting; runs in its window are not counted"
        out.append(rec)
    return out


def verdict(home: Path, g: Optional["steward.Grant"] = None, eid: Optional[str] = None, now: Optional[datetime] = None,
            write: bool = True) -> List[Dict[str, Any]]:
    g = g or steward.grant(None, home)
    now = _now(now)
    cfg = _settings(g)
    pts = g.rules.get("points") or {}
    out = []
    for path, rec in records(home):
        if eid and rec.get("id") != eid:
            continue
        if rec.get("status") not in ACTIVE:
            continue
        t = _treatment(home, rec, now, pts)
        if t["runs"] < t["needed"]:
            continue
        rec["treatment"] = t
        d = decide(rec, cfg)
        small, caveat = xc.sample_caveat((rec["baseline"].get("runs") or 0) + t["runs"])
        item = {"id": rec["id"], "target": rec["target"], "lever": rec["lever"], "verdict": d["verdict"], "why": d["why"],
                "result": {k: v for k, v in d.items() if k not in ("verdict", "why")}, "git": git_command(rec, d["verdict"]),
                "restore": rec.get("restore") if d["verdict"] == "revert" else None, "small_sample": small, "caveat": caveat,
                "label": "MEASURED counts over %d plus %d runs" % (rec["baseline"].get("runs") or 0, t["runs"])}
        if write:
            if d["verdict"] == "extend":
                rec["extended"] = True
                rec["status"] = "extended"
                rec["treatment"] = {"runs": t["runs"], "needed": t["needed"] + cfg["extend_runs"]}
            else:
                rec["status"] = "kept" if d["verdict"] == "keep" else "reverted"
                rec["closed"] = oc.iso(now)
            rec["verdict"] = d["verdict"]
            rec["verdict_why"] = d["why"]
            rec["result"] = item["result"]
            oc.write_json(path, rec)
        out.append(item)
    return out


def propose(home: Path, g: Optional["steward.Grant"] = None, now: Optional[datetime] = None, days: int = 30,
            diagnosis: Optional[Dict[str, Any]] = None, settings_path: Optional[str] = None) -> Dict[str, Any]:
    g = g or steward.grant(None, home)
    d = diagnosis or steward.load_script("diagnose").report(home, days, now, g, settings_path=settings_path)
    yrep = steward.load_script("yield").report(home, days, now, g.rules)
    med = yrep.get("fleet_median_yield_per_unit") or 0.0
    lim = g.max_active()
    act = active(home)
    fleet_active = sum(1 for r in act if _is_fleet(r))
    busy = {r["target"] for r in act if not _is_fleet(r)}
    cands: List[Dict[str, Any]] = []
    held: List[Dict[str, Any]] = []
    review_targets: List[str] = []
    new_strategy: List[Dict[str, Any]] = []
    for name, dg in d["strategies"].items():
        s = yrep["strategies"].get(name) or {}
        for a in dg["actions"]:
            if a["lever"] == "propose-strategy":
                new_strategy.append({"from": name, "why": a["change"], "leak": dg["leak"]})
                continue
            if a["lever"] not in EXPERIMENT_LEVERS:
                continue
            if a["lever"] == "skills":
                review_targets.append(name)
                continue
            gap = max(0.0, med - (s.get("smoothed_yield") or 0.0))
            gain = round(LEAK_WEIGHT.get(dg["leak"], 0.5) * (gap + 0.01) * max(1, s.get("runs") or 0) / 7.0, 4)
            c = {"target": name, "lever": a["lever"], "scope": "strategy", "leak": dg["leak"], "change": a["change"],
                 "expected_gain": gain, "allowed": a["allowed"], "grant": a["grant"], "tentative": dg["tentative"],
                 "metric": "yield-per-run-unit"}
            cands.append(c)
    if review_targets:
        gain = round(LEAK_WEIGHT["review"] * len(review_targets) * (med + 0.01), 4)
        ok, why = g.why("skills")
        cands.append({"target": FLEET_TARGET, "lever": "skills", "scope": "fleet", "leak": "review",
                      "change": "the reviewing persona's wording, from the kills in %s" % ", ".join(sorted(review_targets)),
                      "expected_gain": gain, "allowed": ok, "grant": why, "tentative": False, "metric": "review-quality"})
    # Tentative candidates (small sample, or any lever the grant does not let apply on this
    # strategy yet) never enter the actionable list.
    small = [dict(c, allowed=False) for c in cands if c["tentative"] or str(c.get("grant", "")).startswith("tentative:")]
    cands = [c for c in cands if not (c["tentative"] or str(c.get("grant", "")).startswith("tentative:"))]
    small.sort(key=lambda c: (-c["expected_gain"], c["target"]))
    cands.sort(key=lambda c: (-c["expected_gain"], c["target"]))
    picked: List[Dict[str, Any]] = []
    seen = set()
    fleet_slots = lim["fleet-wide"] - fleet_active
    for c in cands:
        if c["target"] in seen:
            continue
        if c["scope"] == "fleet":
            if fleet_slots <= 0:
                held.append(dict(c, held="max-active fleet-wide reached"))
                continue
            fleet_slots -= 1
        else:
            if fleet_active:
                held.append(dict(c, held="a fleet-wide experiment is collecting"))
                continue
            if c["target"] in busy and lim["per-strategy"] <= sum(1 for r in act if r.get("target") == c["target"]):
                held.append(dict(c, held="already has an experiment collecting"))
                continue
        seen.add(c["target"])
        picked.append(c)
    # a fleet-wide pick holds every strategy pick behind it this week
    if any(c["scope"] == "fleet" for c in picked):
        first_fleet = next(i for i, c in enumerate(picked) if c["scope"] == "fleet")
        if first_fleet == 0:
            held.extend(dict(c, held="waits behind the fleet-wide experiment") for c in picked[1:] if c["scope"] != "fleet")
            picked = [c for c in picked if c["scope"] == "fleet"]
        else:
            held.append(dict(picked[first_fleet], held="ranked below strategy experiments; runs after them"))
            picked = [c for c in picked if c["scope"] != "fleet"]
    # At most two new-strategy proposals at a time; the strongest evidence first (failed method
    # experiments, then over-performance).
    new_strategy.sort(key=lambda x: (x["leak"] != "source", x["from"]))
    return {"mode": g.mode, "candidates": picked, "held": held, "propose_strategy": new_strategy[:2],
            "small_sample": small, "skipped": dict(d.get("skipped") or {}),
            "label": "expected_gain is an ESTIMATE used for ranking only; nothing here is measured",
            "next": "for each candidate the client writes the change, commits it, then runs evolve.py start with the hash"}


# --------------------------------------------------------------------------- rendering

def render_status(items: List[Dict[str, Any]]) -> str:
    act = [r for r in items if r.get("status") in ACTIVE]
    if not act:
        return "Experiments: none collecting."
    L = ["Experiments collecting:"]
    for r in act:
        L.append("  %s [%s] %s %s: %d of %d runs, %d remaining%s" % (r["id"], r["metric"], r["target"], r["lever"], r["treatment"]["runs"],
                                                                     r["treatment"]["needed"], r["remaining"], (" (%s)" % r["paused"]) if r.get("paused") else ""))
    return "\n".join(L)


def render_verdicts(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "Verdicts: none due."
    L = ["Verdicts:"]
    for v in items:
        L.append("  %s: %s (%s)%s" % (v["id"], v["verdict"], v["why"], (" [%s]" % v["caveat"]) if v.get("caveat") else ""))
        if v.get("git"):
            L.append("    run: %s" % v["git"])
        if v.get("restore"):
            L.append("    restore: %s" % json.dumps(v["restore"]))
    return "\n".join(L)


def render_proposals(p: Dict[str, Any]) -> str:
    L = ["Proposed experiments (%s mode; %s):" % (p["mode"], p["label"])]
    if not p["candidates"]:
        L.append("  none")
    for c in p["candidates"]:
        L.append("  %s %s (%s leak): %s, gain %.3f [%s]%s" % (c["target"], c["lever"], c["leak"], c["change"], c["expected_gain"],
                                                         "apply" if c["allowed"] else "propose", " (tentative)" if c["tentative"] else ""))
    for h in p["held"]:
        L.append("  held: %s %s, %s" % (h["target"], h["lever"], h["held"]))
    if p.get("small_sample"):
        L.append("Proposals (small sample), for the person only:")
        for c in p["small_sample"]:
            L.append("  %s %s (%s leak): %s [propose: %s]" % (c["target"], c["lever"], c["leak"], c["change"], c.get("grant") or "tentative"))
    for name, why in sorted((p.get("skipped") or {}).items()):
        L.append("  skipped: %s, %s" % (name, why))
    for s in p["propose_strategy"]:
        L.append("  for the person: new strategy from %s (%s)" % (s["from"], s["why"]))
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    common = steward.common_flags()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose", parents=[common]); p.add_argument("--days", type=int, default=30); p.add_argument("--settings")
    s = sub.add_parser("start", parents=[common])
    s.add_argument("--target", required=True); s.add_argument("--lever", required=True, choices=EXPERIMENT_LEVERS)
    s.add_argument("--hypothesis", required=True); s.add_argument("--commit", required=True)
    s.add_argument("--metric", choices=METRICS); s.add_argument("--empty-runs", type=int)
    s.add_argument("--by-person", action="store_true", help="the person made this change; allowed on a small sample")
    st = sub.add_parser("status", parents=[common]); st.add_argument("id", nargs="?")
    v = sub.add_parser("verdict", parents=[common]); v.add_argument("id", nargs="?"); v.add_argument("--dry-run", action="store_true")
    args = steward.parse_args(ap, argv)
    if args is None:
        return 0
    try:
        home = Path(args.home).expanduser() if args.home else oc.otto_home()
        g = steward.grant(args.grant, home)
        now = oc.parse_when(args.now) if args.now else None
        if args.cmd == "propose":
            rep: Any = propose(home, g, now, args.days, settings_path=args.settings)
            text = render_proposals(rep)
        elif args.cmd == "start":
            rep = start(home, g, args.target, args.lever, args.hypothesis, args.commit, args.metric, args.empty_runs, now,
                        by_person=args.by_person)
            text = ("refused: " + rep["error"]) if rep.get("error") else "recorded %s. Baseline: %s. Revert with: %s" % (
                rep["id"], json.dumps(rep["baseline"], sort_keys=True), rep["revert"])
        elif args.cmd == "status":
            rep = status(home, g, args.id, now)
            text = render_status(rep)
        else:
            rep = verdict(home, g, args.id, now, write=not args.dry_run)
            text = render_verdicts(rep)
        print(json.dumps(rep, indent=2, default=str) if args.json else text)
    except Exception as e:  # fail open
        oc.log_error("evolve: %s" % e)
        oc.eprint("evolve: %s (logged; nothing was changed)" % oc.short(e, 200))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
