#!/usr/bin/env python3
"""Token estimates for text files, labelled honestly.

Claude's tokenizer is not public, and Otto makes no network calls, so these are
estimates: characters / 4 and words x 1.3. Markdown with paths, tables and code usually
lands at or above characters / 4, so treat results as plus or minus 25 percent.

The measured numbers in an Otto audit come from somewhere else: the usage block of the
first request in a real session (see audit.py, "measured-prefix"). Use estimates to rank
components against each other and measured numbers to say what a session actually pays.

Usage: otto_tokens.py FILE [FILE ...]
"""
from __future__ import annotations

import json
import math
import re
import sys
from typing import Dict


def estimate(text: str) -> Dict[str, int]:
    chars = len(text)
    words = len(re.findall(r"\S+", text))
    return {
        "chars": chars,
        "words": words,
        "lines": text.count("\n") + (1 if text and not text.endswith("\n") else 0),
        "tokens_chars4": int(math.ceil(chars / 4.0)),
        "tokens_words13": int(round(words * 1.3)),
    }


def main(argv=None) -> int:
    paths = (argv if argv is not None else sys.argv[1:])
    if not paths:
        print(__doc__)
        return 2
    out = {}
    for p in paths:
        with open(p, encoding="utf-8", errors="replace") as fh:
            out[p] = estimate(fh.read())
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
