"""The portable bundles: frontmatter rules, zip layout, and the audit script running from inside its bundle."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import bundle  # noqa: E402


class Bundles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "dist"
        if bundle.main(["--out", str(cls.out)]) != 0:
            raise RuntimeError("bundle build failed")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_check_passes(self):
        self.assertEqual(bundle.main(["--check"]), 0)

    def test_every_portable_skill_is_built_with_its_folder_at_top_level(self):
        for folder in (ROOT / "portable").iterdir():
            if not folder.is_dir():
                continue
            name = folder.name
            for ext in (".skill", ".zip"):
                path = self.out / (name + ext)
                self.assertTrue(path.is_file(), path)
            with zipfile.ZipFile(self.out / (name + ".skill")) as zf:
                names = zf.namelist()
                self.assertIn("%s/SKILL.md" % name, names)
                self.assertTrue(all(n.startswith(name + "/") for n in names), names)
                self.assertFalse(any("__pycache__" in n for n in names))
                fm, body = bundle.read_frontmatter(folder / "SKILL.md")
                self.assertEqual(fm["name"], name)
                self.assertTrue(set(fm) <= bundle.PORTABLE_KEYS)
                self.assertNotIn("CLAUDE_PLUGIN_ROOT", body)

    def test_audit_bundle_carries_its_scripts_and_runs(self):
        with zipfile.ZipFile(self.out / "otto-audit.skill") as zf:
            names = zf.namelist()
            for required in ("otto-audit/scripts/audit.py", "otto-audit/scripts/otto_common.py",
                             "otto-audit/references/audit-checks.md", "otto-audit/LICENSE"):
                self.assertIn(required, names)
            work = Path(self.tmp.name) / "unpacked"
            zf.extractall(work)
        project = Path(self.tmp.name) / "project"
        (project / ".claude/skills/demo").mkdir(parents=True)
        (project / ".claude/skills/demo/SKILL.md").write_text("---\nname: demo\ndescription: d\n---\nbody\n")
        (project / "CLAUDE.md").write_text("# rules\n" * 300)
        env = dict(os.environ, OTTO_HOME=str(Path(self.tmp.name) / "home"), HOME=str(Path(self.tmp.name) / "fakehome"))
        r = subprocess.run([sys.executable, str(work / "otto-audit/scripts/audit.py"), "--project", str(project), "--json"],
                           capture_output=True, text=True, env=env, cwd=str(work / "otto-audit"))
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = json.loads(r.stdout)
        self.assertEqual(rep["project"], str(project.resolve()))
        self.assertIn("findings", rep)

    def test_checksums_cover_every_archive(self):
        sums = (self.out / "SHA256SUMS").read_text().split()
        listed = {s for s in sums if s.endswith((".skill", ".zip"))}
        on_disk = {p.name for p in self.out.iterdir() if p.suffix in (".skill", ".zip")}
        self.assertEqual(listed, on_disk)


if __name__ == "__main__":
    unittest.main()
