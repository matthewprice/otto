#!/usr/bin/env python3
"""Measure a change instead of hoping. One change, one automation, a before and an after.

  experiment.py estimate NAME [--model M] [--cadence daily|weekdays|weekly] [--max-turns N]
      Project the cost of a change from the job's own token mix and the dated list prices in
      prices.json. ESTIMATE, always. Says when history is too thin and a dry run would be better.
  experiment.py start NAME --change "text" [--kind model|effort|description|cap|other] [--runs 3]
      Record the hypothesis and a baseline from the last passing runs, then print the change for
      you to apply. Otto applies nothing.
  experiment.py status [ID]
      Collect passing runs since the start; at --runs on each side, report medians, the delta and a
      verdict, with the small-sample caveat under seven runs in total.
  experiment.py list

State lives in ~/.otto/experiments/<id>.json. Each start is also recorded with retro.py so the
weekly retro shows it.
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
import retro  # noqa: E402

PRICES = Path(__file__).resolve().parent / "prices.json"
CADENCE_RUNS = {"daily": 7, "weekdays": 5, "weekly": 1}


def exp_dir(home: Path) -> Path:
    d = home / "experiments"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _passing(home: Path, name: str, since: Optional[datetime] = None, until: Optional[datetime] = None) -> List[Dict[str, Any]]:
    rows = ledger.read_rows(home, since=since, until=until, automation=oc.slug(name), kind="run")
    return [r for r in rows if health.row_outcome(r) == "pass"]


def _medians(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    def med(key, scale=1.0):
        xs = [r[key] * scale for r in rows if r.get(key) is not None]
        return round(oc.median(xs), 4) if xs else None
    toks = [sum((r.get("tokens") or {}).values()) for r in rows if r.get("tokens")]
    return {"runs": len(rows), "cost_usd": med("cost_usd"), "duration_min": med("duration_ms", 1 / 60000.0),
            "num_turns": med("num_turns"), "tokens": int(oc.median(toks)) if toks else None,
            "first": rows[0].get("ts") if rows else None, "last": rows[-1].get("ts") if rows else None}


# --------------------------------------------------------------------------- estimate

def load_prices() -> Dict[str, Any]:
    return oc.read_json(PRICES, {"as_of": "unknown", "per_mtok": {}, "aliases": {}})


def _resolve_model(prices: Dict[str, Any], name: str) -> Optional[str]:
    if name in prices["per_mtok"]:
        return name
    return prices.get("aliases", {}).get(name.lower())


def _token_mix(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_model: Dict[str, Dict[str, List[int]]] = {}
    for r in rows:
        for m, v in (r.get("models") or {}).items():
            slot = by_model.setdefault(m, {k: [] for k in ledger.TOKEN_KEYS})
            for k in ledger.TOKEN_KEYS:
                slot[k].append(int(v.get(k, 0)))
    mix = {m: {k: int(oc.median(xs) or 0) for k, xs in v.items()} for m, v in by_model.items()}
    dominant = max(mix, key=lambda m: sum(mix[m].values())) if mix else None
    return {"per_run": mix, "dominant": dominant}


def _price_run(mix: Dict[str, Dict[str, int]], prices: Dict[str, Any], swap: Optional[Dict[str, str]] = None) -> Optional[float]:
    total = 0.0
    for m, toks in mix.items():
        target = (swap or {}).get(m, m)
        p = prices["per_mtok"].get(target)
        if not p:
            return None
        total += sum(toks[k] * p[{"input": "input", "output": "output", "cache_read": "cache_read", "cache_create": "cache_write"}[k]] for k in ledger.TOKEN_KEYS) / 1e6
    return round(total, 4)


def estimate(home: Path, name: str, model: Optional[str] = None, cadence: Optional[str] = None, max_turns: Optional[int] = None,
             now: Optional[datetime] = None) -> Dict[str, Any]:
    cfg = oc.load_config(home)
    now = now or oc.parse_when(None, oc.get_tz(cfg.get("timezone")))
    prices = load_prices()
    rows = _passing(home, name, since=now - timedelta(days=60))[-14:]
    out: Dict[str, Any] = {"automation": oc.slug(name), "label": "ESTIMATE", "prices_as_of": prices.get("as_of"), "sample_runs": len(rows)}
    if len(rows) < 3:
        out["thin"] = True
        out["advice"] = "fewer than 3 passing runs in the ledger; a one-off dry run under the proposed setting would measure this instead"
    base = _medians(rows)
    out["baseline"] = base
    mix = _token_mix(rows)
    out["token_mix_per_run"] = mix["per_run"]
    current_price = _price_run(mix["per_run"], prices) if mix["per_run"] else None
    out["priced_current_usd"] = current_price
    reported = base.get("cost_usd")
    scale = (reported / current_price) if (reported and current_price) else 1.0
    autos, _ = health.load_registry(home, cfg)
    a = next((x for x in autos if x["name"] == oc.slug(name)), None)
    cur_runs_week = len(health.normalize_days(a.get("days"))) if a else 7
    per_run = reported or current_price
    if model:
        target = _resolve_model(prices, model)
        if not target:
            out["error"] = "no price for model %r in prices.json (known: %s)" % (model, ", ".join(sorted(prices["per_mtok"])))
            return out
        if not mix["per_run"]:
            out["error"] = "no per-model token mix in the ledger for this automation yet"
            return out
        swap = {m: target for m in mix["per_run"]}
        priced_target = _price_run(mix["per_run"], prices, swap)
        projected = round(priced_target * scale, 4) if priced_target is not None else None
        out["model_change"] = {"from": mix["dominant"], "to": target, "priced_target_usd": priced_target, "projected_per_run_usd": projected,
                               "assumes": "the same token mix per run; a different model may use more or fewer turns, which this cannot see"}
        per_run = projected or per_run
    if max_turns and base.get("num_turns"):
        ratio = min(1.0, max_turns / float(base["num_turns"]))
        out["turn_cap"] = {"to": max_turns, "median_turns_now": base["num_turns"], "projected_per_run_usd": round((per_run or 0) * ratio, 4),
                           "assumes": "cost scales with turns and the job still finishes inside the cap; it may instead fail at the cap"}
        per_run = out["turn_cap"]["projected_per_run_usd"]
    runs_week = CADENCE_RUNS.get(cadence or "", cur_runs_week)
    out["weekly"] = {"runs_now": cur_runs_week, "runs_after": runs_week, "now_usd": round((reported or 0) * cur_runs_week, 2),
                     "after_usd": round((per_run or 0) * runs_week, 2)}
    out["basis"] = "Reported cost is Claude Code's client-side estimate; the price table is dated %s and may be stale. Nothing here is a measurement." % prices.get("as_of")
    return out


# --------------------------------------------------------------------------- start / status

def start(home: Path, name: str, change: str, kind: str = "other", runs: int = 3, now: Optional[datetime] = None) -> Dict[str, Any]:
    cfg = oc.load_config(home)
    now = now or oc.parse_when(None, oc.get_tz(cfg.get("timezone")))
    name = oc.slug(name)
    before = _passing(home, name, since=now - timedelta(days=60), until=now)[-max(runs, 7):]
    n = len(list(exp_dir(home).glob(name + "-*.json"))) + 1
    eid = "%s-%s-%d" % (name, now.strftime("%Y%m%d"), n)
    rec = {"id": eid, "automation": name, "change": oc.short(change, 200), "kind": oc.short(kind, 32), "runs_needed": int(runs),
           "started": oc.iso(now), "status": "collecting", "baseline": _medians(before),
           "note": "Apply the change yourself. Otto records; it does not apply."}
    if len(before) < runs:
        rec["warning"] = "only %d passing runs before the change; the baseline is thin" % len(before)
    oc.write_json(exp_dir(home) / (eid + ".json"), rec)
    retro.record_change(home, name, "experiment %s: %s" % (eid, change), oc.iso(now), kind)
    return rec


def status(home: Path, eid: Optional[str] = None, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    cfg = oc.load_config(home)
    now = now or oc.parse_when(None, oc.get_tz(cfg.get("timezone")))
    out = []
    for p in sorted(exp_dir(home).glob("*.json")):
        rec = oc.read_json(p, None)
        if not rec or (eid and rec.get("id") != eid):
            continue
        started = oc.parse_when(rec["started"], now.tzinfo)
        after_all = _passing(home, rec["automation"], since=started, until=now)
        after = after_all[:rec["runs_needed"]]
        fails = [r for r in ledger.read_rows(home, since=started, until=now, automation=rec["automation"], kind="run") if health.row_outcome(r) == "fail"]
        rec["after"] = _medians(after)
        rec["failed_runs_after"] = len(fails)
        b, a = rec["baseline"], rec["after"]
        if a["runs"] >= rec["runs_needed"] and b["runs"] >= 1:
            res: Dict[str, Any] = {}
            for key in ("cost_usd", "duration_min", "tokens"):
                if b.get(key) and a.get(key) is not None:
                    res[key] = {"before": b[key], "after": a[key], "change_percent": round((a[key] / b[key] - 1) * 100)}
            cp = (res.get("cost_usd") or {}).get("change_percent")
            if cp is None:
                verdict = "inconclusive: no cost on one side"
            elif len(fails) > 0 and cp <= -10:
                verdict = "cheaper but %d run%s failed after the change; not a saving yet" % (len(fails), "" if len(fails) == 1 else "s")
            elif cp <= -10:
                verdict = "pays: median cost down %d%%" % -cp
            elif cp >= 10:
                verdict = "does not pay: median cost up %d%%" % cp
            else:
                verdict = "inconclusive: within 10%"
            total = b["runs"] + a["runs"]
            rec.update({"result": res, "verdict": verdict, "status": "done", "small_sample": total < 7,
                        "caveat": ("%d runs in total is a small sample" % total) if total < 7 else None})
            oc.write_json(p, rec)
        else:
            rec["waiting"] = "%d of %d passing runs after the change" % (a["runs"], rec["runs_needed"])
        out.append(rec)
    return out


def render(items: Any) -> str:
    if isinstance(items, dict):
        d = items
        if "weekly" in d:
            L = ["Estimate for %s (%s, prices as of %s, %d sample runs)" % (d["automation"], d["label"], d["prices_as_of"], d["sample_runs"])]
            if d.get("error"):
                return L[0] + "\n  " + d["error"]
            if d.get("advice"):
                L.append("  " + d["advice"])
            b = d["baseline"]
            L.append("  now: median $%s per run, %s runs a week = $%.2f" % (b.get("cost_usd"), d["weekly"]["runs_now"], d["weekly"]["now_usd"]))
            if d.get("model_change"):
                m = d["model_change"]
                L.append("  model %s -> %s: about $%s per run (%s)" % (m["from"], m["to"], m["projected_per_run_usd"], m["assumes"]))
            if d.get("turn_cap"):
                t = d["turn_cap"]
                L.append("  max_turns %s (median now %s): about $%s per run (%s)" % (t["to"], t["median_turns_now"], t["projected_per_run_usd"], t["assumes"]))
            L.append("  after: about $%.2f a week over %s runs" % (d["weekly"]["after_usd"], d["weekly"]["runs_after"]))
            L.append("  " + d["basis"])
            return "\n".join(L)
        return json.dumps(d, indent=2)
    L = []
    for r in items:
        L.append("%s [%s] %s: %s" % (r["id"], r["status"], r["automation"], r["change"]))
        if r.get("waiting"):
            L.append("  waiting: " + r["waiting"])
        if r.get("verdict"):
            L.append("  verdict: " + r["verdict"] + ((" (%s)" % r["caveat"]) if r.get("caveat") else ""))
            for k, v in (r.get("result") or {}).items():
                L.append("  %s: %s -> %s (%+d%%)" % (k, v["before"], v["after"], v["change_percent"]))
    return "\n".join(L) if L else "(no experiments)"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home"); ap.add_argument("--now"); ap.add_argument("--json", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("estimate"); e.add_argument("name"); e.add_argument("--model"); e.add_argument("--cadence", choices=sorted(CADENCE_RUNS)); e.add_argument("--max-turns", type=int)
    s = sub.add_parser("start"); s.add_argument("name"); s.add_argument("--change", required=True); s.add_argument("--kind", default="other"); s.add_argument("--runs", type=int, default=3)
    st = sub.add_parser("status"); st.add_argument("id", nargs="?")
    sub.add_parser("list")
    args = ap.parse_args(argv)
    home = Path(args.home).expanduser() if args.home else oc.otto_home()
    now = oc.parse_when(args.now) if args.now else None
    if args.cmd == "estimate":
        rep: Any = estimate(home, args.name, args.model, args.cadence, args.max_turns, now)
    elif args.cmd == "start":
        rep = start(home, args.name, args.change, args.kind, args.runs, now)
        if not args.json:
            print("recorded %s. Baseline: %s. Now apply the change: %s" % (rep["id"], json.dumps(rep["baseline"]), rep["change"]))
            return 0
    else:
        rep = status(home, getattr(args, "id", None), now)
    print(json.dumps(rep, indent=2) if args.json else render(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
