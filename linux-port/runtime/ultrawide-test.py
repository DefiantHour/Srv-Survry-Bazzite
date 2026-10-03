#!/usr/bin/env python3
"""Short panel on the ultrawide game monitor only.

HUD-sized, override-redirect so Mutter may show it over borderless fullscreen.
No synthetic clicks. Closes itself quickly.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "overlay-presenter"))

from elite import ensure_session_display, find_elite_window  # noqa: E402
from host import discover  # noqa: E402
from journal import CommanderLocation, latest_journal_file, read_location_file  # noqa: E402
from panel import render_status_bitmap  # noqa: E402
from presenter import OverlayPresenter, Panel, PresenterMode, Rect  # noqa: E402


def load_location() -> CommanderLocation:
    _data, journal_folder, _vdf = discover()
    if journal_folder is None or not journal_folder.is_dir():
        return CommanderLocation(None, None, None)
    latest = latest_journal_file(journal_folder)
    if latest is None:
        return CommanderLocation(None, None, None)
    return read_location_file(latest)


def scale_nearest(rgba: bytes, width: int, height: int, factor: int) -> tuple[bytes, int, int]:
    out_w = width * factor
    out_h = height * factor
    src = rgba
    out = bytearray(out_w * out_h * 4)
    for y in range(out_h):
        sy = y // factor
        for x in range(out_w):
            sx = x // factor
            si = (sy * width + sx) * 4
            di = (y * out_w + x) * 4
            out[di:di + 4] = src[si:si + 4]
    return bytes(out), out_w, out_h


def paint_border(rgba: bytes, width: int, height: int, thickness: int = 4) -> bytes:
    px = bytearray(rgba)
    orange = bytes((255, 140, 0, 255))
    for y in range(height):
        for x in range(width):
            if x < thickness or y < thickness or x >= width - thickness or y >= height - thickness:
                i = (y * width + x) * 4
                px[i:i + 4] = orange
    return bytes(px)


def main() -> int:
    ensure_session_display()
    elite = find_elite_window()
    if elite is None:
        print("elite window not found", flush=True)
        return 1
    location = load_location()
    rgba, width, height = render_status_bitmap(location)
    rgba, width, height = scale_nearest(rgba, width, height, 3)
    rgba = paint_border(rgba, width, height)
    margin = 80
    x = elite.width - width - margin
    y = margin
    panel = Panel(x, y, width, height, rgba)
    print(f"elite {elite.width}x{elite.height} @({elite.x},{elite.y})", flush=True)
    print(
        f"ultrawide panel {width}x{height} game-local ({x},{y}) "
        f"system={location.system or '-'} commander={location.commander or '-'}",
        flush=True,
    )
    print("on the game monitor; 12s; session override-redirect default; no clicks", flush=True)
    presenter = OverlayPresenter(PresenterMode.SESSION_X11, os.environ["DISPLAY"])
    try:
        presenter.present(elite, [panel])
        time.sleep(12)
    finally:
        presenter.close()
    print("ultrawide panel closed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
