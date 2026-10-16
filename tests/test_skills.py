"""The five roadmap skills: discover, verify, timeline, experiment, watch. Standard library only."""
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import discover  # noqa: E402
import experiment  # noqa: E402
import health  # noqa: E402
import ledger  # noqa: E402
import otto_common as oc  # noqa: E402
import retro  # noqa: E402
import timeline  # noqa: E402
import verify  # noqa: E402
import watch  # noqa: E402

NOW = oc.parse_when("2026-09-24T09:15-05:00")


def demo_home(tmp):
    subprocess.run([sys.executable, str(ROOT / "fixtures/generate.py"), "--out", tmp], check=True, capture_output=True)
    return Path(tmp)


class Frontmatter(unittest.TestCase):
    def test_dump_round_trips(self):
        fm = {"name": "a-b", "days": ["mon", "wed"], "expected_by": "08:00", "n": 3, "flag": True, "cmd": "/x: y"}
        back, body = oc.parse_frontmatter(oc.dump_frontmatter(fm, "body text"))
        self.assertEqual(back, fm)
        self.assertEqual(body.strip(), "body text")


class Discover(unittest.TestCase):
    def test_cron_parsing(self):
        s = discover.parse_cron("30 6 * * 1-5")
        self.assertEqual(s["kind"], "calendar"); self.assertEqual(s["time"], "06:30"); self.assertEqual(s["days"], [0, 1, 2, 3, 4])
        self.assertEqual(discover.parse_cron("0 7 * * 0")["days"], [6])
        self.assertEqual(discover.parse_cron("*/15 * * * *")["kind"], "interval")
        self.assertEqual(discover.parse_cron("0 7 1 * *")["kind"], "irregular")

    def test_launchd_and_drift(self):
        with tempfile.TemporaryDirectory() as t:
            h = demo_home(t)
            agents = Path(t) / "agents"; agents.mkdir()
            pl = {"Label": "com.otto.morning-digest", "ProgramArguments": ["/usr/bin/python3", "/Users/x/.otto/bin/run.py", "morning-digest"],
                  "StartCalendarInterval": [{"Weekday": d, "Hour": 7, "Minute": 30} for d in (1, 2, 3, 4, 5)]}
            with open(agents / "com.otto.morning-digest.plist", "wb") as fh:
                plistlib.dump(pl, fh)
            other = {"Label": "com.example.backup", "ProgramArguments": ["/usr/bin/rsync", "-a", "x", "y"], "StartInterval": 3600}
            with open(agents / "com.example.backup.plist", "wb") as fh:
                plistlib.dump(other, fh)
            rep = discover.scan(h, Path(t), NOW, claude_home=Path(t) / "nohome", agents_dir=agents, unit_dir=Path(t) / "nounits", crontab=False)
            ids = [c["id"] for c in rep["candidates"]]
            self.assertIn("launchd-com.otto.morning-digest", ids)
            self.assertNotIn("launchd-com.example.backup", ids)
            c = next(c for c in rep["candidates"] if c["id"] == "launchd-com.otto.morning-digest")
            self.assertEqual(c["registry"], "morning-digest")
            self.assertTrue(any(d.startswith("time:") or d.startswith("days:") for d in c["drift"]), c["drift"])

    def test_draft_writes_note(self):
        with tempfile.TemporaryDirectory() as t:
            h = demo_home(t)
            cand = discover._cand("cron-9", "local-cli", "crontab", "new-job", {"kind": "calendar", "time": "05:00", "days": [0, 1, 2, 3, 4]},
                                  'claude -p "/brief" --output-format json', "/tmp", "crontab line 9")
            path = discover.draft(h, cand, None, None, "~/out/{date}.md", datetime(2026, 9, 24).date())
            fm, body = oc.read_frontmatter(path)
            self.assertEqual(fm["name"], "new-job"); self.assertEqual(fm["expected_by"], "05:30"); self.assertEqual(fm["days"], "weekdays")
            self.assertEqual(fm["success_file"], "~/out/{date}.md"); self.assertIn("Drafted by /otto:discover", body)
            with self.assertRaises(FileExistsError):
                discover.draft(h, cand, None, None, None, datetime(2026, 9, 24).date())
            autos, problems = health.load_registry(h, oc.load_config(h))
            self.assertIn("new-job", [a["name"] for a in autos]); self.assertEqual(problems, [])

    def test_desktop_tasks(self):
        with tempfile.TemporaryDirectory() as t:
            ch = Path(t) / ".claude"; (ch / "scheduled-tasks/pepper-brief").mkdir(parents=True)
            (ch / "scheduled-tasks/pepper-brief/SKILL.md").write_text("---\nname: pepper-brief\ndescription: Daily brief\n---\nbody\n")
            c = discover.scan_desktop(ch)
            self.assertEqual(c[0]["surface"], "desktop-task"); self.assertEqual(c[0]["schedule"]["kind"], "unknown")


