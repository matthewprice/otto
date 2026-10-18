#!/usr/bin/env python3
"""Generate a synthetic Otto home: a registry of six fictional automations and 24 days of ledger.

Everything here is invented. The automations, the costs, and the failures are planted so
Otto has something to say on day one:

  morning-digest   ok today; cost stepped up about 40 percent on Sep 17 (a skill grew)
  inbox-triage     ran, succeeded, but cost 3.7x its median today (drift)
  weekly-brief     Monday Sep 21 failed twice with error_max_turns (fail)
  repo-watch       a cloud routine; today's output file never appeared (miss)
  nightly-sync     three auth failures, circuit breaker open since Sep 22 (breaker)
  desktop-notes    a desktop task, fine

It also writes a synthetic yield ledger for steward mode: six fictional discovery strategies over
the 30 days to the same NOW, in yield/, with outcomes, a settings file and a sample grant:

  public-data      the over-performer: daily, scores often, three reach the top 20, two survive review
  accelerators     a source leak: examines many, almost nothing becomes a candidate
  subscriptions    a triage leak: many candidates, none pass the prescreen, drops cluster on one filter
  app-lists        a judgment leak: passes and scores, nothing reaches the persona floor
  vanishing-data   blocked: every run stopped by network policy
  new-angle        a small sample: two runs only

Usage:  generate.py --out DIR
Then:   OTTO_HOME=DIR python3 scripts/health.py --now "$(cat DIR/DEMO_NOW)" --table

Deterministic: the same output every time. Fixture rows carry note="fixture".
Never quote these numbers as results. They are not results.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
NOW = datetime(2026, 9, 24, 9, 15, tzinfo=TZ)
NS = uuid.UUID("0e2f6a1e-5c0b-4c6e-9d0f-0a0770770770")
MODEL = "claude-sonnet-5-5"
AUX = "claude-haiku-5-5"


def at(day: int, hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(2026, 9, day, hh, mm, ss, tzinfo=TZ)


def sid(name: str) -> str:
    return str(uuid.uuid5(NS, name))


def usage(cost: float, rng: random.Random) -> dict:
    s = max(cost, 0.05)
    j = lambda x: int(x * s * rng.uniform(0.93, 1.07))
    main = {"input": j(52000), "output": j(8200), "cache_read": j(380000), "cache_create": j(61000), "cost_usd": round(cost * 0.93, 4)}
    aux = {"input": j(9000), "output": j(1100), "cache_read": 0, "cache_create": 0, "cost_usd": round(cost * 0.07, 4)}
    return {MODEL: main, AUX: aux}


# Which account each fixture automation bills. The API-key jobs draw on the monthly API credit;
# the one on the subscription login draws on the 5-hour and 7-day windows.
CREDENTIAL = {"weekly-brief": "api_key", "inbox-triage": "api_key", "morning-digest": "api_key", "nightly-sync": "subscription"}


def run_row(name, start, minutes, cost, rng, *, exit_code=0, stop="success", attempt=1, outcome="pass",
            evidence=None, skipped=None):
    row = {
        "kind": "run", "ts": start.isoformat(timespec="seconds"),
        "end_ts": (start + timedelta(minutes=minutes)).isoformat(timespec="seconds"),
        "automation": name, "surface": "local-cli", "source": "wrapper",
        "session_id": sid("%s-%s-%d" % (name, start.isoformat(), attempt)),
        "entrypoint": "sdk-cli", "version": "2.1.301", "attempt": attempt, "note": "fixture",
    }
    if name in CREDENTIAL:
        row["credential"] = CREDENTIAL[name]
    if skipped:
        row.update({"outcome": "skipped", "skipped_reason": skipped, "exit": 0})
        return row
    models = usage(cost, rng)
    tokens = {k: sum(m[k] for m in models.values()) for k in ("input", "output", "cache_read", "cache_create")}
    row.update({
        "models": models, "tokens": tokens, "cost_usd": round(cost, 4), "cost_basis": "reported",
        "duration_ms": int(minutes * 60000), "num_turns": rng.randint(14, 31), "exit": exit_code,
        "is_error": exit_code != 0, "stop_reason": stop, "outcome": outcome,
    })
    if evidence:
        row["outcome_evidence"] = evidence
    return row


NOTE_BODY = """
Synthetic example automation shipped with Otto's fixtures. Nothing here is real.

