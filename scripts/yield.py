#!/usr/bin/env python3
"""The yield ledger: what each discovery strategy run cost and what it produced.

  yield.py ingest ROWS.jsonl          upsert validated run rows into OTTO_HOME/yield/YYYY-MM.jsonl
  yield.py outcomes EVENTS.jsonl      upsert later outcome events into OTTO_HOME/yield/outcomes.jsonl
  yield.py reviews ROWS.jsonl         upsert review-quality rows into OTTO_HOME/yield/reviews.jsonl
  yield.py report [--days 30] [--json] [--grant PATH]
      Per strategy: the funnel, points, points per 100 searches, points per run-unit, runs,
      smoothed yield, and a small-sample flag. Blocked runs are excluded and counted apart.

A run row is keyed by (strategy, run); an outcome by (slug, event); a review row by (job, ts). Re-
ingesting the same rows changes nothing, so a client can rebuild every night.

Rows are an allowlist of numbers and short labels. Free text is dropped, except `notes` (120
characters) and the strategy and opportunity slugs. The points table is in steward_rules.json and a
grant may override it with a `metric-points:` block.

Exit code 0 always: an unreadable row is skipped and counted, never fatal.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import otto_common as oc  # noqa: E402
import steward  # noqa: E402

RUN_INT_KEYS = ("run", "searches", "examined", "candidates", "prescreen_pass", "scored", "at_floor")
RUN_KEYS = set(RUN_INT_KEYS) | {"ts", "strategy", "model", "stages", "run_units", "run_units_label",
                                "dropped", "best_score", "slugs", "blocked", "notes"}
EVENTS = ("scored", "at_floor", "top20", "keep", "kill", "archived")
OUTCOME_KEYS = {"ts", "slug", "event", "strategy", "score"}
REVIEW_KEYS = {"ts", "job", "persona", "ratings_high", "ratings_high_sourced", "reversed", "searches"}
LABELS = ("MEASURED", "ESTIMATE")
MAX_SLUGS = 50
MAX_DROP_KEYS = 24


# --------------------------------------------------------------------------- paths and files

def yield_dir(home: Optional[Path] = None) -> Path:
    return (home or oc.otto_home()) / "yield"


def outcomes_path(home: Optional[Path] = None) -> Path:
    return yield_dir(home) / "outcomes.jsonl"


def reviews_path(home: Optional[Path] = None) -> Path:
    return yield_dir(home) / "reviews.jsonl"


def _read_jsonl(p: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not p.exists():
        return out
    with open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if isinstance(o, dict):
                out.append(o)
    return out


def _write_jsonl(p: Path, rows: Iterable[Dict[str, Any]]) -> None:
    oc.atomic_write(p, "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def _lock(home: Path):
    return oc.file_lock(oc.state_dir(home) / "yield.lock")


# --------------------------------------------------------------------------- validation

def _int(v: Any) -> Optional[int]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _float(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ts(v: Any) -> Optional[str]:
    try:
        return oc.iso(oc.parse_when(str(v)))
    except (ValueError, TypeError):
        return None


def sanitize_run(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate one run row. None when the row lacks ts, strategy or run."""
    if not isinstance(row, dict):
        return None
    ts, strat, run = _ts(row.get("ts")), steward.ident(row.get("strategy")), _int(row.get("run"))
    if not ts or not strat or run is None:
        return None
    r: Dict[str, Any] = {"ts": ts, "strategy": strat}
    for k in RUN_INT_KEYS:
        n = _int(row.get(k))
        if n is not None:
            r[k] = max(0, n)
    if row.get("model"):
        r["model"] = oc.slug(row["model"])[:32]
    if isinstance(row.get("stages"), dict):
        r["stages"] = {oc.slug(k)[:24]: oc.slug(v)[:32] for k, v in list(row["stages"].items())[:12] if k and v}
    u = _float(row.get("run_units"))
    if u is not None:
        r["run_units"] = round(max(0.0, u), 4)
    lab = str(row.get("run_units_label") or "ESTIMATE").upper()
    r["run_units_label"] = lab if lab in LABELS else "ESTIMATE"
    if isinstance(row.get("dropped"), dict):
        d = {}
        for k, v in list(row["dropped"].items())[:MAX_DROP_KEYS]:
            n = _int(v)
            if k and n is not None:
                d[oc.slug(k)[:32].replace("-", "_")] = max(0, n)
        r["dropped"] = d
    b = _float(row.get("best_score"))
    r["best_score"] = round(b, 2) if b is not None else None
    if isinstance(row.get("slugs"), list):
        r["slugs"] = [oc.slug(s) for s in row["slugs"][:MAX_SLUGS] if oc.slug(s)]
    r["blocked"] = bool(row.get("blocked")) if not isinstance(row.get("blocked"), str) else row["blocked"].lower() in ("true", "yes", "1")
    if row.get("notes"):
        r["notes"] = oc.short(row["notes"], 120)
    return r


