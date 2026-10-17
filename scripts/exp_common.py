"""Helpers shared by experiment.py (cost experiments on automations) and evolve.py (steward
experiments on strategies): the state directory, medians, change percentages, sample caveats and
record listing. Standard library only.

Both scripts keep their records in OTTO_HOME/experiments/<id>.json. A steward record carries
`"family": "steward"`; a record without a family is a cost experiment. Each script reads only its
own family, so neither trips over the other's records.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import otto_common as oc  # noqa: E402

SMALL_SAMPLE_RUNS = 7  # playbook rule 12: no trend from fewer than seven runs


def exp_dir(home: Path) -> Path:
    d = home / "experiments"
    d.mkdir(parents=True, exist_ok=True)
    return d


def median_of(rows: List[Dict[str, Any]], key: str, scale: float = 1.0, ndigits: int = 4) -> Optional[float]:
    """Median of one numeric field across rows, scaled, rounded; None when no row has it."""
    xs = [r[key] * scale for r in rows if isinstance(r.get(key), (int, float)) and not isinstance(r.get(key), bool)]
    return round(oc.median(xs), ndigits) if xs else None


def last_n(rows: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    """The baseline window: the last n rows of an already time-sorted list."""
    return rows[-n:] if n > 0 else []


def change_percent(before: Optional[float], after: Optional[float], ndigits: Optional[int] = 1) -> Optional[float]:
    """Percent change from before to after. None when before is missing or zero.
    ndigits=None rounds to a whole number, the form experiment.py has always printed."""
    if before is None or after is None or before == 0:
        return None
    x = (after / before - 1) * 100
    return round(x) if ndigits is None else round(x, ndigits)


def sample_caveat(total_runs: int) -> Tuple[bool, Optional[str]]:
    small = total_runs < SMALL_SAMPLE_RUNS
    return small, ("%d runs in total is a small sample" % total_runs) if small else None


def iter_records(home: Path, family: Optional[str] = None) -> Iterator[Tuple[Path, Dict[str, Any]]]:
    """Yield (path, record) for every record of one family. family=None means cost experiments."""
    for p in sorted(exp_dir(home).glob("*.json")):
        rec = oc.read_json(p, None)
        if not isinstance(rec, dict):
            continue
        if rec.get("family") != family:
            continue
        yield p, rec


def next_id(home: Path, prefix: str, stamp: str) -> str:
    n = len(list(exp_dir(home).glob(prefix + "-*.json"))) + 1
    return "%s-%s-%d" % (prefix, stamp, n)


def records_where(home: Path, family: Optional[str], pred: Callable[[Dict[str, Any]], bool]) -> List[Dict[str, Any]]:
    return [rec for _, rec in iter_records(home, family) if pred(rec)]
