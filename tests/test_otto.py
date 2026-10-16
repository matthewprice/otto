"""Otto's tests. Standard library only: python3 -m unittest discover -s tests -v"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import budget  # noqa: E402
import health  # noqa: E402
import ledger  # noqa: E402
import otto_common as oc  # noqa: E402
import retro  # noqa: E402

NOW = "2026-09-24T09:15-05:00"


def demo_home(tmp):
    subprocess.run([sys.executable, str(ROOT / "fixtures/generate.py"), "--out", tmp], check=True, capture_output=True)
    return Path(tmp)


class Frontmatter(unittest.TestCase):
    def test_parse(self):
        fm, body = oc.parse_frontmatter('---\nname: "a"\nn: 3\nl: [x, y]\nd:\n  - 1\n  - 2\nb: true\n---\nbody')
        self.assertEqual(fm["name"], "a"); self.assertEqual(fm["n"], 3); self.assertEqual(fm["l"], ["x", "y"])
        self.assertEqual(fm["d"], [1, 2]); self.assertIs(fm["b"], True); self.assertEqual(body.strip(), "body")

    def test_no_frontmatter(self):
        fm, body = oc.parse_frontmatter("just text")
        self.assertEqual(fm, {})


class Ledger(unittest.TestCase):
    def test_allowlist_drops_text(self):
        row = ledger.sanitize_run({"ts": "2026-09-01T10:00:00-05:00", "automation": "a", "session_id": "s",
                                   "prompt": "SECRET", "result": "SECRET", "outcome": "pass", "cost_usd": 0.5})
        self.assertNotIn("SECRET", json.dumps(row)); self.assertNotIn("prompt", row)

    def test_upsert_prefers_wrapper(self):
        with tempfile.TemporaryDirectory() as t:
            h = Path(t)
            ledger.upsert_run(h, {"ts": "2026-09-01T10:00:00-05:00", "automation": "a", "session_id": "s1", "source": "hook", "cost_usd": 1.0})
            ledger.upsert_run(h, {"ts": "2026-09-01T10:00:00-05:00", "automation": "a", "session_id": "s1", "source": "wrapper", "cost_usd": 2.0, "outcome": "pass"})
            rows = ledger.read_rows(h, kind="run")
            self.assertEqual(len(rows), 1); self.assertEqual(rows[0]["cost_usd"], 2.0)

    def test_real_result_parses(self):
        res = json.loads((ROOT / "tests/data/claude-result-real.json").read_text())
        row = ledger.row_from_result(res, "x", 0)
        self.assertIsNotNone(row.get("cost_usd")); self.assertTrue(row["models"])
        self.assertNotIn("result", row)


class Scenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.home = demo_home(cls.tmp.name)
        cls.now = oc.parse_when(NOW)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_statuses(self):
        rep = health.evaluate(self.home, self.now)
        got = {f["automation"]: f["status"] for f in rep["findings"]}
        self.assertEqual(got["repo-watch"], "miss"); self.assertEqual(got["nightly-sync"], "breaker")
        self.assertEqual(got["weekly-brief"], "fail"); self.assertEqual(got["inbox-triage"], "drift")
        self.assertEqual(got["morning-digest"], "ok")

    def test_budget_pools(self):
        rep = budget.report(self.home, self.now)
        self.assertEqual(len(rep["windows"]), 2)
        self.assertIn("sdk_credit", rep["spend"])
        self.assertTrue(all("level" in w for w in rep["windows"] if w.get("available")))

    def test_retro_step_change(self):
        rep = retro.report(self.home, 7, self.now)
        self.assertIn("step_change", rep["by_automation"]["morning-digest"])
        self.assertGreater(rep["totals"]["this_period"]["failed_cost_usd"], 0)


class Runner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        h = Path(self.tmp.name)
        (h / "vault/Automations").mkdir(parents=True)
        (h / "vault/Automations/job.md").write_text(
            '---\nname: job\nsurface: local-cli\ncommand: "/x"\ndays: daily\nexpected_by: "23:59"\ntimezone: UTC\n'
            'success_file: "out/{date}.txt"\nsuccess_cwd: "{OTTO_HOME}"\nsuccess_min_bytes: 2\ncwd: /tmp\ntimeout_min: 1\nregistered: "2026-01-01"\n---\n')
        (h / "otto.md").write_text("---\nbreaker_threshold: 2\nattempt_cap_per_day: 5\n---\n")
        stub = h / "stub.sh"
        stub.write_text('#!/bin/bash\nif [ "$STUB" = ok ]; then mkdir -p $OTTO_HOME/out; echo hi > $OTTO_HOME/out/2026-01-10.txt; '
                        'echo \'{"type":"result","is_error":false,"total_cost_usd":0.1,"result":"SECRETTEXT"}\'; else echo \'{"type":"result","is_error":true,"api_error_status":401}\'; exit 1; fi\n')
        stub.chmod(0o755)
        self.env = dict(os.environ, OTTO_HOME=str(h), CLAUDE_BIN=str(stub))
        self.h = h

    def tearDown(self):
        self.tmp.cleanup()

    def run_(self, stub, *extra):
        # The clock is pinned so the target cycle (due 2026-01-10 23:59 UTC) never depends on when the tests run.
        return subprocess.run([sys.executable, str(ROOT / "scripts/run.py"), "job", "--now", "2026-01-10T12:00:00+00:00", *extra],
                              env=dict(self.env, STUB=stub), capture_output=True, text=True)

    def test_pass_then_idempotent(self):
        self.assertEqual(self.run_("ok").returncode, 0)
        r = self.run_("ok")
        self.assertIn("already done", r.stdout)
        self.assertNotIn("SECRETTEXT", "".join(p.read_text() for p in (self.h / "ledger").glob("*.jsonl")))

    def test_breaker_opens_and_resets(self):
        self.run_("bad"); self.run_("bad")
        self.assertTrue(json.loads((self.h / "state/breaker.json").read_text())["job"]["open"])
        self.assertIn("breaker", self.run_("ok").stdout)
        self.run_("x", "--reset-breaker")
        self.assertEqual(self.run_("ok").returncode, 0)

    def test_dry_run_writes_nothing(self):
        r = self.run_("ok", "--dry-run")
        self.assertIn('"decision": "run"', r.stdout)
        self.assertFalse(list((self.h / "ledger").glob("*.jsonl")))

    def test_never_bypasses_permissions(self):
        self.assertNotIn("dangerously", (ROOT / "scripts/run.py").read_text().replace("never uses --dangerously", "").split("def build_argv")[1])


class Hooks(unittest.TestCase):
    def test_guard_off_allows(self):
        with tempfile.TemporaryDirectory() as t:
            r = subprocess.run([sys.executable, str(ROOT / "scripts/guard.py")], input='{"prompt":"hi"}', env=dict(os.environ, OTTO_HOME=t), capture_output=True, text=True)
            self.assertEqual(r.returncode, 0)

    def test_guard_blocks_and_allows_override(self):
        import time
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "state").mkdir()
            (Path(t) / "otto.md").write_text("---\nguard: block\n---\n")
            (Path(t) / "state/statusline.json").write_text(json.dumps({"captured_at": int(time.time()), "rate_limits": {"five_hour": {"used_percentage": 97}}}))
            env = dict(os.environ, OTTO_HOME=t)
            run = lambda p: subprocess.run([sys.executable, str(ROOT / "scripts/guard.py")], input=json.dumps({"prompt": p}), env=env, capture_output=True, text=True).returncode
            self.assertEqual(run("hello"), 2); self.assertEqual(run("/otto:status"), 0); self.assertEqual(run("otto: go ahead"), 0)


class Repo(unittest.TestCase):
    def test_no_em_dashes_in_prose(self):
        bad = []
        for p in list(ROOT.glob("*.md")) + list(ROOT.glob("docs/*.md")) + list(ROOT.glob("skills/*/SKILL.md")):
            if "—" in p.read_text(encoding="utf-8"):
                bad.append(p.name)
        self.assertEqual(bad, [])

    def test_skill_frontmatter(self):
        for p in ROOT.glob("skills/*/SKILL.md"):
            fm, _ = oc.parse_frontmatter(p.read_text())
            self.assertEqual(fm["name"], p.parent.name); self.assertLess(len(fm["description"]), 1024)


if __name__ == "__main__":
    unittest.main()
