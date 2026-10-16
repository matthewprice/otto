#!/usr/bin/env python3
"""Regenerate Otto's pixel sprites and the README banner from the pixel data.

    python3 assets/make_sprites.py

The sprites are a 22 by 16 pixel grid on the Clawd body. Clawd belongs to Anthropic, redrawn with
affection and no affiliation. The driver styling is the archetype (hair, cap, headphones, a stop
arm), not a copy of any other character. Edit the pixel lists below and re-run; every SVG under
assets/ is written from here. No dependencies beyond the standard library.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

HERE = Path(__file__).resolve().parent

C = {
    "o": "#d97757", "e": "#1c1e21", "w": "#f2efe6", "r": "#c8352e", "R": "#962720",
    "y": "#f7b32b", "h": "#241e1b", "k": "#111214", "g": "#8e949c", "G": "#e6b84a",
    "s": "#1f3c56", "d": "#3a3e46", "m": "#5c6066", "n": "#2f8f5b",
}
BASE = [
    "......................", "......................", "......................", "......................", "......................",
    ".......oooooooo.......", "......ooeooooeoo......", "......ooeooooeoo......", ".....oooooooooooo.....", ".....oooooooooooo.....",
    "......oooooooooo......", "......oooooooooo......", "........o...o.........", "........o...o.........", "......................", "......................",
]
Px = Tuple[int, int, str]


def span(y: int, x0: int, x1: int, k: str) -> List[Px]:
    return [(x, y, k) for x in range(x0, x1 + 1)]


def block(x0: int, y0: int, x1: int, y1: int, k: str) -> List[Px]:
    out: List[Px] = []
    for y in range(y0, y1 + 1):
        out += span(y, x0, x1, k)
    return out


SPRITES: Dict[str, Dict] = {
    "otto-driver": {
        "label": "Otto the Driver: Clawd with shaggy hair, a cap on backwards and headphones",
        "px": [
            *span(3, 6, 15, "h"), *span(4, 4, 17, "h"), *span(5, 4, 17, "h"),
            *block(4, 6, 4, 12, "h"), *block(17, 6, 17, 12, "h"),
            *block(5, 6, 5, 13, "h"), *block(16, 6, 16, 13, "h"),
            (6, 6, "h"), (15, 6, "h"), (5, 14, "h"), (16, 14, "h"),
            *span(1, 9, 12, "r"), *span(2, 8, 13, "r"), *span(3, 8, 14, "R"),
            (10, 2, "y"), (11, 2, "y"), (15, 3, "R"), (16, 3, "R"), (17, 3, "R"),
            *block(2, 7, 3, 9, "k"), *block(18, 7, 19, 9, "k"), (3, 8, "g"), (18, 8, "g"),
            *block(19, 10, 19, 12, "g"), (18, 13, "g"), (17, 13, "g"),
        ],
    },
    "otto-later": {
        "label": "Otto in shades with headphones over the top, one hand raised",
        "px": [
            *span(4, 6, 15, "h"), *span(5, 5, 16, "h"),
            *block(5, 6, 5, 11, "h"), *block(16, 6, 16, 11, "h"), (5, 12, "h"), (16, 12, "h"),
            *span(3, 7, 14, "k"), (6, 4, "k"), (15, 4, "k"),
            *block(4, 5, 5, 8, "k"), *block(16, 5, 17, 8, "k"), (5, 6, "g"), (16, 6, "g"),
            *span(6, 6, 15, "k"), *span(7, 7, 14, "k"), (7, 6, "w"), (12, 6, "w"),
            *block(0, 6, 2, 7, "o"), (0, 5, "o"), (2, 5, "o"), (0, 4, "o"), (2, 4, "o"),
        ],
    },
    "otto-captain": {
        "label": "Otto the transit captain: peaked cap, gold badge, run sheet with a green tick",
        "px": [
            *span(2, 8, 13, "k"), *span(3, 7, 14, "k"),
            *span(4, 6, 15, "d"), (10, 4, "G"), (11, 4, "G"),
            *span(5, 4, 17, "k"), (4, 6, "k"), (17, 6, "k"),
            *block(0, 8, 3, 13, "d"), *block(1, 9, 3, 13, "w"), (1, 8, "g"), (2, 8, "g"),
            *span(10, 1, 2, "m"), *span(12, 1, 2, "m"), (2, 11, "n"),
            (4, 10, "o"), (4, 11, "o"),
        ],
    },
    "otto-wheel": {
        "label": "Otto behind the wheel, both hands on it",
        "px": [
            *span(2, 8, 13, "k"), *span(3, 7, 14, "k"), *span(4, 5, 16, "d"),
            *block(5, 5, 5, 9, "h"), *block(16, 5, 16, 9, "h"),
            *span(10, 8, 13, "k"), (6, 11, "k"), (7, 11, "k"), (14, 11, "k"), (15, 11, "k"),
            *block(5, 12, 5, 13, "k"), *block(16, 12, 16, 13, "k"),
            (6, 14, "k"), (7, 14, "k"), (14, 14, "k"), (15, 14, "k"), *span(15, 8, 13, "k"),
            *block(9, 12, 12, 13, "g"), (10, 11, "g"), (11, 11, "g"),
            (7, 12, "g"), (8, 12, "g"), (13, 12, "g"), (14, 12, "g"),
            *block(3, 11, 4, 12, "o"), *block(17, 11, 18, 12, "o"),
        ],
    },
    "otto-stoparm": {
        "label": "Otto with the stop arm out: the circuit breaker, drawn",
        "px": [
            *span(4, 7, 14, "h"), *span(5, 6, 15, "h"),
            *block(6, 6, 6, 9, "h"), *block(15, 6, 15, 9, "h"),
            (16, 9, "g"), (17, 9, "g"),
            *span(5, 18, 20, "r"), *span(6, 17, 21, "r"), *span(7, 17, 21, "r"),
            *span(8, 17, 21, "r"), *span(9, 18, 20, "r"), *span(7, 18, 20, "w"),
            (1, 7, "G"), (2, 7, "G"), (1, 9, "r"), (2, 9, "r"),
        ],
    },
    "otto-window": {
        "label": "Otto in the window seat: a badge with the bus panel and destination blind",
        "bg": [
            *block(0, 0, 21, 15, "y"),
            *block(5, 0, 16, 1, "k"), (6, 1, "G"), (8, 1, "G"), (10, 1, "G"), (12, 1, "G"), (14, 1, "G"),
            *block(2, 2, 19, 14, "k"), *block(3, 3, 18, 13, "s"), *span(15, 0, 21, "k"),
        ],
        "px": [
            *span(4, 6, 15, "h"), *span(5, 5, 16, "h"),
            *block(5, 6, 5, 11, "h"), *block(16, 6, 16, 11, "h"),
            *span(6, 6, 15, "k"), *span(7, 7, 14, "k"), (7, 6, "w"), (12, 6, "w"),
        ],
    },
}


def cells(spec: Dict) -> str:
    grid: Dict[Tuple[int, int], str] = {}
    for x, y, k in spec.get("bg", []):
        grid[(x, y)] = k
    for y, row in enumerate(BASE):
        for x, ch in enumerate(row):
            if ch != ".":
                grid[(x, y)] = ch
    for x, y, k in spec.get("px", []):
        grid[(x, y)] = k
    return "".join('<rect x="%d" y="%d" width="1" height="1" fill="%s"/>' % (x, y, C[k]) for (x, y), k in grid.items())


def sprite_svg(name: str, spec: Dict) -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 22 16" width="264" height="192" '
            'shape-rendering="crispEdges" role="img" aria-label="%s">%s</svg>\n' % (spec["label"], cells(spec)))


def banner_svg() -> str:
    """The README hero: depot at night, the Driver at the left, the name and the one-line pitch.
    Plain monospace text with room to spare, so it survives whatever font the viewer substitutes."""
    sprite = cells(SPRITES["otto-driver"])
    stripe = "".join('<rect x="%d" y="226" width="14" height="14" fill="#f7b32b"/>' % x for x in range(0, 1200, 28))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 240" width="1200" height="240" role="img" aria-label="Otto, the ops manager for your Claude automations">
  <rect width="1200" height="240" fill="#0e1013"/>
  <rect width="1200" height="8" fill="#f7b32b"/>
  <rect y="226" width="1200" height="14" fill="#111214"/>
  {stripe}
  <g transform="translate(44,36) scale(10)" shape-rendering="crispEdges">{sprite}</g>
  <g font-family="'Courier New', Courier, monospace" font-weight="bold">
    <text x="300" y="100" font-size="52" fill="#f7b32b" letter-spacing="4">OTTO</text>
    <text x="300" y="144" font-size="21" fill="#e9e3d6">The ops manager for your Claude automations.</text>
    <text x="300" y="176" font-size="16" fill="#9aa0a8">Knows what should have run. Reads what did. Says what it cost.</text>
    <text x="300" y="204" font-size="16" fill="#d97757">He proposes. You run the command.</text>
  </g>
</svg>
'''


def main() -> int:
    for name, spec in SPRITES.items():
        (HERE / (name + ".svg")).write_text(sprite_svg(name, spec), encoding="utf-8")
    (HERE / "banner.svg").write_text(banner_svg(), encoding="utf-8")
    print("wrote %d sprites and banner.svg to %s" % (len(SPRITES), HERE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
