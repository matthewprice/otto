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
        self.assertIn("api_credit", rep["spend"])
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


class ApiKeyAccount(unittest.TestCase):
    """An API-key login has no subscription windows; everything else must still work."""

    def test_budget_without_windows(self):
        with tempfile.TemporaryDirectory() as t:
            h = Path(t)
            (h / "otto.md").write_text("---\nbudget_weekly_usd: 10\n---\n")
            now = oc.parse_when(NOW)
            ledger.upsert_run(h, {"ts": "2026-09-23T10:00:00-05:00", "automation": "a", "session_id": "k1", "source": "wrapper",
                                  "surface": "local-cli", "outcome": "pass", "cost_usd": 2.5})
            rep = budget.report(h, now)
            self.assertFalse(any(w["available"] for w in rep["windows"]))
            self.assertIn("API-key", rep["windows"][0]["reason"])
            self.assertEqual(rep["spend"]["weekly_used_percent"], 25.0)
            self.assertNotIn("api_credit", rep["spend"])

    def test_capture_without_rate_limits(self):
        # An API-key session still writes a statusline capture, just with no rate_limits block.
        import time
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "state").mkdir()
            (Path(t) / "otto.md").write_text("---\nguard: block\n---\n")
            (Path(t) / "state/statusline.json").write_text(json.dumps({"captured_at": int(time.time())}))
            rep = budget.report(Path(t), oc.parse_when(NOW))
            self.assertFalse(any(w["available"] for w in rep["windows"]))
            r = subprocess.run([sys.executable, str(ROOT / "scripts/guard.py")], input='{"prompt":"hi"}',
                               env=dict(os.environ, OTTO_HOME=t), capture_output=True, text=True)
            self.assertEqual(r.returncode, 0)

    def run_job(self, t, settings, **env_extra):
        """Run a stub job and return (result, what the stub saw for the two credential variables)."""
        h = Path(t)
        (h / "vault/Automations").mkdir(parents=True, exist_ok=True)
        (h / "vault/Automations/job.md").write_text(
            '---\nname: job\nsurface: local-cli\ncommand: "/x"\ndays: daily\nexpected_by: "23:59"\ntimezone: UTC\n'
            'cwd: /tmp\ntimeout_min: 1\nregistered: "2026-01-01"\n---\n')
        (h / "otto.md").write_text("---\nbreaker_threshold: 2\n%s---\n" % settings)
        dump = h.parent / (h.name + "-env.txt")
        stub = h / "stub.sh"
        stub.write_text('#!/bin/bash\necho "key=${ANTHROPIC_API_KEY-unset} oauth=${CLAUDE_CODE_OAUTH_TOKEN-unset}" > %s\n'
                        'echo \'{"type":"result","is_error":false,"total_cost_usd":0.1,"result":"x"}\'\n' % dump)
        stub.chmod(0o755)
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")}
        env.update(OTTO_HOME=t, CLAUDE_BIN=str(stub), **env_extra)
        try:
            r = subprocess.run([sys.executable, str(ROOT / "scripts/run.py"), "job", "--now", "2026-01-10T12:00:00+00:00"],
                               env=env, capture_output=True, text=True)
            return r, dump.read_text().strip() if dump.exists() else None
        finally:
            dump.unlink(missing_ok=True)

    def test_runner_inherits_key_without_a_command(self):
        with tempfile.TemporaryDirectory() as t:
            r, seen = self.run_job(t, "", ANTHROPIC_API_KEY="sk-ant-test-KEYVALUE")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(seen, "key=sk-ant-test-KEYVALUE oauth=unset")

    def test_api_key_cmd_supplies_key_and_drops_oauth(self):
        # A scheduler environment with a stale OAuth token and no key: the job must see only the key.
        with tempfile.TemporaryDirectory() as t:
            r, seen = self.run_job(t, 'api_key_cmd: "echo sk-ant-test-KEYVALUE"\n', CLAUDE_CODE_OAUTH_TOKEN="stale")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(seen, "key=sk-ant-test-KEYVALUE oauth=unset")
            self.assertEqual([x.get("credential") for x in ledger.read_rows(Path(t), kind="run")], ["api_key"])
            for f in Path(t).rglob("*"):
                if f.is_file() and f.name != "otto.md":
                    self.assertNotIn("KEYVALUE", f.read_text(errors="ignore"), f)

    def test_token_cmd_drops_inherited_key(self):
        with tempfile.TemporaryDirectory() as t:
            r, seen = self.run_job(t, 'token_cmd: "echo oauth-test"\n', ANTHROPIC_API_KEY="sk-ant-test-KEYVALUE")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(seen, "key=unset oauth=oauth-test")
            self.assertEqual([x.get("credential") for x in ledger.read_rows(Path(t), kind="run")], ["subscription"])

    def test_both_commands_refused(self):
        with tempfile.TemporaryDirectory() as t:
            r, seen = self.run_job(t, 'token_cmd: "echo a"\napi_key_cmd: "echo b"\n')
            self.assertEqual(r.returncode, 2)
            self.assertIn("not both", r.stderr)
            self.assertIsNone(seen)

    def test_api_key_failures_classify(self):
        import run
        self.assertEqual(run.classify_failure(1, {}, "Invalid API key · Please run /login", False), "auth")
        self.assertEqual(run.classify_failure(1, {}, "Credit balance is too low", False), "budget")


