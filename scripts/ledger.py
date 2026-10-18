#!/usr/bin/env python3
"""Otto's ledger: one JSON line per run or event, kept by month under ~/.otto/ledger/.

Rows hold numbers, automation names, and short enum-like labels. The schema is an
allowlist: any other key (for example a stray `last_assistant_message`) is dropped
before it reaches disk. That is the privacy guarantee, and tests/test_ledger.py
checks it.

Usage:
  ledger.py add --json '{...}'                 append or merge a run row
  ledger.py from-result --automation NAME --file RESULT.json [--exit N]
  ledger.py session --transcript FILE [--automation NAME]
  ledger.py event --event NAME [--detail TEXT] [--session-id ID]
  ledger.py query [--since 7d] [--automation NAME] [--kind run|event] [--json]
  ledger.py stats
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import otto_common as oc  # noqa: E402

RUN_KEYS = {
    "kind", "ts", "end_ts", "automation", "surface", "source", "session_id", "entrypoint",
    "version", "models", "tokens", "cost_usd", "cost_basis", "duration_ms", "num_turns",
    "exit", "is_error", "stop_reason", "terminal_reason", "outcome", "outcome_evidence", "attempt",
    "permission_denials", "prefix_tokens", "skills", "mcp", "note", "skipped_reason", "credential",
}
CREDENTIALS = {"api_key", "subscription"}
EVENT_KEYS = {"kind", "ts", "event", "detail", "session_id", "automation"}
OUTCOMES = {"pass", "fail", "skipped", "unknown"}
SOURCE_RANK = {"wrapper": 3, "manual": 2, "hook": 1}
TOKEN_KEYS = ("input", "output", "cache_read", "cache_create")


def _num(x: Any) -> Optional[float]:
    try:
        if x is None or isinstance(x, bool):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _clean_models(models: Any) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(models, dict):
        return out
    for name, v in models.items():
        if not isinstance(v, dict):
            continue
        rec: Dict[str, Any] = {}
        for k in TOKEN_KEYS + ("messages",):
            n = _num(v.get(k))
            if n is not None:
                rec[k] = int(n)
        c = _num(v.get("cost_usd"))
        if c is not None:
            rec["cost_usd"] = round(c, 6)
        out[oc.short(name, 48)] = rec
    return out


def sanitize_run(row: Dict[str, Any]) -> Dict[str, Any]:
    r: Dict[str, Any] = {"kind": "run"}
    for k in RUN_KEYS:
        if k not in row or row[k] is None or k == "kind":
            continue
        v = row[k]
        if k in ("ts", "end_ts"):
            r[k] = oc.short(v, 40)
        elif k == "automation":
            r[k] = oc.slug(v)
        elif k == "models":
            r[k] = _clean_models(v)
        elif k == "tokens":
            if isinstance(v, dict):
                r[k] = {t: int(_num(v.get(t)) or 0) for t in TOKEN_KEYS}
        elif k in ("skills", "mcp"):
            if isinstance(v, dict):
                r[k] = {oc.short(a, 64): int(_num(b) or 0) for a, b in list(v.items())[:40]}
        elif k in ("cost_usd",):
            n = _num(v)
            if n is not None:
                r[k] = round(n, 6)
        elif k in ("duration_ms", "num_turns", "exit", "attempt", "permission_denials", "prefix_tokens"):
            n = _num(v)
            if n is not None:
                r[k] = int(n)
        elif k == "is_error":
            r[k] = bool(v)
        elif k in ("note", "outcome_evidence", "skipped_reason"):
            r[k] = oc.short(v, 200)
        elif k == "outcome":
            r[k] = v if v in OUTCOMES else "unknown"
        elif k == "credential":
            if v in CREDENTIALS:
                r[k] = v
        else:
            r[k] = oc.short(v, 64)
    if "tokens" not in r and r.get("models"):
        t = {k: 0 for k in TOKEN_KEYS}
        for m in r["models"].values():
            for k in TOKEN_KEYS:
                t[k] += int(m.get(k, 0))
        r["tokens"] = t
    r.setdefault("outcome", "unknown")
    r.setdefault("source", "manual")
    return r


def sanitize_event(row: Dict[str, Any]) -> Dict[str, Any]:
    e: Dict[str, Any] = {"kind": "event"}
    for k in EVENT_KEYS:
        if k in row and row[k] is not None and k != "kind":
            e[k] = oc.slug(row[k]) if k in ("automation", "event") else oc.short(row[k], 120 if k == "detail" else 64)
    return e


def _local(ts: Optional[str]) -> datetime:
    return oc.parse_when(ts).astimezone() if ts else datetime.now().astimezone()


def month_file(home: Path, ts: Optional[str]) -> Path:
    d = _local(ts)
    return oc.ledger_dir(home) / ("%04d-%02d.jsonl" % (d.year, d.month))


def _read_file(p: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not p.exists():
        return rows
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
                rows.append(o)
    return rows


def _write_file(p: Path, rows: Iterable[Dict[str, Any]]) -> None:
    oc.atomic_write(p, "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def _lock(home: Path):
    return oc.file_lock(oc.state_dir(home) / "ledger.lock")


def merge_rows(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """Higher-ranked source wins per field; the lower-ranked source fills gaps."""
    ro = SOURCE_RANK.get(old.get("source", "manual"), 1)
    rn = SOURCE_RANK.get(new.get("source", "manual"), 1)
    hi, lo = (new, old) if rn >= ro else (old, new)
    out = dict(lo)
    for k, v in hi.items():
        if k == "outcome" and v == "unknown" and lo.get("outcome") not in (None, "unknown"):
            continue
        out[k] = v
    # keep the earliest start and the latest end
    if old.get("ts") and new.get("ts"):
        out["ts"] = min(old["ts"], new["ts"], key=lambda t: _local(t))
    if old.get("end_ts") and new.get("end_ts"):
        out["end_ts"] = max(old["end_ts"], new["end_ts"], key=lambda t: _local(t))
    out["source"] = hi.get("source", "manual")
    return out


def upsert_run(home: Path, row: Dict[str, Any]) -> Dict[str, Any]:
    oc.ensure_dirs(home)
    r = sanitize_run(row)
    r.setdefault("ts", datetime.now().astimezone().isoformat(timespec="seconds"))
    sid = r.get("session_id")
    with _lock(home):
        target = month_file(home, r["ts"])
        if sid:
            # a session can straddle midnight at a month boundary; look in the neighbours too
            first = _local(r["ts"]).replace(day=1)
            months = [first, (first - timedelta(days=1)).replace(day=1), (first + timedelta(days=32)).replace(day=1)]
            candidates = [oc.ledger_dir(home) / ("%04d-%02d.jsonl" % (d.year, d.month)) for d in months]
            for p in candidates:
                rows = _read_file(p)
                for i, ex in enumerate(rows):
                    if ex.get("kind") == "run" and ex.get("session_id") == sid:
                        merged = merge_rows(ex, r)
                        rows[i] = merged
                        _write_file(p, rows)
                        return merged
        rows = _read_file(target)
        rows.append(r)
        _write_file(target, rows)
        return r


def add_event(home: Path, event: str, detail: str = "", session_id: str = "", automation: str = "") -> Dict[str, Any]:
    oc.ensure_dirs(home)
    e = sanitize_event({
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "event": event, "detail": detail, "session_id": session_id, "automation": automation,
    })
    with _lock(home):
        p = month_file(home, e["ts"])
        rows = _read_file(p)
        rows.append(e)
        _write_file(p, rows)
    return e


def read_rows(home: Path, since: Optional[datetime] = None, until: Optional[datetime] = None,
              automation: Optional[str] = None, kind: Optional[str] = None) -> List[Dict[str, Any]]:
    d = oc.ledger_dir(home)
    if not d.exists():
        return []
    out: List[Dict[str, Any]] = []
    for p in sorted(d.glob("*.jsonl")):
        for r in _read_file(p):
            if kind and r.get("kind") != kind:
                continue
            if automation and r.get("automation") != automation:
                continue
            try:
                t = _local(r.get("ts"))
            except ValueError:
                continue
            if since and t < since:
                continue
            if until and t > until:
                continue
            out.append(r)
    out.sort(key=lambda r: _local(r.get("ts")))
    return out


# --------------------------------------------------------------------------- builders

def row_from_result(result: Any, automation: str, exit_code: Optional[int], surface: str = "local-cli",
                    started: Optional[str] = None, attempt: Optional[int] = None) -> Dict[str, Any]:
    """Build a run row from `claude -p --output-format json` output."""
    if isinstance(result, list):
        found = [x for x in result if isinstance(x, dict) and x.get("type") == "result"]
        result = found[-1] if found else {}
    if not isinstance(result, dict):
        result = {}
    models: Dict[str, Dict[str, Any]] = {}
    mu = result.get("modelUsage") or result.get("model_usage") or {}
    if isinstance(mu, dict):
        for name, v in mu.items():
            if not isinstance(v, dict):
                continue

            def g(*keys: str) -> int:
                for k in keys:
                    if k in v and v[k] is not None:
                        return int(_num(v[k]) or 0)
                return 0
            models[name] = {
                "input": g("inputTokens", "input_tokens", "input"),
                "output": g("outputTokens", "output_tokens", "output"),
                "cache_read": g("cacheReadInputTokens", "cache_read_input_tokens", "cache_read"),
                "cache_create": g("cacheCreationInputTokens", "cache_creation_input_tokens", "cache_create"),
            }
            c = _num(v.get("costUSD", v.get("cost_usd")))
            if c is not None:
                models[name]["cost_usd"] = c
    cost = _num(result.get("total_cost_usd", result.get("totalCostUSD")))
    if cost is None and models and all("cost_usd" in m for m in models.values()):
        cost = sum(m["cost_usd"] for m in models.values())
    denials = result.get("permission_denials")
    row: Dict[str, Any] = {
        "ts": started, "automation": automation, "surface": surface, "source": "wrapper",
        "session_id": result.get("session_id") or result.get("sessionId"),
        "models": models, "cost_usd": cost, "cost_basis": "reported" if cost is not None else None,
        "duration_ms": result.get("duration_ms"), "num_turns": result.get("num_turns"),
        "exit": exit_code, "is_error": bool(result.get("is_error")) if result else None,
        "stop_reason": result.get("subtype"), "terminal_reason": result.get("terminal_reason"), "attempt": attempt,
        "permission_denials": len(denials) if isinstance(denials, list) else None,
    }
    return row


def row_from_transcript(path: Path, automation: Optional[str] = None, surface: str = "interactive") -> Optional[Dict[str, Any]]:
    import transcript
    s = transcript.summarize(path)
    if not s.get("session_id") or s.get("truncated"):
        return None
    # Tokens come from the per-message usage blocks (current). Cost comes from the transcript's
    # `cost-state` snapshot when there is one; that snapshot can lag the end of a long session and
    # includes small auxiliary calls the message log omits, so it is labelled as such.
    models = s["models"]
    cost = s.get("reported_cost")
    for name, rec in (s.get("reported_models") or {}).items():
        if name in models:
            models[name]["cost_usd"] = rec["cost_usd"]
    def local(ts: Optional[str]) -> Optional[str]:
        return oc.parse_when(ts).astimezone().isoformat(timespec="seconds") if ts else None
    row: Dict[str, Any] = {
        "ts": local(s["first_ts"]), "end_ts": local(s["last_ts"]), "automation": automation, "surface": surface,
        "source": "hook", "session_id": s["session_id"], "entrypoint": s.get("entrypoint"),
        "version": s.get("version"), "models": models, "prefix_tokens": s.get("prefix_tokens"),
        "skills": s.get("skills"), "mcp": s.get("mcp"),
    }
    if cost is not None:
        row["cost_usd"] = cost
        row["cost_basis"] = "cost-state"
    return row


# --------------------------------------------------------------------------- cli

def _fmt_table(rows: List[Dict[str, Any]]) -> str:
    lines = ["%-19s %-6s %-18s %-8s %-7s %9s %8s" % ("ts", "kind", "automation", "outcome", "exit", "cost_usd", "tokens")]
    for r in rows:
        t = r.get("tokens") or {}
        tok = sum(t.values()) if t else 0
        lines.append("%-19s %-6s %-18s %-8s %-7s %9s %8s" % (
            str(r.get("ts", ""))[:19], r.get("kind", ""), (r.get("automation") or r.get("event") or "-")[:18],
            r.get("outcome", "-"), r.get("exit", "-"),
            ("%.4f" % r["cost_usd"]) if r.get("cost_usd") is not None else "-", tok or "-"))
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", help="override OTTO_HOME")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("--json", required=True, help="row as JSON, or - for stdin")
    r = sub.add_parser("from-result")
    r.add_argument("--automation", required=True); r.add_argument("--file", required=True)
    r.add_argument("--exit", type=int, default=None); r.add_argument("--surface", default="local-cli")
    r.add_argument("--started"); r.add_argument("--attempt", type=int)
    s = sub.add_parser("session"); s.add_argument("--transcript", required=True); s.add_argument("--automation")
    e = sub.add_parser("event"); e.add_argument("--event", required=True)
    e.add_argument("--detail", default=""); e.add_argument("--session-id", default=""); e.add_argument("--automation", default="")
    q = sub.add_parser("query")
    q.add_argument("--since"); q.add_argument("--automation"); q.add_argument("--kind", choices=["run", "event"])
    q.add_argument("--json", action="store_true"); q.add_argument("--now")
    sub.add_parser("stats")
    args = ap.parse_args(argv)
    home = Path(args.home).expanduser() if args.home else oc.otto_home()

    if args.cmd == "add":
        raw = sys.stdin.read() if args.json == "-" else args.json
        print(json.dumps(upsert_run(home, json.loads(raw))))
    elif args.cmd == "from-result":
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
        try:
            res = json.loads(text)
        except ValueError:
            res = {}
        print(json.dumps(upsert_run(home, row_from_result(res, args.automation, args.exit, args.surface, args.started, args.attempt))))
    elif args.cmd == "session":
        row = row_from_transcript(Path(args.transcript), args.automation or os.environ.get("OTTO_AUTOMATION"))
        if not row:
            print("{}")
            return 0
        print(json.dumps(upsert_run(home, row)))
    elif args.cmd == "event":
        print(json.dumps(add_event(home, args.event, args.detail, args.session_id, args.automation)))
    elif args.cmd == "query":
        now = oc.parse_when(args.now)
        rows = read_rows(home, oc.parse_since(args.since, now), None, oc.slug(args.automation) if args.automation else None, args.kind)
        print(json.dumps(rows, indent=2) if args.json else _fmt_table(rows))
    elif args.cmd == "stats":
        rows = read_rows(home)
        runs = [x for x in rows if x.get("kind") == "run"]
        print(json.dumps({
            "rows": len(rows), "runs": len(runs), "events": len(rows) - len(runs),
            "automations": sorted({x["automation"] for x in runs if x.get("automation")}),
            "first": rows[0].get("ts") if rows else None, "last": rows[-1].get("ts") if rows else None,
        }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
