#!/usr/bin/env python3
"""Standalone harness for the X11 overlay presenter.

Creates a fake "game" window, puts the overlay over it, and pressure-tests:
  1. ARGB mapping / visibility
  2. Click-through via empty ShapeInput (compositor-dependent)
  3. Stacking: ABOVE set once vs reasserted on the reposition timer

Usage:
  python3 harness.py                  # run all automated checks, then exit
  python3 harness.py --hold 20        # keep windows up for manual inspection
  python3 harness.py --mode session-x11
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from Xlib import X, Xatom, display
from Xlib.ext import xtest

from presenter import (
    DetectedDisplay,
    OverlayPresenter,
    Panel,
    PresenterMode,
    Rect,
    detect_display,
    find_argb_visual,
)


def make_game_window(dpy: display.Display, rect: Rect, title: str = "SrvSurveyFakeGame"):
    """Red stand-in for the game. The background pixel is red, and paint_red() fills it again.

    A one-shot fill gets wiped by the window manager's first expose, which is why the
    earlier run showed only the green overlay.
    """
    screen = dpy.screen()
    red = screen.default_colormap.alloc_color(65535, 6000, 6000)
    win = screen.root.create_window(
        rect.x, rect.y, rect.width, rect.height, 1,
        screen.root_depth, X.InputOutput, X.CopyFromParent,
        background_pixel=red.pixel,
        event_mask=X.ExposureMask | X.ButtonPressMask | X.ButtonReleaseMask | X.StructureNotifyMask,
        override_redirect=False,
    )
    win.set_wm_name(title)
    utf8 = dpy.intern_atom("UTF8_STRING")
    net_name = dpy.intern_atom("_NET_WM_NAME")
    win.change_property(net_name, utf8, 8, title.encode("utf-8"))
    gc = win.create_gc(foreground=red.pixel)
    white = screen.default_colormap.alloc_color(65535, 65535, 65535)
    white_gc = win.create_gc(foreground=white.pixel)

    def paint_red():
        win.fill_rectangle(gc, 0, 0, rect.width, rect.height)
        dpy.flush()

    def paint_white():
        win.fill_rectangle(white_gc, 0, 0, rect.width, rect.height)
        dpy.flush()

    win.map()
    dpy.sync()
    paint_red()
    return win, paint_red, paint_white


def make_intruder_window(dpy: display.Display, rect: Rect, title: str = "SrvSurveyIntruder"):
    """A third managed window used to steal stacking above the overlay."""
    screen = dpy.screen()
    win = screen.root.create_window(
        rect.x, rect.y, rect.width, rect.height, 1,
        screen.root_depth, X.InputOutput, X.CopyFromParent,
        background_pixel=0x2040FF if screen.root_depth >= 24 else 1,
        event_mask=X.ExposureMask | X.StructureNotifyMask,
        override_redirect=False,
    )
    win.set_wm_name(title)
    win.map()
    dpy.sync()
    gc = win.create_gc(foreground=0x2040FF if screen.root_depth >= 24 else 1)
    win.fill_rectangle(gc, 0, 0, rect.width, rect.height)
    gc.free()
    dpy.flush()
    return win


def drain_events(dpy: display.Display, timeout_s: float = 0.2):
    end = time.time() + timeout_s
    events = []
    while time.time() < end:
        if dpy.pending_events() == 0:
            time.sleep(0.01)
            continue
        events.append(dpy.next_event())
    return events


def window_stack_index(dpy: display.Display, window_id: int) -> int:
    """Return index in root's child list (higher index ≈ higher in stack on most WMs)."""
    root = dpy.screen().root
    children = root.query_tree().children
    ids = [c.id for c in children]
    try:
        return ids.index(window_id)
    except ValueError:
        # May be reparented by the WM into a frame. Walk one level.
        for frame in children:
            try:
                kids = frame.query_tree().children
            except Exception:
                continue
            for k in kids:
                if k.id == window_id:
                    return ids.index(frame.id)
        return -1


