"""Steward mode: grant, yield ledger, allocation, diagnosis, evolution. Standard library only.

Hand-computed expectations use small homes built in the test; the fixture home is used only for
the acceptance checks in the implementation brief. Fixture numbers are not results.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import allocate  # noqa: E402
import diagnose  # noqa: E402
import evolve  # noqa: E402
import experiment  # noqa: E402
import otto_common as oc  # noqa: E402
import steward  # noqa: E402

Y = steward.load_script("yield")
NOW = oc.parse_when("2026-09-24T09:15-05:00")
GRANT = """---
steward:
  enabled: true
  levers: [budget, cadence, model, gates, method, skills]   # any subset
  requires-approval: [create-strategy, delete-strategy, raise-pool]
  bounds:
    searches: {min: 50, max: 200, max-daily-shift: 20%}
    daily-cap: {min: 10, max: 60}
    cadence: [daily, alternate, weekly, parked]
    models: [haiku, sonnet, opus]                            # fable never
    exploration-share: 15%
  experiment:
    baseline-runs: 3
    treatment-runs: 3
    metric: yield-per-run-unit
    keep-if: "delta > +10% and survivors not fewer"
    on-fail: revert
    max-active: {per-strategy: 1, fleet-wide: 1}
  pools: ops/budget.md
  log: ops/steward-log.md
  pause: ops/control.md
