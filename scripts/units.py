#!/usr/bin/env python3
"""Print scheduler units for a registered local-cli automation. Prints only; installs nothing.

  units.py NAME [--kind launchd|cron|systemd] [--at HH:MM]

The time defaults to the registry's `run_at` or, failing that, 30 minutes before `expected_by`.
Review the output, then install it yourself.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import health  # noqa: E402
import otto_common as oc  # noqa: E402

TMPL = Path(__file__).resolve().parent / "units"
DOW = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name"); ap.add_argument("--kind", default="")
    ap.add_argument("--at"); ap.add_argument("--home")
    a = ap.parse_args(argv)
    home = Path(a.home).expanduser() if a.home else oc.otto_home()
    cfg = oc.load_config(home)
    autos, _ = health.load_registry(home, cfg)
    reg = next((x for x in autos if x["name"] == oc.slug(a.name)), None)
    if not reg:
        oc.eprint("no registry note named %s" % a.name)
        return 2
    kind = a.kind or ("launchd" if sys.platform == "darwin" else "cron")
    h, m = oc.parse_hhmm(a.at or reg.get("run_at") or None) if (a.at or reg.get("run_at")) else (None, None)
    if h is None:
        eh, em = oc.parse_hhmm(reg.get("expected_by"))
        t = datetime(2000, 1, 1, eh, em) - timedelta(minutes=30)
        h, m = t.hour, t.minute
    days = health.normalize_days(reg.get("days"))
    runner = home / "bin" / "run.py"
    ctx = {"name": reg["name"], "python": sys.executable or "python3", "runner": runner, "home": home}
    if kind == "launchd":
        iv = "".join("<dict><key>Weekday</key><integer>%d</integer><key>Hour</key><integer>%d</integer><key>Minute</key><integer>%d</integer></dict>"
                     % ((d + 1) % 7, h, m) for d in days)
        out = (TMPL / "launchd.plist.tmpl").read_text().format(intervals=iv, **ctx)
    elif kind == "cron":
        dow = ",".join(str((d + 1) % 7) for d in days)
        out = (TMPL / "cron.tmpl").read_text().format(minute=m, hour=h, dow=dow, **ctx)
    else:
        cal = "%s *-*-* %02d:%02d:00" % (",".join(DOW[d].title() for d in days), h, m)
        out = (TMPL / "systemd.service.tmpl").read_text().format(**ctx) + "\n# --- timer ---\n" + \
              (TMPL / "systemd.timer.tmpl").read_text().format(oncalendar=cal, **ctx)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
