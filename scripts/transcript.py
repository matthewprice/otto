"""Read usage numbers out of a Claude Code session transcript (JSONL).

The transcript format is internal and changes between Claude Code versions, so every
field is read defensively and nothing but numbers, model names, and short enum-like
labels leaves this module. Message text is never read into the result.

Verified against Claude Code 2.1.300/2.1.301 transcripts: assistant lines carry
`message.id`, `message.model`, and `message.usage`; one assistant message can span
several lines with the same id, so usage is deduplicated on `message.id`.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Optional


def _int(x: Any) -> int:
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


def summarize(path: Path, max_bytes: int = 200 * 1024 * 1024) -> Dict[str, Any]:
    """Return per-session totals from one transcript file."""
    path = Path(path)
    size = path.stat().st_size
    out: Dict[str, Any] = {
        "session_id": None, "first_ts": None, "last_ts": None, "entrypoint": None,
        "version": None, "models": {}, "prefix_tokens": None, "sidechain_messages": 0,
        "skills": {}, "mcp": {}, "reported_cost": None, "reported_models": {},
        "truncated": size > max_bytes, "messages": 0,
    }
    if size > max_bytes:
        return out
    by_id: Dict[str, Dict[str, Any]] = {}
    skills: Counter = Counter()
    mcp: Counter = Counter()
    first_main_usage: Optional[Dict[str, int]] = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict):
                continue
            ts = o.get("timestamp")
            if ts:
                if out["first_ts"] is None or ts < out["first_ts"]:
                    out["first_ts"] = ts
                if out["last_ts"] is None or ts > out["last_ts"]:
                    out["last_ts"] = ts
            if o.get("sessionId") and not out["session_id"]:
                out["session_id"] = o["sessionId"]
            if o.get("entrypoint") and not out["entrypoint"]:
                out["entrypoint"] = str(o["entrypoint"])[:32]
            if o.get("version"):
                out["version"] = str(o["version"])[:16]
            if o.get("attributionSkill"):
                skills[str(o["attributionSkill"])[:64]] += 1
            if o.get("attributionMcpServer"):
                mcp[str(o["attributionMcpServer"])[:64]] += 1
            typ = o.get("type")
            if typ == "cost-state":
                if o.get("totalCostUSD") is not None:
                    out["reported_cost"] = float(o["totalCostUSD"])
                mu = o.get("modelUsage")
                if isinstance(mu, dict):
                    out["reported_models"] = {
                        str(m)[:48]: {
                            "input": _int(v.get("inputTokens")),
                            "output": _int(v.get("outputTokens")),
                            "cache_read": _int(v.get("cacheReadInputTokens")),
                            "cache_create": _int(v.get("cacheCreationInputTokens")),
                            "cost_usd": float(v.get("costUSD") or 0.0),
                        }
                        for m, v in mu.items() if isinstance(v, dict)
                    }
                continue
            if typ != "assistant":
                continue
            msg = o.get("message")
            if not isinstance(msg, dict):
                continue
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue
            side = bool(o.get("isSidechain"))
            mid = msg.get("id") or o.get("uuid") or ("line-%d" % len(by_id))
            rec = {
                "model": str(msg.get("model") or "unknown")[:48],
                "input": _int(usage.get("input_tokens")),
                "output": _int(usage.get("output_tokens")),
                "cache_read": _int(usage.get("cache_read_input_tokens")),
                "cache_create": _int(usage.get("cache_creation_input_tokens")),
                "side": side,
            }
            prev = by_id.get(mid)
            if prev is None or rec["output"] >= prev["output"]:
                by_id[mid] = rec
            if first_main_usage is None and not side and rec["model"] != "<synthetic>":
                first_main_usage = rec
    models: Dict[str, Dict[str, int]] = {}
    for rec in by_id.values():
        if rec["model"] == "<synthetic>":
            continue
        m = models.setdefault(rec["model"], {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0, "messages": 0})
        for k in ("input", "output", "cache_read", "cache_create"):
            m[k] += rec[k]
        m["messages"] += 1
        if rec["side"]:
            out["sidechain_messages"] += 1
    out["models"] = models
    out["messages"] = sum(m["messages"] for m in models.values())
    out["skills"] = dict(skills)
    out["mcp"] = dict(mcp)
    if first_main_usage:
        out["prefix_tokens"] = first_main_usage["input"] + first_main_usage["cache_read"] + first_main_usage["cache_create"]
    return out


def totals(models: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    t = {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}
    for m in models.values():
        for k in t:
            t[k] += _int(m.get(k))
    return t


def project_slug(path: str) -> str:
    """Claude Code names a project's transcript folder after its path with non-alphanumerics as '-'."""
    import re
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def project_transcripts(claude_home: Path, project_path: str):
    d = Path(claude_home) / "projects" / project_slug(project_path)
    if not d.is_dir():
        return []
    return sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