def sanitize_outcome(ev: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(ev, dict):
        return None
    ts, sl, event = _ts(ev.get("ts")), oc.slug(ev.get("slug") or ""), str(ev.get("event") or "").strip().lower()
    if not ts or not sl or event not in EVENTS:
        return None
    o: Dict[str, Any] = {"ts": ts, "slug": sl, "event": event}
    if ev.get("strategy"):
        o["strategy"] = steward.ident(ev["strategy"])
    s = _float(ev.get("score"))
    if s is not None:
        o["score"] = round(s, 2)
    return o


def sanitize_review(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One persona review job, for the review-quality metric. Counts only."""
    if not isinstance(row, dict):
        return None
    ts, job = _ts(row.get("ts")), oc.slug(row.get("job") or "")
    if not ts or not job:
        return None
    r: Dict[str, Any] = {"ts": ts, "job": job}
    if row.get("persona"):
        r["persona"] = oc.slug(row["persona"])[:32]
    for k in ("ratings_high", "ratings_high_sourced", "searches"):
        n = _int(row.get(k))
        if n is not None:
            r[k] = max(0, n)
    if row.get("reversed") is not None:
        r["reversed"] = bool(row.get("reversed"))
    return r


# --------------------------------------------------------------------------- writing

def _load_input(path: str) -> Tuple[List[Dict[str, Any]], int]:
    p = Path(path).expanduser()
    if path == "-":
        lines = sys.stdin.read().splitlines()
    else:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    rows, bad = [], 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(o, list):
            rows.extend(x for x in o if isinstance(x, dict))
        elif isinstance(o, dict):
            rows.append(o)
        else:
            bad += 1
    return rows, bad


def _month_file(home: Path, ts: str) -> Path:
    d = oc.parse_when(ts)
    return yield_dir(home) / ("%04d-%02d.jsonl" % (d.year, d.month))


def ingest(home: Path, rows: List[Dict[str, Any]]) -> Dict[str, int]:
    oc.ensure_dirs(home)
    added = updated = skipped = 0
    with _lock(home):
        index: Dict[Tuple[str, int], Path] = {}
        for p in sorted(yield_dir(home).glob("[0-9][0-9][0-9][0-9]-[0-9][0-9].jsonl")):
            for r in _read_jsonl(p):
                if r.get("strategy") and r.get("run") is not None:
                    index[(r["strategy"], r["run"])] = p
        cache: Dict[Path, List[Dict[str, Any]]] = {}

        def rows_of(p: Path) -> List[Dict[str, Any]]:
            if p not in cache:
                cache[p] = _read_jsonl(p)
            return cache[p]
        for raw in rows:
            r = sanitize_run(raw)
            if not r:
                skipped += 1
                continue
            key = (r["strategy"], r["run"])
            if key in index:
                p = index[key]
                lst = rows_of(p)
                for i, ex in enumerate(lst):
                    if (ex.get("strategy"), ex.get("run")) == key:
                        lst[i] = r
                        break
                target = _month_file(home, r["ts"])
                if target != p:  # the run moved month; drop the old copy
                    cache[p] = [x for x in lst if (x.get("strategy"), x.get("run")) != key]
                    rows_of(target).append(r)
                    index[key] = target
                updated += 1
            else:
                p = _month_file(home, r["ts"])
                rows_of(p).append(r)
                index[key] = p
                added += 1
        for p, lst in cache.items():
            lst.sort(key=lambda x: (x.get("ts", ""), x.get("strategy", ""), x.get("run", 0)))
            _write_jsonl(p, lst)
    return {"added": added, "updated": updated, "skipped": skipped}


def _upsert_keyed(home: Path, path: Path, rows: List[Dict[str, Any]], clean, keyf) -> Dict[str, int]:
    oc.ensure_dirs(home)
    added = updated = skipped = 0
    with _lock(home):
        existing = _read_jsonl(path)
        pos = {keyf(r): i for i, r in enumerate(existing)}
        for raw in rows:
            r = clean(raw)
            if not r:
                skipped += 1
                continue
            k = keyf(r)
            if k in pos:
                existing[pos[k]] = r
                updated += 1
            else:
                pos[k] = len(existing)
                existing.append(r)
                added += 1
        existing.sort(key=lambda x: x.get("ts", ""))
        _write_jsonl(path, existing)
    return {"added": added, "updated": updated, "skipped": skipped}


def add_outcomes(home: Path, events: List[Dict[str, Any]]) -> Dict[str, int]:
    return _upsert_keyed(home, outcomes_path(home), events, sanitize_outcome, lambda o: (o["slug"], o["event"]))


def add_reviews(home: Path, rows: List[Dict[str, Any]]) -> Dict[str, int]:
    return _upsert_keyed(home, reviews_path(home), rows, sanitize_review, lambda r: (r["job"], r["ts"]))


# --------------------------------------------------------------------------- reading

def read_runs(home: Path, since: Optional[datetime] = None, until: Optional[datetime] = None,
              strategy: Optional[str] = None) -> List[Dict[str, Any]]:
    out = []
    d = yield_dir(home)
    if not d.exists():
        return out
    for p in sorted(d.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9].jsonl")):
        for r in _read_jsonl(p):
            if strategy and r.get("strategy") != steward.ident(strategy):
                continue
            try:
                t = oc.parse_when(r.get("ts"))
            except (ValueError, TypeError):
                continue
            if since and t < since:
                continue
            if until and t > until:
                continue
            out.append(r)
    out.sort(key=lambda r: (oc.parse_when(r["ts"]), r.get("run", 0)))
    return out


def read_outcomes(home: Path) -> List[Dict[str, Any]]:
    return _read_jsonl(outcomes_path(home))


def read_reviews(home: Path, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
    rows = _read_jsonl(reviews_path(home))
    if since:
        rows = [r for r in rows if oc.parse_when(r["ts"]) >= since]
    rows.sort(key=lambda r: oc.parse_when(r["ts"]))
    return rows


# --------------------------------------------------------------------------- the math

def default_rules() -> Dict[str, Any]:
    return steward.load_rules()


def row_points(r: Dict[str, Any], pts: Dict[str, Any]) -> float:
    """Points a run earns on its own: scored and at-floor counts. Lagged outcomes add to this."""
    return (r.get("scored") or 0) * pts.get("scored", 1) + (r.get("at_floor") or 0) * pts.get("at_floor", 3)


def outcome_points(events: List[Dict[str, Any]], pts: Dict[str, Any]) -> float:
    return sum(pts.get(e["event"], 0) for e in events if e["event"] not in ("scored", "at_floor"))


def _slug_owner(runs: List[Dict[str, Any]]) -> Dict[str, Tuple[str, int]]:
    own: Dict[str, Tuple[str, int]] = {}
    for r in runs:
        for s in r.get("slugs") or []:
            own.setdefault(s, (r["strategy"], r.get("run", 0)))
    return own


def per_run_yield(runs: List[Dict[str, Any]], outcomes_by_run: Dict[Tuple[str, int], List[Dict[str, Any]]],
                  pts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Points and points per run-unit for each passing run, outcomes credited to the run that found the slug."""
    out = []
    for r in runs:
        if r.get("blocked"):
            continue
        p = row_points(r, pts) + outcome_points(outcomes_by_run.get((r["strategy"], r.get("run", 0)), []), pts)
        u = r.get("run_units") or 0
        out.append({"run": r.get("run"), "ts": r["ts"], "points": p, "per_unit": (p / u) if u else None})
    return out


def report(home: Path, days: int = 30, now: Optional[datetime] = None, rules: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    rules = rules or default_rules()
    pts = rules.get("points") or {}
    k = int(rules.get("smoothing_runs", 3))
    small_n = int(rules.get("small_sample_runs", 7))
    frac = float(rules.get("below_median_fraction", 0.25))
    now = now or datetime.now().astimezone()
    since = now - timedelta(days=days)
    runs = read_runs(home, since=since, until=now)
    events = read_outcomes(home)
    owner = _slug_owner(read_runs(home, until=now))
    window_slugs = {s for r in runs for s in (r.get("slugs") or [])}

    by_strat: Dict[str, Dict[str, Any]] = {}
    outcomes_by_run: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for r in runs:
        by_strat.setdefault(r["strategy"], {"rows": [], "events": []})["rows"].append(r)
    unattributed = 0
    for e in events:
        try:
            t = oc.parse_when(e["ts"])
        except (ValueError, TypeError, KeyError):
            continue
        if t > now:
            continue
        if not (t >= since or e["slug"] in window_slugs):
            continue
        strat = e.get("strategy") or (owner.get(e["slug"]) or (None,))[0]
        if not strat:
            unattributed += 1
            continue
        by_strat.setdefault(strat, {"rows": [], "events": []})["events"].append(e)
        if e["slug"] in owner and owner[e["slug"]][0] == strat:
            outcomes_by_run.setdefault(owner[e["slug"]], []).append(e)

    strategies: Dict[str, Dict[str, Any]] = {}
    for name, d in by_strat.items():
        rows = d["rows"]
        passing = [r for r in rows if not r.get("blocked")]
        blocked = len(rows) - len(passing)
        f = {key: sum(r.get(key) or 0 for r in passing) for key in ("searches", "examined", "candidates", "prescreen_pass", "scored", "at_floor")}
        ev = d["events"]
        ev_slugs = {e2: {e["slug"] for e in ev if e["event"] == e2} for e2 in EVENTS}
        # Run rows and outcome events are two views of scored and at-floor; the larger wins so nothing counts twice.
        scored = max(f["scored"], len(ev_slugs["scored"]))
        at_floor = max(f["at_floor"], len(ev_slugs["at_floor"]))
        drops: Dict[str, int] = {}
        for r in passing:
            for key, v in (r.get("dropped") or {}).items():
                drops[key] = drops.get(key, 0) + v
        points = (scored * pts.get("scored", 1) + at_floor * pts.get("at_floor", 3) +
                  sum(len(ev_slugs[e2]) * pts.get(e2, 0) for e2 in ("top20", "keep", "kill", "archived")))
        units = round(sum(r.get("run_units") or 0 for r in passing), 4)
        labels = {r.get("run_units_label", "ESTIMATE") for r in passing}
        n = len(passing)
        best = [r["best_score"] for r in passing if r.get("best_score") is not None]
        series = per_run_yield(passing, outcomes_by_run, pts)
        strategies[name] = {
            "strategy": name, "runs": n, "blocked_runs": blocked, "runs_total": len(rows),
            "funnel": {"examined": f["examined"], "candidates": f["candidates"], "prescreen_pass": f["prescreen_pass"],
                       "scored": scored, "at_floor": at_floor, "top20": len(ev_slugs["top20"]), "keep": len(ev_slugs["keep"]),
                       "kill": len(ev_slugs["kill"]), "archived": len(ev_slugs["archived"])},
            "dropped": drops, "searches": f["searches"], "run_units": units,
            "run_units_label": "MEASURED" if labels == {"MEASURED"} else "ESTIMATE",
            "points": round(points, 4),
            "points_per_run": round(points / n, 4) if n else None,
            "points_per_100_searches": round(points * 100.0 / f["searches"], 4) if f["searches"] else None,
            "yield_per_unit": round(points / units, 4) if units else None,
            "best_score": max(best) if best else None,
            "sample": "small" if n < small_n else "ok",
            "series": series,
            "last_ts": rows[-1]["ts"] if rows else None,
        }
    own = [s["points"] / s["run_units"] for s in strategies.values() if s["run_units"] and s["runs"] > 0]
    fleet_median = oc.median(own) if own else None
    for s in strategies.values():
        n = s["runs"]
        y = (s["points"] / s["run_units"]) if s["run_units"] else None
        if n == 0 or y is None:
            s["smoothed_yield"] = None
            s["smoothing"] = "no passing runs"
        elif n < k and fleet_median is not None:
            s["smoothed_yield"] = round((n * y + (k - n) * fleet_median) / k, 4)
            s["smoothing"] = "blended with the fleet median (%d of %d runs)" % (n, k)
        else:
            s["smoothed_yield"] = round(y, 4)
            s["smoothing"] = "own yield"
        # consecutive latest passing runs below the line (a fraction of the fleet median)
        streak = 0
        if fleet_median is not None and fleet_median > 0:
            line = frac * fleet_median
            for pr in reversed(s["series"]):
                if pr["per_unit"] is not None and pr["per_unit"] < line:
                    streak += 1
                else:
                    break
        s["runs_below_median"] = streak
    ranked = sorted(strategies.values(), key=lambda s: (s["smoothed_yield"] is None, -(s["smoothed_yield"] or 0), s["strategy"]))
    return {
        "window_days": days, "now": oc.iso(now), "fleet_median_yield_per_unit": round(fleet_median, 4) if fleet_median is not None else None,
        "points_table": pts, "ranked": [s["strategy"] for s in ranked], "strategies": {s["strategy"]: s for s in ranked},
        "blocked_runs": sum(s["blocked_runs"] for s in strategies.values()), "unattributed_outcomes": unattributed,
        "label": "MEASURED counts; run-units are %s" % ("MEASURED" if all(s["run_units_label"] == "MEASURED" for s in strategies.values()) and strategies else "ESTIMATE"),
        "basis": "Points follow the table in steward_rules.json (or the grant). Blocked runs are excluded from yield. Under %d runs a strategy is a small sample and no trend is inferred." % small_n,
    }


def _fmt(x: Any, nd: int = 2) -> str:
    if x is None:
        return "-"
    if isinstance(x, float):
        return ("%." + str(nd) + "f") % x
    return str(x)


def render(rep: Dict[str, Any]) -> str:
    L = ["Yield, last %d days (%s). Fleet median %s points per run-unit." % (rep["window_days"], rep["label"], _fmt(rep["fleet_median_yield_per_unit"]))]
    L.append("%-14s %4s %4s %6s %5s %5s %5s %4s %4s %4s %4s %7s %8s %8s %8s %s" % (
        "strategy", "runs", "blk", "exam", "cand", "pass", "score", "flr", "t20", "keep", "kill", "points", "per100s", "per-unit", "smoothed", "sample"))
    for name in rep["ranked"]:
        s = rep["strategies"][name]
        f = s["funnel"]
        L.append("%-14s %4d %4d %6d %5d %5d %5d %4d %4d %4d %4d %7s %8s %8s %8s %s" % (
            name[:14], s["runs"], s["blocked_runs"], f["examined"], f["candidates"], f["prescreen_pass"], f["scored"], f["at_floor"],
            f["top20"], f["keep"], f["kill"], _fmt(s["points"], 1), _fmt(s["points_per_100_searches"]), _fmt(s["yield_per_unit"]),
            _fmt(s["smoothed_yield"]), s["sample"]))
    if rep["blocked_runs"]:
        L.append("%d blocked run%s excluded from yield (a Sentinel matter, not a yield one)." % (rep["blocked_runs"], "" if rep["blocked_runs"] == 1 else "s"))
    L.append(rep["basis"])
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    common = steward.common_flags()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("ingest", "outcomes", "reviews"):
        sub.add_parser(c, parents=[common]).add_argument("file")
    r = sub.add_parser("report", parents=[common]); r.add_argument("--days", type=int, default=30)
    args = steward.parse_args(ap, argv)
    if args is None:
        return 0
    try:
        home = Path(args.home).expanduser() if args.home else oc.otto_home()
        if args.cmd in ("ingest", "outcomes", "reviews"):
            rows, bad = _load_input(args.file)
            fn = {"ingest": ingest, "outcomes": add_outcomes, "reviews": add_reviews}[args.cmd]
            res = fn(home, rows)
            res["unparseable_lines"] = bad
            print(json.dumps(res) if args.json else "%s: %d added, %d updated, %d skipped, %d unparseable" % (
                args.cmd, res["added"], res["updated"], res["skipped"], bad))
        else:
            g = steward.grant(args.grant, home)
            now = oc.parse_when(args.now) if args.now else None
            rep = report(home, args.days, now, g.rules)
            print(json.dumps(rep, indent=2) if args.json else render(rep))
    except Exception as e:  # fail open
        oc.log_error("yield: %s" % e, None)
        oc.eprint("yield: %s (logged)" % oc.short(e, 200))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