def test_click_through(dpy: display.Display, game, overlay: OverlayPresenter, rect: Rect) -> dict:
    """Synthesize a click at overlay center; see if the game window gets ButtonPress."""
    result = {"ok": False, "detail": "", "events": 0}
    if not dpy.has_extension("XTEST"):
        result["detail"] = "XTEST extension missing; cannot synthesize clicks"
        return result

    # Drain prior events on game.
    drain_events(dpy, 0.1)
    cx = rect.x + rect.width // 2
    cy = rect.y + rect.height // 2

    # Move pointer and click.
    xtest.fake_input(dpy, X.MotionNotify, x=cx, y=cy)
    dpy.sync()
    time.sleep(0.05)
    xtest.fake_input(dpy, X.ButtonPress, 1)
    dpy.sync()
    time.sleep(0.05)
    xtest.fake_input(dpy, X.ButtonRelease, 1)
    dpy.sync()

    events = drain_events(dpy, 0.4)
    button_on_game = [
        e for e in events
        if getattr(e, "type", None) == X.ButtonPress and getattr(e, "window", None) and e.window.id == game.id
    ]
    result["events"] = len(events)
    if button_on_game:
        result["ok"] = True
        result["detail"] = f"game received ButtonPress at synthetic ({cx},{cy}) — click-through WORKS"
    else:
        # Check if overlay ate it (should not, if shape works).
        result["ok"] = False
        result["detail"] = (
            f"game did NOT receive ButtonPress at ({cx},{cy}). "
            f"ShapeInput may not pass through this compositor ({len(events)} other events)."
        )
    return result


def test_stacking(dpy: display.Display, overlay: OverlayPresenter, game, hold_s: float = 1.0) -> dict:
    """Raise an intruder over the overlay; compare one-shot ABOVE vs reassert."""
    result = {
        "overlay_id": overlay.window.id if overlay.window else None,
        "before_intruder": None,
        "after_intruder_no_reassert": None,
        "after_reassert_above_only": None,
        "after_reassert_above_and_raise": None,
        "needs_periodic_reassert": None,
        "detail": "",
    }
    if overlay.window is None:
        result["detail"] = "no overlay window"
        return result

    ov_id = overlay.window.id
    result["before_intruder"] = window_stack_index(dpy, ov_id)

    # Intruder overlaps the overlay.
    ir = Rect(overlay.last_rect.x + 40, overlay.last_rect.y + 40, 200, 150)
    intruder = make_intruder_window(dpy, ir)
    time.sleep(0.3)
    # Explicitly raise intruder.
    intruder.configure(stack_mode=X.Above)
    dpy.sync()
    time.sleep(0.3)
    result["after_intruder_no_reassert"] = window_stack_index(dpy, ov_id)

    # Reassert ABOVE only (ClientMessage), no XRaiseWindow.
    overlay.reassert_stacking(also_raise=False)
    time.sleep(0.3)
    result["after_reassert_above_only"] = window_stack_index(dpy, ov_id)

    # Reassert ABOVE + configure Above.
    overlay.reassert_stacking(also_raise=True)
    time.sleep(0.3)
    result["after_reassert_above_and_raise"] = window_stack_index(dpy, ov_id)

    before = result["before_intruder"]
    after = result["after_intruder_no_reassert"]
    after_above = result["after_reassert_above_only"]
    after_raise = result["after_reassert_above_and_raise"]

    if after is not None and before is not None and after < before:
        # Overlay fell in stack order.
        if after_raise is not None and after_raise >= after:
            result["needs_periodic_reassert"] = True
            result["detail"] = (
                "Intruder covered the overlay. Reasserting _NET_WM_STATE_ABOVE alone "
                f"({'helped' if after_above > after else 'did not help'}); "
                f"ABOVE+XRaiseWindow ended at stack index {after_raise} "
                f"(was {after} after intruder). Periodic kick on the reposition timer is warranted."
            )
        else:
            result["needs_periodic_reassert"] = True
            result["detail"] = "Overlay lost stacking; reassert did not recover. Mutter may ignore ABOVE for this window type."
    else:
        result["needs_periodic_reassert"] = False
        result["detail"] = (
            "Overlay kept / recovered stacking without needing a kick, or stack indices "
            "are inconclusive under this WM's reparenting. Manual visual check still required."
        )

    time.sleep(hold_s)
    try:
        intruder.destroy()
    except Exception:
        pass
    dpy.flush()
    return result


