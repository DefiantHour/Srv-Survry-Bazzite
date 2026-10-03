#!/usr/bin/env python3
"""Show the status panel as a small corner window.

No synthetic clicks. No gamescope. The window is only as large as the panel.
Kept off the Elite rectangle so fullscreen Elite is untouched.
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
        print("elite window not found on this display", flush=True)
        return 1
    location = load_location()
    rgba, width, height = render_status_bitmap(location)
    rgba, width, height = scale_nearest(rgba, width, height, 3)
    rgba = paint_border(rgba, width, height)
    # Keep completely off the game rectangle so fullscreen Elite is untouched.
    gap = 24
    x = max(0, elite.x - width - gap)
    y = elite.y + 80
    game = Rect(x, y, width, height)
    panel = Panel(0, 0, width, height, rgba)
    print(
        f"elite window {elite.width}x{elite.height} at ({elite.x},{elite.y})",
        flush=True,
    )
    print(
        f"safe panel {width}x{height} at ({game.x},{game.y}) "
        f"system={location.system or '-'} commander={location.commander or '-'}",
        flush=True,
    )
    print(
        "look left of the game (side monitor); no overlap; "
        "override-redirect off for this off-game check; closing in 15s",
        flush=True,
    )
    presenter = OverlayPresenter(PresenterMode.SESSION_X11, os.environ["DISPLAY"])
    # Side-monitor check: managed window is enough when not over the game.
    presenter.force_override_redirect = False
    try:
        presenter.present(game, [panel])
        time.sleep(15)
    finally:
        presenter.close()
    print("corner panel closed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
