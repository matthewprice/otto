#!/usr/bin/env python3
"""Find the automations you already have, and draft registry notes for them.

  discover.py scan  [--project DIR] [--home DIR] [--now ISO] [--json]
  discover.py draft ID [--name NAME] [--expected-by HH:MM] [--success-file PATTERN] [--force] [--home DIR]

Sources, in order:
  crontab              lines that call claude or Otto's runner
  launchd              ~/Library/LaunchAgents/*.plist whose program calls claude or the runner
  systemd              ~/.config/systemd/user/*.timer with a matching .service
  desktop              ~/.claude/scheduled-tasks/<name>/SKILL.md (name and description only; the
                       schedule lives in the app, so the skill asks for it)
  session              <project>/.claude/scheduled_tasks.json (tasks a session asked to keep)
  actions              <project>/.github/workflows/*.yml with a schedule trigger that run Claude
  transcripts          headless sessions under ~/.claude/projects that recur at the same hour on
                       three or more days: inferred, and labelled as such
Cloud routines are only listable inside a session (/schedule list), so they are not scanned.

`scan` writes nothing. `draft` writes one registry note, which is Otto's own file. Candidates are
matched to the registry by name and by command; a match whose live schedule or command differs
from the note is reported as drift with the proposed note change.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import plistlib
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import health  # noqa: E402
import otto_common as oc  # noqa: E402

CLAUDE_RE = re.compile(r"(^|[\s/\"'=])(claude|run\.py)\b")
DOW_NAMES = {"sun": 6, "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5}


# --------------------------------------------------------------------------- schedule parsing

def _expand_field(field: str, lo: int, hi: int) -> Optional[List[int]]:
    """A cron field into a sorted list of ints, or None for anything with a step or a name."""
    out = set()
    for part in field.split(","):
        part = part.strip()
        if part == "*":
            return list(range(lo, hi + 1))
        m = re.fullmatch(r"(\d+)-(\d+)", part)
        if m:
            out.update(range(int(m.group(1)), int(m.group(2)) + 1))
            continue
        if re.fullmatch(r"\d+", part):
            out.add(int(part))
            continue
        return None
    return sorted(x for x in out if lo <= x <= hi)


def parse_cron(expr: str) -> Dict[str, Any]:
    """Five-field cron to Otto's schedule shape. Interval and stepped schedules keep the cron only."""
    f = expr.split()
    sched: Dict[str, Any] = {"kind": "unknown", "cron": expr.strip()}
    if len(f) != 5:
        return sched
    minute, hour, dom, mon, dow = f
    if "/" in minute or "/" in hour or minute == "*" or hour == "*":
        sched["kind"] = "interval"
        return sched
    mins, hours = _expand_field(minute, 0, 59), _expand_field(hour, 0, 23)
    if not mins or not hours or len(mins) != 1 or len(hours) != 1 or dom != "*" or mon != "*":
        sched["kind"] = "irregular"
        return sched
    days = _expand_field(dow, 0, 7)
    if days is None:
        sched["kind"] = "irregular"
        return sched
    days = sorted({(d - 1) % 7 for d in days})  # cron 0/7 = Sunday -> Otto 6
    sched.update({"kind": "calendar", "time": "%02d:%02d" % (hours[0], mins[0]), "days": days})
    return sched


def days_label(days: List[int]) -> Any:
    if sorted(days) == list(range(7)):
        return "daily"
    if sorted(days) == [0, 1, 2, 3, 4]:
        return "weekdays"
    return [oc.DAYS[d] for d in sorted(days)]


def guess_name(command: str, fallback: str) -> str:
    m = re.search(r"run\.py\s+([A-Za-z0-9_.\-]+)", command)
    if m:
        return oc.slug(m.group(1))
    m = re.search(r"(?:^|\s|\")(/[a-z][a-z0-9:_\-]+)", command)
    if m:
        return oc.slug(m.group(1).lstrip("/").replace(":", "-"))
    return oc.slug(fallback)


def _cand(cid: str, surface: str, source: str, name: str, sched: Dict[str, Any], command: str = "",
          cwd: str = "", evidence: str = "", inferred: bool = False) -> Dict[str, Any]:
    return {"id": cid, "surface": surface, "source": source, "name": name, "schedule": sched,
            "command": oc.short(command, 200), "cwd": cwd, "evidence": oc.short(evidence, 200), "inferred": inferred}


