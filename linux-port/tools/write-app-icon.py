#!/usr/bin/env python3
"""Write the SrvSurvey checker logo as a PNG (PlotQuestMini.drawLogo)."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw


ORANGE = (255, 111, 0, 255)
ORANGE_DIM = (95, 48, 3, 255)
BACK = (20, 24, 28, 255)
LINE = (255, 168, 64, 255)


def draw_logo(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), BACK)
    draw = ImageDraw.Draw(img)
    pad = size // 8
    box = size - pad * 2
    half = box // 2
    x0, y0 = pad, pad
    draw.rectangle((x0, y0, x0 + half - 1, y0 + half - 1), fill=ORANGE_DIM)
    draw.rectangle(
        (x0 + half, y0 + half, x0 + box - 1, y0 + box - 1),
        fill=ORANGE_DIM,
    )
    cx = x0 + half
    cy = y0 + half
    thick = max(2, size // 32)
    draw.line((cx, y0, cx, y0 + box), fill=ORANGE, width=thick)
    draw.line((x0, cy, x0 + box, cy), fill=ORANGE, width=thick)
    thin = max(1, thick // 2)
    draw.line((x0, cy, cx, y0 + box), fill=LINE, width=thin)
    draw.line((cx, y0, x0 + box, cy), fill=LINE, width=thin)
    return img


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: write-app-icon.py <out.png> [size]", file=sys.stderr)
        return 2
    out = Path(sys.argv[1])
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 256
    out.parent.mkdir(parents=True, exist_ok=True)
    draw_logo(size).save(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
