#!/usr/bin/env python3
"""Prove an expectation before you need it.

  verify.py NAME [--home DIR] [--now ISO] [--json]
      Lint the registry note and run its success check against the current cycle, right now.
  verify.py NAME --drill miss|auth|budget|timeout [--keep] [--json]
      Copy the registry, ledger and state to a scratch home, inject that failure there, and show
      what the next /otto:status would say. The real ledger is never touched; the scratch home is
      deleted afterwards unless --keep.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import health  # noqa: E402
import ledger  # noqa: E402
import otto_common as oc  # noqa: E402

DRILLS = ("miss", "auth", "budget", "timeout")


def _find(home: Path, name: str):
    cfg = oc.load_config(home)
    autos, problems = health.load_registry(home, cfg)
    a = next((x for x in autos if x["name"] == oc.slug(name)), None)
    return cfg, a, problems


def lint(a: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    surface = str(a.get("surface") or "other")
    if surface not in health.SURFACES:
        out.append("surface %r is not one of %s" % (surface, ", ".join(sorted(health.SURFACES))))
    try:
        oc.parse_hhmm(a.get("expected_by"))
    except ValueError:
        out.append("expected_by must be HH:MM")
    if a.get("run_at"):
        try:
            oc.parse_hhmm(a.get("run_at"))
        except ValueError:
            out.append("run_at must be HH:MM")
    if a.get("timezone"):
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(str(a["timezone"]))
        except Exception:
            out.append("timezone %r is not a known IANA zone" % a["timezone"])
    if not a.get("success_file"):
        out.append("no success_file: a miss cannot be told from a quiet success" + ("" if surface == "local-cli" else ", and this surface has no other evidence"))
    cwd = a.get("cwd")
    if cwd and not os.path.isdir(os.path.expanduser(str(cwd))):
        out.append("cwd %s does not exist" % cwd)
    sc = a.get("success_cwd")
    if sc and "{OTTO_HOME}" not in str(sc) and not os.path.isdir(os.path.expanduser(str(sc))):
        out.append("success_cwd %s does not exist" % sc)
    if surface == "local-cli":
        if not str(a.get("command") or "").strip():
            out.append("local-cli note has no command")
        for cap in ("max_turns", "max_budget_usd", "timeout_min"):
            if not a.get(cap):
                out.append("no %s cap; the runner will use its default" % cap)
    if a.get("days") is not None:
        d = health.normalize_days(a.get("days"))
        if not d:
            out.append("days did not parse")
    return out


def check_now(home: Path, a: Dict[str, Any], cfg: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    tz = oc.get_tz(a.get("timezone") or cfg.get("timezone"))
    now_l = now.astimezone(tz)
    res: Dict[str, Any] = {"automation": a["name"], "checked_at": oc.iso(now_l)}
    try:
        hhmm = oc.parse_hhmm(a.get("expected_by"))
    except ValueError:
        res["check"] = None
        return res
    days = health.normalize_days(a.get("days"))
    inst = health.scheduled_instants(days, hhmm, tz, now_l, 2)
    nxt = health.next_instant(days, hhmm, tz, now_l)
    res["next_expected"] = oc.iso(nxt)
    if not inst:
        res["check"] = None
        res["note"] = "nothing has been due yet"
        return res
    latest, prev = inst[0], (inst[1] if len(inst) > 1 else inst[0] - timedelta(days=1))
    res["cycle_due"] = oc.iso(latest)
    res["check"] = health.check_artifact(a, latest, prev, home)
    rows = ledger.read_rows(home, since=prev, automation=a["name"], kind="run")
    res["ledger_rows_this_cycle"] = len([r for r in rows if oc.parse_when(r.get("ts"), tz) > prev])
    return res


def verify(home: Path, name: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    cfg, a, problems = _find(home, name)
    if a is None:
        return {"automation": oc.slug(name), "error": "no registry note named %s" % name, "registry_problems": problems}
    now = now or oc.parse_when(None, oc.get_tz(cfg.get("timezone")))
    out = {"automation": a["name"], "note": a.get("_path"), "lint": lint(a)}
    out.update(check_now(home, a, cfg, now))
    status = health.evaluate(home, now, a["name"])
    out["status_now"] = status["findings"][0] if status["findings"] else None
    c = out.get("check")
    out["verdict"] = ("pass" if c and c.get("ok") else "fail" if c else "no-check")
    return out


# --------------------------------------------------------------------------- drills

def _copy_home(home: Path, name: str) -> Path:
    cfg = oc.load_config(home)
    scratch = Path(tempfile.mkdtemp(prefix="otto-drill-"))
    (scratch / "vault/Automations").mkdir(parents=True)
    src = oc.vault_dir(cfg, home) / "Automations" / (name + ".md")
    shutil.copy2(src, scratch / "vault/Automations" / src.name)
    if oc.ledger_dir(home).is_dir():
        shutil.copytree(oc.ledger_dir(home), oc.ledger_dir(scratch))
    oc.state_dir(scratch).mkdir(parents=True, exist_ok=True)
    br = oc.state_dir(home) / "breaker.json"
    if br.exists():
        shutil.copy2(br, oc.state_dir(scratch) / "breaker.json")
    fm = {k: v for k, v in cfg.items() if k in oc.DEFAULT_CONFIG and v not in (None, "", [])}
    fm.pop("vault_dir", None)
    oc.write_note(oc.config_path(scratch), fm, "Scratch copy for a drill.\n")
    return scratch


def _remove_cycle_rows(scratch: Path, name: str, after: datetime) -> int:
    n = 0
    for p in sorted(oc.ledger_dir(scratch).glob("*.jsonl")):
        rows = ledger._read_file(p)
        keep = [r for r in rows if not (r.get("automation") == name and r.get("kind") == "run" and oc.parse_when(r.get("ts"), after.tzinfo) > after)]
        n += len(rows) - len(keep)
        ledger._write_file(p, keep)
    return n


def drill(home: Path, name: str, kind: str, now: Optional[datetime] = None, keep: bool = False) -> Dict[str, Any]:
    if kind not in DRILLS:
        raise ValueError("drill must be one of %s" % ", ".join(DRILLS))
    cfg, a, _ = _find(home, name)
    if a is None:
        return {"automation": oc.slug(name), "error": "no registry note named %s" % name}
    tz = oc.get_tz(a.get("timezone") or cfg.get("timezone"))
    now = (now or oc.parse_when(None, tz)).astimezone(tz)
    hhmm = oc.parse_hhmm(a.get("expected_by"))
    days = health.normalize_days(a.get("days"))
    grace = timedelta(minutes=int(a.get("grace_min") or 15))
    inst = health.scheduled_instants(days, hhmm, tz, now, 3)
    nxt = health.next_instant(days, hhmm, tz, now)
    due = inst[0] if inst else nxt
    prev = inst[1] if len(inst) > 1 else due - timedelta(days=1)
    scratch = _copy_home(home, a["name"])
    note = scratch / "vault/Automations" / (a["name"] + ".md")
    fm, body = oc.read_frontmatter(note)
    fm["success_file"] = "drill/never-{date}.txt"
    fm["success_cwd"] = "{OTTO_HOME}"
    fm["registered"] = (prev - timedelta(days=2)).date().isoformat()
    oc.write_note(note, fm, body)
    injected: List[str] = []
    removed = _remove_cycle_rows(scratch, a["name"], prev)
    if removed:
        injected.append("removed %d ledger rows from the current cycle" % removed)
    if kind in ("auth", "budget", "timeout"):
        threshold = int(cfg.get("breaker_threshold") or 3)
        count = threshold if kind == "auth" else 1
        instants = [due] + [i for i in inst[1:count]]
        while len(instants) < count:
            instants.append(instants[-1] - timedelta(days=1))
        for i, when in enumerate(instants):
            ledger.upsert_run(scratch, {"ts": oc.iso(when - timedelta(minutes=20)), "automation": a["name"], "surface": "local-cli",
                                        "source": "wrapper", "session_id": str(uuid.uuid4()), "exit": 1, "is_error": True,
                                        "outcome": "fail", "outcome_evidence": kind, "cost_usd": 0.02, "duration_ms": 3000 if kind != "timeout" else 1800000,
                                        "note": "drill"})
        injected.append("appended %d failed run%s labelled %s" % (count, "" if count == 1 else "s", kind))
        if kind == "auth":
            oc.write_json(oc.state_dir(scratch) / "breaker.json", {a["name"]: {"open": True, "since": oc.iso(due), "failures": threshold,
                                                                                "reason": "authentication_failed %d runs in a row (drill)" % threshold}})
            injected.append("opened the circuit breaker")
    else:
        injected.append("pointed the success check at a file that will never exist")
    at = max(now, due + grace + timedelta(minutes=1))
    rep = health.evaluate(scratch, at, a["name"])
    finding = rep["findings"][0] if rep["findings"] else None
    out = {"automation": a["name"], "drill": kind, "scratch_home": str(scratch) if keep else None, "injected": injected,
           "evaluated_at": oc.iso(at), "would_report": finding,
           "caught": bool(finding and finding["status"] in ("miss", "fail", "breaker")),
           "note": "Scratch copy only. Nothing in %s was changed." % home}
    if not keep:
        shutil.rmtree(scratch, ignore_errors=True)
    return out


def render(rep: Dict[str, Any]) -> str:
    if rep.get("error"):
        return "otto verify: " + rep["error"]
    if "drill" in rep:
        f = rep.get("would_report") or {}
        L = ["Drill %s on %s: %s" % (rep["drill"], rep["automation"], "CAUGHT" if rep["caught"] else "NOT CAUGHT")]
        L += ["  " + s for s in rep["injected"]]
        L.append("  status at %s would be: [%s] %s" % (rep["evaluated_at"][:16], f.get("status", "?"), f.get("summary", "")))
        if f.get("fix"):
            L.append("  fix shown: %s" % f["fix"])
        L.append("  " + rep["note"])
        return "\n".join(L)
    L = ["Verify %s: %s" % (rep["automation"], rep["verdict"].upper())]
    for p in rep["lint"]:
        L.append("  lint: " + p)
    c = rep.get("check")
    if c:
        L.append("  check: %s %s" % ("ok" if c["ok"] else "fail", c.get("path") or c.get("pattern")))
        for r in c.get("reasons", []):
            L.append("    " + r)
    elif rep.get("note"):
        L.append("  " + rep["note"])
    if rep.get("status_now"):
        L.append("  status now: [%s] %s" % (rep["status_now"]["status"], rep["status_now"]["summary"]))
    if rep.get("next_expected"):
        L.append("  next expected: %s" % rep["next_expected"][:16])
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name"); ap.add_argument("--home"); ap.add_argument("--now")
    ap.add_argument("--drill", choices=DRILLS); ap.add_argument("--keep", action="store_true"); ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    home = Path(args.home).expanduser() if args.home else oc.otto_home()
    now = oc.parse_when(args.now) if args.now else None
    rep = drill(home, args.name, args.drill, now, args.keep) if args.drill else verify(home, args.name, now)
    print(json.dumps(rep, indent=2) if args.json else render(rep))
    return 0 if not rep.get("error") else 2


if __name__ == "__main__":
    raise SystemExit(main())