---
body
"""


def demo_home(tmp):
    subprocess.run([sys.executable, str(ROOT / "fixtures/generate.py"), "--out", tmp], check=True, capture_output=True)
    return Path(tmp)


def write_grant(dirpath, text=GRANT):
    p = Path(dirpath) / "steward.md"
    p.write_text(text, encoding="utf-8")
    return p


def run_row(strategy, run, day, **kw):
    r = {"ts": oc.iso(NOW - timedelta(days=day)), "strategy": strategy, "run": run, "searches": 100, "run_units": 2.0,
         "run_units_label": "ESTIMATE", "examined": 20, "candidates": 5, "prescreen_pass": 2, "scored": 0, "at_floor": 0}
    r.update(kw)
    return r


# --------------------------------------------------------------------------- grant

class Grant(unittest.TestCase):
    def test_parses_the_design_grant(self):
        with tempfile.TemporaryDirectory() as t:
            g = steward.grant(str(write_grant(t)), Path(t), Path(t))
            self.assertTrue(g.enabled); self.assertEqual(g.mode, "steward")
            self.assertEqual(g.levers(), ["budget", "cadence", "model", "gates", "method", "skills"])
            self.assertEqual(g.bounds("searches"), {"min": 50, "max": 200, "max-daily-shift": 0.2})
            self.assertEqual(g.bounds("daily-cap"), {"min": 10, "max": 60})
            self.assertAlmostEqual(g.bounds("exploration-share"), 0.15)
            self.assertEqual(g.bounds("models"), ["haiku", "sonnet", "opus"])
            self.assertEqual(g.max_active(), {"per-strategy": 1, "fleet-wide": 1})
            self.assertEqual(g.experiment("keep-if"), "delta > +10% and survivors not fewer")
            self.assertEqual(g.pause_path(), Path(t) / "ops/control.md")
            self.assertTrue(g.allowed("method"))

    def test_no_grant_is_propose_mode(self):
        with tempfile.TemporaryDirectory() as t:
            g = steward.grant(None, Path(t))
            self.assertEqual(g.mode, "propose")
            for lever in steward.LEVERS:
                self.assertFalse(g.allowed(lever))
            self.assertEqual(g.bounds("searches")["max"], 200)  # defaults still answer
            missing = steward.grant(str(Path(t) / "nope.md"), Path(t))
            self.assertEqual(missing.mode, "propose"); self.assertTrue(missing.problems)

    def test_local_grant_in_otto_md(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "otto.md").write_text(GRANT.replace("  levers: [budget, cadence, model, gates, method, skills]   # any subset", "  levers: [budget]"))
            g = steward.grant(None, Path(t), Path(t))
            self.assertTrue(g.allowed("budget")); self.assertFalse(g.allowed("method"))
            self.assertIn("not in the grant", g.why("method")[1])
            self.assertEqual(oc.load_config(Path(t))["lights"], "off")  # otto.md settings unaffected

    def test_disabled_and_never_levers(self):
        with tempfile.TemporaryDirectory() as t:
            g = steward.grant(str(write_grant(t, GRANT.replace("enabled: true", "enabled: false"))), Path(t), Path(t))
            self.assertEqual(g.mode, "propose"); self.assertFalse(g.allowed("budget"))
            g2 = steward.grant(str(write_grant(t, GRANT.replace("levers: [budget,", "levers: [raise-pool, create-strategy, budget,"))), Path(t), Path(t))
            self.assertFalse(g2.allowed("raise-pool")); self.assertFalse(g2.allowed("create-strategy"))
            self.assertNotIn("raise-pool", g2.levers())

    def test_model_ceiling_never_includes_fable(self):
        with tempfile.TemporaryDirectory() as t:
            g = steward.grant(str(write_grant(t, GRANT.replace("models: [haiku, sonnet, opus]", "models: [haiku, sonnet, fable]"))), Path(t), Path(t))
            self.assertEqual(g.bounds("models"), ["haiku", "sonnet"]); self.assertEqual(g.model_ceiling(), "sonnet")

    def test_pause(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "ops").mkdir()
            g = steward.grant(str(write_grant(t)), Path(t) / "home", Path(t))
            self.assertFalse(g.paused())
            (Path(t) / "ops/control.md").write_text("---\npaused: true\n---\n")
            self.assertTrue(g.paused()); self.assertEqual(g.mode, "paused"); self.assertFalse(g.allowed("budget"))
            (Path(t) / "ops/control.md").write_text("# Control\n\n- **paused**: false\n")
            self.assertFalse(g.paused())
            (Path(t) / "ops/PAUSE").write_text("")
            self.assertTrue(g.paused())

    def test_broken_grant_fails_open(self):
        with tempfile.TemporaryDirectory() as t:
            p = write_grant(t, "---\nsteward:\n  enabled: [unterminated\n  bounds: {min: \n---\n")
            g = steward.grant(str(p), Path(t))
            self.assertEqual(g.mode, "propose")
            r = subprocess.run([sys.executable, str(ROOT / "scripts/steward.py"), "--grant", str(p), "show"], capture_output=True, text=True,
                               env=dict(os.environ, OTTO_HOME=t))
            self.assertEqual(r.returncode, 0); self.assertIn("propose", r.stdout)

    def test_metric_points_override(self):
        with tempfile.TemporaryDirectory() as t:
            g = steward.grant(str(write_grant(t, GRANT.replace("  pools:", "  metric-points:\n    archived: 0\n    keep: 30\n    bogus: 5\n  pools:"))), Path(t))
            self.assertEqual(g.rules["points"]["archived"], 0); self.assertEqual(g.rules["points"]["keep"], 30)
            self.assertNotIn("bogus", g.rules["points"])
            self.assertEqual(steward.load_rules()["points"]["archived"], -1)


# --------------------------------------------------------------------------- yield

class Yield(unittest.TestCase):
    def test_points_and_smoothing_by_hand(self):
        with tempfile.TemporaryDirectory() as t:
            h = Path(t)
            Y.ingest(h, [
                run_row("A", 1, 5, scored=2, at_floor=1, slugs=["a-one", "a-two"]),
                run_row("A", 2, 4, scored=1, slugs=["a-three"]),
                run_row("A", 3, 3, scored=0),
                run_row("A", 4, 2, blocked=True, scored=9),
                run_row("B", 1, 2, scored=1, run_units=1.0, slugs=["b-one"]),
            ])
            Y.add_outcomes(h, [{"ts": oc.iso(NOW - timedelta(days=1)), "slug": "a-one", "event": "top20"}])
            rep = Y.report(h, 30, NOW)
            a, b = rep["strategies"]["A"], rep["strategies"]["B"]
            # A: 2*1 + 1*3 (run 1) + 1 (run 2) + 0 (run 3) + 8 (a-one top 20) = 14 points over 6.0 run-units
            self.assertEqual(a["points"], 14); self.assertEqual(a["run_units"], 6.0)
            self.assertAlmostEqual(a["yield_per_unit"], 2.3333, places=4)
            self.assertAlmostEqual(a["points_per_100_searches"], 14 * 100 / 300.0, places=4)
            self.assertEqual(a["runs"], 3); self.assertEqual(a["blocked_runs"], 1); self.assertEqual(a["funnel"]["top20"], 1)
            # B: 1 point over 1.0 run-units, one run: blended with the fleet median (2.3333 + 1.0) / 2 = 1.6667
            self.assertEqual(b["yield_per_unit"], 1.0)
            self.assertAlmostEqual(rep["fleet_median_yield_per_unit"], 1.6667, places=4)
            self.assertAlmostEqual(b["smoothed_yield"], (1 * 1.0 + 2 * (7 / 3.0 + 1.0) / 2) / 3, places=3)
            self.assertAlmostEqual(a["smoothed_yield"], 2.3333, places=4)
            self.assertEqual(b["sample"], "small"); self.assertEqual(a["sample"], "small")
            self.assertEqual(rep["ranked"][0], "A"); self.assertEqual(rep["blocked_runs"], 1)

    def test_kill_and_archive_subtract(self):
        with tempfile.TemporaryDirectory() as t:
            h = Path(t)
            Y.ingest(h, [run_row("K", i, 10 - i, scored=1, slugs=["k-%d" % i]) for i in range(1, 8)])
            Y.add_outcomes(h, [{"ts": oc.iso(NOW - timedelta(days=1)), "slug": "k-1", "event": "kill"},
                               {"ts": oc.iso(NOW - timedelta(days=1)), "slug": "k-2", "event": "archived"}])
            s = Y.report(h, 30, NOW)["strategies"]["K"]
            self.assertEqual(s["points"], 7 - 2 - 1); self.assertEqual(s["sample"], "ok")

    def test_ingest_is_idempotent_and_drops_text(self):
        with tempfile.TemporaryDirectory() as t:
            h = Path(t)
            row = run_row("S08", 2, 1, prompt="SECRET PROMPT", result="SECRET", notes="x" * 300, dropped={"filter3": 4, "Overlap": 2})
            self.assertEqual(Y.ingest(h, [row])["added"], 1)
            self.assertEqual(Y.ingest(h, [row]), {"added": 0, "updated": 1, "skipped": 0})
            self.assertEqual(Y.ingest(h, [{"strategy": "x"}])["skipped"], 1)
            text = "".join(p.read_text() for p in (h / "yield").glob("*.jsonl"))
            self.assertNotIn("SECRET", text); self.assertEqual(text.count("\n"), 1)
            r = Y.read_runs(h)[0]
            self.assertEqual(r["strategy"], "S08"); self.assertEqual(len(r["notes"]), 120)
            self.assertEqual(r["dropped"], {"filter3": 4, "overlap": 2})
            self.assertTrue(set(r) <= Y.RUN_KEYS)
            o = {"ts": oc.iso(NOW), "slug": "Drone Rule Index", "event": "keep", "strategy": "S00", "detail": "SECRET"}
            Y.add_outcomes(h, [o, o, {"ts": oc.iso(NOW), "slug": "x", "event": "liked"}])
            outs = Y.read_outcomes(h)
            self.assertEqual(len(outs), 1); self.assertEqual(outs[0]["slug"], "drone-rule-index"); self.assertNotIn("detail", outs[0])

    def test_fixture_acceptance(self):
        with tempfile.TemporaryDirectory() as t:
            h = demo_home(t)
            rep = Y.report(h, 30, NOW)
            self.assertEqual(rep["ranked"][0], "public-data")
            self.assertEqual(rep["strategies"]["new-angle"]["runs"], 2)
            self.assertEqual(rep["strategies"]["new-angle"]["sample"], "small")
            self.assertEqual(rep["strategies"]["vanishing-data"]["runs"], 0)
            self.assertGreater(rep["strategies"]["vanishing-data"]["blocked_runs"], 0)


# --------------------------------------------------------------------------- allocation

class Allocation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.home = demo_home(cls.tmp.name)
        cls.g = steward.grant(str(cls.home / "steward-grant.md"), cls.home, cls.home)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def plan(self, pool=600, **kw):
        return allocate.plan(self.home, pool, self.g, str(self.home / "strategies.json"), now=NOW, write=False, **kw)

    def test_acceptance_on_fixtures(self):
        p = self.plan(600, dry_run=True)
        s = p["strategies"]
        self.assertLessEqual(p["total_searches"], 600)
        self.assertEqual(s["vanishing-data"]["searches"], 0)
        self.assertGreaterEqual(s["new-angle"]["searches"], 0.15 * 600)
        self.assertTrue(all(not c["apply"] for r in s.values() for c in r["changes"]))

    def test_shift_bound_and_searches_bounds(self):
        p = self.plan(600)
        settings = json.loads((self.home / "strategies.json").read_text())
        for n, r in p["strategies"].items():
            if r["searches"] == 0 or n == "new-angle":
                continue
            was = settings[n]["searches"]
            self.assertLessEqual(r["searches"], was * 1.2 + 1e-9, n)
            self.assertGreaterEqual(r["searches"], was * 0.8 - 1, n)
            self.assertGreaterEqual(r["searches"], 50); self.assertLessEqual(r["searches"], 200)
        self.assertTrue(any(c["apply"] for r in p["strategies"].values() for c in r["changes"]))

    def test_small_pool_is_never_exceeded(self):
        for pool in (0, 120, 250):
            p = self.plan(pool)
            self.assertLessEqual(p["total_searches"], pool, pool)

    def _reserve_home(self, t, small=("s1", "s2"), settings_extra=None):
        h = Path(t)
        rows = [run_row("big", i, 20 - i, scored=3, at_floor=1) for i in range(1, 11)]
        rows += [run_row("mid", i, 20 - i, scored=1) for i in range(1, 11)]
        rows += [run_row(n, 1, 2, scored=0) for n in small]
        Y.ingest(h, rows)
        st = {n: {"searches": 100, "schedule": "daily", "status": "running"} for n in ("big", "mid") + tuple(small)}
        st.update(settings_extra or {})
        sp = h / "settings.json"
        sp.write_text(json.dumps(st))
        return h, steward.grant(str(write_grant(t)), h, h), str(sp)

    def test_new_strategies_drawn_from_reserve_at_floor(self):
        with tempfile.TemporaryDirectory() as t:
            h, g, sp = self._reserve_home(t, settings_extra={"s2": {"searches": 100, "schedule": "daily", "status": "ready"}})
            p = allocate.plan(h, 600, g, sp, now=NOW, write=False)
            for n in ("s1", "s2"):
                r = p["strategies"][n]
                self.assertEqual(r["reserve_consumer"], "new-strategy")
                self.assertEqual(r["searches"], 50)  # 15% of 600 over two is 45, raised to searches.min 50
            self.assertEqual(p["reserve_drawn"]["new-strategy"], 100)
            self.assertEqual(p["reserve"], 600 - p["allocated_regular"])
            self.assertLessEqual(p["total_searches"], 600)

    def test_experiment_drawn_from_reserve_at_searches_max(self):
        with tempfile.TemporaryDirectory() as t:
            h, g, sp = self._reserve_home(t)
            evolve.start(h, g, "mid", "method", "new sources", "abcdef1", now=NOW)
            p = allocate.plan(h, 600, g, sp, now=NOW, write=False)
            m = p["strategies"]["mid"]
            self.assertEqual(m["reserve_consumer"], "experiment"); self.assertEqual(m["searches"], 200)
            self.assertEqual(p["reserve_drawn"]["experiment"], 200)
            self.assertNotIn("reserve_consumer", p["strategies"]["big"])
            rec = next(iter(evolve.records(h)))[1]
            self.assertIn("reserve", rec["funding"])

    def test_reserve_clips_experiments_first_then_new_strategies(self):
        with tempfile.TemporaryDirectory() as t:
            h, g, sp = self._reserve_home(t)
            evolve.start(h, g, "mid", "method", "new sources", "abcdef1", now=NOW)
            # big alone holds at least 80 (shift bound from 100); 300 - 80 leaves 220 of reserve:
            # the experiment takes 200, 20 is left, below searches.min 50 for either new strategy.
            p = allocate.plan(h, 300, g, sp, now=NOW, write=False)
            s = p["strategies"]
            self.assertEqual(s["mid"]["searches"], 200)
            for n in ("s1", "s2"):
                self.assertIsNone(s[n]["searches"]); self.assertTrue(s[n]["unfunded"])
                self.assertIn("below searches.min", s[n]["reason"])
                self.assertNotIn("searches", [c["field"] for c in s[n]["changes"]])
            self.assertEqual(sorted(p["unfunded"]), ["s1", "s2"])
            self.assertLessEqual(p["total_searches"], 300)
            self.assertEqual(p["reserve_unspent"], 20)

    def test_slack_stays_unspent(self):
        with tempfile.TemporaryDirectory() as t:
            h, g, sp = self._reserve_home(t, small=())
            p = allocate.plan(h, 600, g, sp, now=NOW, write=False)
            # two regular strategies at 100 searches can move at most 20%: 240 at most of 600
            self.assertLessEqual(p["allocated_regular"], 240)
            self.assertEqual(p["reserve_drawn"], {"experiment": 0, "new-strategy": 0})
            self.assertEqual(p["reserve_unspent"], 600 - p["allocated_regular"])
            self.assertEqual(p["total_searches"], p["allocated_regular"])
            self.assertIn("never redistributed", p["reserve_note"])
            self.assertIn("stays unspent", allocate.render(p))

    def test_old_slow_strategy_is_not_new(self):
        with tempfile.TemporaryDirectory() as t:
            h, g, sp = self._reserve_home(t, small=())
            Y.ingest(h, [run_row("slow", i, 200 - 20 * i) for i in range(1, 10)] + [run_row("slow", 10, 3)])
            st = json.loads(Path(sp).read_text()); st["slow"] = {"searches": 100, "schedule": "weekly", "status": "running"}
            Path(sp).write_text(json.dumps(st))
            p = allocate.plan(h, 600, g, sp, now=NOW, write=False)
            self.assertNotIn("reserve_consumer", p["strategies"]["slow"])

    def test_every_value_inside_min_max_and_zero_only_when_parked_or_blocked(self):
        for pool in (120, 250, 600, 1200):
            p = self.plan(pool)
            for n, r in p["strategies"].items():
                if r["searches"] is None:
                    self.assertTrue(r["unfunded"], n)
                elif r["searches"] == 0:
                    self.assertTrue(r["schedule"] == "parked" or r["leak"] == "blocked", (pool, n, r["reason"]))
                else:
                    self.assertGreaterEqual(r["searches"], 50, (pool, n)); self.assertLessEqual(r["searches"], 200, (pool, n))
            self.assertLessEqual(p["total_searches"], pool)

    def test_shift_bound_below_min_is_raised_to_min(self):
        with tempfile.TemporaryDirectory() as t:
            h, g, sp = self._reserve_home(t, small=(), settings_extra={"mid": {"searches": 40, "schedule": "daily", "status": "running"}})
            p = allocate.plan(h, 600, g, sp, now=NOW, write=False)
            self.assertGreaterEqual(p["strategies"]["mid"]["searches"], 50)

    def test_ad_hoc_gets_no_schedule_change(self):
        with tempfile.TemporaryDirectory() as t:
            sp = Path(t) / "s.json"
            st = json.loads((self.home / "strategies.json").read_text())
            st["subscriptions"]["mode"] = "ad-hoc"
            st["accelerators"]["mode"] = "ad-hoc"
            sp.write_text(json.dumps(st))
            p = allocate.plan(self.home, 600, self.g, str(sp), now=NOW, write=False)
            for n in ("subscriptions", "accelerators"):
                r = p["strategies"][n]
                self.assertEqual(r["schedule"], r["schedule_now"])
                self.assertNotIn("schedule", [c["field"] for c in r["changes"]])

    def test_young_fleet_still_allocates_most_of_the_pool(self):
        # Every strategy has 2 to 6 runs: none is newly approved except a 2-run, 3-day-old one.
        with tempfile.TemporaryDirectory() as t:
            h = Path(t)
            rows = []
            for name, n_runs, first_back, scored in (("y2", 2, 20, 1), ("y3", 3, 20, 2), ("y4", 4, 20, 1), ("y5", 5, 20, 3), ("y6", 6, 20, 2)):
                rows += [run_row(name, i + 1, first_back - 3 * i, scored=scored) for i in range(n_runs)]
            rows += [run_row("fresh", 1, 3, scored=0), run_row("fresh", 2, 1, scored=1)]
            Y.ingest(h, rows)
            sp = h / "settings.json"
            sp.write_text(json.dumps({n: {"searches": 100, "daily_cap": 30, "schedule": "daily", "status": "running"}
                                      for n in ("y2", "y3", "y4", "y5", "y6", "fresh")}))
            g = steward.grant(str(write_grant(t)), h, h)
            p = allocate.plan(h, 600, g, str(sp), now=NOW, write=False)
            s = p["strategies"]
            self.assertGreaterEqual(p["allocated_regular"], 0.6 * 600, allocate.render(p))
            self.assertEqual(s["fresh"]["reserve_consumer"], "new-strategy")
            self.assertEqual(s["fresh"]["searches"], 90)  # 15% of 600, one new strategy
            for n in ("y2", "y3", "y4", "y5", "y6"):
                self.assertNotIn("reserve_consumer", s[n], n)  # y2 has 2 runs but its first is 20 days old
                self.assertGreaterEqual(s[n]["searches"], 50)
            self.assertEqual(Y.report(h, 30, NOW)["strategies"]["y5"]["sample"], "small")  # smoothing flags unchanged
            self.assertLessEqual(p["total_searches"], 600)

    def _cost_home(self, t, x_runs):
        h = Path(t)
        rows = []
        for name in ("a", "b"):
            rows += [run_row(name, i, 25 - i, scored=1) for i in range(1, 11)]
        rows += [run_row("x", i, 25 - i, scored=6, at_floor=1, prescreen_pass=6, candidates=8, run_units=6.0) for i in range(1, x_runs + 1)]
        Y.ingest(h, rows)
        sp = h / "settings.json"
        st = {n: {"searches": 100, "daily_cap": 30, "schedule": "daily", "status": "running", "stages": {"triage": "haiku", "score": "opus"}}
              for n in ("a", "b", "x")}
        sp.write_text(json.dumps(st))
        return h, steward.grant(str(write_grant(t)), h, h), str(sp)

    def test_small_sample_cost_leak_applies_budget_and_proposes_model(self):
        with tempfile.TemporaryDirectory() as t:
            h, g, sp = self._cost_home(t, 6)
            d = diagnose.report(h, 30, NOW, g)["strategies"]["x"]
            self.assertEqual(d["leak"], "cost"); self.assertTrue(d["tentative"])
            acts = {a["lever"]: a for a in d["actions"]}
            self.assertTrue(acts["budget"]["allowed"])
            self.assertFalse(acts["model"]["allowed"])
            self.assertEqual(acts["model"]["grant"], "tentative: 6 runs, structural changes apply at 7")
            x = allocate.plan(h, 600, g, sp, now=NOW, write=False)["strategies"]["x"]
            fields = {c["field"]: c for c in x["changes"]}
            self.assertIn("searches", fields); self.assertTrue(fields["searches"]["apply"])
            self.assertNotIn("stages", fields)
            self.assertEqual(x["stages"], {"triage": "haiku", "score": "opus"})
            self.assertEqual([c["field"] for c in x["proposed"]], ["stages"])
            self.assertEqual(x["proposed"][0]["to"]["score"], "sonnet")
            self.assertIn("tentative: 6 runs", x["proposed"][0]["grant"])

    def test_full_sample_cost_leak_applies_both(self):
        with tempfile.TemporaryDirectory() as t:
            h, g, sp = self._cost_home(t, 7)
            d = diagnose.report(h, 30, NOW, g)["strategies"]["x"]
            self.assertEqual(d["leak"], "cost")
            self.assertTrue(all(a["allowed"] for a in d["actions"] if a["lever"] in ("budget", "model")))
            x = allocate.plan(h, 600, g, sp, now=NOW, write=False)["strategies"]["x"]
            fields = {c["field"]: c for c in x["changes"]}
            self.assertTrue(fields["searches"]["apply"]); self.assertTrue(fields["stages"]["apply"])
            self.assertEqual(x["stages"]["score"], "sonnet"); self.assertEqual(x["proposed"], [])

    def test_grant_can_lower_structural_threshold(self):
        with tempfile.TemporaryDirectory() as t:
            h, _, sp = self._cost_home(t, 6)
            g = steward.grant(str(write_grant(t, GRANT.replace("  pools:", "  structural-min-runs: 5\n  pools:"))), h, h)
            self.assertEqual(g.structural_min_runs(), 5)
            x = allocate.plan(h, 600, g, sp, now=NOW, write=False)["strategies"]["x"]
            self.assertIn("stages", [c["field"] for c in x["changes"]])

    def test_park_needs_a_full_sample(self):
        self.assertEqual(allocate._cadence("daily", 10, self.g, small=True)[0], "alternate")
        self.assertEqual(allocate._cadence("alternate", 12, self.g, small=True)[0], "alternate")
        self.assertEqual(allocate._cadence("daily", 5, self.g, small=True)[0], "alternate")
        self.assertEqual(allocate._cadence("daily", 10, self.g, small=False)[0], "parked")

    def test_reserve_rule_is_visible(self):
        r = steward.load_rules()["reserve"]
        self.assertEqual(r["consumers"], ["experiment", "new-strategy"])
        self.assertEqual((r["new_strategy_runs"], r["new_strategy_days"]), (3, 14))

    def test_demotion_at_5_and_10(self):
        self.assertEqual(allocate._cadence("daily", 4, self.g)[0], "daily")
        self.assertEqual(allocate._cadence("daily", 5, self.g)[0], "alternate")
        self.assertEqual(allocate._cadence("alternate", 9, self.g)[0], "alternate")
        self.assertEqual(allocate._cadence("alternate", 10, self.g)[0], "parked")
        self.assertEqual(allocate._cadence("alternate", 0, self.g)[0], "daily")
        with tempfile.TemporaryDirectory() as t:
            sp = Path(t) / "s.json"
            st = json.loads((self.home / "strategies.json").read_text())
            st["app-lists"]["runs_below_median"] = 5
            st["public-data"]["runs_below_median"] = 10
            sp.write_text(json.dumps(st))
            p = allocate.plan(self.home, 600, self.g, str(sp), now=NOW, write=False)
            self.assertEqual(p["strategies"]["app-lists"]["schedule"], "alternate")
            self.assertEqual(p["strategies"]["public-data"]["schedule"], "parked")
            self.assertEqual(p["strategies"]["public-data"]["searches"], 0)

    def test_models_follow_the_diagnosis_and_the_ceiling(self):
        new, _ = allocate.plan_models({"triage": "sonnet", "score": "sonnet"}, "judgment", self.g)
        self.assertEqual(new, {"triage": "haiku", "score": "opus"})
        new, _ = allocate.plan_models({"triage": "haiku", "score": "opus", "write": "sonnet"}, "cost", self.g)
        self.assertEqual(new, {"triage": "haiku", "score": "sonnet", "write": "haiku"})
        new, _ = allocate.plan_models({"score": "fable"}, "healthy", self.g)
        self.assertEqual(new, {"score": "opus"})
        p = self.plan(600)
        self.assertEqual(p["strategies"]["app-lists"]["stages"]["score"], "opus")
        self.assertEqual(p["strategies"]["public-data"]["stages"], p["strategies"]["public-data"]["stages_now"])

    def test_propose_mode_applies_nothing_and_writes_only_allocation(self):
        with tempfile.TemporaryDirectory() as t:
            h = demo_home(t)
            before = sorted(str(p.relative_to(h)) for p in h.rglob("*") if p.is_file())
            r = subprocess.run([sys.executable, str(ROOT / "scripts/allocate.py"), "--now", oc.iso(NOW), "plan", "--pool", "600", "--json"],
                               capture_output=True, text=True, env=dict(os.environ, OTTO_HOME=str(h)))
            self.assertEqual(r.returncode, 0, r.stderr)
            p = json.loads(r.stdout)
            self.assertEqual(p["mode"], "propose")
            self.assertTrue(all(not c["apply"] for s in p["strategies"].values() for c in s["changes"]))
            after = sorted(str(p.relative_to(h)) for p in h.rglob("*") if p.is_file())
            self.assertEqual(sorted(set(after) - set(before)), ["allocation.json"])


# --------------------------------------------------------------------------- diagnosis

class Diagnosis(unittest.TestCase):
    def test_fixture_strategies(self):
        with tempfile.TemporaryDirectory() as t:
            h = demo_home(t)
            g = steward.grant(str(h / "steward-grant.md"), h, h)
            rep = diagnose.report(h, 30, NOW, g)["strategies"]
            self.assertEqual(rep["accelerators"]["leak"], "source")
            self.assertIn("method", [a["lever"] for a in rep["accelerators"]["actions"]])
            self.assertEqual(rep["subscriptions"]["leak"], "triage")
            self.assertEqual(rep["app-lists"]["leak"], "judgment")
            self.assertEqual([a["lever"] for a in rep["app-lists"]["actions"]][:2], ["model", "gates"])
            self.assertEqual(rep["vanishing-data"]["leak"], "blocked")
            self.assertIn("over-performer", rep["public-data"]["signals"])
            self.assertTrue(rep["new-angle"]["tentative"])

    def test_two_failed_method_experiments_propose_a_strategy(self):
        with tempfile.TemporaryDirectory() as t:
            h = demo_home(t)
            for i in (1, 2):
                oc.write_json(h / "experiments" / ("old-%d.json" % i), {"id": "old-%d" % i, "family": "steward", "target": "accelerators",
                                                                      "lever": "method", "verdict": "revert", "status": "reverted", "started": oc.iso(NOW)})
            g = steward.grant(str(h / "steward-grant.md"), h, h)
            d = diagnose.report(h, 30, NOW, g)["strategies"]["accelerators"]
            self.assertEqual([a["lever"] for a in d["actions"]], ["propose-strategy"])
            self.assertFalse(d["actions"][0]["allowed"])

    def test_review_and_cost_leaks(self):
        rules = steward.load_rules()
        base = {"runs": 10, "runs_total": 10, "blocked_runs": 0, "dropped": {"filter1": 2, "filter2": 2}, "run_units": 20.0, "yield_per_unit": 1.0,
                "funnel": {"examined": 200, "candidates": 60, "prescreen_pass": 30, "scored": 20, "at_floor": 6, "top20": 0, "keep": 0, "kill": 5, "archived": 0}}
        self.assertEqual(diagnose.classify(base, {"median_yield": 1.0, "median_units_per_run": 2.0}, rules)["leak"], "review")
        cost = json.loads(json.dumps(base)); cost["funnel"]["kill"] = 0; cost["run_units"] = 40.0
        self.assertEqual(diagnose.classify(cost, {"median_yield": 0.5, "median_units_per_run": 2.0}, rules)["leak"], "cost")
        cost["run_units"] = 20.0
        self.assertEqual(diagnose.classify(cost, {"median_yield": 0.5, "median_units_per_run": 2.0}, rules)["leak"], "healthy")

    def test_seasonality_surface(self):
        rules = steward.load_rules()
        s = {"runs": 7, "runs_total": 7, "blocked_runs": 0, "dropped": {"filter3": 40, "filter1": 5}, "run_units": 14.0, "yield_per_unit": 0.0,
             "funnel": {"examined": 140, "candidates": 60, "prescreen_pass": 1, "scored": 1, "at_floor": 0, "top20": 0, "keep": 0, "kill": 0, "archived": 0}}
        c = diagnose.classify(s, {"median_yield": 1.0, "median_units_per_run": 2.0}, rules)
        self.assertEqual(c["leak"], "triage"); self.assertIn("seasonality", c["surface"])


# --------------------------------------------------------------------------- evolution

class Evolve(unittest.TestCase):
    CFG = {"keep_delta_percent": 10.0, "survivors_not_fewer": True, "higher_cost_percent": 10.0, "extend_runs": 2}

    def rec(self, by, bs, bu, ty, ts, tu, extended=False):
        return {"metric": "yield-per-run-unit", "extended": extended,
                "baseline": {"yield_per_unit": by, "survivors": bs, "run_units_per_run": bu},
                "treatment": {"yield_per_unit": ty, "survivors": ts, "run_units_per_run": tu}}

    def test_decide(self):
        self.assertEqual(evolve.decide(self.rec(1.0, 3, 2.0, 1.2, 3, 2.0), self.CFG)["verdict"], "keep")
        self.assertEqual(evolve.decide(self.rec(1.0, 3, 2.0, 1.2, 2, 2.0), self.CFG)["verdict"], "revert")  # survivors fewer
        self.assertEqual(evolve.decide(self.rec(1.0, 3, 2.0, 0.8, 3, 2.0), self.CFG)["verdict"], "revert")
        self.assertEqual(evolve.decide(self.rec(1.0, 3, 2.0, 1.05, 3, 2.0), self.CFG)["verdict"], "extend")
        self.assertEqual(evolve.decide(self.rec(1.0, 3, 2.0, 1.05, 3, 2.5), self.CFG)["verdict"], "revert")  # inconclusive, dearer
        self.assertEqual(evolve.decide(self.rec(1.0, 3, 2.0, 1.05, 3, 2.0, extended=True), self.CFG)["verdict"], "revert")
        self.assertEqual(evolve.decide(self.rec(0.0, 0, 2.0, 0.5, 1, 2.0), self.CFG)["verdict"], "keep")  # up from zero
        self.assertEqual(evolve.decide(self.rec(0.0, 0, 2.0, 0.0, 0, 2.0), self.CFG)["verdict"], "extend")

    def test_decide_review_quality(self):
        r = {"metric": "review-quality", "baseline": {"sourced_share": 0.5, "reversal_rate": 0.3, "searches_per_job": 10},
             "treatment": {"sourced_share": 0.7, "reversal_rate": 0.2, "searches_per_job": 10}}
        self.assertEqual(evolve.decide(r, self.CFG)["verdict"], "keep")
        r["treatment"]["searches_per_job"] = 14
        self.assertEqual(evolve.decide(r, self.CFG)["verdict"], "revert")
        r["treatment"] = {"sourced_share": 0.4, "reversal_rate": 0.3, "searches_per_job": 10}
        self.assertEqual(evolve.decide(r, self.CFG)["verdict"], "revert")

    def _home(self, t):
        h = demo_home(t)
        return h, steward.grant(str(h / "steward-grant.md"), h, h)

    def _treat(self, h, strategy, first_run, n, scored, units=4.0, start_day=1):
        Y.ingest(h, [{"ts": oc.iso(NOW + timedelta(days=start_day + i)), "strategy": strategy, "run": first_run + i, "searches": 140,
                      "run_units": units, "examined": 40, "candidates": 10, "prescreen_pass": scored, "scored": scored} for i in range(n)])

    def test_keep_flow(self):
        with tempfile.TemporaryDirectory() as t:
            h, g = self._home(t)
            rec = evolve.start(h, g, "accelerators", "method", "new cursor", "a1b2c3d", empty_runs=3, now=NOW)
            self.assertEqual(rec["status"], "collecting"); self.assertEqual(rec["baseline"]["runs"], 3)
            self.assertEqual(rec["revert"], "git revert --no-edit a1b2c3d")
            self.assertEqual(evolve.verdict(h, g, now=NOW), [])
            self._treat(h, "accelerators", 100, 2, scored=2)
            st = evolve.status(h, g, rec["id"], NOW + timedelta(days=5))[0]
            self.assertEqual(st["remaining"], 1)
            self._treat(h, "accelerators", 102, 1, scored=2, start_day=3)
            v = evolve.verdict(h, g, now=NOW + timedelta(days=5))
            self.assertEqual(len(v), 1); self.assertEqual(v[0]["verdict"], "keep"); self.assertIsNone(v[0]["git"])
            self.assertTrue(v[0]["small_sample"])
            saved = oc.read_json(h / "experiments" / (rec["id"] + ".json"))
            self.assertEqual(saved["status"], "kept")

    def test_revert_flow_prints_git_and_restores_counter(self):
        with tempfile.TemporaryDirectory() as t:
            h, g = self._home(t)
            rec = evolve.start(h, g, "app-lists", "gates", "tighter evidence", "deadbeef", empty_runs=1, now=NOW)
            self._treat(h, "app-lists", 100, 3, scored=1)
            v = evolve.verdict(h, g, now=NOW + timedelta(days=5))[0]
            self.assertEqual(v["verdict"], "revert"); self.assertEqual(v["git"], "git revert --no-edit deadbeef")
            self.assertEqual(v["restore"], {"empty-runs-so-far": 1})
            self.assertEqual(evolve.verdict(h, g, now=NOW + timedelta(days=6)), [])  # closed
            dry = evolve.start(h, g, "app-lists", "gates", "again", "cafef00d", now=NOW + timedelta(days=6))
            self.assertEqual(dry["status"], "collecting")  # slot freed by the verdict

    def test_extend_then_revert(self):
        with tempfile.TemporaryDirectory() as t:
            h, g = self._home(t)
            rec = evolve.start(h, g, "subscriptions", "gates", "new questions", "0badc0de", now=NOW)
            self._treat(h, "subscriptions", 100, 3, scored=0)
            v = evolve.verdict(h, g, now=NOW + timedelta(days=5))[0]
            self.assertEqual(v["verdict"], "extend"); self.assertIsNone(v["git"])
            self.assertEqual(oc.read_json(h / "experiments" / (rec["id"] + ".json"))["treatment"]["needed"], 5)
            self.assertEqual(evolve.verdict(h, g, now=NOW + timedelta(days=5)), [])
            self._treat(h, "subscriptions", 103, 2, scored=0, start_day=4)
            v = evolve.verdict(h, g, now=NOW + timedelta(days=9))[0]
            self.assertEqual(v["verdict"], "revert"); self.assertIn("after the extension", v["why"])

    def test_max_active(self):
        with tempfile.TemporaryDirectory() as t:
            h, g = self._home(t)
            self.assertEqual(evolve.start(h, g, "accelerators", "method", "a", "1111111", now=NOW)["status"], "collecting")
            self.assertIn("max-active", evolve.start(h, g, "accelerators", "gates", "b", "2222222", now=NOW)["error"])
            self.assertEqual(evolve.start(h, g, "app-lists", "gates", "c", "3333333", now=NOW)["status"], "collecting")
            self.assertEqual(evolve.start(h, g, "fleet", "skills", "gilfoyle anchors", "4444444", now=NOW)["scope"], "fleet")
            self.assertIn("max-active", evolve.start(h, g, "fleet", "skills", "again", "5555555", now=NOW)["error"])
            self.assertIn("fleet-wide", evolve.start(h, g, "subscriptions", "gates", "d", "6666666", now=NOW)["error"])
            self.assertIn("error", evolve.start(h, g, "x", "budget", "nightly lever", "7777777", now=NOW))
            self.assertIn("error", evolve.start(h, g, "x", "method", "no hash", "", now=NOW))
            p = evolve.propose(h, g, NOW)
            self.assertTrue(all(c["scope"] == "fleet" for c in p["candidates"]) or not p["candidates"])

    def test_propose_ranks_one_per_target(self):
        with tempfile.TemporaryDirectory() as t:
            h, g = self._home(t)
            p = evolve.propose(h, g, NOW)
            targets = [c["target"] for c in p["candidates"]]
            self.assertEqual(len(targets), len(set(targets)))
            self.assertEqual(targets[0], "accelerators"); self.assertEqual(p["candidates"][0]["lever"], "method")
            gains = [c["expected_gain"] for c in p["candidates"]]
            self.assertEqual(gains, sorted(gains, reverse=True))
            self.assertIn("public-data", [s["from"] for s in p["propose_strategy"]])

    def test_experiment_py_ignores_steward_records(self):
        with tempfile.TemporaryDirectory() as t:
            h, g = self._home(t)
            evolve.start(h, g, "accelerators", "method", "a", "1111111", now=NOW)
            self.assertEqual(experiment.status(h, None, NOW), [])
            self.assertEqual(len(evolve.status(h, g, None, NOW)), 1)


# --------------------------------------------------------------------------- the runner and the CLIs

class Runner(unittest.TestCase):
    def test_nightly_and_weekly_runs(self):
        with tempfile.TemporaryDirectory() as t:
            h = demo_home(t)
            g = steward.grant(str(h / "steward-grant.md"), h, h)
            o = steward.run("nightly", g, h, 600, str(h / "strategies.json"), True, NOW)
            self.assertIn("allocation plan (dry run)", o["steps"]); self.assertNotIn("proposals", o)
            w = steward.run("weekly", g, h, 600, str(h / "strategies.json"), True, NOW)
            self.assertIn("proposals", w)
            (h / "control.md").write_text("---\npaused: true\n---\n")
            p = steward.run("nightly", steward.grant(str(h / "steward-grant.md"), h, h), h, 600, None, False, NOW)
            self.assertIn("stopped", p); self.assertNotIn("allocation", p)

    def test_clis_exit_zero_on_bad_input(self):
        with tempfile.TemporaryDirectory() as t:
            env = dict(os.environ, OTTO_HOME=t)
            bad = Path(t) / "bad.jsonl"
            bad.write_text("not json\n{\"strategy\": 1}\n")
            for args in (["yield.py", "report"], ["yield.py", "ingest", str(bad)], ["yield.py", "ingest", str(Path(t) / "missing")],
                         ["diagnose.py", "report"], ["allocate.py", "plan", "--pool", "600", "--settings", str(Path(t) / "missing.json")],
                         ["evolve.py", "propose"], ["evolve.py", "status"], ["evolve.py", "verdict"],
                         ["steward.py", "run", "nightly"], ["steward.py", "--grant", str(bad), "check", "budget"]):
                r = subprocess.run([sys.executable, str(ROOT / "scripts" / args[0])] + args[1:], capture_output=True, text=True, env=env)
                self.assertEqual(r.returncode, 0, (args, r.stderr))

    def test_fixture_cli_acceptance(self):
        with tempfile.TemporaryDirectory() as t:
            h = demo_home(t)
            env = dict(os.environ, OTTO_HOME=str(h))
            run = lambda *a: subprocess.run([sys.executable] + list(a), capture_output=True, text=True, env=env, cwd=str(h))
            g = str(h / "steward-grant.md")
            y = json.loads(run(str(ROOT / "scripts/yield.py"), "--grant", g, "--now", oc.iso(NOW), "report", "--json").stdout)
            self.assertEqual(y["ranked"][0], "public-data"); self.assertEqual(y["strategies"]["new-angle"]["sample"], "small")
            p = json.loads(run(str(ROOT / "scripts/allocate.py"), "--grant", g, "--now", oc.iso(NOW), "plan", "--pool", "600", "--json").stdout)
            self.assertLessEqual(p["total_searches"], 600); self.assertEqual(p["strategies"]["vanishing-data"]["searches"], 0)
            self.assertGreaterEqual(p["strategies"]["new-angle"]["searches"], 90)
            self.assertTrue((h / "allocation.json").exists())
            d = json.loads(run(str(ROOT / "scripts/diagnose.py"), "--grant", g, "--now", oc.iso(NOW), "report", "--json").stdout)
            self.assertIn("method", [a["lever"] for a in d["strategies"]["accelerators"]["actions"]])


class Repo(unittest.TestCase):
    def test_new_skills_are_thin_and_restricted(self):
        for name in ("yield", "allocate", "evolve", "steward"):
            fm, body = oc.parse_frontmatter((ROOT / "skills" / name / "SKILL.md").read_text())
            self.assertEqual(fm["name"], name)
            tools = fm["allowed-tools"]
            self.assertTrue(tools.startswith("Read"), tools)
            self.assertNotIn("Write", tools); self.assertNotIn("Edit", tools)
            self.assertLess(len(body.splitlines()), 40)

    def test_no_em_dashes_in_new_files(self):
        for p in [ROOT / "config/steward.template.md", ROOT / ".out-of-scope/auto-apply.md", ROOT / "agents/otto.md"] + list((ROOT / "scripts").glob("*.py")):
            self.assertNotIn("\u2014", p.read_text(encoding="utf-8"), p.name)


if __name__ == "__main__":
    unittest.main()