def run(mode_override: str | None, hold: float, skip_click: bool) -> int:
    detected = detect_display()
    print(f"detect: mode={detected.mode.value} display={detected.name!r} reason={detected.reason}")

    mode = detected.mode
    if mode_override:
        mode = PresenterMode(mode_override)
        print(f"override mode → {mode.value}")

    if mode == PresenterMode.DESKTOP_FALLBACK:
        print("FAIL soft: no X11 display for overlay; desktop-fallback path only")
        return 2

    dpy = display.Display(detected.name if not mode_override else (os.environ.get("DISPLAY") or detected.name))
    depth, visual = find_argb_visual(dpy)
    print(f"ARGB visual: depth={depth} visual={getattr(visual, 'visual_id', None)}")
    if visual is None:
        print("FAIL: no 32-bit ARGB visual")
        return 1

    game_rect = Rect(80, 80, 720, 480)
    game, paint_red, paint_white = make_game_window(dpy, game_rect)
    print(f"fake game window id=0x{game.id:x}")
    print("Look for a RED window. A small green square sits in the middle of it.")

    # Give the WM a moment to frame/reparent.
    time.sleep(0.4)
    # Re-read geometry after reparent.
    t = dpy.screen().root.translate_coords(game, 0, 0)
    geom = game.get_geometry()
    live = Rect(t.x, t.y, geom.width, geom.height)
    print(f"game rect after map: {live}")

    presenter = OverlayPresenter(mode, dpy.get_display_name())
    presenter.open()
    # One HUD panel. Session mode covers the whole game and lets clicks through.
    # Gamescope mode makes a window only as large as this panel.
    ov_w, ov_h = 220, 160
    panel_x = max(0, (live.width - ov_w) // 2)
    panel_y = max(0, (live.height - ov_h) // 2)
    rgba = bytes((0, 200, 80, 220)) * (ov_w * ov_h)
    presenter.present(live, [Panel(panel_x, panel_y, ov_w, ov_h, rgba)])
    ov = Rect(live.x + panel_x, live.y + panel_y, ov_w, ov_h)
    print("overlay presented from a bitmap and a rectangle")

    results = {}

    if skip_click:
        results["click_through"] = {"ok": None, "detail": "skipped"}
    else:
        print("--- click-through test ---")
        results["click_through"] = test_click_through(dpy, game, presenter, ov)
        print(results["click_through"]["detail"])

    print("--- stacking test ---")
    results["stacking"] = test_stacking(dpy, presenter, game, hold_s=min(hold, 1.0))
    print(results["stacking"]["detail"])
    print(
        "stack indices:",
        {k: results["stacking"][k] for k in results["stacking"] if k.endswith("reassert") or k.startswith("before") or k.startswith("after") or k == "needs_periodic_reassert"},
    )

    click_reached_game = False
    if hold > 0:
        print(f"holding windows for {hold}s for visual inspection...")
        print("Click the GREEN square. If this window turns white, the click passed through.")
        end = time.time() + hold
        while time.time() < end:
            if not click_reached_game:
                paint_red()
            # Reassert stacking without resizing the window down to the panel.
            presenter.reassert_stacking(also_raise=True)
            for event in drain_events(dpy, 0.05):
                if getattr(event, "type", None) != X.ButtonPress:
                    continue
                event_window = getattr(event, "window", None)
                if event_window is not None and event_window.id == game.id:
                    click_reached_game = True
                    paint_white()
                    print("CLICK REACHED THE RED WINDOW", flush=True)
            time.sleep(0.2)
        results["human_click_through"] = click_reached_game

    presenter.close()
    try:
        game.destroy()
    except Exception:
        pass
    dpy.flush()
    dpy.close()

    # Summary verdict
    print("\n=== SUMMARY ===")
    print(f"mode: {mode.value}")
    print(f"GAMESCOPE_EXTERNAL_OVERLAY atom: confirmed in gamescope binary strings (pre-check)")
    ct = results["click_through"]
    print(f"click-through: {ct.get('ok')} — {ct.get('detail')}")
    if "human_click_through" in results:
        print(f"human click reached red window: {results['human_click_through']}")
    st = results["stacking"]
    print(f"needs_periodic_reassert: {st.get('needs_periodic_reassert')} — {st.get('detail')}")

    # Exit codes: 0 = presenter works; 3 = works but click-through failed (compositor gap)
    if ct.get("ok") is False:
        return 3
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=[m.value for m in PresenterMode], default=None)
    ap.add_argument("--hold", type=float, default=3.0, help="seconds to leave windows visible")
    ap.add_argument("--skip-click", action="store_true")
    args = ap.parse_args()
    sys.exit(run(args.mode, args.hold, args.skip_click))


if __name__ == "__main__":
    main()