## What success looks like
{success}

## Owner notes
{notes}
"""


def registry_note(fm: dict, success: str, notes: str) -> str:
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            lines.append("%s: [%s]" % (k, ", ".join(json.dumps(x) if isinstance(x, str) else str(x) for x in v)))
        elif isinstance(v, bool):
            lines.append("%s: %s" % (k, "true" if v else "false"))
        elif isinstance(v, (int, float)):
            lines.append("%s: %s" % (k, v))
        else:
            lines.append("%s: %s" % (k, json.dumps(v)))
    lines.append("---")
    return "\n".join(lines) + NOTE_BODY.format(success=success, notes=notes)


def write_file(path: Path, text: str, when: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    t = when.timestamp()
    os.utime(path, (t, t))


def output_text(title: str, marker: str) -> str:
    body = "\n".join("- synthetic line %02d: placeholder content for the fixture." % i for i in range(1, 30))
    return "# %s\n\n%s\n\n%s\n" % (title, body, marker)


def generate(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    rng = random.Random(24)
    (out / "ledger").mkdir(parents=True)
    (out / "state").mkdir(parents=True)
    auto_dir = out / "vault" / "Automations"
    auto_dir.mkdir(parents=True)
    rows = []
    events = []

    # ---- config
    (out / "otto.md").write_text("\n".join([
        "---", 'timezone: "America/Chicago"', "lights: on", "notify: none", 'plan: "Max 5x (example)"',
        "budget_weekly_usd: 40", "api_credit_usd: 100", "api_credit_reset_day: 1",
        "alert_percents: [50, 75, 90]", "guard: off", "attempt_cap_per_day: 2", "breaker_threshold: 3",
        "---", "Synthetic Otto config for the fixture month.", ""]), encoding="utf-8")

    # ---- registry
    common = {"timezone": "America/Chicago", "grace_min": 15, "registered": "2026-08-31", "success_cwd": "{OTTO_HOME}"}
    notes = {
        "morning-digest": dict(surface="local-cli", command="/morning-digest", run_at="07:00", days="daily", expected_by="07:45",
                               duration_min=[6, 25], cost_usd=[0.6, 1.8], success_file="work/digests/{date}.md",
                               success_min_bytes=800, success_pattern="Summary:", max_turns=40, max_budget_usd=3,
                               timeout_min=30, permission_mode="acceptEdits", allowed_tools=["Read", "Write", "Glob", "Grep", "WebFetch"],
                               cwd="~/projects/digest"),
        "inbox-triage": dict(surface="local-cli", command="/inbox-triage", run_at="08:00", days="weekdays", expected_by="08:30",
                             duration_min=[2, 12], cost_usd=[0.3, 1.5], success_file="work/triage/{date}.md",
                             success_min_bytes=400, max_turns=30, max_budget_usd=2, timeout_min=20,
                             permission_mode="acceptEdits", allowed_tools=["Read", "Write", "Glob", "Grep"], cwd="~/projects/mail"),
        "weekly-brief": dict(surface="local-cli", command="/weekly-brief", run_at="08:00", days=["mon"], expected_by="08:45",
                             duration_min=[10, 40], cost_usd=[2, 7], success_file="work/briefs/{iso_week}.md",
                             success_min_bytes=1500, success_pattern="Summary:", max_turns=60, max_budget_usd=8, timeout_min=45,
                             permission_mode="acceptEdits", allowed_tools=["Read", "Write", "Glob", "Grep", "WebFetch", "WebSearch"],
                             cwd="~/projects/brief"),
        "repo-watch": dict(surface="routine", cadence="daily 06:00, runs in the cloud", days="daily", expected_by="06:30",
                           success_file="work/repo-watch/{date}.md", success_min_bytes=300),
        "nightly-sync": dict(surface="local-cli", command="/nightly-sync", run_at="02:00", days="daily", expected_by="02:30",
                             duration_min=[3, 15], cost_usd=[0.4, 1.6], success_file="work/sync/{date}.md", success_min_bytes=200,
                             max_turns=25, max_budget_usd=2, timeout_min=20, permission_mode="acceptEdits",
                             allowed_tools=["Read", "Write", "Glob", "Grep"], cwd="~/projects/sync"),
        "desktop-notes": dict(surface="desktop-task", cadence="weekdays 17:00 in Claude Desktop", days="weekdays", expected_by="17:30",
                              success_file="work/notes/{date}.md", success_min_bytes=200),
    }
    succ = {
        "morning-digest": "A file at work/digests/<date>.md of at least 800 bytes containing a line starting 'Summary:'.",
        "inbox-triage": "A file at work/triage/<date>.md of at least 400 bytes.",
        "weekly-brief": "A file at work/briefs/<ISO week>.md of at least 1,500 bytes containing 'Summary:'.",
        "repo-watch": "A file at work/repo-watch/<date>.md. The routine runs in the cloud, so Otto can only see this file.",
        "nightly-sync": "A file at work/sync/<date>.md of at least 200 bytes.",
        "desktop-notes": "A file at work/notes/<date>.md. The task runs in Claude Desktop, so Otto can only see this file.",
    }
    for n, fm in notes.items():
        full = {"name": n}
        full.update(fm)
        full.update(common)
        (auto_dir / ("%s.md" % n)).write_text(registry_note(full, succ[n], "Fixture automation. Safe to delete."), encoding="utf-8")

    # ---- morning-digest: daily, a 40 percent step on Sep 17
    for d in range(1, 25):
        if at(d, 7, 0) > NOW:
            break
        start = at(d, 7, rng.randint(0, 5), rng.randint(0, 59))
        base = 0.95 if d < 17 else 1.32
        cost = base * rng.uniform(0.94, 1.06)
        mins = rng.uniform(9, 14)
        rows.append(run_row("morning-digest", start, mins, cost, rng))
        write_file(out / ("work/digests/2026-09-%02d.md" % d), output_text("Digest 2026-09-%02d" % d, "Summary: fixture."), start + timedelta(minutes=mins))

    # ---- inbox-triage: weekdays; today is a spike
    for d in range(1, 25):
        day = at(d, 8, 0)
        if day.weekday() > 4 or day > NOW:
            continue
        start = at(d, 8, rng.randint(0, 4), rng.randint(0, 59))
        if d == 24:
            cost, mins = 2.94, 19.0
        else:
            cost, mins = 0.8 * rng.uniform(0.88, 1.12), rng.uniform(4, 6.5)
        rows.append(run_row("inbox-triage", start, mins, cost, rng))
        write_file(out / ("work/triage/2026-09-%02d.md" % d), output_text("Triage 2026-09-%02d" % d, ""), start + timedelta(minutes=mins))

    # ---- weekly-brief: Mondays Sep 7, 14 pass; Sep 21 fails twice
    for d in (7, 14):
        start = at(d, 8, 1)
        mins = rng.uniform(18, 26)
        rows.append(run_row("weekly-brief", start, mins, 4.5 * rng.uniform(0.95, 1.05), rng))
        iso = at(d, 8, 0).isocalendar()
        write_file(out / ("work/briefs/%04d-W%02d.md" % (iso[0], iso[1])), output_text("Brief week %d" % iso[1], "Summary: fixture.") * 2, start + timedelta(minutes=mins))
    for attempt, (hh, mm) in enumerate(((8, 1), (8, 29)), start=1):
        rows.append(run_row("weekly-brief", at(21, hh, mm), 21.0, 5.2 * rng.uniform(0.97, 1.03), rng, exit_code=1,
                            stop="error_max_turns", attempt=attempt, outcome="fail", evidence="stopped at the turn limit"))

    # ---- nightly-sync: 02:00 daily; fails Sep 20-22; breaker skips afterwards
    for d in range(1, 25):
        start = at(d, 2, rng.randint(0, 3), rng.randint(0, 59))
        if start > NOW:
            break
        if d in (20, 21, 22):
            rows.append(run_row("nightly-sync", start, 0.4, 0.02, rng, exit_code=1, stop="error_during_execution", outcome="fail",
                                evidence="authentication_failed"))
            events.append({"kind": "event", "ts": (start + timedelta(seconds=30)).isoformat(timespec="seconds"),
                           "event": "stopfailure", "detail": "authentication_failed", "automation": "nightly-sync"})
        elif d in (23, 24):
            rows.append(run_row("nightly-sync", start, 0, 0, rng, skipped="breaker open"))
        else:
            mins = rng.uniform(5, 8)
            rows.append(run_row("nightly-sync", start, mins, 0.9 * rng.uniform(0.9, 1.1), rng))
            write_file(out / ("work/sync/2026-09-%02d.md" % d), output_text("Sync 2026-09-%02d" % d, ""), start + timedelta(minutes=mins))

    # ---- repo-watch (cloud routine): files only; silent skips on Sep 9, 16, and today
    for d in range(1, 25):
        if d in (9, 16, 24):
            continue
        write_file(out / ("work/repo-watch/2026-09-%02d.md" % d), output_text("Repo watch 2026-09-%02d" % d, ""), at(d, 6, 4))

    # ---- desktop-notes: weekdays through yesterday
    for d in range(1, 24):
        if at(d, 17, 0).weekday() > 4:
            continue
        write_file(out / ("work/notes/2026-09-%02d.md" % d), output_text("Notes 2026-09-%02d" % d, ""), at(d, 17, 6))

    # ---- interactive sessions (unattributed), for the budget view
    for d in range(1, 25):
        for k in range(rng.randint(1, 3)):
            start = at(d, rng.randint(9, 19), rng.randint(0, 59))
            if start > NOW - timedelta(minutes=30):
                continue
            cost = rng.uniform(0.4, 5.5)
            r = run_row(None, start, rng.uniform(8, 70), cost, rng)
            r.pop("automation", None); r["surface"] = "interactive"; r["source"] = "hook"; r["entrypoint"] = "cli"
            r.pop("attempt", None)
            rows.append(r)
    events.append({"kind": "event", "ts": at(12, 15, 2).isoformat(timespec="seconds"), "event": "stopfailure", "detail": "rate_limit"})

    # ---- write the ledger by month
    allrows = sorted(rows + events, key=lambda r: r["ts"])
    (out / "ledger" / "2026-09.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in allrows), encoding="utf-8")

    # ---- state
    json.dump({
        "captured_at": (NOW - timedelta(minutes=3)).isoformat(timespec="seconds"),
        "session_id": sid("demo-live"),
        "rate_limits": {
            "five_hour": {"used_percentage": 31, "resets_at": int((NOW + timedelta(hours=2, minutes=50)).timestamp())},
            "seven_day": {"used_percentage": 58, "resets_at": int((NOW + timedelta(days=2, hours=6)).timestamp())},
        },
        "cost": {"total_cost_usd": 0.42},
    }, open(out / "state" / "statusline.json", "w"), indent=2)
    json.dump({"nightly-sync": {"open": True, "since": at(22, 2, 6).isoformat(timespec="seconds"), "failures": 3,
                                "reason": "authentication_failed three runs in a row"}},
              open(out / "state" / "breaker.json", "w"), indent=2)
    write_yield(out, random.Random(30))
    (out / "DEMO_NOW").write_text(NOW.isoformat(timespec="seconds") + "\n", encoding="utf-8")
    (out / "README.txt").write_text("Synthetic Otto home generated by fixtures/generate.py. Every number here is invented.\n", encoding="utf-8")


YIELD_STRATEGIES = {
    # name: (first day offset back from NOW, every n days, searches, run_units, model, stages)
    "public-data": (29, 1, 100, 3.0, "sonnet", {"triage": "haiku", "score": "sonnet"}),
    "accelerators": (29, 1, 140, 4.5, "sonnet", {"triage": "haiku", "score": "sonnet"}),
    "subscriptions": (28, 2, 140, 4.0, "opus", {"triage": "haiku", "score": "opus"}),
    "app-lists": (29, 1, 90, 3.0, "sonnet", {"triage": "haiku", "score": "sonnet"}),
    "vanishing-data": (27, 3, 80, 0.5, "sonnet", {"triage": "haiku", "score": "sonnet"}),
    "new-angle": (2, 1, 50, 2.0, "sonnet", {"triage": "haiku", "score": "sonnet"}),
}


def yield_rows(rng: random.Random):
    """Synthetic strategy runs and outcomes. Invented end to end; never quote them as results."""
    runs, outcomes = [], []
    for name, (back, every, searches, units, model, stages) in YIELD_STRATEGIES.items():
        n = 0
        for off in range(back, 0, -every):
            if name == "new-angle" and n >= 2:
                break
            day = NOW - timedelta(days=off)
            ts = day.replace(hour=9 + (n % 3), minute=7 * (n % 8), second=0)
            n += 1
            row = {"ts": ts.isoformat(timespec="seconds"), "strategy": name, "run": n, "model": model, "stages": dict(stages),
                   "searches": searches, "run_units": round(units * rng.uniform(0.9, 1.1), 2), "run_units_label": "ESTIMATE",
                   "blocked": False, "best_score": None, "slugs": [], "notes": "fixture"}
            if name == "public-data":
                ex, cand = rng.randint(18, 26), rng.randint(6, 9)
                ps = rng.randint(3, 5)
                sc = min(ps, rng.randint(2, 4))
                fl = 1 if n % 3 == 0 else 0
                drops = {"filter1": rng.randint(0, 2), "filter2": rng.randint(0, 2), "filter3": 1, "filter5": cand - ps - 2 if cand - ps > 2 else 0, "overlap": 1}
            elif name == "accelerators":
                ex, cand = rng.randint(55, 70), rng.randint(0, 2)
                ps, sc, fl = (1 if n % 6 == 0 else 0), 0, 0
                sc = ps if n % 12 == 0 else 0
                drops = {"filter1": cand - ps if cand > ps else 0, "no_source": rng.randint(0, 1)}
            elif name == "subscriptions":
                ex, cand = rng.randint(28, 34), rng.randint(12, 16)
                ps, sc, fl = 0, 0, 0
                f5 = cand - 4
                drops = {"filter1": 1, "filter2": 1, "filter3": 1, "filter5": f5, "overlap": 1}
            elif name == "app-lists":
                ex, cand = rng.randint(25, 32), rng.randint(6, 9)
                ps = rng.randint(3, 4)
                sc, fl = ps, 0
                drops = {"filter2": cand - ps - 1, "filter4": 1}
            elif name == "vanishing-data":
                row.update({"blocked": True, "examined": 0, "candidates": 0, "prescreen_pass": 0, "scored": 0, "at_floor": 0,
                            "dropped": {}, "notes": "fixture: blocked by network policy"})
                runs.append(row)
                continue
            else:  # new-angle
                ex, cand, ps, sc, fl = 20, 5, 2, 1, 0
                drops = {"filter1": 2, "filter3": 1}
            slugs = ["%s-opp-%02d-%d" % (name, n, k) for k in range(sc)]
            row.update({"examined": ex, "candidates": cand, "prescreen_pass": ps, "scored": sc, "at_floor": fl,
                        "dropped": drops, "slugs": slugs,
                        "best_score": (round(rng.uniform(66, 74) if fl else rng.uniform(40, 63), 1)) if sc else None})
            runs.append(row)
            for k, sl in enumerate(slugs):
                outcomes.append({"ts": row["ts"], "slug": sl, "event": "scored", "strategy": name})
                if name == "public-data" and fl and k == 0:
                    outcomes.append({"ts": row["ts"], "slug": sl, "event": "at_floor", "strategy": name})
    # lagged outcomes for the over-performer: top 20, Keeps, one archive
    later = [o["slug"] for o in outcomes if o["event"] == "at_floor"]
    for i, sl in enumerate(later[:3]):
        outcomes.append({"ts": (NOW - timedelta(days=12 - 3 * i)).isoformat(timespec="seconds"), "slug": sl, "event": "top20", "strategy": "public-data"})
    for i, sl in enumerate(later[:2]):
        outcomes.append({"ts": (NOW - timedelta(days=6 - 2 * i)).isoformat(timespec="seconds"), "slug": sl, "event": "keep", "strategy": "public-data"})
    if len(later) > 3:
        outcomes.append({"ts": (NOW - timedelta(days=2)).isoformat(timespec="seconds"), "slug": later[3], "event": "archived", "strategy": "public-data"})
    return runs, outcomes


STEWARD_GRANT = """---
steward:
  enabled: true
  levers: [budget, cadence, model, gates, method, skills]
  requires-approval: [create-strategy, delete-strategy, raise-pool]
  bounds:
    searches: {min: 50, max: 200, max-daily-shift: 20%}
    daily-cap: {min: 10, max: 60}
    cadence: [daily, alternate, weekly, parked]
    models: [haiku, sonnet, opus]
    exploration-share: 15%
  experiment:
    baseline-runs: 3
    treatment-runs: 3
    metric: yield-per-run-unit
    keep-if: "delta > +10% and survivors not fewer"
    on-fail: revert
    max-active: {per-strategy: 1, fleet-wide: 1}
  pools: budget.md
  log: steward-log.md
  pause: control.md
