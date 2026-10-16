#!/usr/bin/env python3
"""Copy Otto's scripts to ~/.otto/bin so schedulers (cron, launchd) have a stable path.

A plugin's install directory changes with every version, so a cron line pointing into it would
break on update. Run this again after updating the plugin. It only writes inside ~/.otto.
"""
import shutil
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import otto_common as oc  # noqa: E402


def main() -> int:
    src = Path(__file__).resolve().parent
    home = oc.otto_home()
    dst = home / "bin"
    oc.ensure_dirs(home)
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in sorted(list(src.glob("*.py")) + list(src.glob("*.json"))):
        shutil.copy2(p, dst / p.name)
        n += 1
    if (src / "units").is_dir():
        shutil.copytree(src / "units", dst / "units", dirs_exist_ok=True)
    cfg = oc.config_path(home)
    if not cfg.exists():
        cfg.write_text("---\nlights: off\nnotify: none\nguard: off\n---\nOtto settings. See docs for every key.\n", encoding="utf-8")
    (dst / "VERSION").write_text(oc.VERSION + "\n", encoding="utf-8")
    print("installed %d scripts to %s (version %s)" % (n, dst, oc.VERSION))
    print("wrapper: python3 %s/run.py NAME" % dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
