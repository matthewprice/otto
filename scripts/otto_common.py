"""Shared helpers for Otto: paths, config, a tiny frontmatter parser, time, locking.

Standard library only. Python 3.9 or newer. POSIX only (macOS, Linux).

Privacy rule for everything built on this module: Otto stores numbers, names of
automations, and short enum-like strings. It never stores prompt or output text.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

VERSION = "0.2.0"

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

DEFAULT_CONFIG: Dict[str, Any] = {
    "vault_dir": "",            # default: <home>/vault
    "timezone": "",             # default: system local time
    "lights": "off",            # "on" prints status lights in the dashboard
    "notify": "none",           # none | macos | file | command
    "notify_command": "",       # used when notify == command; message arrives in $OTTO_MESSAGE
    "plan": "",                 # free text, for the Ops read only
    "budget_daily_usd": None,   # optional soft budgets for headless spend
    "budget_weekly_usd": None,
    "sdk_credit_usd": None,     # your monthly Agent SDK credit, if you have one
    "sdk_credit_reset_day": 1,  # day of month the credit refreshes
    "alert_percents": [50, 75, 90],
    "guard": "off",             # off | warn | block (opt-in UserPromptSubmit guard)
    "guard_5h_percent": 90,
    "guard_7d_percent": 95,
    "guard_max_age_s": 900,
    "resume_cost_warn_usd": 0.5,
    "attempt_cap_per_day": 2,   # wrapper: max attempts per automation per day
    "breaker_threshold": 3,     # wrapper: consecutive failures before the breaker opens
    "claude_bin": "",
    "token_cmd": "",            # command that prints CLAUDE_CODE_OAUTH_TOKEN (keychain, pass, op...)
    "tone": "dry",
    "watch_desktop": True,      # watch: also send a desktop notification on a state change
    "watch_interval_s": 300,    # watch: seconds between polls
    "cache_ttl_min": 5,         # timeline: prompt cache TTL used to spot cold starts
}


# --------------------------------------------------------------------------- paths

def otto_home() -> Path:
    env = os.environ.get("OTTO_HOME")
    return Path(env).expanduser() if env else Path.home() / ".otto"


def ledger_dir(home: Optional[Path] = None) -> Path:
    return (home or otto_home()) / "ledger"


def state_dir(home: Optional[Path] = None) -> Path:
    return (home or otto_home()) / "state"


def config_path(home: Optional[Path] = None) -> Path:
    return (home or otto_home()) / "otto.md"


def vault_dir(cfg: Dict[str, Any], home: Optional[Path] = None) -> Path:
    v = cfg.get("vault_dir")
    return Path(str(v)).expanduser() if v else (home or otto_home()) / "vault"


def ensure_dirs(home: Optional[Path] = None) -> None:
    h = home or otto_home()
    for p in (h, ledger_dir(h), state_dir(h)):
        p.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- frontmatter

_KEY_RE = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_\-]*):(?:\s+(.*)|\s*)$")


def _split_inline_list(s: str) -> List[str]:
    out: List[str] = []
    cur: List[str] = []
    quote = ""
    for ch in s:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch == ",":
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    tail = "".join(cur).strip()
    if tail or out:
        out.append(tail)
    return [x for x in out if x != ""]


def parse_scalar(raw: str) -> Any:
    s = raw.strip()
    if s == "":
        return ""
    if s[0] == '"':
        end = s.rfind('"')
        if end > 0:
            try:
                return json.loads(s[: end + 1])
            except ValueError:
                return s[1:end]
    if s[0] == "'":
        end = s.rfind("'")
        if end > 0:
            return s[1:end].replace("''", "'")
    # strip trailing comment on unquoted values
    s = re.sub(r"\s+#.*$", "", s)
    if s.startswith("[") and s.endswith("]"):
        return [parse_scalar(x) for x in _split_inline_list(s[1:-1])]
    low = s.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~", "none"):
        return None
    if re.fullmatch(r"[-+]?\d+", s):
        return int(s)
    if re.fullmatch(r"[-+]?\d*\.\d+", s):
        return float(s)
    return s


def parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Parse a small YAML subset: flat keys, scalars, inline lists, dash lists."""
    text = text.lstrip("﻿")
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    data: Dict[str, Any] = {}
    i = 1
    while i < end:
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _KEY_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if val is None or val.strip() == "":
            items: List[Any] = []
            j = i
            while j < end and (lines[j].startswith("  - ") or lines[j].startswith("- ") or lines[j].strip() == ""):
                if lines[j].strip():
                    items.append(parse_scalar(lines[j].strip()[2:]))
                j += 1
            if items:
                data[key] = items
                i = j
            else:
                data[key] = ""
        elif val.strip() in (">", "|", ">-", "|-"):
            buf: List[str] = []
            while i < end and (lines[i].startswith(" ") or not lines[i].strip()):
                buf.append(lines[i].strip())
                i += 1
            data[key] = " ".join(x for x in buf if x)
        else:
            data[key] = parse_scalar(val)
    body = "\n".join(lines[end + 1:])
    return data, body


