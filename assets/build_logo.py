#!/usr/bin/env python3
"""Generate the Irigate Iris-gate mark and horizontal lockup."""

from __future__ import annotations

import subprocess
from pathlib import Path

GOLD = "#ffc72c"
AMBER = "#f9a23a"
GLYPH_W = 240
GLYPH_H = 220
BAND_TOP = 150
BAND_HEIGHT = 30
WORDMARK = "IRIGATE"
WORDMARK_FONT = 168
WORDMARK_X = 384
WORDMARK_BASELINE = 214
LOCKUP_W = 1548
LOCKUP_H = 300
OUT = Path(__file__).parent

# Five outer petals form the Iris standards and side falls. The sixth,
# central fall is cut through with an arched opening to form the gate.
PETALS = (
    "M120 150 C103 118 92 66 120 10 C148 66 137 118 120 150 Z",
    "M112 145 C78 136 38 102 24 48 C68 55 105 82 120 126 C119 135 116 141 112 145 Z",
    "M128 145 C162 136 202 102 216 48 C172 55 135 82 120 126 C121 135 124 141 128 145 Z",
    "M112 137 C79 145 43 172 24 220 C67 213 96 194 112 174 C106 196 99 211 91 220 C108 211 118 184 120 151 C119 145 116 140 112 137 Z",
    "M128 137 C161 145 197 172 216 220 C173 213 144 194 128 174 C134 196 141 211 149 220 C132 211 122 184 120 151 C121 145 124 140 128 137 Z",
)
GATE_PETAL = (
    "M120 137 C91 158 87 190 88 220 L152 220 C153 190 149 158 120 137 Z"
)
GATE_OPENING = "M102 220 L102 185 C102 155 138 155 138 185 L138 220 Z"


def glyph(*, x: int, y: int, clip_id: str) -> str:
    paths = "\n".join(f'    <path d="{path}"/>' for path in PETALS)
    paths += f'\n    <path d="{GATE_PETAL}"/>'
    mask_id = f"{clip_id}-gate"
    return (
        "  <defs>\n"
        f'    <clipPath id="{clip_id}">\n'
        f'      <rect x="0" y="{BAND_TOP}" width="{GLYPH_W}" height="{BAND_HEIGHT}"/>\n'
        "    </clipPath>\n"
        f'    <mask id="{mask_id}">\n'
        f'      <rect x="0" y="0" width="{GLYPH_W}" height="{GLYPH_H}" fill="white"/>\n'
        f'      <path d="{GATE_OPENING}" fill="black"/>\n'
        "    </mask>\n"
        "  </defs>\n"
        f'  <g transform="translate({x} {y})" fill="{GOLD}" mask="url(#{mask_id})">\n{paths}\n  </g>\n'
        f'  <g transform="translate({x} {y})" fill="{AMBER}" clip-path="url(#{clip_id})" '
        f'mask="url(#{mask_id})">\n'
        f"{paths}\n  </g>"
    )


def render_lockup() -> str:
    mark = glyph(x=64, y=30, clip_id="irigate-glyph-band")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {LOCKUP_W} {LOCKUP_H}" '
        'role="img" aria-labelledby="title desc">\n'
        '  <title id="title">Irigate</title>\n'
        '  <desc id="desc">An Iris flower forming an open gate beside the Irigate wordmark</desc>\n'
        f"{mark}\n"
        "  <defs>\n"
        '    <clipPath id="irigate-word-band">\n'
        f'      <text x="{WORDMARK_X}" y="{WORDMARK_BASELINE}" '
        f'font-family="Georgia, \'Times New Roman\', serif" font-size="{WORDMARK_FONT}" '
        f'font-weight="700" letter-spacing="12">{WORDMARK}</text>\n'
        "    </clipPath>\n"
        "  </defs>\n"
        f'  <text x="{WORDMARK_X}" y="{WORDMARK_BASELINE}" '
        f'font-family="Georgia, \'Times New Roman\', serif" font-size="{WORDMARK_FONT}" '
        f'font-weight="700" letter-spacing="12" fill="{GOLD}">{WORDMARK}</text>\n'
        f'  <rect x="{WORDMARK_X - 4}" y="{30 + BAND_TOP}" width="1100" '
        f'height="{BAND_HEIGHT}" fill="{AMBER}" clip-path="url(#irigate-word-band)"/>\n'
        "</svg>\n"
    )


def render_mark() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 336 280" '
        'role="img" aria-labelledby="title desc">\n'
        '  <title id="title">Irigate mark</title>\n'
        '  <desc id="desc">A six-petal Iris flower whose lower petals frame an open gate</desc>\n'
        f'{glyph(x=48, y=30, clip_id="irigate-mark-band")}\n'
        "</svg>\n"
    )


def export_png(width: int) -> None:
    subprocess.run(
        [
            "inkscape",
            "logo.svg",
            "--export-type=png",
            f"--export-filename=logo-{width}.png",
            f"--export-width={width}",
        ],
        cwd=OUT,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> None:
    (OUT / "logo.svg").write_text(render_lockup(), encoding="utf-8")
    (OUT / "logo-mark.svg").write_text(render_mark(), encoding="utf-8")
    for width in (256, 512, 1024):
        export_png(width)
    print("wrote logo.svg, logo-mark.svg, and 256/512/1024px lockup PNGs")


if __name__ == "__main__":
    main()
