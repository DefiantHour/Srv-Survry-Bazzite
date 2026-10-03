"""Toggle visibility for the overlay (X11 grab + main-monitor chip + SIGUSR1).

On Bazzite / GNOME Wayland, Elite under Proton is an XWayland client on the
session ``DISPLAY``. Passive ``XGrabKey`` often *appears* to succeed but does
not deliver KeyPress events while another XWayland client (Elite) has focus —
Mutter routes keys to the focused surface before the X11 grab sees them.

Reliable toggle: a small always-on-top, clickable chip inside the bottom-right
of the Elite window, off the plotters.json anchors. GNOME GlobalShortcuts
BindShortcuts is not used: it opens a shortcut-binding dialog on every start.
X11 GrabKey, evdev, and SIGUSR1 remain as extra paths.

Real pointer clicks (not SendEvent) only reach the chip when Mutter/XWayland
sees a non-empty input region and an input-capable window. Empty ShapeInput
or InputHint=0 makes SendEvent still work while human clicks miss — the same
class of false positive as XTEST vs Mutter.
"""

from __future__ import annotations

import os
import select
import signal
import threading
import time
from dataclasses import dataclass
from typing import Callable

# python-xlib is not thread-safe unless threaded is imported first.
import Xlib.threaded  # noqa: F401
from Xlib import X, XK, display
from Xlib.error import CatchError, BadAccess, BadWindow
from Xlib.ext import shape


# Lock modifiers that still mean "same chord" to the user.
_LOCK_MASKS = (
    0,
    X.LockMask,
    X.Mod2Mask,
    X.LockMask | X.Mod2Mask,
    X.Mod5Mask,
    X.LockMask | X.Mod5Mask,
    X.Mod2Mask | X.Mod5Mask,
    X.LockMask | X.Mod2Mask | X.Mod5Mask,
)

_CHIP_W = 132
_CHIP_H = 40
_CHIP_GAP = 16


@dataclass(frozen=True)
class ParsedChord:
    """Normalized hotkey chord."""

    label: str
    modifiers: int
    keysym: int
    keyname: str


@dataclass(frozen=True)
class ChipRect:
    """Screen-space rectangle for the main-monitor toggle chip."""

    x: int
    y: int
    width: int
    height: int


def normalize_chord(text: str) -> str:
    parts = [p.strip() for p in text.replace("-", "+").split("+") if p.strip()]
    if not parts:
        return "Pause"
    *mods, key = parts
    mod_out: list[str] = []
    for mod in mods:
        low = mod.lower()
        if low in {"super", "meta", "win", "mod4"}:
            token = "Super"
        elif low in {"shift"}:
            token = "Shift"
        elif low in {"ctrl", "control"}:
            token = "Ctrl"
        elif low in {"alt", "mod1"}:
            token = "Alt"
        else:
            token = mod.capitalize()
        if token not in mod_out:
            mod_out.append(token)
    low_key = key.lower().replace(" ", "_")
    special = {
        "pause": "Pause",
        "break": "Pause",
        "scroll_lock": "Scroll_Lock",
        "scrolllock": "Scroll_Lock",
        "scroll": "Scroll_Lock",
    }
    if low_key in special:
        key_out = special[low_key]
    elif low_key.startswith("f") and low_key[1:].isdigit():
        key_out = low_key.upper()
    elif len(key) == 1:
        key_out = key.upper()
    else:
        key_out = key[:1].upper() + key[1:]
    return "+".join([*mod_out, key_out])


def parse_chord(text: str) -> ParsedChord:
    """Parse ``Pause`` / ``F9`` / ``Super+Shift+S`` into X modifiers + keysym."""
    label = normalize_chord(text)
    parts = label.split("+")
    *mod_names, key_name = parts
    modifiers = 0
    for name in mod_names:
        low = name.lower()
        if low == "shift":
            modifiers |= X.ShiftMask
        elif low == "ctrl":
            modifiers |= X.ControlMask
        elif low == "alt":
            modifiers |= X.Mod1Mask
        elif low == "super":
            modifiers |= X.Mod4Mask
    keysym = XK.string_to_keysym(key_name)
    if keysym == 0:
        keysym = XK.string_to_keysym(key_name.capitalize())
    if keysym == 0 and len(key_name) == 1:
        keysym = XK.string_to_keysym(key_name.lower())
    if keysym == 0:
        # Fall back to Pause rather than crash the present loop.
        keysym = XK.XK_Pause
        key_name = "Pause"
        label = normalize_chord("+".join([*mod_names, "Pause"]) if mod_names else "Pause")
    return ParsedChord(label=label, modifiers=modifiers, keysym=keysym, keyname=key_name)


