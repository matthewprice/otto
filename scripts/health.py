#!/usr/bin/env python3
"""Compare what every registered automation should have done with what the evidence says.

The registry is Markdown with frontmatter, one note per automation, in
<vault>/Automations/. The evidence is the ledger plus, for any automation that names
one, the output file it is supposed to leave behind. Silence is a finding: an
automation that was due and left no evidence is reported as `miss`.

Statuses, most urgent first: miss, fail, breaker, late, drift, unobservable, config,
pending, ok, paused, new.

Usage:
  health.py [--home DIR] [--now ISO] [--automation NAME] [--json | --table]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ledger  # noqa: E402
import otto_common as oc  # noqa: E402

SURFACES = {"local-cli", "desktop-task", "routine", "cowork", "github-actions", "loop", "managed-agent", "other"}
SEVERITY = {"miss": 5, "fail": 4, "breaker": 4, "late": 3, "drift": 2, "unobservable": 2, "config": 2,
            "pending": 1, "ok": 0, "paused": 0, "new": 0}
SKIP_FILES = {"readme.md", "template.md", "_template.md"}


# --------------------------------------------------------------------------- registry

def _as_list(v: Any) -> List[Any]:
    if v is None or v == "":
        return []
    return v if isinstance(v, list) else [v]


def _band(v: Any) -> Optional[Tuple[float, float]]:
    xs = _as_list(v)
    if len(xs) == 2:
        try:
            return float(xs[0]), float(xs[1])
        except (TypeError, ValueError):
            return None
    return None


def normalize_days(v: Any) -> List[int]:
    if v is None or v == "" or str(v).lower() in ("daily", "every day", "all"):
        return list(range(7))
    if isinstance(v, str) and v.lower() in ("weekdays", "workdays"):
        return [0, 1, 2, 3, 4]
    out = []
    for d in _as_list(v):
        k = str(d).strip().lower()[:3]
        if k in oc.DAYS:
            out.append(oc.DAYS.index(k))
    return sorted(set(out)) or list(range(7))


def load_registry(home: Path, cfg: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    d = oc.vault_dir(cfg, home) / "Automations"
    autos: List[Dict[str, Any]] = []
    problems: List[str] = []
    if not d.is_dir():
        return autos, ["no registry folder at %s" % d]
    for p in sorted(d.glob("*.md")):
        if p.name.lower() in SKIP_FILES:
            continue
        try:
            fm, body = oc.read_frontmatter(p)
        except OSError as e:
            problems.append("%s: %s" % (p.name, e))
            continue
        if not fm:
            problems.append("%s: no frontmatter" % p.name)
            continue
        a = dict(fm)
        a["name"] = oc.slug(fm.get("name") or p.stem)
        a["_path"] = str(p)
        a["_mtime"] = datetime.fromtimestamp(p.stat().st_mtime).astimezone()
        autos.append(a)
    return autos, problems


# --------------------------------------------------------------------------- schedule math

def scheduled_instants(days: List[int], hhmm: Tuple[int, int], tz, now: datetime, count: int = 3) -> List[datetime]:
    """Most recent expected-by instants at or before `now`, newest first."""
    out: List[datetime] = []
    today = now.astimezone(tz).date()
    for back in range(0, 40):
        d = today - timedelta(days=back)
        if d.weekday() not in days:
            continue
        inst = datetime.combine(d, time(hhmm[0], hhmm[1]), tzinfo=tz)
        if inst <= now:
            out.append(inst)
            if len(out) >= count:
                break
    return out


def next_instant(days: List[int], hhmm: Tuple[int, int], tz, now: datetime) -> Optional[datetime]:
    today = now.astimezone(tz).date()
    for fwd in range(0, 40):
        d = today + timedelta(days=fwd)
        if d.weekday() not in days:
            continue
        inst = datetime.combine(d, time(hhmm[0], hhmm[1]), tzinfo=tz)
        if inst > now:
            return inst
    return None


def registered_at(a: Dict[str, Any], tz) -> datetime:
    ra = a.get("registered_at")
    if ra:
        try:
            return oc.parse_when(str(ra), tz)
        except ValueError:
            pass
    r = a.get("registered")
    if r:
        try:
            d = date.fromisoformat(str(r)[:10])
            return datetime.combine(d + timedelta(days=1), time(0, 0), tzinfo=tz)
        except ValueError:
            pass
    return a["_mtime"].astimezone(tz)


# --------------------------------------------------------------------------- artifact check

def expand_pattern(pat: str, due: datetime) -> str:
    iso_year, iso_week, _ = due.isocalendar()
    return (pat.replace("{date}", due.strftime("%Y-%m-%d")).replace("{yyyy}", due.strftime("%Y"))
            .replace("{mm}", due.strftime("%m")).replace("{dd}", due.strftime("%d"))
            .replace("{iso_week}", "%04d-W%02d" % (iso_year, iso_week)))


def check_artifact(a: Dict[str, Any], due: datetime, window_start: datetime, home: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Look for the output file the automation is supposed to leave. None when none is registered."""
    pat = a.get("success_file")
    if not pat:
        return None
    home_s = str(home or oc.otto_home())
    base = Path(str(a.get("success_cwd") or ".").replace("{OTTO_HOME}", home_s)).expanduser()
    shown = expand_pattern(str(pat), due)
    full = shown.replace("{OTTO_HOME}", home_s)
    full = os.path.expanduser(full)
    if not os.path.isabs(full):
        full = str(base / full)
    matches = [Path(x) for x in glob.glob(full)]
    res: Dict[str, Any] = {"pattern": shown, "ok": False, "reasons": [], "path": None}
    if not matches:
        res["reasons"].append("no file matches %s" % shown)
        return res
    newest = max(matches, key=lambda p: p.stat().st_mtime)
    st = newest.stat()
    mtime = datetime.fromtimestamp(st.st_mtime).astimezone()
    res["path"] = str(newest)
    res["mtime"] = oc.iso(mtime)
    res["bytes"] = st.st_size
    if mtime < window_start:
        res["reasons"].append("newest match was last written %s, before this cycle began" % mtime.strftime("%a %H:%M"))
    mb = a.get("success_min_bytes")
    if isinstance(mb, (int, float)) and st.st_size < mb:
        res["reasons"].append("file is %d bytes, expected at least %d" % (st.st_size, mb))
    sp = a.get("success_pattern")
    if sp:
        try:
            with open(newest, encoding="utf-8", errors="replace") as fh:
                text = fh.read(2_000_000)
            if not re.search(str(sp), text):
                res["reasons"].append("pattern %r not found in output" % str(sp)[:40])
        except OSError as e:
            res["reasons"].append("could not read output: %s" % e.__class__.__name__)
    res["ok"] = not res["reasons"]
    return res