class Verify(unittest.TestCase):
    def test_check_and_lint(self):
        with tempfile.TemporaryDirectory() as t:
            h = demo_home(t)
            rep = verify.verify(h, "morning-digest", NOW)
            self.assertIn(rep["verdict"], ("pass", "fail", "no-check"))
            self.assertIsNotNone(rep["status_now"])
            bad = verify.verify(h, "nope", NOW)
            self.assertIn("error", bad)

    def test_drills_are_caught_and_leave_the_ledger_alone(self):
        with tempfile.TemporaryDirectory() as t:
            h = demo_home(t)
            before = ledger.read_rows(h)
            for kind, statuses in (("miss", {"miss"}), ("auth", {"breaker"}), ("budget", {"fail"}), ("timeout", {"fail"})):
                rep = verify.drill(h, "morning-digest", kind, NOW)
                self.assertTrue(rep["caught"], rep)
                self.assertIn(rep["would_report"]["status"], statuses, rep["would_report"])
                self.assertIsNone(rep["scratch_home"])
            self.assertEqual(ledger.read_rows(h), before)


class Timeline(unittest.TestCase):
    def test_grid_and_cold_starts(self):
        with tempfile.TemporaryDirectory() as t:
            h = demo_home(t)
            hist = oc.state_dir(h) / "statusline-history.jsonl"
            resets = int((NOW + timedelta(hours=2)).timestamp())
            hist.write_text(json.dumps({"captured_at": int(NOW.timestamp()) - 600, "rate_limits": {"five_hour": {"used_percentage": 72, "resets_at": resets}}}) + "\n")
            rep = timeline.report(h, NOW, 14, claude_home=Path(t) / "nohome")
            names = {r["automation"] for r in rep["rows"]}
            self.assertIn("morning-digest", names)
            self.assertIn("morning-digest", rep["grid"])
            self.assertTrue(rep["hot_windows"]["hours"])
            self.assertTrue(all(isinstance(c["cold_fraction"], float) for c in rep["cold_starts"].values()))
            md = timeline.render_markdown(rep)
            self.assertIn("Proposed moves", md)
            for p in rep["proposals"]:
                self.assertIn(p["kind"], ("collision", "keyboard", "cold"))


class Experiment(unittest.TestCase):
    def test_estimate_start_status(self):
        with tempfile.TemporaryDirectory() as t:
            h = demo_home(t)
            est = experiment.estimate(h, "morning-digest", model="haiku", now=NOW)
            self.assertEqual(est["label"], "ESTIMATE")
            self.assertIn("model_change", est)
            self.assertLess(est["model_change"]["projected_per_run_usd"], est["baseline"]["cost_usd"])
            rec = experiment.start(h, "morning-digest", "switch to haiku", "model", 3, NOW)
            self.assertEqual(rec["status"], "collecting")
            self.assertEqual(rec["baseline"]["runs"], 7)
            st = experiment.status(h, rec["id"], NOW)[0]
            self.assertIn("waiting", st)
            for i in range(3):
                ledger.upsert_run(h, {"ts": oc.iso(NOW + timedelta(days=i + 1, hours=-2)), "automation": "morning-digest", "surface": "local-cli",
                                      "source": "wrapper", "session_id": "exp-%d" % i, "outcome": "pass", "cost_usd": 0.4, "duration_ms": 300000, "exit": 0})
            st = experiment.status(h, rec["id"], NOW + timedelta(days=5))[0]
            self.assertEqual(st["status"], "done")
            self.assertTrue(st["verdict"].startswith("pays"), st["verdict"])
            self.assertTrue(st["small_sample"] is False or st["caveat"])
            self.assertTrue(any(c["note"].startswith("experiment") for c in retro.effects(h, NOW + timedelta(days=5))))


class Watch(unittest.TestCase):
    def test_alerts_only_on_change(self):
        with tempfile.TemporaryDirectory() as t:
            h = demo_home(t)
            first = watch.tick(h, NOW, desktop=False)
            self.assertEqual(len(first), 1); self.assertIn("watch started", first[0])
            second = watch.tick(h, NOW + timedelta(minutes=5), desktop=False)
            self.assertEqual(second, [])
            # a new day with no evidence for morning-digest becomes a miss
            later = NOW + timedelta(days=1)
            third = watch.tick(h, later, desktop=False)
            self.assertTrue(any("morning-digest is now MISS" in a for a in third), third)
            alerts = (h / "vault/Alerts.md").read_text()
            self.assertIn("MISS", alerts)
            fourth = watch.tick(h, later + timedelta(minutes=5), desktop=False)
            self.assertEqual(fourth, [])

    def test_once_runs_from_cli(self):
        with tempfile.TemporaryDirectory() as t:
            h = demo_home(t)
            r = subprocess.run([sys.executable, str(ROOT / "scripts/watch.py"), "--home", str(h), "--once", "--now", oc.iso(NOW), "--no-desktop"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("Otto watch started", r.stdout)


class RetroMarkdown(unittest.TestCase):
    def test_shareable_report_has_no_text_fields(self):
        with tempfile.TemporaryDirectory() as t:
            h = demo_home(t)
            md = retro.render_markdown(retro.report(h, 7, NOW))
            self.assertIn("| Runs |", md); self.assertIn("morning-digest", md); self.assertNotIn("prompt", md.lower())


if __name__ == "__main__":
    unittest.main()