class ApiCredit(unittest.TestCase):
    """The monthly API credit pays for headless API-key runs only."""

    def test_credential_from_env(self):
        self.assertEqual(oc.credential_from_env({"ANTHROPIC_API_KEY": "k", "CLAUDE_CODE_OAUTH_TOKEN": "t"}), "api_key")
        self.assertEqual(oc.credential_from_env({"CLAUDE_CODE_OAUTH_TOKEN": "t"}), "subscription")
        self.assertIsNone(oc.credential_from_env({}))

    def test_ledger_keeps_only_known_credentials(self):
        self.assertEqual(ledger.sanitize_run({"credential": "api_key"})["credential"], "api_key")
        self.assertNotIn("credential", ledger.sanitize_run({"credential": "sk-ant-leaked"}))

    def test_only_api_key_headless_runs_count(self):
        with tempfile.TemporaryDirectory() as t:
            h = Path(t)
            (h / "otto.md").write_text("---\napi_credit_usd: 100\n---\n")
            rows = [("a1", "local-cli", "api_key", 4.0), ("a2", "local-cli", "subscription", 8.0),
                    ("a3", "local-cli", None, 16.0), ("a4", "github-actions", "api_key", 32.0), ("a5", "interactive", "api_key", 64.0)]
            for sid, surface, cred, cost in rows:
                row = {"ts": "2026-09-10T10:00:00-05:00", "automation": "job", "session_id": sid, "source": "wrapper",
                       "surface": surface, "outcome": "pass", "cost_usd": cost}
                if cred:
                    row["credential"] = cred
                ledger.upsert_run(h, row)
            c = budget.report(h, oc.parse_when(NOW))["spend"]["api_credit"]
            self.assertEqual(c["estimated_used_usd"], 4.0)
            self.assertEqual(c["runs_in_period"], 1)
            self.assertEqual(c["runs_not_counted"], 1)
            self.assertIn("api_key_cmd", c["not_counted_reason"])

    def test_stop_hook_records_credential(self):
        with tempfile.TemporaryDirectory() as t:
            tp = Path(t) / "s.jsonl"
            tp.write_text(json.dumps({"type": "assistant", "sessionId": "hook-1", "timestamp": "2026-09-10T15:00:00Z",
                                      "message": {"id": "m1", "model": "claude-sonnet-5-5", "usage": {"input_tokens": 10, "output_tokens": 5}}}) + "\n")
            env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")}
            env.update(OTTO_HOME=t, OTTO_AUTOMATION="job", ANTHROPIC_API_KEY="sk-ant-test-KEYVALUE")
            r = subprocess.run([sys.executable, str(ROOT / "scripts/hook.py"), "stop"], input=json.dumps({"session_id": "hook-1", "transcript_path": str(tp)}),
                               env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0)
            rows = ledger.read_rows(Path(t), kind="run")
            self.assertEqual([x.get("credential") for x in rows], ["api_key"])
            self.assertNotIn("KEYVALUE", json.dumps(rows))


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