def place_toggle_chip(game_x: int, game_y: int, game_w: int, game_h: int,
                      screen_w: int, screen_h: int) -> ChipRect:
    """Keep the chip inside Elite, off every plotters.json anchor.

    Top-left is PlotBodyInfo. Bottom-right is not used by a Windows plotter.
    """
    w, h = _CHIP_W, _CHIP_H
    gap = 8
    if game_w >= w and game_h >= h:
        x = game_x + game_w - w - min(gap, game_w - w)
        y = game_y + game_h - h - min(gap, game_h - h)
    else:
        x = game_x
        y = game_y
    x = max(0, min(x, max(0, screen_w - w)))
    y = max(0, min(y, max(0, screen_h - h)))
    return ChipRect(x, y, w, h)


def _find_argb_visual(dpy: display.Display):
    """Return (depth, visual) for a 32-bit TrueColor visual, or (None, None)."""
    screen = dpy.screen()
    for depth_info in screen.allowed_depths:
        if depth_info.depth != 32:
            continue
        for visual in depth_info.visuals:
            if visual.visual_class == X.TrueColor:
                return depth_info.depth, visual
    return None, None


def _render_chip_rgba(visible: bool, width: int = _CHIP_W, height: int = _CHIP_H) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    # Fully opaque: Mutter/XWayland often passes clicks through translucent ARGB.
    bg = (28, 140, 72, 255) if visible else (55, 55, 58, 255)
    fg = (245, 245, 245, 255)
    border = (210, 210, 210, 255) if visible else (140, 140, 140, 255)
    label = "HUD ON" if visible else "HUD OFF"
    img = Image.new("RGBA", (width, height), bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, width - 1, height - 1), outline=border, width=2)
    font = ImageFont.load_default()
    for path in (
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            font = ImageFont.truetype(path, 14)
            break
        except OSError:
            continue
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((width - tw) / 2, (height - th) / 2 - 1), label, fill=fg, font=font)
    return img.tobytes()


