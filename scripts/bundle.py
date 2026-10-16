#!/usr/bin/env python3
"""Build the portable .skill bundles that upload to the Claude app, Cowork and the Skills API.

    bundle.py                build dist/otto.skill and dist/otto-audit.skill (plus .zip twins and SHA256SUMS)
    bundle.py --check        validate the portable sources and build nothing
    bundle.py --out DIR      build somewhere other than dist/

The plugin's ten skills depend on ${CLAUDE_PLUGIN_ROOT}, Claude Code hooks and the local ledger, so
they cannot be uploaded one by one. The two folders under portable/ are the skills that can travel:

    otto         the dispatcher persona and playbook, for people who use Otto's judgment in the app
    otto-audit   the context-tax audit, with its scripts bundled inside the skill folder

"Portable" means the agentskills.io rules: only the six frontmatter keys (name, description, license,
compatibility, metadata, allowed-tools), the folder named after the skill, no Claude Code variables,
and every script the skill runs shipped inside the folder. The zip has one top-level folder named
after the skill, the layout Anthropic's own packager produces. No third-party dependencies.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
PORTABLE = ROOT / "portable"
PORTABLE_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
EXCLUDE = {"__pycache__", ".DS_Store", ".pytest_cache"}

# What each bundle pulls in from the rest of the repo, as (source relative to ROOT, destination inside the skill).
EXTRA_FILES: Dict[str, List[Tuple[str, str]]] = {
    "otto": [
        ("config/ops_playbook.md", "references/ops_playbook.md"),
        ("LICENSE", "LICENSE"),
    ],
    "otto-audit": [
        ("scripts/audit.py", "scripts/audit.py"),
        ("scripts/health.py", "scripts/health.py"),
        ("scripts/ledger.py", "scripts/ledger.py"),
        ("scripts/otto_common.py", "scripts/otto_common.py"),
        ("scripts/otto_tokens.py", "scripts/otto_tokens.py"),
        ("scripts/transcript.py", "scripts/transcript.py"),
        ("skills/audit/references/audit-checks.md", "references/audit-checks.md"),
        ("LICENSE", "LICENSE"),
    ],
}


def read_frontmatter(path: Path) -> Tuple[Dict[str, str], str]:
    """A small reader for the flat YAML these skills use. Nested keys (metadata) are kept as a block."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("%s: no frontmatter" % path)
    end = text.find("\n---", 4)
    if end < 0:
        raise ValueError("%s: unterminated frontmatter" % path)
    block, body = text[4:end], text[end + 4:]
    fm: Dict[str, str] = {}
    current = None
    for line in block.splitlines():
        if not line.strip():
            continue
        if line.startswith((" ", "\t")):
            if current is None:
                raise ValueError("%s: indented line outside a key" % path)
            fm[current] = (fm[current] + "\n" + line.strip()).strip()
            continue
        if ":" not in line:
            raise ValueError("%s: bad frontmatter line %r" % (path, line))
        key, _, value = line.partition(":")
        current = key.strip()
        fm[current] = value.strip().strip('"').strip("'")
    return fm, body


def check_skill(folder: Path) -> List[str]:
    problems: List[str] = []
    skill_md = folder / "SKILL.md"
    if not skill_md.is_file():
        return ["%s: SKILL.md missing" % folder.name]
    try:
        fm, body = read_frontmatter(skill_md)
    except ValueError as e:
        return [str(e)]
    name = fm.get("name", "")
    if name != folder.name:
        problems.append("%s: name %r must equal the folder name" % (folder.name, name))
    if not NAME_RE.match(name) or len(name) > 64:
        problems.append("%s: name must be 1-64 chars of lowercase letters, digits and single hyphens" % folder.name)
    if re.search(r"\b(claude|anthropic)\b", name):
        problems.append("%s: name may not contain the words claude or anthropic" % folder.name)
    desc = fm.get("description", "")
    if not 1 <= len(desc) <= 1024:
        problems.append("%s: description must be 1-1024 characters (is %d)" % (folder.name, len(desc)))
    extra = set(fm) - PORTABLE_KEYS
    if extra:
        problems.append("%s: non-portable frontmatter keys: %s" % (folder.name, ", ".join(sorted(extra))))
    if "${CLAUDE_PLUGIN_ROOT}" in body or "$CLAUDE_PLUGIN_ROOT" in body:
        problems.append("%s: body references CLAUDE_PLUGIN_ROOT, which does not exist outside Claude Code" % folder.name)
    if len(body.splitlines()) > 500:
        problems.append("%s: body is over 500 lines" % folder.name)
    for src, _ in EXTRA_FILES.get(folder.name, []):
        if not (ROOT / src).is_file():
            problems.append("%s: bundled file %s is missing from the repo" % (folder.name, src))
    return problems


def assemble(folder: Path, stage: Path) -> Path:
    dest = stage / folder.name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(folder, dest, ignore=shutil.ignore_patterns(*EXCLUDE))
    for src, rel in EXTRA_FILES.get(folder.name, []):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / src, target)
    return dest


def zip_skill(skill_dir: Path, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    skill_file = out / ("%s.skill" % skill_dir.name)
    with zipfile.ZipFile(skill_file, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(skill_dir.rglob("*")):
            if p.is_dir() or any(part in EXCLUDE for part in p.parts):
                continue
            zf.write(p, p.relative_to(skill_dir.parent).as_posix())
    shutil.copy2(skill_file, out / ("%s.zip" % skill_dir.name))
    return skill_file


def write_sums(out: Path) -> None:
    lines = []
    for p in sorted(out.glob("*")):
        if p.suffix in (".skill", ".zip"):
            lines.append("%s  %s" % (hashlib.sha256(p.read_bytes()).hexdigest(), p.name))
    (out / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate only")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    args = ap.parse_args(argv)
    folders = sorted(p for p in PORTABLE.iterdir() if p.is_dir() and not p.name.startswith("."))
    if not folders:
        print("no skill folders under %s" % PORTABLE, file=sys.stderr)
        return 1
    problems = [m for f in folders for m in check_skill(f)]
    for m in problems:
        print("problem: " + m, file=sys.stderr)
    if problems:
        return 1
    print("portable check passed for: " + ", ".join(f.name for f in folders))
    if args.check:
        return 0
    out = Path(args.out).expanduser().resolve()
    stage = out / ".stage"
    if stage.exists():
        shutil.rmtree(stage)
    for f in folders:
        built = zip_skill(assemble(f, stage), out)
        size_kb = built.stat().st_size / 1024.0
        print("built %s (%.1f KB)" % (built.relative_to(ROOT) if built.is_relative_to(ROOT) else built, size_kb))
    shutil.rmtree(stage, ignore_errors=True)
    write_sums(out)
    print("checksums in %s" % (out / "SHA256SUMS"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
