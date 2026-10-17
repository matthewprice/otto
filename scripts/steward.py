#!/usr/bin/env python3
"""Steward mode: the opt-in grant that lets Otto apply named levers, and the nightly or weekly run.

Otto proposes by default. A client turns the Steward on by writing a grant: a `steward:` block in
the frontmatter of OTTO_HOME/otto.md (a local install) or of a file named with --grant (a fleet
whose state lives in a repo). Anything missing or unreadable falls back to propose mode, and every
command still prints what it would have done.

  steward.py show [--grant PATH] [--json]          the grant as Otto reads it: mode, levers, bounds, pause
  steward.py check LEVER [--grant PATH]            allowed or propose-only, with the reason
  steward.py run nightly|weekly [--grant PATH] [--pool N] [--settings FILE] [--dry-run] [--json]
      One pass in order: control check, yield report, diagnosis, allocation plan, experiment status
      and verdicts (nightly); the same plus experiment proposals (weekly). Writes nothing but
      OTTO_HOME/allocation.json and Otto's own experiment records. Applying is the client's job.

Rules a grant cannot override: never raise a pool, never use a model above the ceiling or the
banned list, never edit the rubric, kill list, recommendation or archive, never queue a persona
review, never create or delete a strategy, and stop when the pause file says paused.

Exit code 0 always. The Steward observes and fails open like every Otto script except guard.py.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import otto_common as oc  # noqa: E402

RULES_PATH = Path(__file__).resolve().parent / "steward_rules.json"
LEVERS = ("budget", "cadence", "model", "gates", "method", "skills")
# Actions no grant can turn on. requires-approval in the grant may only add to this list.
NEVER = ("create-strategy", "delete-strategy", "raise-pool", "edit-rubric", "edit-kill-list",
         "edit-recommendation", "edit-archive", "queue-review")
DEFAULT_APPROVAL = ["create-strategy", "delete-strategy", "raise-pool"]


_IDENT = re.compile(r"[^A-Za-z0-9_.\-]+")


def ident(name: Any) -> str:
    """A strategy or target id: case kept (S08 stays S08), anything else becomes a dash."""
    return _IDENT.sub("-", str(name or "").strip()).strip("-")[:64]


# --------------------------------------------------------------------------- a nested YAML subset

def _flow_map(s: str) -> Dict[str, Any]:
    """`{min: 50, max: 200, max-daily-shift: 20%}` into a dict, values via otto_common.parse_scalar."""
    out: Dict[str, Any] = {}
    for part in oc._split_inline_list(s.strip()[1:-1]):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        out[k.strip()] = oc.parse_scalar(v)
    return out


def _value(raw: str) -> Any:
    s = re.sub(r"\s+#.*$", "", raw.strip()) if not raw.strip().startswith(("'", '"')) else raw.strip()
    if s.startswith("{") and s.endswith("}"):
        return _flow_map(s)
    return oc.parse_scalar(s)


def parse_block(lines: List[str]) -> Dict[str, Any]:
    """Indentation-nested mappings with the same leaves otto_common reads: scalars, inline lists,
    dash lists, and inline maps. Enough for a grant; not a YAML parser."""
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    last_key: Optional[Tuple[int, Dict[str, Any], str]] = None
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        text = line.strip()
        if text.startswith("- "):
            if last_key and indent > last_key[0]:
                parent, key = last_key[1], last_key[2]
                if not isinstance(parent.get(key), list):
                    parent[key] = []
                parent[key].append(_value(text[2:]))
            continue
        m = re.match(r"^([A-Za-z0-9_][A-Za-z0-9_\-]*):(?:\s+(.*)|\s*)$", text)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if val is None or val.strip() == "" or val.strip().startswith("#"):
            child: Dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
            last_key = (indent, parent, key)
        else:
            parent[key] = _value(val)
            last_key = (indent, parent, key)
    return root


def _frontmatter_lines(text: str) -> List[str]:
    lines = text.lstrip("﻿").replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return []
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i]
    return []


def _empty_maps_to_none(d: Any) -> Any:
    if isinstance(d, dict):
        return {k: (None if v == {} else _empty_maps_to_none(v)) for k, v in d.items()}
    return d


# --------------------------------------------------------------------------- grant

def percent(v: Any, default: Optional[float] = None) -> Optional[float]:
    """'20%' or 20 or 0.2 into 0.2. None when unreadable."""
    if v is None or v == "":
        return default
    try:
        if isinstance(v, str):
            s = v.strip()
            return float(s[:-1]) / 100.0 if s.endswith("%") else float(s)
        x = float(v)
        return x / 100.0 if x > 1 else x
    except (TypeError, ValueError):
        return default


def load_rules(grant_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    rules = oc.read_json(RULES_PATH, {}) or {}
    pts = dict(rules.get("points") or {})
    override = (grant_data or {}).get("metric-points")
    if isinstance(override, dict):
        for k, v in override.items():
            if k in pts and isinstance(v, (int, float)) and not isinstance(v, bool):
                pts[k] = v
    rules["points"] = pts
    return rules


class Grant:
    """What the grant allows. Built by grant(); every accessor falls back to propose mode."""

    def __init__(self, data: Dict[str, Any], source: Optional[Path], root: Path, problems: List[str]):
        self.data = data or {}
        self.source = source
        self.root = root
        self.problems = problems
        self.rules = load_rules(self.data)

    # -- mode
    @property
    def enabled(self) -> bool:
        return self.data.get("enabled") is True

    @property
    def mode(self) -> str:
        if self.paused():
            return "paused"
        return "steward" if self.enabled else "propose"

    def levers(self) -> List[str]:
        raw = self.data.get("levers")
        if not isinstance(raw, list):
            return []
        return [str(x) for x in raw if str(x) in LEVERS]

    def requires_approval(self) -> List[str]:
        raw = self.data.get("requires-approval")
        extra = [str(x) for x in raw] if isinstance(raw, list) else []
        return sorted(set(DEFAULT_APPROVAL) | set(extra))

    def allowed(self, lever: str) -> bool:
        return self.why(lever)[0]

    def why(self, lever: str) -> Tuple[bool, str]:
        if lever in NEVER or lever in self.requires_approval():
            return False, "%s always needs the person; no grant can apply it" % lever
        if lever not in LEVERS:
            return False, "unknown lever %r (known: %s)" % (lever, ", ".join(LEVERS))
        if self.paused():
            return False, "paused by %s" % (self.pause_path() or "the pause file")
        if not self.enabled:
            return False, "steward.enabled is not true; propose mode"
        if lever not in self.levers():
            return False, "%s is not in the grant's levers; propose only" % lever
        return True, "granted"

    # -- bounds
    def bounds(self, key: str) -> Any:
        """A bound from the grant, else the default in steward_rules.json. Percent strings become
        fractions; the model list never includes a banned model."""
        defaults = (self.rules.get("default_bounds") or {})
        mine = (self.data.get("bounds") or {}) if isinstance(self.data.get("bounds"), dict) else {}
        v = mine.get(key, defaults.get(key))
        dv = defaults.get(key)
        if key == "searches":
            d = dict(dv or {})
            if isinstance(v, dict):
                d.update({k: x for k, x in v.items() if x is not None})
            return {"min": int(d.get("min", 0) or 0), "max": int(d.get("max", 10 ** 6) or 10 ** 6),
                    "max-daily-shift": percent(d.get("max-daily-shift"), 0.2)}
        if key == "daily-cap":
            d = dict(dv or {})
            if isinstance(v, dict):
                d.update({k: x for k, x in v.items() if x is not None})
            return {"min": int(d.get("min", 0) or 0), "max": int(d.get("max", 10 ** 6) or 10 ** 6)}
        if key == "exploration-share":
            return percent(v, percent(dv, 0.15))
        if key == "models":
            tiers = list(self.rules.get("model_tiers") or ["haiku", "sonnet", "opus"])
            banned = set(self.rules.get("banned_models") or ["fable"])
            got = [str(x).lower() for x in (v if isinstance(v, list) else (dv or tiers))]
            return [m for m in tiers if m in got and m not in banned]
        if key == "cadence":
            return [str(x) for x in (v if isinstance(v, list) else (dv or []))]
        return v

    def model_ceiling(self) -> Optional[str]:
        ms = self.bounds("models")
        return ms[-1] if ms else None

    def experiment(self, key: str, default: Any = None) -> Any:
        e = self.data.get("experiment") if isinstance(self.data.get("experiment"), dict) else {}
        if key in e and e[key] is not None:
            return e[key]
        return default

    def max_active(self) -> Dict[str, int]:
        m = self.experiment("max-active", {}) or {}
        def num(k: str) -> int:
            try:
                return max(0, int(m.get(k, 1)))
            except (TypeError, ValueError):
                return 1
        return {"per-strategy": num("per-strategy"), "fleet-wide": num("fleet-wide")}

    # -- files named by the grant
    def path(self, key: str) -> Optional[Path]:
        v = self.data.get(key)
        if not v or not isinstance(v, str):
            return None
        p = Path(v).expanduser()
        return p if p.is_absolute() else self.root / p

    def pause_path(self) -> Optional[Path]:
        return self.path("pause")

    def paused(self) -> bool:
        return paused(self.pause_path(), oc.otto_home())

    def summary(self) -> Dict[str, Any]:
        return {"mode": self.mode, "enabled": self.enabled, "levers": self.levers() if self.enabled else [],
                "levers_named": self.levers(), "requires_approval": self.requires_approval(),
                "never": list(NEVER), "paused": self.paused(),
                "bounds": {k: self.bounds(k) for k in ("searches", "daily-cap", "cadence", "models", "exploration-share")},
                "model_ceiling": self.model_ceiling(), "max_active": self.max_active(),
                "pools": str(self.path("pools")) if self.path("pools") else None,
                "log": str(self.path("log")) if self.path("log") else None,
                "pause": str(self.pause_path()) if self.pause_path() else None,
                "source": str(self.source) if self.source else None, "problems": self.problems}


def paused(pause_file: Optional[Path], home: Optional[Path] = None) -> bool:
    """Paused when the pause file says `paused: true` (frontmatter or a plain line), or a PAUSE file
    sits beside it, or OTTO_HOME/PAUSE exists. Unreadable means not paused: observers fail open."""
    try:
        if home is not None and (Path(home) / "PAUSE").exists():
            return True
        if pause_file is None:
            return False
        if (pause_file.parent / "PAUSE").exists():
            return True
        if not pause_file.exists():
            return False
        text = pause_file.read_text(encoding="utf-8", errors="replace")
        fm, _ = oc.parse_frontmatter(text)
        if fm.get("paused") is True:
            return True
        return bool(re.search(r"(?im)^\s*[-*]?\s*\**paused\**\s*:\s*\**\s*(true|yes)\b", text))
    except OSError:
        return False


def grant(path: Optional[str] = None, home: Optional[Path] = None, root: Optional[Path] = None) -> Grant:
    """Load the grant from --grant PATH, else OTTO_HOME/otto.md. Relative paths inside the grant
    (pools, log, pause) resolve against root, default the current directory."""
    home = home or oc.otto_home()
    root = root or Path.cwd()
    src = Path(path).expanduser() if path else oc.config_path(home)
    problems: List[str] = []
    data: Dict[str, Any] = {}
    try:
        if src.exists():
            block = parse_block(_frontmatter_lines(src.read_text(encoding="utf-8", errors="replace")))
            st = block.get("steward")
            if isinstance(st, dict):
                data = _empty_maps_to_none(st)
            elif path:
                problems.append("no steward: block in %s; propose mode" % src.name)
        elif path:
            problems.append("grant file %s not found; propose mode" % src)
    except Exception as e:  # fail open: a broken grant is propose mode, never a crash
        problems.append("could not read the grant (%s); propose mode" % oc.short(e, 120))
        data = {}
    return Grant(data, src if src.exists() else None, root, problems)


def allowed(lever: str, g: Optional[Grant] = None) -> bool:
    return (g or grant()).allowed(lever)


def bounds(key: str, g: Optional[Grant] = None) -> Any:
    return (g or grant()).bounds(key)


def common_flags() -> argparse.ArgumentParser:
    """Flags every Steward script takes, accepted before or after the subcommand."""
    c = argparse.ArgumentParser(add_help=False)
    for f in ("--home", "--grant", "--now", "--root"):
        c.add_argument(f, default=argparse.SUPPRESS)
    c.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    return c


def parse_args(ap: argparse.ArgumentParser, argv: Optional[List[str]]) -> Optional[argparse.Namespace]:
    """Parse, filling the common flags; None on a usage error (printed by argparse), so callers
    can still exit 0."""
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        if e.code not in (0, None):
            return None
        raise
    for k, v in (("home", None), ("grant", None), ("now", None), ("root", None), ("json", False)):
        if not hasattr(args, k):
            setattr(args, k, v)
    return args


def load_script(name: str):
    """Import a sibling script by file name. `yield` is a Python keyword, so yield.py is loaded here."""
    return importlib.import_module(name)


# --------------------------------------------------------------------------- the run

def run(kind: str, g: Grant, home: Path, pool: Optional[int], settings: Optional[str], dry_run: bool,
        now=None, days: int = 30) -> Dict[str, Any]:
    out: Dict[str, Any] = {"kind": kind, "grant": g.summary(), "steps": []}
    if g.paused():
        out["stopped"] = "paused: the Steward does nothing while %s says paused" % (g.pause_path() or "the pause file")
        return out
    y = load_script("yield")
    diag = load_script("diagnose")
    alloc = load_script("allocate")
    evo = load_script("evolve")
    rep = y.report(home, days=days, now=now, rules=g.rules)
    out["yield"] = rep
    out["steps"].append("yield report")
    d = diag.report(home, days=days, now=now, g=g, yield_report=rep)
    out["diagnosis"] = d
    out["steps"].append("diagnosis")
    if pool is not None:
        plan = alloc.plan(home, pool, g, settings_path=settings, dry_run=dry_run, now=now, days=days,
                          yield_report=rep, diagnosis=d)
        out["allocation"] = plan
        out["steps"].append("allocation plan" + (" (dry run)" if dry_run else ""))
    else:
        out["allocation"] = None
        out["steps"].append("allocation skipped: no --pool given")
    out["experiments"] = evo.status(home, g, now=now)
    out["steps"].append("experiment status")
    out["verdicts"] = evo.verdict(home, g, now=now, write=not dry_run)
    out["steps"].append("experiment verdicts")
    if kind == "weekly":
        out["proposals"] = evo.propose(home, g, now=now, days=days, diagnosis=d)
        out["steps"].append("experiment proposals")
    return out


def render_show(s: Dict[str, Any]) -> str:
    L = ["Steward mode: %s" % s["mode"]]
    if s["mode"] == "steward":
        L.append("steward mode is on for %d lever%s: %s" % (len(s["levers"]), "" if len(s["levers"]) == 1 else "s", ", ".join(s["levers"]) or "none"))
    else:
        L.append("propose mode: every Steward command prints what it would do and applies nothing")
    b = s["bounds"]
    L.append("searches %s to %s per run, max daily shift %d%%; daily cap %s to %s; exploration share %d%%" % (
        b["searches"]["min"], b["searches"]["max"], round((b["searches"]["max-daily-shift"] or 0) * 100),
        b["daily-cap"]["min"], b["daily-cap"]["max"], round((b["exploration-share"] or 0) * 100)))
    L.append("models: %s (ceiling %s); cadence: %s" % (", ".join(b["models"]), s["model_ceiling"], ", ".join(b["cadence"])))
    L.append("always needs the person: %s" % ", ".join(s["requires_approval"]))
    for p in s["problems"]:
        L.append("note: " + p)
    return "\n".join(L)


def render_run(o: Dict[str, Any]) -> str:
    L = ["Steward %s run, mode %s" % (o["kind"], o["grant"]["mode"])]
    if o.get("stopped"):
        L.append(o["stopped"])
        return "\n".join(L)
    y = load_script("yield")
    L.append(y.render(o["yield"]))
    diag = load_script("diagnose")
    L.append(diag.render(o["diagnosis"]))
    if o.get("allocation"):
        L.append(load_script("allocate").render(o["allocation"]))
    evo = load_script("evolve")
    L.append(evo.render_status(o["experiments"]))
    L.append(evo.render_verdicts(o["verdicts"]))
    if o.get("proposals") is not None:
        L.append(evo.render_proposals(o["proposals"]))
    return "\n\n".join(x for x in L if x)


def main(argv: Optional[List[str]] = None) -> int:
    common = common_flags()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", parents=[common])
    c = sub.add_parser("check", parents=[common]); c.add_argument("lever")
    r = sub.add_parser("run", parents=[common]); r.add_argument("kind", choices=["nightly", "weekly"])
    r.add_argument("--pool", type=int); r.add_argument("--settings"); r.add_argument("--dry-run", action="store_true")
    r.add_argument("--days", type=int, default=30)
    args = parse_args(ap, argv)
    if args is None:
        return 0
    try:
        home = Path(args.home).expanduser() if args.home else oc.otto_home()
        g = grant(args.grant, home, Path(args.root).expanduser() if args.root else None)
        now = oc.parse_when(args.now) if args.now else None
        if args.cmd == "show":
            s = g.summary()
            print(json.dumps(s, indent=2) if args.json else render_show(s))
        elif args.cmd == "check":
            ok, why = g.why(args.lever)
            print(json.dumps({"lever": args.lever, "allowed": ok, "reason": why}) if args.json else
                  "%s: %s (%s)" % (args.lever, "allowed" if ok else "propose only", why))
        else:
            o = run(args.kind, g, home, args.pool, args.settings, args.dry_run, now, args.days)
            print(json.dumps(o, indent=2, default=str) if args.json else render_run(o))
    except Exception as e:  # fail open
        oc.log_error("steward: %s" % e)
        oc.eprint("steward: %s (logged; nothing was changed)" % oc.short(e, 200))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