class HotkeyToggle:
    """Process-level visibility toggle via chip, X11 GrabKey, and/or SIGUSR1."""

    def __init__(
        self,
        chord: str = "Pause",
        *,
        display_name: str | None = None,
        on_toggle: Callable[[], None] | None = None,
        prefer_x11: bool = True,
        enable_chip: bool = True,
        game_x: int | None = None,
        game_y: int | None = None,
        game_w: int | None = None,
        game_h: int | None = None,
        initially_visible: bool = True,
        on_visibility_saved: Callable[[bool], None] | None = None,
        on_open_settings: Callable[[], None] | None = None,
        action_bindings: list[tuple[str, Callable[[str], None]]] | None = None,
    ) -> None:
        self.chord = parse_chord(chord)
        self.display_name = display_name or os.environ.get("DISPLAY")
        self.on_toggle = on_toggle
        self.on_visibility_saved = on_visibility_saved
        self.on_open_settings = on_open_settings
        self.prefer_x11 = prefer_x11
        self.enable_chip = enable_chip
        # Optional Windows-style keyActions: (chord_text, callback(action_or_label)).
        # Stored as (ParsedChord, callback, source_label) after parse.
        self._action_specs: list[tuple[str, Callable[[str], None]]] = list(
            action_bindings or []
        )
        self._action_grabs: list[tuple[object, int, int, bool, Callable[[str], None], str]] = []
        self._game = None
        if None not in (game_x, game_y, game_w, game_h):
            self._game = (int(game_x), int(game_y), int(game_w), int(game_h))
        self._visible = bool(initially_visible)
        self._lock = threading.Lock()
        self._dpy_lock = threading.RLock()
        self._stop = threading.Event()
        self._changed = threading.Event()
        self._thread: threading.Thread | None = None
        self._dpy: display.Display | None = None
        self._grabbed = False
        self._chip = None
        self._chip_gc = None
        self._chip_rect: ChipRect | None = None
        self._backend = "none"
        self._prev_usr1 = None
        self._use_any_modifier = self.chord.modifiers == 0
        # Ignore chip clicks for a short time after map — mapping under the
        # cursor can deliver a spurious ButtonPress on some Mutter builds.
        self._chip_armed_at = 0.0
        self._chip_arm_delay = 0.45
        self._evdev_thread: threading.Thread | None = None
        self._portal = None

    def _start_global_shortcuts(self) -> bool:
        """Bind configured chords through the GNOME portal. Chip stays either way."""
        try:
            from global_shortcuts import GlobalShortcutBridge, gtk_trigger, shortcut_id
        except ImportError:
            return False
        bindings: list[tuple[str, str, str, Callable[[], None]]] = []
        toggle_trigger = gtk_trigger(self.chord.label)
        if toggle_trigger:
            bindings.append(
                (
                    "toggle-overlay",
                    "Toggle the SrvSurvey overlay",
                    toggle_trigger,
                    self.toggle,
                )
            )
        seen = {toggle_trigger} if toggle_trigger else set()
        for chord_text, callback in self._action_specs:
            trigger = gtk_trigger(chord_text)
            if not trigger or trigger in seen:
                continue
            seen.add(trigger)
            label = chord_text

            def _fire(bound: str = label, fn: Callable[[str], None] = callback) -> None:
                fn(bound)

            bindings.append(
                (
                    shortcut_id(chord_text),
                    f"SrvSurvey {chord_text}",
                    trigger,
                    _fire,
                )
            )
        if not bindings:
            return False
        bridge = GlobalShortcutBridge()
        if not bridge.start(bindings):
            bridge.stop()
            return False
        self._portal = bridge
        return True

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def visible(self) -> bool:
        """Thread-safe overlay visibility (honored by the present loop)."""
        with self._lock:
            return self._visible

    @visible.setter
    def visible(self, value: bool) -> None:
        with self._lock:
            self._visible = bool(value)
        self._changed.set()

    def consume_change(self) -> bool:
        """Return True once if visibility changed since the last consume."""
        if not self._changed.is_set():
            return False
        self._changed.clear()
        return True

    def wait_changed(self, timeout: float) -> bool:
        """Block until visibility flips or timeout. Clears the latch on wake."""
        fired = self._changed.wait(timeout=max(0.0, timeout))
        if fired:
            self._changed.clear()
        return fired

    def start(self) -> str:
        """Install handlers. Returns the active backend name."""
        self._install_signal()
        parts: list[str] = ["signal"]
        if self.prefer_x11 and self.display_name:
            try:
                self._start_x11()
                if self._grabbed:
                    parts.insert(0, f"x11:{self.chord.label}")
                if self._action_grabs:
                    parts.insert(0, f"chords:{len(self._action_grabs)}")
                if self._chip is not None:
                    parts.insert(0, "chip")
            except Exception as exc:  # noqa: BLE001 — best-effort
                parts.append(f"x11-failed({exc})")
        if self._start_evdev():
            parts.insert(0, "evdev")
        # Do not call BindShortcuts. The portal dialog asks the user to confirm
        # shortcut keys on every launch. The on-screen chip still toggles.
        self._backend = "+".join(parts)
        return self._backend

    def stop(self) -> None:
        self._stop.set()
        portal = getattr(self, "_portal", None)
        if portal is not None:
            portal.stop()
            self._portal = None
        if self._evdev_thread is not None:
            self._evdev_thread.join(timeout=1.5)
            self._evdev_thread = None
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None
        with self._dpy_lock:
            self._destroy_chip()
            self._ungrab_x11()
            if self._dpy is not None:
                try:
                    self._dpy.close()
                except Exception:  # noqa: BLE001
                    pass
                self._dpy = None
        if self._prev_usr1 is not None:
            signal.signal(signal.SIGUSR1, self._prev_usr1)
            self._prev_usr1 = None

    def request_refresh(self) -> None:
        """Wake the present loop so panels can rebuild (force-show chords)."""
        self._changed.set()

    def toggle(self) -> bool:
        """Flip visibility; return the new visible state."""
        with self._lock:
            self._visible = not self._visible
            state = self._visible
        self._changed.set()
        self._repaint_chip()
        if self.on_toggle is not None:
            self.on_toggle()
        if self.on_visibility_saved is not None:
            try:
                self.on_visibility_saved(state)
            except Exception:  # noqa: BLE001 — persistence must not kill the loop
                pass
        return state

    def set_visible(self, visible: bool) -> None:
        with self._lock:
            self._visible = bool(visible)
        self._changed.set()
        self._repaint_chip()
        if self.on_visibility_saved is not None:
            try:
                self.on_visibility_saved(bool(visible))
            except Exception:  # noqa: BLE001
                pass

    def reposition_for_game(self, game_x: int, game_y: int, game_w: int, game_h: int) -> None:
        """Move the chip when Elite moves/resizes."""
        self._game = (int(game_x), int(game_y), int(game_w), int(game_h))
        with self._dpy_lock:
            if self._dpy is None or self._chip is None:
                return
            screen = self._dpy.screen()
            rect = place_toggle_chip(
                game_x, game_y, game_w, game_h, screen.width_in_pixels, screen.height_in_pixels,
            )
            self._chip_rect = rect
            try:
                self._chip.configure(x=rect.x, y=rect.y, width=rect.width, height=rect.height)
                self._apply_full_input_shape(rect.width, rect.height)
                self._chip.configure(stack_mode=X.Above)
                self._dpy.flush()
            except BadWindow:
                return
        self._repaint_chip()

    def reassert_chip(self) -> None:
        with self._dpy_lock:
            if self._dpy is None or self._chip is None:
                return
            try:
                # Keep the chip above HUD panels so real clicks hit it, not a
                # higher override-redirect surface (even click-through ones can
                # steal hits when Mutter's ShapeInput path is imperfect).
                self._chip.configure(stack_mode=X.Above)
                self._dpy.flush()
            except BadWindow:
                pass

    def _install_signal(self) -> None:
        def _handler(_signum, _frame) -> None:
            state = self.toggle()
            print(
                f"overlay {'shown' if state else 'hidden'} (SIGUSR1)",
                flush=True,
            )

        self._prev_usr1 = signal.signal(signal.SIGUSR1, _handler)

    def _start_x11(self) -> None:
        assert self.display_name is not None
        dpy = display.Display(self.display_name)
        root = dpy.screen().root
        keycode = dpy.keysym_to_keycode(self.chord.keysym)
        if keycode == 0:
            dpy.close()
            raise RuntimeError(f"no keycode for {self.chord.keyname}")

        # owner_events=False: force KeyPress to this connection when the grab
        # fires. AnyModifier covers NumLock/CapsLock/Mode_switch for bare keys.
        errorer = CatchError(BadAccess)
        if self._use_any_modifier:
            root.grab_key(
                keycode,
                X.AnyModifier,
                False,
                X.GrabModeAsync,
                X.GrabModeAsync,
                onerror=errorer,
            )
        else:
            for extra in _LOCK_MASKS:
                root.grab_key(
                    keycode,
                    self.chord.modifiers | extra,
                    False,
                    X.GrabModeAsync,
                    X.GrabModeAsync,
                    onerror=errorer,
                )
        dpy.sync()
        if errorer.get_error():
            # Grab failed (chord taken) — still allow chip + signal.
            self._grabbed = False
        else:
            self._grabbed = True

        self._dpy = dpy
        self._grab_action_chords(root)
        if self.enable_chip and self._game is not None:
            try:
                self._map_chip()
            except Exception as exc:  # noqa: BLE001 — chip is best-effort
                print(f"toggle chip unavailable: {exc}", flush=True)
                self._destroy_chip()

        self._thread = threading.Thread(
            target=self._x11_loop,
            name="srvsurvey-hotkey",
            daemon=True,
        )
        self._thread.start()

    def _grab_action_chords(self, root) -> None:
        """XGrabKey for Windows keyActions bindings (best-effort)."""
        dpy = self._dpy
        if dpy is None or not self._action_specs:
            return
        # Import here to keep hotkey usable without key_chords in older trees.
        try:
            from key_chords import windows_chord_to_linux
        except ImportError:
            windows_chord_to_linux = lambda t: t  # noqa: E731

        self._action_grabs = []
        seen: set[tuple[int, int]] = set()
        for chord_text, callback in self._action_specs:
            linux = windows_chord_to_linux(chord_text) if chord_text else ""
            if not linux:
                continue
            try:
                parsed = parse_chord(linux)
            except Exception:  # noqa: BLE001
                continue
            keycode = dpy.keysym_to_keycode(parsed.keysym)
            if keycode == 0:
                continue
            use_any = parsed.modifiers == 0
            # Skip duplicate (keycode, modifiers) grabs.
            grab_key = (keycode, parsed.modifiers if not use_any else -1)
            if grab_key in seen:
                # Still register dispatch for the same physical chord.
                self._action_grabs.append(
                    (parsed, keycode, parsed.modifiers, use_any, callback, chord_text)
                )
                continue
            seen.add(grab_key)
            errorer = CatchError(BadAccess)
            if use_any:
                root.grab_key(
                    keycode,
                    X.AnyModifier,
                    False,
                    X.GrabModeAsync,
                    X.GrabModeAsync,
                    onerror=errorer,
                )
            else:
                for extra in _LOCK_MASKS:
                    root.grab_key(
                        keycode,
                        parsed.modifiers | extra,
                        False,
                        X.GrabModeAsync,
                        X.GrabModeAsync,
                        onerror=errorer,
                    )
            dpy.sync()
            if errorer.get_error():
                print(
                    f"key chord grab failed for {chord_text!r} ({parsed.label})",
                    flush=True,
                )
                continue
            self._action_grabs.append(
                (parsed, keycode, parsed.modifiers, use_any, callback, chord_text)
            )
        if self._action_grabs:
            print(
                f"key chords grabbed: {len(self._action_grabs)} binding(s)",
                flush=True,
            )

    def _map_chip(self) -> None:
        assert self._dpy is not None and self._game is not None
        from Xlib import Xutil

        if not self._dpy.has_extension("SHAPE"):
            raise RuntimeError("SHAPE extension missing; chip needs an explicit input region")

        screen = self._dpy.screen()
        gx, gy, gw, gh = self._game
        rect = place_toggle_chip(
            gx, gy, gw, gh, screen.width_in_pixels, screen.height_in_pixels,
        )
        self._chip_rect = rect
        depth, visual = _find_argb_visual(self._dpy)
        if visual is None:
            depth = screen.root_depth
            visual_id = screen.root_visual
            cmap = screen.default_colormap
        else:
            visual_id = visual.visual_id
            cmap = screen.root.create_colormap(visual_id, X.AllocNone)

        # Chip must receive real pointer clicks. Do NOT apply empty ShapeInput
        # (that is only for HUD panels). InputHint must be 1 so XWayland/Mutter
        # publishes a non-empty Wayland input region — InputHint=0 + ARGB made
        # SendEvent work while human clicks missed the surface.
        event_mask = (
            X.ExposureMask
            | X.ButtonPressMask
            | X.ButtonReleaseMask
            | X.EnterWindowMask
            | X.LeaveWindowMask
            | X.StructureNotifyMask
        )
        window = screen.root.create_window(
            rect.x, rect.y, rect.width, rect.height, 0,
            depth, X.InputOutput, visual_id,
            colormap=cmap,
            background_pixel=0,
            border_pixel=0,
            override_redirect=True,
            event_mask=event_mask,
        )
        window.set_wm_name("SrvSurveyToggle")
        window.set_wm_class("SrvSurveyToggle", "SrvSurvey")
        window.set_wm_hints(flags=Xutil.InputHint, input=1)
        self._chip = window
        self._apply_full_input_shape(rect.width, rect.height)
        window.map()
        window.configure(stack_mode=X.Above)
        # Re-select the mask after map; some XWayland builds drop it on ARGB.
        window.change_attributes(event_mask=event_mask)
        self._dpy.sync()
        self._chip_gc = window.create_gc()
        self._repaint_chip()
        self._chip_armed_at = time.monotonic() + self._chip_arm_delay
        print(
            f"toggle chip mapped 0x{window.id:x} {rect.width}x{rect.height} "
            f"@({rect.x},{rect.y}) ButtonPressMask+full ShapeInput",
            flush=True,
        )

    def _apply_full_input_shape(self, width: int, height: int) -> None:
        """Ensure the chip's ShapeInput covers the whole window (receives clicks)."""
        if self._chip is None or self._dpy is None:
            return
        rects = [{"x": 0, "y": 0, "width": int(width), "height": int(height)}]
        # Bounding = visible footprint; Input = hit-test footprint. Both full.
        self._chip.shape_rectangles(shape.SO.Set, shape.SK.Bounding, 0, 0, 0, rects)
        self._chip.shape_rectangles(shape.SO.Set, shape.SK.Input, 0, 0, 0, rects)
        self._dpy.flush()

    def _repaint_chip(self) -> None:
        with self._dpy_lock:
            if self._dpy is None or self._chip is None or self._chip_gc is None:
                return
            rect = self._chip_rect or ChipRect(0, 0, _CHIP_W, _CHIP_H)
            with self._lock:
                visible = self._visible
            rgba = _render_chip_rgba(visible, rect.width, rect.height)
            bgra = bytearray(len(rgba))
            for i in range(0, len(rgba), 4):
                r, g, b, a = rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3]
                bgra[i] = b
                bgra[i + 1] = g
                bgra[i + 2] = r
                bgra[i + 3] = a
            try:
                self._chip.put_image(
                    self._chip_gc, 0, 0, rect.width, rect.height, X.ZPixmap, 32, 0, bytes(bgra),
                )
                self._dpy.flush()
            except Exception:  # noqa: BLE001
                pass

    def _x11_loop(self) -> None:
        dpy = self._dpy
        if dpy is None:
            return
        keycode = dpy.keysym_to_keycode(self.chord.keysym)
        try:
            fileno = dpy.fileno()
        except Exception:  # noqa: BLE001
            fileno = None
        while not self._stop.is_set():
            with self._dpy_lock:
                pending = dpy.pending_events()
            if pending == 0:
                if fileno is not None:
                    try:
                        select.select([fileno], [], [], 0.05)
                    except (ValueError, OSError):
                        self._stop.wait(0.05)
                else:
                    self._stop.wait(0.05)
                continue
            with self._dpy_lock:
                event = dpy.next_event()
            if event.type == X.Expose and self._chip is not None:
                if getattr(event, "window", None) is not None and event.window.id == self._chip.id:
                    self._repaint_chip()
                continue
            if event.type == X.ButtonPress and self._chip is not None:
                if getattr(event, "window", None) is not None and event.window.id == self._chip.id:
                    if time.monotonic() < self._chip_armed_at:
                        continue
                    detail = getattr(event, "detail", 1)
                    if detail == 3 and self.on_open_settings is not None:
                        try:
                            self.on_open_settings()
                        except Exception as exc:  # noqa: BLE001
                            print(f"settings open failed: {exc}", flush=True)
                        continue
                    if detail == 1:
                        state = self.toggle()
                        print(
                            f"overlay {'shown' if state else 'hidden'} (chip)",
                            flush=True,
                        )
                continue
            if event.type != X.KeyPress:
                continue
            detail = event.detail
            mods = event.state & ~(X.LockMask | X.Mod2Mask | X.Mod5Mask)

            # Windows keyActions first (ALT F / ALT S / …).
            action_hit = False
            for _parsed, act_code, modifiers, use_any, callback, label in self._action_grabs:
                if detail != act_code:
                    continue
                if use_any:
                    pass
                elif mods != modifiers:
                    continue
                action_hit = True
                try:
                    callback(label)
                except Exception as exc:  # noqa: BLE001
                    print(f"key chord action failed ({label}): {exc}", flush=True)
                break
            if action_hit:
                continue

            if detail != keycode:
                continue
            if self._use_any_modifier:
                # Bare key: ignore all modifiers (NumLock, Caps, etc.).
                pass
            else:
                if mods != self.chord.modifiers:
                    continue
            state = self.toggle()
            print(
                f"overlay {'shown' if state else 'hidden'} ({self.chord.label})",
                flush=True,
            )

    def _destroy_chip(self) -> None:
        if self._chip_gc is not None:
            try:
                self._chip_gc.free()
            except Exception:  # noqa: BLE001
                pass
            self._chip_gc = None
        if self._chip is not None:
            try:
                self._chip.unmap()
                self._chip.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._chip = None
        self._chip_rect = None

    def _ungrab_x11(self) -> None:
        if self._dpy is None:
            self._grabbed = False
            self._action_grabs = []
            return
        try:
            root = self._dpy.screen().root
            if self._grabbed:
                keycode = self._dpy.keysym_to_keycode(self.chord.keysym)
                if self._use_any_modifier:
                    root.ungrab_key(keycode, X.AnyModifier)
                else:
                    for extra in _LOCK_MASKS:
                        root.ungrab_key(keycode, self.chord.modifiers | extra)
            # Ungrab action chords (dedupe by keycode+mods).
            seen: set[tuple[int, int]] = set()
            for _parsed, act_code, modifiers, use_any, _cb, _label in self._action_grabs:
                grab_key = (act_code, modifiers if not use_any else -1)
                if grab_key in seen:
                    continue
                seen.add(grab_key)
                if use_any:
                    root.ungrab_key(act_code, X.AnyModifier)
                else:
                    for extra in _LOCK_MASKS:
                        root.ungrab_key(act_code, modifiers | extra)
            self._dpy.sync()
        except Exception:  # noqa: BLE001
            pass
        self._grabbed = False
        self._action_grabs = []

    def _start_evdev(self) -> bool:
        """Read /dev/input when the user can already read it. No sudo, no XTEST."""
        code = _evdev_code(self.chord.keyname)
        devices = _readable_event_devices()
        if code is None or not devices:
            return False
        need_ctrl = "ctrl" in self.chord.label.lower()
        need_shift = "shift" in self.chord.label.lower()
        need_alt = "alt" in self.chord.label.lower()

        def run() -> None:
            import struct

            fmt = "llHHi"
            size = struct.calcsize(fmt)
            fds = []
            try:
                for path in devices:
                    fds.append(os.open(path, os.O_RDONLY | os.O_NONBLOCK))
                held: set[int] = set()
                last = 0.0
                while not self._stop.is_set():
                    ready, _, _ = select.select(fds, [], [], 0.4)
                    for fd in ready:
                        try:
                            data = os.read(fd, size * 8)
                        except OSError:
                            continue
                        for offset in range(0, len(data) - size + 1, size):
                            _sec, _usec, typ, key, value = struct.unpack_from(fmt, data, offset)
                            if typ != 1:
                                continue
                            if value == 1:
                                held.add(key)
                            elif value == 0:
                                held.discard(key)
                            if value != 1 or key != code:
                                continue
                            if need_ctrl and 29 not in held and 97 not in held:
                                continue
                            if need_shift and 42 not in held and 54 not in held:
                                continue
                            if need_alt and 56 not in held and 100 not in held:
                                continue
                            now = time.monotonic()
                            if now - last < 0.35:
                                continue
                            last = now
                            self.toggle()
            finally:
                for fd in fds:
                    try:
                        os.close(fd)
                    except OSError:
                        pass

        self._evdev_thread = threading.Thread(target=run, name="srvsurvey-evdev", daemon=True)
        self._evdev_thread.start()
        return True


def _evdev_code(keyname: str) -> int | None:
    name = keyname.lower().replace(" ", "").replace("_", "")
    if len(name) == 1 and "a" <= name <= "z":
        return 30 + ord(name) - ord("a")
    if name.startswith("f") and name[1:].isdigit():
        number = int(name[1:])
        if 1 <= number <= 10:
            return 58 + number
        if number == 11:
            return 87
        if number == 12:
            return 88
    return {
        "pause": 119,
        "scrolllock": 70,
        "insert": 110,
        "home": 102,
        "space": 57,
    }.get(name)


def _readable_event_devices() -> list[str]:
    base = "/dev/input"
    if not os.path.isdir(base):
        return []
    found: list[str] = []
    try:
        names = os.listdir(base)
    except OSError:
        return []
    for name in names:
        if not name.startswith("event"):
            continue
        path = os.path.join(base, name)
        if os.access(path, os.R_OK):
            found.append(path)
    return found[:8]