---
Synthetic steward grant for the fixture home. Every number here is invented.
"""


def write_yield(out: Path, rng: random.Random) -> None:
    runs, outcomes = yield_rows(rng)
    ydir = out / "yield"
    ydir.mkdir(parents=True, exist_ok=True)
    by_month = {}
    for r in runs:
        by_month.setdefault(r["ts"][:7], []).append(r)
    for month, rows in sorted(by_month.items()):
        rows.sort(key=lambda r: (r["ts"], r["strategy"], r["run"]))
        (ydir / ("%s.jsonl" % month)).write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    outcomes.sort(key=lambda o: o["ts"])
    (ydir / "outcomes.jsonl").write_text("".join(json.dumps(o, sort_keys=True) + "\n" for o in outcomes), encoding="utf-8")
    settings = {}
    for name, (_, every, searches, _, _, stages) in YIELD_STRATEGIES.items():
        settings[name] = {"searches": searches, "daily_cap": 30, "schedule": "daily" if every == 1 else "alternate",
                          "status": "running", "stages": dict(stages)}
    settings["new-angle"]["status"] = "ready"
    (out / "strategies.json").write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "steward-grant.md").write_text(STEWARD_GRANT, encoding="utf-8")
    (out / "control.md").write_text("---\npaused: false\n---\nSynthetic control file.\n", encoding="utf-8")
    (out / "budget.md").write_text("---\nstrategy_pool_searches: 600\n---\nSynthetic pools. Only the person raises these.\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    generate(Path(args.out).expanduser())
    print("wrote synthetic Otto home to %s (now = %s)" % (args.out, NOW.isoformat(timespec="minutes")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