# --------------------------------------------------------------------------- outcomes

def row_outcome(r: Dict[str, Any]) -> str:
    o = r.get("outcome")
    if o in ("pass", "fail", "skipped"):
        return o
    if r.get("is_error") or (r.get("exit") not in (None, 0)):
        return "fail"
    return "pass"


def consecutive_failures(rows: List[Dict[str, Any]]) -> int:
    n = 0
    for r in reversed(rows):
        o = row_outcome(r)
        if o == "skipped":
            continue
        if o == "fail":
            n += 1
        else:
            break
    return n


def last_success(rows: List[Dict[str, Any]]) -> Optional[str]:
    for r in reversed(rows):
        if row_outcome(r) == "pass":
            return r.get("ts")
    return None


def drift_reasons(a: Dict[str, Any], row: Dict[str, Any], prior: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    dur = row.get("duration_ms")
    band = _band(a.get("duration_min"))
    if dur is not None and band:
        m = dur / 60000.0
        if m < band[0] or m > band[1]:
            out.append("duration %.1f min is outside the registered band %g to %g min" % (m, band[0], band[1]))
    cost = row.get("cost_usd")
    cband = _band(a.get("cost_usd"))
    if cost is not None and cband and (cost < cband[0] or cost > cband[1]):
        out.append("cost $%.2f is outside the registered band $%g to $%g" % (cost, cband[0], cband[1]))
    hist = [p["cost_usd"] for p in prior if p.get("cost_usd") is not None and row_outcome(p) == "pass"][-7:]
    med = oc.median(hist) if len(hist) >= 3 else None
    if cost is not None and med and cost > med * 1.4 and (cost - med) > 0.05:
        out.append("cost $%.2f is %d%% above the median $%.2f of the previous %d passing runs" % (cost, round((cost / med - 1) * 100), med, len(hist)))
    return out


# --------------------------------------------------------------------------- evaluation

def _finding(a: Dict[str, Any], status: str, summary: str, **kw: Any) -> Dict[str, Any]:
    f: Dict[str, Any] = {"automation": a["name"], "surface": a.get("surface", "other"), "status": status,
                         "severity": SEVERITY[status], "summary": summary}
    f.update({k: v for k, v in kw.items() if v is not None})
    return f


def evaluate_one(a: Dict[str, Any], rows_all: List[Dict[str, Any]], cfg: Dict[str, Any], now: datetime,
                 breaker: Dict[str, Any], home: Optional[Path] = None) -> Dict[str, Any]:
    name = a["name"]
    surface = str(a.get("surface") or "other")
    tz = oc.get_tz(a.get("timezone") or cfg.get("timezone"))
    now_l = now.astimezone(tz)
    if a.get("paused") is True:
        return _finding(a, "paused", "Paused in the registry.")
    problems: List[str] = []
    if surface not in SURFACES:
        problems.append("unknown surface %r (use one of %s)" % (surface, ", ".join(sorted(SURFACES))))
    try:
        hhmm = oc.parse_hhmm(a.get("expected_by"))
    except ValueError:
        return _finding(a, "config", "No usable expected_by (HH:MM). Without it Otto cannot tell if this ran." +
                        ("" if not problems else " " + "; ".join(problems)))
    days = normalize_days(a.get("days"))
    grace = timedelta(minutes=int(a.get("grace_min") or 15))
    instants = scheduled_instants(days, hhmm, tz, now_l, 3)
    nxt = next_instant(days, hhmm, tz, now_l)
    if not instants:
        return _finding(a, "new", "Nothing has been due yet.", next_expected=oc.iso(nxt))
    latest = instants[0]
    prev = instants[1] if len(instants) > 1 else latest - timedelta(days=1)
    reg = registered_at(a, tz)
    mine = [r for r in rows_all if r.get("kind") == "run" and r.get("automation") == name]
    cf = consecutive_failures(mine)
    base = dict(due=oc.iso(latest), next_expected=oc.iso(nxt), consecutive_failures=cf,
                last_success=last_success(mine))
    br = breaker.get(name) or {}
    if br.get("open"):
        return _finding(a, "breaker", "Circuit breaker is open since %s after %s consecutive failures. Reason: %s." % (
            str(br.get("since", "?"))[:16], br.get("failures", "?"), br.get("reason", "unspecified")),
            fix="python3 ~/.otto/bin/run.py %s --reset-breaker" % name, **base)
    if latest < reg:
        return _finding(a, "new", "Registered after the last expected time. First check at %s." % (nxt.strftime("%a %H:%M") if nxt else "?"), **base)

    def ts(r: Dict[str, Any]) -> datetime:
        return oc.parse_when(r.get("ts"), tz)
    window_end = latest + grace
    in_cycle = [r for r in mine if prev < ts(r) <= window_end]
    late = [r for r in mine if window_end < ts(r) <= now_l and ts(r) > latest]
    art = check_artifact(a, latest, prev, home)

    if in_cycle:
        last = in_cycle[-1]
        attempts = len(in_cycle)
        out = row_outcome(last)
        if out == "skipped":
            reason = str(last.get("skipped_reason") or "")
            if reason.startswith("breaker"):
                return _finding(a, "breaker", "Skipped by the wrapper: %s." % reason, **base)
            return _finding(a, "ok", "Skipped by the wrapper (%s)." % (reason or "already done"), ran_at=last.get("ts"), attempts=attempts, **base)
        if out == "fail" or (art is not None and not art["ok"] and out == "pass"):
            why = []
            if last.get("is_error") or last.get("exit") not in (None, 0):
                why.append("exit %s%s" % (last.get("exit", "?"), (" (%s)" % last["stop_reason"]) if last.get("stop_reason") else ""))
            if art is not None and not art["ok"]:
                why.extend(art["reasons"])
            if last.get("outcome_evidence"):
                why.append(str(last["outcome_evidence"]))
            msg = "Ran at %s but did not succeed: %s." % (ts(last).strftime("%H:%M"), "; ".join(why) or "see ledger row")
            if attempts >= 3:
                msg += " %d attempts in one cycle." % attempts
            return _finding(a, "fail", msg, ran_at=last.get("ts"), attempts=attempts, cost_usd=last.get("cost_usd"),
                            evidence=art, **base)
        prior = [r for r in mine if ts(r) < ts(last)]
        dr = drift_reasons(a, last, prior)
        if attempts >= 3:
            dr.append("%d attempts in one cycle (retry storm)" % attempts)
        if dr:
            return _finding(a, "drift", "Ran and succeeded, but " + "; ".join(dr) + ".", ran_at=last.get("ts"),
                            attempts=attempts, cost_usd=last.get("cost_usd"), duration_ms=last.get("duration_ms"), **base)
        return _finding(a, "ok", "Ran at %s%s." % (ts(last).strftime("%H:%M"),
                        (", $%.2f" % last["cost_usd"]) if last.get("cost_usd") is not None else ""),
                        ran_at=last.get("ts"), attempts=attempts, cost_usd=last.get("cost_usd"), duration_ms=last.get("duration_ms"), **base)

    # no ledger evidence in the cycle
    if art is not None and art["ok"]:
        return _finding(a, "ok", "Output found (%s, %s bytes). No ledger row, so cost is unknown." % (
            Path(art["path"]).name, art.get("bytes")), evidence=art, **base)
    if now_l < window_end:
        return _finding(a, "pending", "Due by %s; the grace period runs to %s." % (latest.strftime("%H:%M"), window_end.strftime("%H:%M")), **base)
    if late:
        r = late[-1]
        return _finding(a, "late", "Ran at %s, after the %s deadline." % (ts(r).strftime("%a %H:%M"), latest.strftime("%H:%M")),
                        ran_at=r.get("ts"), **base)
    if surface != "local-cli" and art is None:
        return _finding(a, "unobservable", "Registered on a surface Otto can only observe by its output, and no success_file is set. Add one so silence can be detected.", **base)
    why = "no ledger row" + ("" if art is None else " and " + "; ".join(art["reasons"]))
    return _finding(a, "miss", "Expected by %s %s, and there is %s." % (latest.strftime("%a"), latest.strftime("%H:%M"), why),
                    evidence=art, **base)


def evaluate(home: Path, now: Optional[datetime] = None, only: Optional[str] = None) -> Dict[str, Any]:
    cfg = oc.load_config(home)
    now = now or oc.parse_when(None)
    autos, problems = load_registry(home, cfg)
    since = now - timedelta(days=60)
    rows = ledger.read_rows(home, since=since)
    breaker = oc.read_json(oc.state_dir(home) / "breaker.json", {}) or {}
    findings = []
    for a in autos:
        if only and a["name"] != only:
            continue
        try:
            findings.append(evaluate_one(a, rows, cfg, now, breaker, home))
        except Exception as e:  # one bad note must not hide the others
            findings.append(_finding(a, "config", "Could not evaluate this note: %s: %s" % (e.__class__.__name__, str(e)[:80])))
    findings.sort(key=lambda f: (-f["severity"], f["automation"]))
    counts: Dict[str, int] = {}
    for f in findings:
        counts[f["status"]] = counts.get(f["status"], 0) + 1
    runs = [r for r in rows if r.get("kind") == "run"]
    last_write = None
    if runs:
        last_write = max(oc.parse_when(r.get("end_ts") or r.get("ts"), now.tzinfo) for r in runs)
    return {
        "generated_at": oc.iso(now), "home": str(home), "registry_problems": problems, "counts": counts,
        "findings": findings, "ledger_rows_60d": len(rows),
        "last_ledger_activity": oc.iso(last_write),
        "hook_errors_24h": oc.count_recent_errors(home, 24),
        "lights": cfg.get("lights", "off"),
    }


def history(home: Path, days: int, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Replay every past cycle in the last `days` days as if Otto had looked right after its grace period.

    This is how the weekly retro counts silent failures: each past cycle is judged only on
    evidence that existed at the time.
    """
    cfg = oc.load_config(home)
    now = now or oc.parse_when(None)
    autos, _ = load_registry(home, cfg)
    rows = ledger.read_rows(home, since=now - timedelta(days=days + 60))
    out: Dict[str, Any] = {}
    totals: Dict[str, int] = {}
    for a in autos:
        try:
            hhmm = oc.parse_hhmm(a.get("expected_by"))
        except ValueError:
            continue
        if a.get("paused") is True:
            continue
        tz = oc.get_tz(a.get("timezone") or cfg.get("timezone"))
        grace = timedelta(minutes=int(a.get("grace_min") or 15))
        cycles = [i for i in scheduled_instants(normalize_days(a.get("days")), hhmm, tz, now.astimezone(tz), 400)
                  if i >= now - timedelta(days=days) and i + grace + timedelta(minutes=1) <= now]
        recs = []
        for inst in sorted(cycles):
            at = inst + grace + timedelta(minutes=1)
            visible = [r for r in rows if oc.parse_when(r.get("ts"), tz) <= at]
            f = evaluate_one(a, visible, cfg, at, {}, home)
            recs.append({"due": oc.iso(inst), "status": f["status"], "summary": f["summary"]})
            totals[f["status"]] = totals.get(f["status"], 0) + 1
        out[a["name"]] = recs
    return {"days": days, "totals": totals, "cycles": out}


def render_table(rep: Dict[str, Any]) -> str:
    lights = {"ok": "[ok]  ", "miss": "[MISS]", "fail": "[FAIL]", "breaker": "[STOP]", "late": "[late]", "drift": "[drift]",
              "pending": "[wait]", "unobservable": "[blind]", "config": "[cfg] ", "paused": "[pause]", "new": "[new] "}
    lines = ["Otto health at %s" % rep["generated_at"]]
    for f in rep["findings"]:
        lines.append("%-8s %-24s %s" % (lights.get(f["status"], f["status"]), f["automation"], f["summary"]))
    if not rep["findings"]:
        lines.append("(no automations registered)")
    for p in rep.get("registry_problems", []):
        lines.append("note: " + p)
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home"); ap.add_argument("--now"); ap.add_argument("--automation")
    ap.add_argument("--history", type=int, metavar="DAYS", help="replay past cycles and count statuses")
    g = ap.add_mutually_exclusive_group(); g.add_argument("--json", action="store_true"); g.add_argument("--table", action="store_true")
    args = ap.parse_args(argv)
    home = Path(args.home).expanduser() if args.home else oc.otto_home()
    cfg = oc.load_config(home)
    now = oc.parse_when(args.now, oc.get_tz(cfg.get("timezone")))
    if args.history:
        print(json.dumps(history(home, args.history, now), indent=2))
        return 0
    rep = evaluate(home, now, oc.slug(args.automation) if args.automation else None)
    print(render_table(rep) if args.table else json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