def read_frontmatter(path: Path) -> Tuple[Dict[str, Any], str]:
    return parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))


def _yaml_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == "" or re.search(r"[:#\[\]{}\"'\n]|^\s|\s$", s) or s.lower() in ("true", "false", "null", "yes", "no", "on", "off"):
        return json.dumps(s)
    return s


def dump_frontmatter(fm: Dict[str, Any], body: str = "") -> str:
    """Write the same small YAML subset parse_frontmatter reads. Lists go inline."""
    lines = ["---"]
    for k, v in fm.items():
        if k.startswith("_"):
            continue
        if isinstance(v, list):
            lines.append("%s: [%s]" % (k, ", ".join(_yaml_scalar(x) for x in v)))
        else:
            lines.append("%s: %s" % (k, _yaml_scalar(v)))
    lines.append("---")
    text = "\n".join(lines) + "\n"
    if body:
        text += body if body.startswith("\n") else "\n" + body
        if not text.endswith("\n"):
            text += "\n"
    return text


def write_note(path: Path, fm: Dict[str, Any], body: str = "") -> None:
    atomic_write(path, dump_frontmatter(fm, body))


# --------------------------------------------------------------------------- config

def load_config(home: Optional[Path] = None) -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    p = config_path(home)
    if p.exists():
        try:
            fm, _ = read_frontmatter(p)
            cfg.update({k: v for k, v in fm.items() if k in DEFAULT_CONFIG})
        except OSError:
            pass
    return cfg


# --------------------------------------------------------------------------- time

def get_tz(name: Optional[str]):
    if name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(str(name))
        except Exception:
            pass
    return datetime.now().astimezone().tzinfo


def parse_when(s: Optional[str], tz=None) -> datetime:
    """Parse ISO text (with or without offset) into an aware datetime. None means now."""
    if not s:
        return datetime.now(tz or datetime.now().astimezone().tzinfo)
    s = s.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz or datetime.now().astimezone().tzinfo)
    return dt


def parse_epoch_or_iso(v: Any) -> Optional[datetime]:
    """Accept epoch seconds, epoch milliseconds, numeric strings, or ISO text."""
    if v is None or v == "":
        return None
    try:
        if isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"\d+(\.\d+)?", v.strip())):
            x = float(v)
            if x > 1e12:
                x /= 1000.0
            return datetime.fromtimestamp(x, tz=timezone.utc)
        return parse_when(str(v), timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def parse_hhmm(s: Any) -> Tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(s))
    if not m:
        raise ValueError("expected HH:MM, got %r" % (s,))
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h < 24 and 0 <= mi < 60):
        raise ValueError("expected HH:MM, got %r" % (s,))
    return h, mi


def parse_since(s: Optional[str], now: datetime) -> Optional[datetime]:
    """'7d', '36h', '2w', or an ISO date/time."""
    if not s:
        return None
    m = re.fullmatch(r"(\d+)\s*([hdw])", s.strip())
    if m:
        n, u = int(m.group(1)), m.group(2)
        return now - timedelta(**{"hours": n} if u == "h" else {"days": n * (7 if u == "w" else 1)})
    return parse_when(s, now.tzinfo)


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat(timespec="seconds") if dt else None


# --------------------------------------------------------------------------- files

@contextlib.contextmanager
def file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path: Path, obj: Any) -> None:
    atomic_write(path, json.dumps(obj, indent=2, sort_keys=True) + "\n")


def log_error(msg: str, home: Optional[Path] = None) -> None:
    """Append to state/errors.log (bounded). Never raises: observers must not break sessions."""
    try:
        p = state_dir(home) / "errors.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        line = "%s %s\n" % (datetime.now().astimezone().isoformat(timespec="seconds"), re.sub(r"\s+", " ", str(msg))[:300])
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(line)
        if p.stat().st_size > 64 * 1024:
            keep = p.read_text(encoding="utf-8").splitlines()[-200:]
            p.write_text("\n".join(keep) + "\n", encoding="utf-8")
    except Exception:
        pass


def count_recent_errors(home: Optional[Path] = None, within_hours: int = 24) -> int:
    p = state_dir(home) / "errors.log"
    if not p.exists():
        return 0
    cutoff = datetime.now().astimezone() - timedelta(hours=within_hours)
    n = 0
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            if datetime.fromisoformat(line.split(" ", 1)[0]) >= cutoff:
                n += 1
        except ValueError:
            continue
    return n


# --------------------------------------------------------------------------- misc

_SAFE_NAME = re.compile(r"[^a-z0-9_.\-]+")


def slug(name: str) -> str:
    return _SAFE_NAME.sub("-", str(name).strip().lower()).strip("-")[:80]


def short(s: Any, n: int = 64) -> str:
    return re.sub(r"\s+", " ", str(s)).strip()[:n]


def eprint(*a: Any) -> None:
    print(*a, file=sys.stderr)


def median(xs: List[float]) -> Optional[float]:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0
