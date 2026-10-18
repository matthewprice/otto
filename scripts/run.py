#!/usr/bin/env python3
"""otto-run: run one registered local automation under guard rails, and write the ledger row.

    run.py NAME                 run it
    run.py NAME --dry-run       say what would happen and print the command, run nothing
    run.py NAME --reset-breaker re-arm the circuit breaker after you fixed the cause

What it does, in order:
  1. Circuit breaker. After `breaker_threshold` consecutive failures the automation is stopped
     and stays stopped until you reset it. A broken login should cost three failed runs, not a day.
  2. Idempotency. If this cycle already produced its output, it records a skip and exits.
  3. Attempt cap. At most `attempt_cap_per_day` tries per cycle; the rest are skipped and recorded.
  4. Runs `claude -p` with --output-format json, a fresh --session-id, --permission-prompts none
     (anything that would prompt is denied, never left hanging), --max-turns, --max-budget-usd,
     an allowlist, and a hard timeout. It never uses --dangerously-skip-permissions.
  5. Judges the result against the registry (exit code, then the output file), writes one ledger
     row, updates the breaker, and tells you through the channel you chose.

The wrapper reads the result JSON for numbers and the stderr text only to classify the failure
into a short label (timeout, auth, rate_limit, budget, max_turns, permission, error). It stores
labels and numbers, never text.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import health  # noqa: E402
import ledger  # noqa: E402
import otto_common as oc  # noqa: E402


# --------------------------------------------------------------------------- helpers

def resolve_claude(cfg: Dict[str, Any]) -> Optional[str]:
    cands = [os.environ.get("CLAUDE_BIN"), cfg.get("claude_bin") or None, shutil.which("claude"),
             str(Path.home() / ".local/bin/claude"), "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def classify_failure(returncode: Optional[int], result: Dict[str, Any], stderr: str, timed_out: bool) -> str:
    if timed_out:
        return "timeout"
    status = result.get("api_error_status")
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limit"
    sub = str(result.get("subtype") or "")
    if sub == "error_max_turns":
        return "max_turns"
    if "budget" in sub:
        return "budget"
    low = (stderr or "").lower()
    if "authentication" in low or "401" in low or "please run /login" in low or "invalid api key" in low or "oauth" in low and "expired" in low:
        return "auth"
    if "rate limit" in low or "usage limit" in low or "429" in low:
        return "rate_limit"
    if "credit balance" in low or "billing" in low:
        return "budget"
    if result.get("permission_denials"):
        return "permission"
    return "error" if (returncode not in (0, None) or result.get("is_error")) else "none"


def last_json(text: str) -> Dict[str, Any]:
    """The result is one JSON object; tolerate leading noise or a JSON array of messages."""
    text = (text or "").strip()
    for candidate in (text, text[text.find("{"):] if "{" in text else "", text[text.find("["):] if "[" in text else ""):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
        if isinstance(obj, list):
            found = [x for x in obj if isinstance(x, dict) and x.get("type") == "result"]
            if found:
                return found[-1]
    return {}


def notify(cfg: Dict[str, Any], home: Path, message: str) -> None:
    mode = str(cfg.get("notify") or "none")
    message = oc.short(message, 180)
    try:
        if mode == "macos" and sys.platform == "darwin":
            subprocess.run(["osascript", "-e", 'display notification %s with title "Otto"' % json.dumps(message)], timeout=10, check=False)
        elif mode == "file":
            with open(home / "notifications.log", "a", encoding="utf-8") as fh:
                fh.write("%s %s\n" % (datetime.now().astimezone().isoformat(timespec="seconds"), message))
        elif mode == "command" and cfg.get("notify_command"):
            env = dict(os.environ, OTTO_MESSAGE=message)
            subprocess.run(shlex.split(str(cfg["notify_command"])), env=env, timeout=30, check=False)
    except Exception as e:  # a failed notification must never fail the run
        oc.log_error("notify failed: %s" % e.__class__.__name__, home)


# Each credential command sets one variable and removes the other, so a job bills exactly the
# account you configured even when the scheduler's environment carries both.
CREDENTIALS = (("token_cmd", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"),
               ("api_key_cmd", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"))


def credential_source(cfg: Dict[str, Any]) -> Optional[str]:
    """Which credential key is configured: token_cmd, api_key_cmd, None (inherit), or 'both' (an error)."""
    set_ = [key for key, _, _ in CREDENTIALS if str(cfg.get(key) or "").strip()]
    return "both" if len(set_) > 1 else (set_[0] if set_ else None)


def read_secret(cmd: str) -> Optional[str]:
    try:
        p = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=20)
        return p.stdout.strip() or None
    except Exception:
        return None


def apply_credential(cfg: Dict[str, Any], env: Dict[str, str]) -> None:
    for key, var, other in CREDENTIALS:
        cmd = str(cfg.get(key) or "").strip()
        if cmd:
            env.pop(other, None)
            secret = read_secret(cmd)
            if secret:
                env[var] = secret


# --------------------------------------------------------------------------- cycle logic

def target_cycle(a: Dict[str, Any], rows: List[Dict[str, Any]], cfg: Dict[str, Any], now: datetime,
                 home: Path) -> Tuple[Optional[datetime], Optional[datetime], str]:
    """Which cycle is this run for: the one that just passed without evidence (catch-up) or the next one?"""
    tz = oc.get_tz(a.get("timezone") or cfg.get("timezone"))
    hhmm = oc.parse_hhmm(a.get("expected_by"))
    days = health.normalize_days(a.get("days"))
    grace = timedelta(minutes=int(a.get("grace_min") or 15))
    inst = health.scheduled_instants(days, hhmm, tz, now.astimezone(tz), 2)
    nxt = health.next_instant(days, hhmm, tz, now.astimezone(tz))
    latest = inst[0] if inst else None
    prev = inst[1] if len(inst) > 1 else (latest - timedelta(days=1) if latest else None)
    if latest and now - latest <= timedelta(hours=12) and not cycle_done(a, rows, latest, prev, grace, tz, home):
        return latest, prev, "catch-up"
    return nxt, latest, "next"


def cycle_done(a: Dict[str, Any], rows: List[Dict[str, Any]], due: Optional[datetime], window_start: Optional[datetime],
               grace: timedelta, tz, home: Path) -> bool:
    if due is None:
        return False
    start = window_start or (due - timedelta(days=1))
    for r in rows:
        if r.get("automation") != a["name"] or r.get("kind") != "run":
            continue
        t = oc.parse_when(r.get("ts"), tz)
        if start < t <= due + grace and health.row_outcome(r) == "pass":
            art = health.check_artifact(a, due, start, home)
            if art is None or art["ok"]:
                return True
    art = health.check_artifact(a, due, start, home)
    return bool(art and art["ok"])


def attempts_in_cycle(a: Dict[str, Any], rows: List[Dict[str, Any]], start: datetime, tz) -> int:
    return sum(1 for r in rows if r.get("automation") == a["name"] and r.get("kind") == "run"
               and health.row_outcome(r) != "skipped" and oc.parse_when(r.get("ts"), tz) > start)


# --------------------------------------------------------------------------- main

def build_argv(a: Dict[str, Any], cfg: Dict[str, Any], claude: str, sid: str) -> List[str]:
    prompt = str(a.get("command") or "").strip()
    argv = [claude, "-p", prompt, "--output-format", "json", "--session-id", sid,
            "--permission-mode", str(a.get("permission_mode") or "acceptEdits"), "--permission-prompts", "none"]
    if a.get("max_turns"):
        argv += ["--max-turns", str(int(a["max_turns"]))]
    if a.get("max_budget_usd"):
        argv += ["--max-budget-usd", str(a["max_budget_usd"])]
    tools = health._as_list(a.get("allowed_tools"))
    if tools:
        argv += ["--allowedTools", ",".join(str(t) for t in tools)]
    if a.get("model"):
        argv += ["--model", str(a["model"])]
    return argv


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name")
    ap.add_argument("--home"); ap.add_argument("--now", help="testing only")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reset-breaker", action="store_true")
    args = ap.parse_args(argv)
    home = Path(args.home).expanduser() if args.home else oc.otto_home()
    oc.ensure_dirs(home)
    cfg = oc.load_config(home)
    name = oc.slug(args.name)
    autos, _ = health.load_registry(home, cfg)
    a = next((x for x in autos if x["name"] == name), None)
    if a is None:
        oc.eprint("otto-run: no registry note named %r in %s" % (name, oc.vault_dir(cfg, home) / "Automations"))
        return 2
    if a.get("surface") != "local-cli":
        oc.eprint("otto-run: %s is on surface %r; the wrapper only runs local-cli automations" % (name, a.get("surface")))
        return 2
    if not str(a.get("command") or "").strip():
        oc.eprint("otto-run: the registry note for %s has no `command`" % name)
        return 2
    tz = oc.get_tz(a.get("timezone") or cfg.get("timezone"))
    now = oc.parse_when(args.now, tz)

    bpath = oc.state_dir(home) / "breaker.json"
    if args.reset_breaker:
        with oc.file_lock(oc.state_dir(home) / "breaker.lock"):
            b = oc.read_json(bpath, {}) or {}
            b.pop(name, None)
            oc.write_json(bpath, b)
        ledger.add_event(home, "breaker_reset", "", automation=name)
        print("breaker reset for %s" % name)
        return 0

    rows = ledger.read_rows(home, since=now - timedelta(days=45), automation=name, kind="run")
    breaker = oc.read_json(bpath, {}) or {}
    cap = int(cfg.get("attempt_cap_per_day") or 2)
    threshold = int(cfg.get("breaker_threshold") or 3)
    due, window_start, mode = target_cycle(a, rows, cfg, now, home)
    grace = timedelta(minutes=int(a.get("grace_min") or 15))
    decision, reason = "run", ""
    if (breaker.get(name) or {}).get("open"):
        decision, reason = "skip", "breaker open"
    elif due is not None and cycle_done(a, rows, due, window_start, grace, tz, home):
        decision, reason = "skip", "already done this cycle"
    elif window_start is not None and attempts_in_cycle(a, rows, window_start, tz) >= cap:
        decision, reason = "skip", "attempt cap reached (%d)" % cap

    cred = credential_source(cfg)
    if cred == "both":
        oc.eprint("otto-run: set token_cmd or api_key_cmd in ~/.otto/otto.md, not both")
        return 2
    claude = resolve_claude(cfg)
    sid = str(uuid.uuid4())
    plan = {"automation": name, "decision": decision, "reason": reason, "cycle": mode, "due": oc.iso(due)}
    if args.dry_run:
        plan["credential"] = cred or "inherited environment"
        plan["command"] = build_argv(a, cfg, claude or "claude", sid)
        plan["claude_found"] = bool(claude)
        plan["timeout_min"] = float(a.get("timeout_min") or 30)
        print(json.dumps(plan, indent=2))
        return 0

    started = now
    if decision == "skip":
        ledger.upsert_run(home, {"ts": oc.iso(now), "automation": name, "surface": "local-cli", "source": "wrapper",
                                 "outcome": "skipped", "skipped_reason": reason, "exit": 0, "session_id": sid})
        if reason.startswith("attempt cap") or reason.startswith("breaker"):
            notify(cfg, home, "%s skipped: %s" % (name, reason))
        print("otto-run: %s skipped (%s)" % (name, reason))
        return 0 if reason.startswith("already") else 3

    if claude is None:
        ledger.upsert_run(home, {"ts": oc.iso(now), "automation": name, "surface": "local-cli", "source": "wrapper",
                                 "outcome": "fail", "exit": 127, "outcome_evidence": "claude binary not found", "session_id": sid})
        notify(cfg, home, "%s failed: claude binary not found" % name)
        oc.eprint("otto-run: claude binary not found. Set claude_bin in ~/.otto/otto.md")
        return 127

    lock = oc.state_dir(home) / ("run-%s.lock" % name)
    import fcntl
    lock.parent.mkdir(parents=True, exist_ok=True)
    lockfh = open(lock, "a+")
    try:
        fcntl.flock(lockfh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("otto-run: %s is already running" % name)
        return 0

    env = dict(os.environ)
    env["OTTO_AUTOMATION"] = name
    env["OTTO_HOME"] = str(home)
    apply_credential(cfg, env)
    cwd = os.path.expanduser(str(a.get("cwd") or "")) or None
    if cwd and not os.path.isdir(cwd):
        oc.eprint("otto-run: cwd %s does not exist" % cwd)
        return 2
    timeout_s = int(float(a.get("timeout_min") or 30) * 60)
    argv_ = build_argv(a, cfg, claude, sid)
    attempt = attempts_in_cycle(a, rows, window_start, tz) + 1 if window_start else 1
    timed_out = False
    out = err = ""
    rc: Optional[int] = None
    proc = subprocess.Popen(argv_, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout_s)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            out, err = proc.communicate(timeout=10)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                pass
            out, err = proc.communicate()
        rc = 124
    finally:
        fcntl.flock(lockfh.fileno(), fcntl.LOCK_UN)
        lockfh.close()

    result = last_json(out)
    kind = classify_failure(rc, result, err, timed_out)
    row = ledger.row_from_result(result, name, rc, "local-cli", oc.iso(started), attempt)
    row["session_id"] = row.get("session_id") or sid
    row["end_ts"] = oc.iso(datetime.now(tz))
    if row.get("duration_ms") is None:
        row["duration_ms"] = int((datetime.now(tz) - started).total_seconds() * 1000)

    outcome, evidence = "pass", ""
    if kind != "none":
        outcome, evidence = "fail", kind
    else:
        art = health.check_artifact(a, due or now, window_start or (now - timedelta(days=1)), home) if due else None
        if art is not None and not art["ok"]:
            outcome, evidence = "fail", "output check: " + "; ".join(art["reasons"])[:150]
    row["outcome"], row["outcome_evidence"] = outcome, evidence
    cred = oc.credential_from_env(env)
    if cred:
        row["credential"] = cred
    saved = ledger.upsert_run(home, row)

    # breaker
    with oc.file_lock(oc.state_dir(home) / "breaker.lock"):
        b = oc.read_json(bpath, {}) or {}
        hist = ledger.read_rows(home, since=now - timedelta(days=45), automation=name, kind="run")
        cf = health.consecutive_failures(hist)
        if outcome == "fail" and cf >= threshold and not (b.get(name) or {}).get("open"):
            b[name] = {"open": True, "since": oc.iso(datetime.now(tz)), "failures": cf, "reason": "%s, %d runs in a row" % (evidence or "failed", cf)}
            oc.write_json(bpath, b)
            ledger.add_event(home, "breaker_open", evidence, row["session_id"], name)
            notify(cfg, home, "%s stopped by the circuit breaker after %d failures (%s). Fix the cause, then: otto-run %s --reset-breaker" % (name, cf, evidence, name))
        elif outcome == "pass" and (b.get(name) or {}).get("open"):
            pass  # an open breaker is only closed by a person
    if outcome == "fail":
        notify(cfg, home, "%s failed (%s), attempt %d" % (name, evidence or "error", attempt))
    cost = saved.get("cost_usd")
    print("otto-run: %s %s in %.1f min%s%s" % (name, outcome, (saved.get("duration_ms") or 0) / 60000.0,
                                               (", $%.2f" % cost) if cost is not None else "", (" (%s)" % evidence) if evidence else ""))
    with open(oc.state_dir(home) / "runs.log", "a", encoding="utf-8") as fh:
        fh.write("%s %s %s exit=%s\n" % (oc.iso(datetime.now(tz)), name, outcome, rc))
    return 0 if outcome == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
