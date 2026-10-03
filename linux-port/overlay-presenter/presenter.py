"""X11 overlay presenter for SrvSurvey (Linux native port).

One presenter, three runtime modes:
  gamescope     — one window per HUD panel, exactly that panel's size
  session-x11   — one HUD-sized click-through override-redirect window per panel
  desktop-fallback — no overlay surface when no X11 display is reachable

No process injection. No Wine. No Win32 fallbacks.
BigOverlay stays a bitmap compositor; this module only owns the windowing surface.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from Xlib import X, display, Xatom
from Xlib.ext import shape
from Xlib.error import BadWindow


GAMESCOPE_EXTERNAL_OVERLAY = "GAMESCOPE_EXTERNAL_OVERLAY"
STEAM_GAME = "STEAM_GAME"
NET_WM_STATE = "_NET_WM_STATE"
NET_WM_STATE_ABOVE = "_NET_WM_STATE_ABOVE"
NET_WM_STATE_SKIP_TASKBAR = "_NET_WM_STATE_SKIP_TASKBAR"
NET_WM_STATE_SKIP_PAGER = "_NET_WM_STATE_SKIP_PAGER"
NET_WM_WINDOW_TYPE = "_NET_WM_WINDOW_TYPE"
NET_WM_WINDOW_TYPE_NOTIFICATION = "_NET_WM_WINDOW_TYPE_NOTIFICATION"
NET_WM_NAME = "_NET_WM_NAME"
WM_NAME = "WM_NAME"
UTF8_STRING = "UTF8_STRING"


class PresenterMode(str, Enum):
    GAMESCOPE = "gamescope"
    SESSION_X11 = "session-x11"
    DESKTOP_FALLBACK = "desktop-fallback"


@dataclass
class Rect:
    x: int
    y: int
    width: int
    height: int


@dataclass
class Panel:
    """One HUD bitmap.

    ``x`` and ``y`` are pixels from the top-left of the game window.
    ``rgba`` is ``width * height * 4`` bytes, RGBA order, straight alpha.
    """

    x: int
    y: int
    width: int
    height: int
    rgba: bytes


@dataclass
class Blit:
    panel_index: int
    dst_x: int
    dst_y: int
    src_x: int
    src_y: int
    width: int
    height: int


@dataclass
class WindowPlacement:
    """Where one X window goes, and which panel pixels land inside it.

    Both session X11 and gamescope use one window per panel, exactly that
    panel's size. Session windows are override-redirect. Click-through is an
    empty ShapeInput with a full bounding shape, matching Windows
    WS_EX_TRANSPARENT: the panel is visible and clicks reach the game.
    Gamescope also uses an empty input shape plus GAMESCOPE_EXTERNAL_OVERLAY;
    the rest of the screen has no overlay window.
    """

    window: Rect
    blits: list[Blit]
    click_through: bool
    gamescope_overlay: bool


def panel_input_rect(width: int, height: int) -> tuple[int, int, int, int]:
    """Bounding region covering the whole panel (visibility, not input)."""
    return (0, 0, max(0, int(width)), max(0, int(height)))


def click_through_input_rect() -> tuple[int, int, int, int]:
    """Non-empty 1x1 input token.

    Mutter/XWayland drops a window that has an empty ShapeInput, so the
    plotter never appears. A 1x1 corner keeps the surface composited.
    The rest of the panel has no input, matching WS_EX_TRANSPARENT.
    """
    return (0, 0, 1, 1)


def click_through_hits_panel(width: int, height: int) -> bool:
    """True when a typical click on the panel hits the plotter.

    Only the 1x1 compositor token accepts input. A click in the panel
    center reaches Elite. The HUD chip is a separate full-input window.
    """
    if width <= 0 or height <= 0:
        return False
    token_w = click_through_input_rect()[2]
    token_h = click_through_input_rect()[3]
    return width <= token_w and height <= token_h


def size_change_requires_remap(previous: Rect | None, next_rect: Rect) -> bool:
    """True when ConfigureResize would drop the XWayland backing store.

    Growing a 32x32 pulse window into PlotSysStatus or PlotBuildCommodities
    leaves the host believing the plotter is mapped while PutImage is lost.
    Recreate the window at the new size instead.
    """
    if previous is None:
        return True
    return previous.width != next_rect.width or previous.height != next_rect.height


def should_unmap_all(panels: list, placements: list) -> bool:
    """Unmap only when the host asked for no plotters.

    An empty placement list with remaining panel bitmaps means the game
    rect clipped everything. Keep the last mapped windows instead of
    calling hide(), which made plotters vanish for a single bad poll.
    """
    return len(panels) == 0


PARK_AFTER_MISSING_GAME = 3


def should_park_overlays(missing_streak: int, *, threshold: int = PARK_AFTER_MISSING_GAME) -> bool:
    """Hide leftover HUD windows after the game rect stays gone.

    One missed poll is not enough (Gamescope flicker). Three in a row means
    Elite left the display and override-redirect plotters must unmap.
    """
    return int(missing_streak) >= int(threshold)


def layout_overlay(
    mode: PresenterMode,
    game: Rect,
    panels: list[Rect],
    *,
    pass_clicks: bool = True,
) -> list[WindowPlacement]:
    """Decide window geometry without opening a display.

    ``game`` is the game window in screen coordinates.
    Each panel rect is in game-window coordinates.
    ``pass_clicks`` is Windows ``hideOverlaysFromMouse``: empty ShapeInput.
    """
    if mode == PresenterMode.DESKTOP_FALLBACK:
        return []
    if game.width <= 0 or game.height <= 0:
        return []

    clipped: list[tuple[int, Rect, int, int]] = []
    for index, panel in enumerate(panels):
        piece = _clip_panel(game, panel)
        if piece is not None:
            clipped.append((index, *piece))

    if mode == PresenterMode.GAMESCOPE:
        placements = []
        for index, local, src_x, src_y in clipped:
            placements.append(WindowPlacement(
                window=Rect(game.x + local.x, game.y + local.y, local.width, local.height),
                blits=[Blit(index, 0, 0, src_x, src_y, local.width, local.height)],
                click_through=pass_clicks,
                gamescope_overlay=True,
            ))
        return placements

    placements = []
    for index, local, src_x, src_y in clipped:
        placements.append(WindowPlacement(
            window=Rect(game.x + local.x, game.y + local.y, local.width, local.height),
            blits=[Blit(index, 0, 0, src_x, src_y, local.width, local.height)],
            click_through=pass_clicks,
            gamescope_overlay=False,
        ))
    return placements


def _clip_panel(game: Rect, panel: Rect) -> Optional[tuple[Rect, int, int]]:
    """Clip a game-local panel to the game window.

    Returns the clipped local rect and the source origin inside the panel bitmap.
    """
    x0 = max(0, panel.x)
    y0 = max(0, panel.y)
    x1 = min(game.width, panel.x + panel.width)
    y1 = min(game.height, panel.y + panel.height)
    if x1 <= x0 or y1 <= y0:
        return None
    return Rect(x0, y0, x1 - x0, y1 - y0), x0 - panel.x, y0 - panel.y


@dataclass
class DetectedDisplay:
    name: str
    mode: PresenterMode
    reason: str


def _open_display(name: Optional[str] = None) -> display.Display:
    return display.Display(name)


def candidate_display_names() -> list[str]:
    """Return X display names to try, without hardcoding :0."""
    names: list[str] = []
    for key in ("DISPLAY", "GAMESCOPE_WAYLAND_DISPLAY"):
        # GAMESCOPE_WAYLAND_DISPLAY is Wayland; keep DISPLAY first.
        pass
    if os.environ.get("DISPLAY"):
        names.append(os.environ["DISPLAY"])
    # Common nested gamescope Xwayland sockets when DISPLAY already taken by session.
    for n in range(0, 8):
        candidate = f":{n}"
        if candidate not in names:
            names.append(candidate)
    return names


def detect_display() -> DetectedDisplay:
    """Pick the X display that should host the overlay.

    Prefer a display that already has a STEAM_GAME / gamescope-tagged window.
    Otherwise use the session DISPLAY. If no X server is reachable, fall back.
    """
    tried: list[str] = []
    session = os.environ.get("DISPLAY")
    for name in candidate_display_names():
        tried.append(name)
        try:
            dpy = _open_display(name)
        except Exception as exc:  # noqa: BLE001 — probe only
            continue
        try:
            if _display_has_gamescope_hint(dpy):
                result = DetectedDisplay(name=name, mode=PresenterMode.GAMESCOPE,
                                         reason="STEAM_GAME or GAMESCOPE_* property seen")
                dpy.close()
                return result
        finally:
            try:
                dpy.close()
            except Exception:  # noqa: BLE001
                pass

    if session:
        try:
            dpy = _open_display(session)
            dpy.close()
            return DetectedDisplay(name=session, mode=PresenterMode.SESSION_X11,
                                   reason="session DISPLAY reachable; no gamescope hint")
        except Exception as exc:  # noqa: BLE001
            return DetectedDisplay(name=session, mode=PresenterMode.DESKTOP_FALLBACK,
                                   reason=f"session DISPLAY unreachable: {exc}")

    return DetectedDisplay(name="", mode=PresenterMode.DESKTOP_FALLBACK,
                           reason=f"no X display reachable (tried {tried})")


def _display_has_gamescope_hint(dpy: display.Display) -> bool:
    """True only when this X server is gamescope's nested Xwayland.

    STEAM_GAME alone is not enough — the desktop Steam client stamps it on
    session XWayland windows (app id 769). Require an env hint that only
    gamescope sets, or a window that already carries GAMESCOPE_EXTERNAL_OVERLAY.
    """
    if os.environ.get("GAMESCOPE_WAYLAND_DISPLAY"):
        return True
    # Nested gamescope often exports XDG_CURRENT_DESKTOP=gamescope inside its session.
    if os.environ.get("XDG_CURRENT_DESKTOP", "").lower() == "gamescope":
        return True
    atom_overlay = dpy.intern_atom(GAMESCOPE_EXTERNAL_OVERLAY, only_if_exists=True)
    if atom_overlay == X.NONE:
        return False
    root = dpy.screen().root
    for win in _walk_windows(dpy, root, depth=3):
        try:
            prop = win.get_full_property(atom_overlay, X.AnyPropertyType)
        except BadWindow:
            continue
        if prop is not None:
            return True
    return False


def _walk_windows(dpy: display.Display, win, depth: int):
    if depth < 0:
        return
    yield win
    try:
        tree = win.query_tree()
    except BadWindow:
        return
    for child in tree.children:
        yield from _walk_windows(dpy, child, depth - 1)


def find_argb_visual(dpy: display.Display, screen_no: int = 0):
    """Return a 32-bit TrueColor visual suitable for per-pixel alpha, or None."""
    screen = dpy.screen(screen_no)
    candidates = []
    for depth_info in screen.allowed_depths:
        if depth_info.depth != 32:
            continue
        for v in depth_info.visuals:
            if v.visual_class == X.TrueColor:
                candidates.append((depth_info.depth, v))
    if not candidates:
        return None, None
    depth, visual = candidates[0]
    return depth, visual


class OverlayPresenter:
    """Creates and maintains the X11 overlay surface."""

    def __init__(self, mode: PresenterMode, display_name: str):
        self.mode = mode
        self.display_name = display_name
        self.dpy: Optional[display.Display] = None
        self.window = None
        self.colormap = None
        self.depth = None
        self.visual = None
        self._atoms: dict[str, int] = {}
        self.game_window = None
        self.last_rect: Optional[Rect] = None
        self.windows: list = []
        self.log: list[str] = []
        self._placed: list[Rect] = []
        self._frame: tuple | None = None
        # Session X11: HUD-sized override-redirect draws over borderless fullscreen.
        # Gamescope: managed panel windows + GAMESCOPE_EXTERNAL_OVERLAY (leave False).
        self.force_override_redirect = mode == PresenterMode.SESSION_X11

    def _log(self, msg: str) -> None:
        line = f"[{self.mode.value}] {msg}"
        if self.log and self.log[-1] == line:
            return
        self.log.append(line)
        print(line, flush=True)

    def _atom(self, name: str, only_if_exists: bool = False) -> int:
        if name not in self._atoms:
            self._atoms[name] = self.dpy.intern_atom(name, only_if_exists=only_if_exists)
        return self._atoms[name]

    def open(self) -> None:
        if self.mode == PresenterMode.DESKTOP_FALLBACK:
            self._log("desktop-fallback selected; no X11 overlay surface will be created here")
            return
        self.dpy = _open_display(self.display_name)
        if not self.dpy.has_extension("SHAPE"):
            raise RuntimeError("SHAPE extension missing on display " + self.display_name)
        self.depth, self.visual = find_argb_visual(self.dpy)
        if self.visual is None:
            raise RuntimeError("No 32-bit TrueColor ARGB visual on " + self.display_name)
        screen = self.dpy.screen()
        self.colormap = screen.root.create_colormap(self.visual.visual_id, X.AllocNone)
        self._log(f"opened {self.display_name} depth={self.depth} visual=0x{self.visual.visual_id:x}")

    def create_overlay(self, rect: Rect, title: str = "SrvSurveyOverlay") -> None:
        if self.mode == PresenterMode.DESKTOP_FALLBACK:
            return
        assert self.dpy is not None and self.colormap is not None
        screen = self.dpy.screen()
        attrs = {
            "colormap": self.colormap,
            "background_pixel": 0,  # fully transparent
            "border_pixel": 0,
            "override_redirect": self.force_override_redirect,
            "event_mask": X.ExposureMask | X.StructureNotifyMask,
            "bit_gravity": X.StaticGravity,
            "win_gravity": X.StaticGravity,
        }
        self.window = screen.root.create_window(
            rect.x, rect.y, rect.width, rect.height, 0,
            self.depth, X.InputOutput, self.visual.visual_id,
            **attrs,
        )
        self._set_title(title)
        if not self.force_override_redirect:
            self._set_wm_hints_input(False)
            self._set_skip_taskbar_pager()
            self._set_window_type_notification()
            self._set_above(True)
        else:
            self._set_wm_hints_input(False)
            self._log("override-redirect so the panel can draw over a fullscreen game")
        if self.force_override_redirect:
            self._apply_click_through_shapes(self.window, rect.width, rect.height)
        elif self.mode == PresenterMode.GAMESCOPE:
            self._apply_click_through_shapes(self.window, rect.width, rect.height)
            self._set_gamescope_external_overlay(True)
        self.window.map()
        if self.force_override_redirect:
            self.window.configure(stack_mode=X.Above)
        self.dpy.sync()
        self.last_rect = rect
        if self.window not in self.windows:
            self.windows.append(self.window)
        self._log(f"mapped overlay id=0x{self.window.id:x} @{rect.x},{rect.y} {rect.width}x{rect.height}")

    def present(
        self,
        game: Rect,
        panels: list[Panel],
        *,
        raise_windows: bool = True,
        pass_clicks: bool = True,
    ) -> None:
        """Show HUD panels.

        Both session X11 and gamescope map one window per panel, exactly that
        panel's size. Session windows are override-redirect. Click-through is
        an empty ShapeInput with a full bounding shape. Window type is set
        once at map, not on a timer. Gamescope sets GAMESCOPE_EXTERNAL_OVERLAY
        instead.

        ``raise_windows`` restacks every panel. Doing that on each poll stops
        the compositor from scanning the game out directly, so call it when
        the windows are first mapped or the game window moves.
        """
        if self.mode == PresenterMode.DESKTOP_FALLBACK:
            self._log("desktop-fallback: no overlay surface")
            return
        if self.dpy is None:
            self.open()
        if self.dpy is None:
            return

        for panel in panels:
            expected = panel.width * panel.height * 4
            if panel.width <= 0 or panel.height <= 0 or len(panel.rgba) != expected:
                raise ValueError(
                    f"panel rgba length {len(panel.rgba)} != {panel.width}*{panel.height}*4"
                )

        import zlib

        frame = (
            game.x,
            game.y,
            game.width,
            game.height,
            pass_clicks,
            tuple(
                (panel.x, panel.y, panel.width, panel.height, zlib.adler32(panel.rgba))
                for panel in panels
            ),
        )
        if frame == self._frame and not raise_windows:
            return
        local = [Rect(panel.x, panel.y, panel.width, panel.height) for panel in panels]
        placements = layout_overlay(self.mode, game, local, pass_clicks=pass_clicks)
        if not placements:
            if should_unmap_all(panels, placements):
                self.hide()
            self._frame = frame
            return
        remapped = self._sync_windows(placements)
        # present() must remap after hide(); configure alone leaves windows unmapped.
        # Mapping an already-viewable window on every heading tick flickers it off.
        for placement, window in zip(placements, self.windows):
            try:
                if window.get_attributes().map_state != X.IsViewable:
                    window.map()
            except BadWindow:
                continue
            self._paint_placement(window, placement, panels)
        # After a remap, drop the frame fingerprint so the next idle poll
        # paints again. XWayland can still lose the first PutImage.
        self._frame = None if remapped else frame
        if raise_windows:
            self.reassert_stacking(also_raise=True)
        spots = ", ".join(
            f"{placement.window.width}x{placement.window.height}"
            f"@{placement.window.x},{placement.window.y}"
            for placement in placements
        )
        self._log(
            f"presented {len(panels)} panel(s) on elite "
            f"{game.width}x{game.height} @({game.x},{game.y}): {spots} "
            f"click_through={pass_clicks} "
            f"override_redirect={self.force_override_redirect}"
        )

    def _sync_windows(self, placements: list[WindowPlacement]) -> bool:
        remapped = False
        while len(self.windows) > len(placements):
            extra = self.windows.pop()
            if self._placed:
                self._placed.pop()
            try:
                extra.destroy()
            except BadWindow:
                pass
        for index, placement in enumerate(placements):
            if index == len(self.windows):
                self._map_window(placement)
                remapped = True
                continue
            window = self.windows[index]
            rect = placement.window
            previous = self._placed[index] if index < len(self._placed) else None
            if previous == rect:
                continue
            if size_change_requires_remap(previous, rect):
                self._remap_window(index, placement)
                remapped = True
                continue
            window.configure(x=rect.x, y=rect.y)
            self._placed[index] = rect
            self.last_rect = rect
            if self.dpy is not None:
                self.dpy.flush()
        self.window = self.windows[-1] if self.windows else None
        return remapped

    def _map_window(self, placement: WindowPlacement) -> None:
        assert self.dpy is not None and self.colormap is not None
        screen = self.dpy.screen()
        rect = placement.window
        event_mask = X.ExposureMask | X.StructureNotifyMask
        window = screen.root.create_window(
            rect.x, rect.y, rect.width, rect.height, 0,
            self.depth, X.InputOutput, self.visual.visual_id,
            colormap=self.colormap,
            background_pixel=0,
            border_pixel=0,
            override_redirect=self.force_override_redirect,
            event_mask=event_mask,
            bit_gravity=X.StaticGravity,
            win_gravity=X.StaticGravity,
        )
        self.window = window
        self.windows.append(window)
        self._set_title("SrvSurveyOverlay")
        if not self.force_override_redirect:
            self._set_wm_hints_input(False)
            self._set_skip_taskbar_pager()
            self._set_window_type_notification()
            self._set_above(True)
        else:
            self._set_wm_hints_input(False)
            self._log("override-redirect so the panel can draw over a fullscreen game")
        if placement.click_through:
            self._apply_click_through_shapes(window, rect.width, rect.height)
        else:
            self._apply_visible_input_shapes(window, rect.width, rect.height)
        if placement.gamescope_overlay:
            self._set_gamescope_external_overlay(True)
        window.map()
        if self.force_override_redirect:
            window.change_attributes(event_mask=event_mask)
            window.configure(stack_mode=X.Above)
        self.dpy.sync()
        self.last_rect = rect
        self._placed.append(rect)
        self._log(
            f"mapped overlay id=0x{window.id:x} @{rect.x},{rect.y} "
            f"{rect.width}x{rect.height} click_through={placement.click_through} "
            f"override-redirect={self.force_override_redirect}"
        )

    def _remap_window(self, index: int, placement: WindowPlacement) -> None:
        """Destroy and recreate one overlay. ConfigureResize drops PutImage."""
        old = self.windows[index]
        try:
            old.unmap()
            old.destroy()
        except BadWindow:
            pass
        if index < len(self._placed):
            self._placed.pop(index)
        self.windows.pop(index)
        window_count = len(self.windows)
        self._map_window(placement)
        if index != window_count:
            created = self.windows.pop()
            placed = self._placed.pop()
            self.windows.insert(index, created)
            self._placed.insert(index, placed)
        self._log(
            f"remapped overlay slot {index} to "
            f"{placement.window.width}x{placement.window.height} "
            "(new X window; resize would lose the bitmap)"
        )

    def _paint_placement(self, window, placement: WindowPlacement, panels: list[Panel]) -> None:
        # Windows are always panel-sized; paint each blit as a cropped PutImage.
        for blit in placement.blits:
            panel = panels[blit.panel_index]
            cropped = _crop_rgba(
                panel.rgba, panel.width, blit.src_x, blit.src_y, blit.width, blit.height,
            )
            saved = self.window
            self.window = window
            self.last_rect = placement.window
            self.paint_bitmap_rgba(cropped, blit.width, blit.height, dst_x=blit.dst_x, dst_y=blit.dst_y)
            self.window = saved

    def _set_title(self, title: str) -> None:
        self.window.set_wm_name(title)
        utf8 = self._atom(UTF8_STRING)
        net_name = self._atom(NET_WM_NAME)
        self.window.change_property(net_name, utf8, 8, title.encode("utf-8"))

    def _set_wm_hints_input(self, accept: bool) -> None:
        from Xlib import Xutil
        self.window.set_wm_hints(flags=Xutil.InputHint, input=1 if accept else 0)

    def _mark_overlay_plane_once(self) -> None:
        """Ask Mutter for the overlay plane once, when the window is created.

        Override-redirect plus _NET_WM_WINDOW_TYPE_NOTIFICATION. Not a raise,
        and not repeated on later polls. _NET_WM_WINDOW_TYPE_DOCK is not used:
        a dock type makes Mutter reserve a strut and relayout the desktop.
        """
        self._set_window_type_notification()
        state = self._atom(NET_WM_STATE)
        above = self._atom(NET_WM_STATE_ABOVE)
        skip_tb = self._atom(NET_WM_STATE_SKIP_TASKBAR)
        skip_pg = self._atom(NET_WM_STATE_SKIP_PAGER)
        self.window.change_property(state, Xatom.ATOM, 32, [above, skip_tb, skip_pg])
        self._log("window type notification set once at map")

    def _set_skip_taskbar_pager(self) -> None:
        state = self._atom(NET_WM_STATE)
        skip_tb = self._atom(NET_WM_STATE_SKIP_TASKBAR)
        skip_pg = self._atom(NET_WM_STATE_SKIP_PAGER)
        self.window.change_property(state, Xatom.ATOM, 32, [skip_tb, skip_pg])

    def _set_window_type_notification(self) -> None:
        wtype = self._atom(NET_WM_WINDOW_TYPE)
        notif = self._atom(NET_WM_WINDOW_TYPE_NOTIFICATION)
        self.window.change_property(wtype, Xatom.ATOM, 32, [notif])

    def _set_above(self, enable: bool) -> None:
        """Request _NET_WM_STATE_ABOVE via ClientMessage (EWMH), not a one-shot property write."""
        assert self.dpy is not None and self.window is not None
        from Xlib.protocol import event as xevent

        root = self.dpy.screen().root
        state = self._atom(NET_WM_STATE)
        above = self._atom(NET_WM_STATE_ABOVE)
        # _NET_WM_STATE action: 0=remove, 1=add, 2=toggle
        action = 1 if enable else 0
        ev = xevent.ClientMessage(
            window=self.window,
            client_type=state,
            data=(32, [action, above, 0, 1, 0]),
        )
        mask = X.SubstructureRedirectMask | X.SubstructureNotifyMask
        root.send_event(ev, event_mask=mask)
        self.dpy.flush()

    def reassert_stacking(self, also_raise: bool = True) -> None:
        """Keep overlays above the game. Call from the reposition timer."""
        if not self.windows:
            return
        for window in self.windows:
            self.window = window
            if self.force_override_redirect:
                if also_raise:
                    window.configure(stack_mode=X.Above)
            else:
                self._set_above(True)
                if also_raise:
                    window.configure(stack_mode=X.Above)
        if self.dpy is not None:
            self.dpy.flush()

    def _apply_visible_input_shapes(self, window, width: int, height: int) -> None:
        """Full bounding and input shapes. Used when click-through is off."""
        assert self.dpy is not None
        x, y, w, h = panel_input_rect(width, height)
        rects = [{"x": x, "y": y, "width": w, "height": h}]
        window.shape_rectangles(shape.SO.Set, shape.SK.Bounding, 0, 0, 0, rects)
        window.shape_rectangles(shape.SO.Set, shape.SK.Input, 0, 0, 0, rects)
        self.dpy.flush()
        self._log(f"full ShapeInput {w}x{h}; hideOverlaysFromMouse=false")

    def _apply_click_through_shapes(self, window, width: int, height: int) -> None:
        """Full bounding shape, empty input shape (Windows WS_EX_TRANSPARENT).

        Bounding keeps the HUD visible. Empty input lets pointer events reach
        Elite. Applied when the window is created or its size changes. Idle
        polls do not call this.
        """
        assert self.dpy is not None
        x, y, w, h = panel_input_rect(width, height)
        bounding = [{"x": x, "y": y, "width": w, "height": h}]
        window.shape_rectangles(shape.SO.Set, shape.SK.Bounding, 0, 0, 0, bounding)
        ix, iy, iw, ih = click_through_input_rect()
        token = [{"x": ix, "y": iy, "width": iw, "height": ih}]
        window.shape_rectangles(shape.SO.Set, shape.SK.Input, 0, 0, 0, token)
        self.dpy.flush()
        self._log(
            f"ShapeBounding {w}x{h}; ShapeInput {iw}x{ih} token (click-through)"
        )

    def _set_gamescope_external_overlay(self, enable: bool) -> None:
        atom = self._atom(GAMESCOPE_EXTERNAL_OVERLAY)
        if atom == X.NONE:
            self._log("WARNING: GAMESCOPE_EXTERNAL_OVERLAY atom missing on this display")
            return
        value = 1 if enable else 0
        self.window.change_property(atom, Xatom.CARDINAL, 32, [value])
        self.dpy.flush()
        self._log(f"set {GAMESCOPE_EXTERNAL_OVERLAY}={value}")

    def paint_solid(self, r: int, g: int, b: int, a: int) -> None:
        """Fill overlay with a solid ARGB color (test helper)."""
        if self.window is None:
            return
        # PutImage of a flat color is enough for the slice.
        # Use XFillRectangle with a GC that has foreground including alpha in high bits.
        pixel = ((a & 0xFF) << 24) | ((r & 0xFF) << 16) | ((g & 0xFF) << 8) | (b & 0xFF)
        gc = self.window.create_gc(foreground=pixel)
        w = self.last_rect.width if self.last_rect else 1
        h = self.last_rect.height if self.last_rect else 1
        self.window.fill_rectangle(gc, 0, 0, w, h)
        gc.free()
        self.dpy.flush()

    def paint_bitmap_rgba(self, rgba: bytes, width: int, height: int, dst_x: int = 0, dst_y: int = 0) -> None:
        """Blit a RGBA bitmap (BigOverlay frame stand-in), tiled to stay under X max-request size."""
        if self.window is None:
            return
        bgra = bytearray(len(rgba))
        for i in range(0, len(rgba), 4):
            r, g, b, a = rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3]
            bgra[i] = b
            bgra[i + 1] = g
            bgra[i + 2] = r
            bgra[i + 3] = a

        # X11 PutImage length field is 16-bit in 4-byte units (~256 KiB). Stay under that.
        max_bytes = 200_000
        stride = width * 4
        rows_per_chunk = max(1, max_bytes // stride)
        gc = self.window.create_gc()
        row = 0
        while row < height:
            n = min(rows_per_chunk, height - row)
            start = row * stride
            end = start + n * stride
            self.window.put_image(
                gc, dst_x, dst_y + row, width, n, X.ZPixmap, 32, 0, bytes(bgra[start:end])
            )
            row += n
        gc.free()
        self.dpy.flush()

    def reposition(self, rect: Rect, reassert_stack: bool = True) -> None:
        if self.window is None:
            return
        self.window.configure(x=rect.x, y=rect.y, width=rect.width, height=rect.height)
        self.last_rect = rect
        if reassert_stack:
            self.reassert_stacking(also_raise=True)
        else:
            self.dpy.flush()

    def attach_game_window(self, window_id: int) -> None:
        self.game_window = self.dpy.create_resource_object("window", window_id)

    def read_game_rect(self) -> Optional[Rect]:
        if self.game_window is None:
            return None
        try:
            geom = self.game_window.get_geometry()
            # Translate to root coordinates.
            abspos = self.game_window.translate_coords(self.dpy.screen().root, 0, 0)
            # translate_coords returns coords of root origin in window space; invert.
            root_x = -abspos.x
            root_y = -abspos.y
            # Better: use translate from window to root.
            t = self.dpy.screen().root.translate_coords(self.game_window, 0, 0)
            return Rect(t.x, t.y, geom.width, geom.height)
        except BadWindow:
            return None

    def hide(self) -> None:
        """Unmap all overlay windows without destroying them (journal can keep running)."""
        if not self.windows:
            return
        for window in self.windows:
            try:
                window.unmap()
            except BadWindow:
                pass
        self._frame = None
        if self.dpy is not None:
            self.dpy.sync()
        self._log(f"hidden {len(self.windows)} overlay window(s)")

    def show(self) -> None:
        """Remap previously hidden overlay windows and reassert stacking."""
        if not self.windows:
            return
        for window in self.windows:
            try:
                window.map()
                if self.force_override_redirect:
                    window.configure(stack_mode=X.Above)
            except BadWindow:
                pass
        self.reassert_stacking(also_raise=True)
        self._log(f"shown {len(self.windows)} overlay window(s)")

    def close(self) -> None:
        for window in self.windows:
            try:
                window.unmap()
                window.destroy()
            except BadWindow:
                pass
        self.windows = []
        self._placed = []
        self._frame = None
        self.window = None
        if self.dpy is not None:
            self.dpy.close()
            self.dpy = None


def _copy_rgba(dest: bytearray, dest_stride_px: int, dst_x: int, dst_y: int,
               src: bytes, src_stride_px: int, src_x: int, src_y: int,
               width: int, height: int) -> None:
    for row in range(height):
        src_start = ((src_y + row) * src_stride_px + src_x) * 4
        dst_start = ((dst_y + row) * dest_stride_px + dst_x) * 4
        dest[dst_start:dst_start + width * 4] = src[src_start:src_start + width * 4]


def _crop_rgba(src: bytes, src_stride_px: int, src_x: int, src_y: int,
               width: int, height: int) -> bytes:
    out = bytearray(width * height * 4)
    _copy_rgba(out, width, 0, 0, src, src_stride_px, src_x, src_y, width, height)
    return bytes(out)
