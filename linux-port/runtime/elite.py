"""Find the Elite Dangerous game window on the session X display.

Shared by the host present path and the ad-hoc corner/ultrawide checks.
Does not map an overlay and does not send input.
"""

from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "overlay-presenter"))

from presenter import Rect  # noqa: E402
from Xlib import display as xdisplay  # noqa: E402
from Xlib.error import BadWindow  # noqa: E402


ELITE_TITLE_FRAGMENT = "Elite - Dangerous"


def game_rect_usable(rect: Rect) -> bool:
    """Windows ``PlotBase.reposition`` skips a minimized or empty game window."""
    return (
        rect.width > 0
        and rect.height > 0
        and rect.x > -30_000
        and rect.y > -30_000
    )


def choose_xauthority(paths: list[str]) -> str | None:
    """Newest existing X authority file. Names are random, so mtime decides."""
    existing = [path for path in paths if path and os.path.isfile(path)]
    if not existing:
        return None
    return max(existing, key=os.path.getmtime)


def ensure_session_display(auth_files: list[str] | None = None) -> None:
    """Point DISPLAY/XAUTHORITY at the session XWayland when unset."""
    os.environ.setdefault("DISPLAY", ":0")
    current = os.environ.get("XAUTHORITY") or ""
    if auth_files is None and current and os.path.isfile(current):
        return
    if auth_files is None:
        pattern = f"/run/user/{os.getuid()}/.mutter-Xwaylandauth.*"
        found = glob.glob(pattern)
    else:
        found = list(auth_files)
    chosen = choose_xauthority(found)
    if chosen:
        os.environ["XAUTHORITY"] = chosen


def _window_title(win, net_name: int, utf8: int) -> str:
    try:
        prop = win.get_full_property(net_name, utf8)
    except (BadWindow, Exception):  # noqa: BLE001 — skip dead windows
        return ""
    raw = prop.value if prop is not None else None
    if isinstance(raw, bytes):
        return raw.decode(errors="replace")
    return str(raw or "")


def _rect_of(dpy, win) -> Rect | None:
    try:
        geom = win.get_geometry()
        origin = dpy.screen().root.translate_coords(win, 0, 0)
    except (BadWindow, Exception):  # noqa: BLE001
        return None
    return Rect(origin.x, origin.y, geom.width, geom.height)


def find_elite_window(display_name: str | None = None) -> Rect | None:
    """Return the mapped Elite window in root coordinates, if present."""
    watch = EliteWindowWatch(display_name)
    try:
        return watch.poll()
    finally:
        watch.close()


class EliteWindowWatch:
    """One X connection. Later polls read that window only.

    ``find_elite_window`` used to open a display and call ``get_full_property``
    on every root child (hundreds of windows) every HUD poll. That X-server
    stall is enough to drop frames across the desktop while docked, even when
    no plotter bitmap changed.
    """

    def __init__(self, display_name: str | None = None) -> None:
        self.display_name = display_name
        self._dpy = None
        self._win = None
        self._net_name = 0
        self._utf8 = 0
        self.scans = 0

    def close(self) -> None:
        dpy = self._dpy
        self._dpy = None
        self._win = None
        if dpy is not None:
            try:
                dpy.close()
            except Exception:  # noqa: BLE001
                pass

    def poll(self) -> Rect | None:
        if self._win is not None and self._dpy is not None:
            # Geometry of the one cached window. No root-tree walk, no shape,
            # no raise. A move shows up in TranslateCoords. A dead window
            # returns None and the next call scans once.
            rect = _rect_of(self._dpy, self._win)
            if rect is not None and game_rect_usable(rect):
                return rect
            self._win = None
        self._ensure()
        return self._scan()

    def _ensure(self) -> None:
        if self._dpy is not None:
            return
        self._dpy = xdisplay.Display(self.display_name)
        self._net_name = self._dpy.intern_atom("_NET_WM_NAME")
        self._utf8 = self._dpy.intern_atom("UTF8_STRING")

    def _scan(self) -> Rect | None:
        assert self._dpy is not None
        self.scans += 1
        root = self._dpy.screen().root
        found_win = None
        found: Rect | None = None
        for win in root.query_tree().children:
            title = _window_title(win, self._net_name, self._utf8)
            if ELITE_TITLE_FRAGMENT not in title:
                continue
            rect = _rect_of(self._dpy, win)
            if rect is None:
                continue
            found_win = win
            found = rect
        self._win = found_win
        return found