# --------------------------------------------------------------------------- sources

def scan_crontab() -> List[Dict[str, Any]]:
    try:
        p = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    n = 0
    for line in (p.stdout or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" in s.split()[0]:
            continue
        f = s.split(None, 5)
        if len(f) < 6 or not CLAUDE_RE.search(f[5]):
            continue
        n += 1
        cmd = f[5]
        out.append(_cand("cron-%d" % n, "local-cli", "crontab", guess_name(cmd, "cron-job-%d" % n),
                         parse_cron(" ".join(f[:5])), cmd, "", "crontab line %d" % n))
    return out


def scan_launchd(agents_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    d = agents_dir or (Path.home() / "Library/LaunchAgents")
    out = []
    for p in sorted(d.glob("*.plist")) if d.is_dir() else []:
        try:
            with open(p, "rb") as fh:
                pl = plistlib.load(fh)
        except Exception:
            continue
        args = pl.get("ProgramArguments") or ([pl["Program"]] if pl.get("Program") else [])
        cmd = " ".join(str(a) for a in args)
        if not CLAUDE_RE.search(cmd):
            continue
        label = str(pl.get("Label") or p.stem)
        sched: Dict[str, Any] = {"kind": "unknown"}
        cal = pl.get("StartCalendarInterval")
        if isinstance(cal, dict):
            cal = [cal]
        if isinstance(cal, list) and cal:
            hours = {int(c.get("Hour", 0)) for c in cal}
            mins = {int(c.get("Minute", 0)) for c in cal}
            wd = [c.get("Weekday") for c in cal]
            days = list(range(7)) if any(w is None for w in wd) else sorted({(int(w) - 1) % 7 for w in wd})
            if len(hours) == 1 and len(mins) == 1:
                sched = {"kind": "calendar", "time": "%02d:%02d" % (hours.pop(), mins.pop()), "days": days}
            else:
                sched = {"kind": "irregular", "detail": "%d calendar entries" % len(cal)}
        elif pl.get("StartInterval"):
            sched = {"kind": "interval", "detail": "every %s seconds" % pl["StartInterval"]}
        name = guess_name(cmd, label.split(".")[-1])
        out.append(_cand("launchd-" + oc.slug(label), "local-cli", "launchd", name, sched, cmd,
                         str(pl.get("WorkingDirectory") or ""), p.name))
    return out


def _parse_oncalendar(spec: str) -> Dict[str, Any]:
    s = spec.strip()
    low = s.lower()
    if low in ("daily", "weekly", "hourly"):
        return {"kind": "calendar" if low != "hourly" else "interval", "time": "00:00", "days": list(range(7)) if low == "daily" else [0], "detail": low}
    m = re.fullmatch(r"(?:([A-Za-z,.\-]+)\s+)?\*-\*-\*\s+(\d{1,2}):(\d{2})(?::\d{2})?", s)
    if not m:
        return {"kind": "irregular", "detail": s}
    days = list(range(7))
    if m.group(1):
        days = []
        for part in m.group(1).split(","):
            if ".." in part:
                a, b = part.split("..")
                ia, ib = DOW_NAMES.get(a[:3].lower()), DOW_NAMES.get(b[:3].lower())
                if ia is not None and ib is not None:
                    days.extend(range(ia, ib + 1))
            elif part[:3].lower() in DOW_NAMES:
                days.append(DOW_NAMES[part[:3].lower()])
        days = sorted(set(days)) or list(range(7))
    return {"kind": "calendar", "time": "%02d:%s" % (int(m.group(2)), m.group(3)), "days": days}


def scan_systemd(unit_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    d = unit_dir or (Path.home() / ".config/systemd/user")
    out = []
    for t in sorted(d.glob("*.timer")) if d.is_dir() else []:
        svc = t.with_suffix(".service")
        if not svc.exists():
            continue
        text = svc.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^ExecStart=(.*)$", text, re.M)
        cmd = m.group(1).strip() if m else ""
        if not CLAUDE_RE.search(cmd):
            continue
        tt = t.read_text(encoding="utf-8", errors="replace")
        mc = re.search(r"^OnCalendar=(.*)$", tt, re.M)
        sched = _parse_oncalendar(mc.group(1)) if mc else {"kind": "unknown"}
        mw = re.search(r"^WorkingDirectory=(.*)$", text, re.M)
        out.append(_cand("systemd-" + oc.slug(t.stem), "local-cli", "systemd", guess_name(cmd, t.stem), sched, cmd,
                         mw.group(1).strip() if mw else "", t.name))
    return out


def scan_desktop(claude_home: Optional[Path] = None) -> List[Dict[str, Any]]:
    d = (claude_home or (Path.home() / ".claude")) / "scheduled-tasks"
    out = []
    for p in sorted(d.glob("*/SKILL.md")) if d.is_dir() else []:
        try:
            fm, _ = oc.read_frontmatter(p)
        except OSError:
            continue
        name = oc.slug(fm.get("name") or p.parent.name)
        out.append(_cand("desktop-" + name, "desktop-task", "desktop", name, {"kind": "unknown", "detail": "set in the Desktop app"},
                         "", "", oc.short(fm.get("description") or p.parent.name, 120)))
    return out


def scan_session_tasks(project: Path) -> List[Dict[str, Any]]:
    p = project / ".claude" / "scheduled_tasks.json"
    data = oc.read_json(p, None)
    if not data:
        return []
    items = data if isinstance(data, list) else (data.get("tasks") if isinstance(data, dict) else None) or []
    out = []
    for i, t in enumerate(items if isinstance(items, list) else []):
        if not isinstance(t, dict):
            continue
        cron = str(t.get("cron") or t.get("schedule") or "")
        prompt = str(t.get("prompt") or t.get("command") or "")
        name = guess_name(prompt, t.get("name") or t.get("id") or "session-task-%d" % (i + 1))
        out.append(_cand("session-" + name, "loop", "session", name, parse_cron(cron) if cron else {"kind": "unknown"},
                         "", str(project), "%s (fires only while a session is open)" % p.name))
    return out


def scan_workflows(project: Path) -> List[Dict[str, Any]]:
    out = []
    for p in sorted(glob.glob(str(project / ".github/workflows/*.y*ml"))):
        text = Path(p).read_text(encoding="utf-8", errors="replace")
        if "claude" not in text.lower():
            continue
        crons = re.findall(r"cron:\s*['\"]?([^'\"\n#]+)", text)
        if not crons:
            continue
        name = oc.slug(Path(p).stem)
        sched = parse_cron(crons[0].strip())
        sched["note"] = "GitHub cron runs in UTC"
        out.append(_cand("actions-" + name, "github-actions", "actions", name, sched, "", str(project), Path(p).name))
    return out


def _first_line_meta(path: Path) -> Tuple[Optional[datetime], str]:
    """Timestamp and entrypoint from the head of a transcript, reading at most a few lines."""
    ts, ep = None, ""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for _ in range(6):
                line = fh.readline()
                if not line:
                    break
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(o, dict):
                    continue
                if o.get("timestamp") and ts is None:
                    ts = oc.parse_epoch_or_iso(o["timestamp"])
                if o.get("entrypoint") and not ep:
                    ep = str(o["entrypoint"])
                if ts and ep:
                    break
    except OSError:
        pass
    return ts, ep


def scan_transcripts(claude_home: Optional[Path] = None, days: int = 30, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    root = (claude_home or (Path.home() / ".claude")) / "projects"
    now = now or oc.parse_when(None)
    since = now - timedelta(days=days)
    groups: Dict[Tuple[str, int], List[datetime]] = defaultdict(list)
    for proj in sorted(root.iterdir()) if root.is_dir() else []:
        if not proj.is_dir():
            continue
        for t in proj.glob("*.jsonl"):
            try:
                if datetime.fromtimestamp(t.stat().st_mtime, tz=now.tzinfo) < since:
                    continue
            except OSError:
                continue
            ts, ep = _first_line_meta(t)
            if ts is None or "sdk" not in ep.lower():
                continue
            local = ts.astimezone(now.tzinfo)
            groups[(proj.name, local.hour)].append(local)
    out = []
    for (proj, hour), stamps in sorted(groups.items()):
        dates = {s.date() for s in stamps}
        if len(dates) < 3:
            continue
        minute = int(oc.median([s.minute for s in stamps]) or 0)
        days_seen = sorted({s.weekday() for s in stamps})
        short = re.sub(r"^-+", "", proj).split("-")[-1] or proj
        name = oc.slug("%s-%02dh" % (short, hour))
        out.append(_cand("transcript-" + name, "local-cli", "transcripts", name,
                         {"kind": "calendar", "time": "%02d:%02d" % (hour, minute), "days": days_seen},
                         "", "", "%d headless sessions on %d days in the last %d days, project %s" % (len(stamps), len(dates), days, proj),
                         inferred=True))
    return out


# --------------------------------------------------------------------------- registry matching

def _norm_cmd(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def match_registry(cands: List[Dict[str, Any]], autos: List[Dict[str, Any]]) -> None:
    by_name = {a["name"]: a for a in autos}
    by_cmd = {_norm_cmd(a.get("command")): a for a in autos if a.get("command")}
    for c in cands:
        a = by_name.get(c["name"])
        if a is None and c["command"]:
            key = _norm_cmd(c["command"])
            a = by_cmd.get(key) or next((x for k, x in by_cmd.items() if k and k in key), None)
        c["registry"] = a["name"] if a else None
        c["drift"] = []
        if not a:
            continue
        s = c["schedule"]
        if s.get("kind") == "calendar":
            if a.get("days") is not None and health.normalize_days(a.get("days")) != s["days"]:
                c["drift"].append("days: live schedule is %s, note says %s" % (days_label(s["days"]), a.get("days")))
            try:
                eh, em = oc.parse_hhmm(a.get("expected_by"))
                rh, rm = oc.parse_hhmm(s["time"])
                if (rh, rm) >= (eh, em):
                    c["drift"].append("time: live schedule starts at %s, note expects output by %s" % (s["time"], a.get("expected_by")))
                if a.get("run_at") and str(a.get("run_at")) != s["time"]:
                    c["drift"].append("run_at: live schedule %s, note says %s" % (s["time"], a.get("run_at")))
            except ValueError:
                pass
        if c["command"] and a.get("command") and _norm_cmd(a["command"]) not in _norm_cmd(c["command"]):
            c["drift"].append("command differs from the note")
        if c["surface"] != a.get("surface"):
            c["drift"].append("surface: found on %s, note says %s" % (c["surface"], a.get("surface")))


def scan(home: Path, project: Path, now: Optional[datetime] = None, claude_home: Optional[Path] = None,
         agents_dir: Optional[Path] = None, unit_dir: Optional[Path] = None, crontab: bool = True) -> Dict[str, Any]:
    cfg = oc.load_config(home)
    now = now or oc.parse_when(None, oc.get_tz(cfg.get("timezone")))
    cands: List[Dict[str, Any]] = []
    if crontab:
        cands += scan_crontab()
    cands += scan_launchd(agents_dir)
    cands += scan_systemd(unit_dir)
    cands += scan_desktop(claude_home)
    cands += scan_session_tasks(project)
    cands += scan_workflows(project)
    cands += scan_transcripts(claude_home, 30, now)
    autos, problems = health.load_registry(home, cfg)
    match_registry(cands, autos)
    seen = {c["name"] for c in cands} | {c["registry"] for c in cands if c.get("registry")}
    unseen = [a["name"] for a in autos if a["name"] not in seen]
    return {"generated_at": oc.iso(now), "project": str(project), "candidates": cands,
            "new": [c["id"] for c in cands if not c["registry"]],
            "drifted": [c["id"] for c in cands if c["drift"]],
            "registered_but_not_found": unseen, "registry_problems": problems,
            "manual": ["Cloud routines: run /schedule list in this session and tell Otto the names and cadences.",
                       "Desktop tasks: the schedule is only in the app; open each task and read its schedule."]}


# --------------------------------------------------------------------------- drafting

def draft(home: Path, cand: Dict[str, Any], name: Optional[str], expected_by: Optional[str],
          success_file: Optional[str], today: date, force: bool = False) -> Path:
    cfg = oc.load_config(home)
    name = oc.slug(name or cand["name"])
    s = cand["schedule"]
    fm: Dict[str, Any] = {"name": name, "surface": cand["surface"]}
    if s.get("kind") == "calendar":
        fm["days"] = days_label(s["days"])
        fm["run_at"] = s["time"]
        if not expected_by:
            h, m = oc.parse_hhmm(s["time"])
            t = datetime(2000, 1, 1, h, m) + timedelta(minutes=30)
            expected_by = "%02d:%02d" % (t.hour, t.minute)
    else:
        fm["days"] = "daily"
    fm["expected_by"] = expected_by or "09:00"
    tzname = cfg.get("timezone") or getattr(datetime.now().astimezone().tzinfo, "key", "") or ""
    if tzname:
        fm["timezone"] = tzname
    if cand["command"] and cand["surface"] == "local-cli":
        fm["command"] = cand["command"]
    if cand["cwd"]:
        fm["cwd"] = cand["cwd"]
    if success_file:
        fm["success_file"] = success_file
    fm["registered"] = today.isoformat()
    body = ["Drafted by /otto:discover from %s (%s)." % (cand["source"], cand["evidence"] or cand["id"])]
    if s.get("kind") != "calendar":
        body.append("Schedule was not readable (%s). Set days, run_at and expected_by by hand." % (s.get("detail") or s.get("cron") or s.get("kind")))
    if s.get("note"):
        body.append(s["note"] + ".")
    if cand.get("inferred"):
        body.append("This automation was inferred from recurring headless sessions; confirm it exists before trusting its status.")
    if not success_file:
        body.append("No success_file yet. Add the file this run leaves behind so a miss can be told from a quiet success.")
    d = oc.vault_dir(cfg, home) / "Automations"
    d.mkdir(parents=True, exist_ok=True)
    path = d / (name + ".md")
    if path.exists() and not force:
        raise FileExistsError("registry note %s already exists; pass --force to overwrite" % path)
    oc.write_note(path, fm, "\n".join(body) + "\n")
    return path


def render_table(rep: Dict[str, Any]) -> str:
    L = ["Otto discover at %s" % rep["generated_at"]]
    if not rep["candidates"]:
        L.append("(no automations found in crontab, launchd, systemd, Desktop tasks, session tasks, workflows or transcripts)")
    for c in rep["candidates"]:
        s = c["schedule"]
        when = ("%s %s" % (days_label(s["days"]), s["time"])) if s.get("kind") == "calendar" else (s.get("detail") or s.get("cron") or s.get("kind"))
        state = "registered as %s" % c["registry"] if c["registry"] else "NEW"
        if c["drift"]:
            state += " (DRIFT: %s)" % "; ".join(c["drift"])
        L.append("%-28s %-15s %-10s %-22s %s" % (c["id"], c["surface"], c["source"], when, state))
        if c["command"]:
            L.append("%-28s   command: %s" % ("", c["command"][:90]))
    for n in rep["registered_but_not_found"]:
        L.append("note: %s is registered but no scheduler on this machine mentions it" % n)
    for m in rep["manual"]:
        L.append("manual: " + m)
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan"); s.add_argument("--project", default="."); s.add_argument("--now"); s.add_argument("--json", action="store_true")
    d = sub.add_parser("draft"); d.add_argument("id"); d.add_argument("--project", default=".")
    d.add_argument("--name"); d.add_argument("--expected-by"); d.add_argument("--success-file"); d.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    home = Path(args.home).expanduser() if args.home else oc.otto_home()
    project = Path(args.project).expanduser().resolve()
    if args.cmd == "scan":
        rep = scan(home, project, oc.parse_when(args.now) if args.now else None)
        print(json.dumps(rep, indent=2) if args.json else render_table(rep))
        return 0
    rep = scan(home, project)
    cand = next((c for c in rep["candidates"] if c["id"] == args.id), None)
    if not cand:
        oc.eprint("no candidate with id %r; run `discover.py scan` for the list" % args.id)
        return 2
    try:
        path = draft(home, cand, args.name, args.expected_by, args.success_file, date.today(), args.force)
    except FileExistsError as e:
        oc.eprint(str(e))
        return 3
    print("wrote %s" % path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
