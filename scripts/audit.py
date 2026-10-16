#!/usr/bin/env python3
"""Context-tax and automation audit. Read-only: it reports, it never edits.

Every finding says whether its number is MEASURED (exact characters, or usage counts that
Claude Code reported) or an ESTIMATE (tokens from characters / 4). Nothing here is applied;
Otto proposes and you decide.

What it looks at:
  user level      ~/.claude/CLAUDE.md, skills/, agents/, commands/          (loaded in every project,
                                                                             including headless runs)
  project level   <project>/CLAUDE.md, .claude/{skills,agents,commands}, .mcp.json
  plugins         every plugin found under ~/.claude/plugins
  MCP servers     names only, from .mcp.json and ~/.claude.json (never their env or tokens)
  transcripts     usage blocks and skill/MCP attribution counts for the last N days of this project
  wrappers        scripts named in the registry (`wrapper:`) checked for missing guard rails

Usage: audit.py [--home DIR] [--project DIR] [--claude-home DIR] [--days 30] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import health  # noqa: E402
import otto_common as oc  # noqa: E402
import otto_tokens as otto_tokenize  # noqa: E402
import transcript  # noqa: E402

DESC_CAP = 1536          # characters of description + when_to_use shown in the skill listing
PORTABLE_DESC_CAP = 1024  # the Agent Skills spec limit for `description`
CLAUDE_MD_LINES = 200
BODY_LINES = 500
LISTING_OVERHEAD_CHARS = 24


# --------------------------------------------------------------------------- discovery

def _component(kind: str, scope: str, path: Path) -> Optional[Dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fm, body = oc.parse_frontmatter(text)
    est = otto_tokenize.estimate(text)
    name = fm.get("name") or (path.parent.name if path.name == "SKILL.md" else path.stem)
    desc = str(fm.get("description") or "")
    when = str(fm.get("when_to_use") or "")
    invocable = fm.get("disable-model-invocation") is not True
    return {
        "kind": kind, "scope": scope, "name": str(name), "path": str(path),
        "chars": est["chars"], "lines": est["lines"], "tokens_est": est["tokens_chars4"],
        "tokens_est_words": est["tokens_words13"],
        "description_chars": len(desc) + len(when), "model_invocable": invocable and kind != "claude_md",
        "model": fm.get("model"), "body_lines": body.count("\n") + 1 if body else 0,
        "frontmatter_keys": sorted(fm.keys()),
    }


def discover(base: Path, scope: str, include_claude_md: bool = True) -> List[Dict[str, Any]]:
    """`base` is a directory that holds CLAUDE.md and/or skills/, agents/, commands/ (a `.claude` dir or a plugin root)."""
    out: List[Dict[str, Any]] = []
    cm = base / "CLAUDE.md"
    if include_claude_md and cm.is_file():
        c = _component("claude_md", scope, cm)
        if c:
            out.append(c)
    for p in sorted((base / "skills").glob("*/SKILL.md")) if (base / "skills").is_dir() else []:
        c = _component("skill", scope, p)
        if c:
            out.append(c)
    for p in sorted((base / "agents").glob("*.md")) if (base / "agents").is_dir() else []:
        c = _component("agent", scope, p)
        if c:
            out.append(c)
    for p in sorted((base / "commands").rglob("*.md")) if (base / "commands").is_dir() else []:
        c = _component("command", scope, p)
        if c:
            out.append(c)
    return out


def find_plugins(claude_home: Path, limit: int = 60) -> List[Path]:
    root = claude_home / "plugins"
    if not root.is_dir():
        return []
    best: Dict[str, Path] = {}
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth > 7:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".git", "data")]
        if os.path.basename(dirpath) == ".claude-plugin" and "plugin.json" in filenames:
            pj = Path(dirpath) / "plugin.json"
            data = oc.read_json(pj, {}) or {}
            name = str(data.get("name") or Path(dirpath).parent.name)
            cur = best.get(name)
            if cur is None or pj.stat().st_mtime > (cur / ".claude-plugin" / "plugin.json").stat().st_mtime:
                best[name] = Path(dirpath).parent
            n += 1
            if n > limit * 4:
                break
    return list(best.values())[:limit]


def mcp_servers(project: Optional[Path], claude_home: Path) -> Dict[str, List[str]]:
    """Server names only, grouped by where they were configured. Env values and headers are never read."""
    out: Dict[str, List[str]] = {}
    if project and (project / ".mcp.json").is_file():
        d = oc.read_json(project / ".mcp.json", {}) or {}
        out["project .mcp.json"] = sorted((d.get("mcpServers") or {}).keys())
    cj = oc.read_json(claude_home.parent / ".claude.json", None) if claude_home.name == ".claude" else None
    if isinstance(cj, dict):
        if cj.get("mcpServers"):
            out["user ~/.claude.json"] = sorted(cj["mcpServers"].keys())
        if project and isinstance(cj.get("projects"), dict):
            pr = cj["projects"].get(str(project))
            if isinstance(pr, dict) and pr.get("mcpServers"):
                out["local (this project)"] = sorted(pr["mcpServers"].keys())
    return out


# --------------------------------------------------------------------------- findings

def F(fid: str, severity: str, title: str, evidence: str, measured: bool, recommendation: str,
      expected_saving: str, risk: str, tokens: Optional[int] = None, targets: Optional[List[str]] = None) -> Dict[str, Any]:
    d: Dict[str, Any] = {"id": fid, "severity": severity, "title": title, "evidence": evidence,
                         "measured": measured, "recommendation": recommendation,
                         "expected_saving": expected_saving, "risk": risk}
    if tokens is not None:
        d["tokens_est"] = tokens
    if targets:
        d["targets"] = targets[:12]
    return d


def check_descriptions(comps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    over = [c for c in comps if c["kind"] != "claude_md" and c["description_chars"] > DESC_CAP]
    if over:
        out.append(F("description-over-cap", "high", "Descriptions longer than the %d-character listing cap" % DESC_CAP,
                     "; ".join("%s (%d chars)" % (c["name"], c["description_chars"]) for c in over[:6]), True,
                     "Cut each description to what it does and when to use it, key use case first. Move detail into the skill body.",
                     "Text past the cap is truncated in the listing, so the model never sees it; the saving is clarity, not tokens.",
                     "Low. Re-test that the skill still triggers on natural phrasing.", targets=[c["path"] for c in over]))
    portable = [c for c in comps if c["kind"] == "skill" and PORTABLE_DESC_CAP < c["description_chars"] <= DESC_CAP]
    if portable:
        out.append(F("description-over-spec", "low", "Skill descriptions over the %d-character Agent Skills limit" % PORTABLE_DESC_CAP,
                     "; ".join("%s (%d)" % (c["name"], c["description_chars"]) for c in portable[:6]), True,
                     "Trim if you want the skill to upload to claude.ai or run in other agents, which enforce the spec limit.",
                     "None for tokens.", "Low.", targets=[c["path"] for c in portable]))
    return out


def check_claude_md(comps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for c in comps:
        if c["kind"] == "claude_md" and c["lines"] > CLAUDE_MD_LINES:
            excess = (c["lines"] - CLAUDE_MD_LINES) / c["lines"]
            saving = int(c["tokens_est"] * excess)
            out.append(F("claude-md-long", "medium", "%s CLAUDE.md is %d lines" % (c["scope"], c["lines"]),
                         "%d lines, %d characters, about %d tokens (estimate), loaded in every session at this scope" % (c["lines"], c["chars"], c["tokens_est"]),
                         False,
                         "Keep only what Claude cannot derive from the code and what applies to every task. Move templates and procedures into skills or reference files that load on demand; drop sections that repeat the README.",
                         "About %d tokens per session if trimmed to %d lines (estimate)." % (saving, CLAUDE_MD_LINES),
                         "A skill forgets to read a moved template. Name the reference file in the first lines of the skills that need it.",
                         tokens=saving, targets=[c["path"]]))
        if c["kind"] == "skill" and c["body_lines"] > BODY_LINES:
            out.append(F("skill-body-long", "low", "Skill %s has a %d-line body" % (c["name"], c["body_lines"]),
                         "body over the %d-line guidance" % BODY_LINES, True,
                         "Split detail into one-level-deep reference files and read them only when needed.", "Loaded only when the skill runs.", "Low.", targets=[c["path"]]))
    return out


def check_listing(comps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    inv = [c for c in comps if c["model_invocable"] and c["kind"] in ("skill", "command", "agent")]
    if not inv:
        return []
    chars = sum(min(c["description_chars"], DESC_CAP) + len(c["name"]) + LISTING_OVERHEAD_CHARS for c in inv)
    top = sorted(inv, key=lambda c: -c["description_chars"])[:5]
    return [F("listing-cost", "info", "%d model-invocable skills, commands and agents sit in the listing" % len(inv),
              "about %d tokens (estimate) on every session. Longest: %s" % (chars // 4, ", ".join("%s (%d)" % (c["name"], c["description_chars"]) for c in top)),
              False, "Mark anything only you or a scheduler should run with `disable-model-invocation: true`; that keeps its description out of context.",
              "Up to %d tokens per session (estimate), if all were hidden. Realistically a fraction." % (chars // 4), "Low.", tokens=chars // 4)]


def check_batch_invocable(comps: List[Dict[str, Any]], autos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cmds = {str(a.get("command") or "").lstrip("/").split(":")[-1].split(" ")[0]: a["name"] for a in autos if a.get("command")}
    hits = [c for c in comps if c["kind"] in ("skill", "command") and c["name"] in cmds and c["model_invocable"]]
    if not hits:
        return []
    toks = sum(min(c["description_chars"], DESC_CAP) // 4 for c in hits)
    return [F("batch-skill-model-invocable", "medium", "%d scheduled skills can also be launched by the model" % len(hits),
              ", ".join("%s (runs as %s)" % (c["name"], cmds[c["name"]]) for c in hits), True,
              "Add `disable-model-invocation: true`. Your scheduler or you can still run them by name; the model can no longer start a full pipeline because a chat message sounded close.",
              "About %d tokens per session (estimate) and one class of surprise run." % toks,
              "Confirm on one scheduled run that `claude -p \"/name\"` still resolves.", tokens=toks, targets=[c["path"] for c in hits])]


def check_agents(comps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    un = [c for c in comps if c["kind"] == "agent" and (not c.get("model") or str(c.get("model")) == "inherit")]
    if not un:
        return []
    return [F("agent-model-unpinned", "low", "%d agents inherit whatever model the session runs" % len(un),
              ", ".join(c["name"] for c in un[:8]), True,
              "For agents that do batch work, pin `model` explicitly (and `effort` where it matters). Check which model your scheduled runs actually use before deciding.",
              "Depends on the tier your headless runs default to. Unknown until you read modelUsage from one wrapped run.",
              "Quality: compare a week of output before keeping a cheaper model.", targets=[c["path"] for c in un])]


def check_usage(comps: List[Dict[str, Any]], servers: Dict[str, List[str]], sessions: List[Dict[str, Any]], days: int) -> List[Dict[str, Any]]:
    out = []
    if len(sessions) < 10:
        if sessions or comps:
            out.append(F("usage-sample-small", "info", "Only %d sessions to judge usage from" % len(sessions),
                         "Unused-skill and unused-server checks need at least 10 sessions in the last %d days." % days, True,
                         "Re-run after more sessions, or widen --days.", "None.", "None."))
        return out
    seen_skills: Dict[str, int] = {}
    seen_mcp: Dict[str, int] = {}
    for s in sessions:
        for k, v in (s.get("skills") or {}).items():
            seen_skills[k] = seen_skills.get(k, 0) + v
        for k, v in (s.get("mcp") or {}).items():
            seen_mcp[k] = seen_mcp.get(k, 0) + v
    unused = [c for c in comps if c["kind"] == "skill" and c["model_invocable"] and c["name"] not in seen_skills
              and not any(k.endswith(":" + c["name"]) or k == c["name"] for k in seen_skills)]
    if unused:
        toks = sum(min(c["description_chars"], DESC_CAP) // 4 for c in unused)
        out.append(F("unused-skills", "low", "%d skills with no recorded use in %d sessions" % (len(unused), len(sessions)),
                     ", ".join(c["name"] for c in unused[:10]), True,
                     "Remove, or mark `disable-model-invocation: true` if you invoke them by hand. Transcript attribution can undercount, so check `/skill-doctor` before deleting.",
                     "About %d tokens per session (estimate)." % toks, "Low, but confirm with /skill-doctor.", tokens=toks, targets=[c["path"] for c in unused]))
    names = [(grp, n) for grp, ns in servers.items() for n in ns]
    idle = [(g, n) for g, n in names if n not in seen_mcp]
    if idle:
        out.append(F("unused-mcp-servers", "medium", "%d MCP servers with no attributed calls in %d sessions" % (len(idle), len(sessions)),
                     ", ".join("%s (%s)" % (n, g) for g, n in idle[:8]), True,
                     "Disable servers you do not use in /mcp. Tool schemas are deferred by default, but server instructions and connection setup still cost something and each server widens what a headless run can reach.",
                     "Small in tokens; larger in attack surface.", "Low. Re-enable when needed.", targets=[n for _, n in idle]))
    return out


def check_prefix(sessions: List[Dict[str, Any]], comps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pre = [s["prefix_tokens"] for s in sessions if s.get("prefix_tokens")]
    if not pre:
        return []
    med = oc.median(pre)
    scanned = sum(c["tokens_est"] for c in comps if c["kind"] == "claude_md") + sum(
        min(c["description_chars"], DESC_CAP) // 4 for c in comps if c["model_invocable"])
    return [F("measured-prefix", "info", "A session in this project starts with about %d tokens before you type" % med,
              "median of %d sessions (min %d, max %d). Files scanned here explain about %d of it (estimate); the rest is the system prompt, built-in tools, and anything not scanned." % (
                  len(pre), min(pre), max(pre), scanned), True,
              "Use this as the baseline. Any change worth making should move this number; re-run after applying it.",
              "n/a", "n/a", tokens=int(med))]


WRAPPER_CHECKS = (
    (r"--dangerously-skip-permissions", "high", "bypasses all permission checks", True,
     "Use `--permission-mode` with an explicit allowlist, so anything unlisted is refused instead of run."),
    (r"--max-turns", "medium", "has no --max-turns", False, "Add `--max-turns` as a ceiling."),
    (r"--max-budget-usd", "medium", "has no --max-budget-usd", False, "Add `--max-budget-usd` as a ceiling, set after you have measured a few runs."),
    (r"--output-format\s+(stream-)?json", "medium", "does not capture the JSON result, so cost, turns and model are thrown away", False,
     "Run with `--output-format json` and record total_cost_usd, duration, turns and modelUsage."),
    (r"\btimeout\b", "medium", "has no timeout", False, "Wrap the call in a timeout."),
)


def check_wrappers(autos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for a in autos:
        w = a.get("wrapper")
        if not w:
            continue
        p = Path(str(w)).expanduser()
        if not p.is_file():
            out.append(F("wrapper-missing", "low", "Registered wrapper for %s not found" % a["name"], str(p), True,
                         "Fix the path in the registry note.", "n/a", "n/a"))
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        probs = []
        for pat, sev, msg, bad_if_present, rec in WRAPPER_CHECKS:
            present = re.search(pat, text) is not None
            if present == bad_if_present:
                probs.append((sev, msg, rec))
        if probs:
            sev = "high" if any(s == "high" for s, _, _ in probs) else "medium"
            out.append(F("wrapper-posture", sev, "Wrapper for %s: %d guard rails missing" % (a["name"], len(probs)),
                         "; ".join(m for _, m, _ in probs), True, " ".join(r for _, _, r in probs),
                         "Bounds the worst case rather than the average. Savings show up only when something goes wrong.",
                         "A cap that is too tight stops a legitimate run mid-way; set caps from measured runs.", targets=[str(p)]))
    return out


def check_cold(autos: List[Dict[str, Any]], prefix: Optional[float]) -> List[Dict[str, Any]]:
    sched = [a for a in autos if a.get("expected_by") and a.get("surface") in ("local-cli", "github-actions")]
    if not sched or not prefix:
        return []
    per_month = 0.0
    for a in sched:
        per_month += len(health.normalize_days(a.get("days"))) * 52 / 12.0
    return [F("cold-start", "info", "Scheduled runs pay for a cold prefix every time",
              "%d scheduled automations, about %d runs a month, each starting with a measured prefix of about %d tokens that is not in the cache." % (len(sched), per_month, prefix),
              True, "Shrink the prefix (CLAUDE.md, listing, user-level context) rather than trying to keep a cache warm between days.",
              "Proportional to the prefix cut times runs a month.", "None.", tokens=int(prefix))]


def check_user_context(user_comps: List[Dict[str, Any]], plugin_comps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not user_comps and not plugin_comps:
        return []
    ut = sum(c["tokens_est"] for c in user_comps if c["kind"] == "claude_md") + sum(
        min(c["description_chars"], DESC_CAP) // 4 for c in user_comps + plugin_comps if c["model_invocable"])
    return [F("hidden-user-context", "info", "User-level and plugin context is also loaded in every headless run",
              "%d user-level components and %d plugin components, about %d tokens (estimate) of CLAUDE.md and listing text in every project." % (len(user_comps), len(plugin_comps), ut),
              False, "Look here first when a scheduled run is heavier than its project suggests. `/context` in an interactive session shows the same prefix.",
              "n/a", "n/a", tokens=ut)]


# --------------------------------------------------------------------------- run

def run(home: Path, project: Optional[Path], claude_home: Path, days: int) -> Dict[str, Any]:
    cfg = oc.load_config(home)
    autos, reg_problems = health.load_registry(home, cfg)
    user_comps = discover(claude_home, "user")
    proj_comps: List[Dict[str, Any]] = []
    if project:
        proj_comps = discover(project, "project", include_claude_md=False)
        for rel in ("CLAUDE.md", ".claude/CLAUDE.md"):
            if (project / rel).is_file():
                c = _component("claude_md", "project", project / rel)
                if c:
                    proj_comps.append(c)
        proj_comps += discover(project / ".claude", "project", include_claude_md=False)
    plugin_comps: List[Dict[str, Any]] = []
    plugins = find_plugins(claude_home)
    for root in plugins:
        plugin_comps += discover(root, "plugin:" + root.name, include_claude_md=False)
    comps = user_comps + proj_comps + plugin_comps

    sessions: List[Dict[str, Any]] = []
    if project:
        cutoff = time.time() - days * 86400
        files = [p for p in transcript.project_transcripts(claude_home, str(project)) if p.stat().st_mtime >= cutoff][-40:]
        for p in files:
            try:
                s = transcript.summarize(p, max_bytes=60 * 1024 * 1024)
            except OSError:
                continue
            if s.get("session_id") and not s.get("truncated"):
                sessions.append(s)
    servers = mcp_servers(project, claude_home)

    findings: List[Dict[str, Any]] = []
    findings += check_descriptions(comps)
    findings += check_claude_md(comps)
    findings += check_batch_invocable(comps, autos)
    findings += check_wrappers(autos)
    findings += check_usage(comps, servers, sessions, days)
    findings += check_agents(comps)
    findings += check_listing(comps)
    findings += check_prefix(sessions, proj_comps + user_comps + plugin_comps)
    pre = oc.median([s["prefix_tokens"] for s in sessions if s.get("prefix_tokens")])
    findings += check_cold(autos, pre)
    findings += check_user_context(user_comps, plugin_comps)
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    findings.sort(key=lambda f: (order[f["severity"]], -(f.get("tokens_est") or 0)))
    return {
        "generated_at": oc.iso(datetime.now().astimezone()), "project": str(project) if project else None,
        "days": days, "sessions_sampled": len(sessions), "registry_automations": len(autos),
        "components": {"user": len(user_comps), "project": len(proj_comps), "plugin": len(plugin_comps), "plugins_found": len(plugins)},
        "mcp_servers": servers, "findings": findings, "registry_problems": reg_problems,
        "method": "Characters are exact. Tokens are estimates (characters / 4) unless a finding says measured. The prefix figure is measured from the first request of real sessions.",
    }


def render_table(rep: Dict[str, Any]) -> str:
    L = ["Otto audit: %d findings, %d sessions sampled" % (len(rep["findings"]), rep["sessions_sampled"])]
    for f in rep["findings"]:
        L.append("[%-6s] %s%s" % (f["severity"], f["title"], "" if f["measured"] else " (estimate)"))
        L.append("         " + f["evidence"][:200])
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home"); ap.add_argument("--project"); ap.add_argument("--claude-home")
    ap.add_argument("--days", type=int, default=30)
    g = ap.add_mutually_exclusive_group(); g.add_argument("--json", action="store_true"); g.add_argument("--table", action="store_true")
    a = ap.parse_args(argv)
    home = Path(a.home).expanduser() if a.home else oc.otto_home()
    project = Path(a.project).expanduser().resolve() if a.project else None
    claude_home = Path(a.claude_home).expanduser() if a.claude_home else Path.home() / ".claude"
    rep = run(home, project, claude_home, a.days)
    print(render_table(rep) if a.table else json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
