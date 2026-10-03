#!/usr/bin/env python3
"""Best-effort FSS pixel-watch for Linux (Windows WatchFssPixelSettings).

On X11 with ``DISPLAY`` set and ``gs.watchFssPixel_TEST`` enabled, attempt a
root/screen grab via mss or Pillow ImageGrab. Wayland and missing grabbers
fail soft — PlotFSS stays journal-driven. Does not use XTEST.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from game_settings import GameSettings


@dataclass(frozen=True)
class FssPixelGrabResult:
    """Outcome of one grab attempt."""

    available: bool
    reason: str
    width: int = 0
    height: int = 0
    mode: str = ""


def is_x11_display(environ: dict[str, str] | None = None) -> bool:
    """True when DISPLAY looks like classic X11 (not Wayland-only)."""
    env = os.environ if environ is None else environ
    display = (env.get("DISPLAY") or "").strip()
    if not display:
        return False
    # Wayland-native sessions often still set DISPLAY via XWayland; treat
    # WAYLAND_DISPLAY-only preference as soft — grab may still work on XWayland.
    # Fail soft later if ImageGrab/mss cannot capture.
    return True


def pixel_watch_enabled(game: GameSettings) -> bool:
    return bool(getattr(game, "watchFssPixel_TEST", False))


def try_grab_screen(
    game: GameSettings | None = None,
    *,
    environ: dict[str, str] | None = None,
    region: tuple[int, int, int, int] | None = None,
) -> FssPixelGrabResult:
    """Attempt one screen grab. Never raises; soft-fails on Wayland / missing libs."""
    gs = game if game is not None else GameSettings()
    if not pixel_watch_enabled(gs):
        return FssPixelGrabResult(False, "watchFssPixel_TEST disabled")
    env = os.environ if environ is None else environ
    wayland = bool((env.get("WAYLAND_DISPLAY") or "").strip())
    if not is_x11_display(env) and not wayland:
        return FssPixelGrabResult(False, "no DISPLAY and no WAYLAND_DISPLAY")

    # Prefer mss when installed; fall back to Pillow ImageGrab.
    try:
        import mss  # type: ignore[import-untyped]

        with mss.mss() as sct:
            mon: dict[str, Any]
            if region is not None:
                left, top, width, height = region
                mon = {"left": left, "top": top, "width": width, "height": height}
            else:
                mon = sct.monitors[0]
            shot = sct.grab(mon)
            return FssPixelGrabResult(
                True,
                "mss",
                width=int(shot.width),
                height=int(shot.height),
                mode="mss",
            )
    except Exception:
        pass

    try:
        from PIL import ImageGrab

        bbox = region  # left, top, right, bottom for ImageGrab
        if region is not None:
            left, top, width, height = region
            bbox = (left, top, left + width, top + height)
        img = ImageGrab.grab(bbox=bbox)
        if img is None:
            return FssPixelGrabResult(False, "ImageGrab returned None")
        w, h = img.size
        return FssPixelGrabResult(True, "ImageGrab", width=w, height=h, mode="ImageGrab")
    except Exception:
        pass

    return _try_ffmpeg(region)


def ffmpeg_grab_command(
    ffmpeg: str,
    display: str,
    dest: str,
    region: tuple[int, int, int, int] | None,
    screen: tuple[int, int] | None,
) -> list[str] | None:
    """One PNG via ffmpeg x11grab. Returns None when the size is unknown."""
    if region is not None:
        left, top, width, height = region
        if width < 1 or height < 1:
            return None
        size = f"{int(width)}x{int(height)}"
        source = f"{display}+{int(left)},{int(top)}"
    elif screen is not None and screen[0] > 0 and screen[1] > 0:
        size = f"{int(screen[0])}x{int(screen[1])}"
        source = display
    else:
        return None
    return [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "x11grab",
        "-video_size",
        size,
        "-i",
        source,
        "-frames:v",
        "1",
        dest,
    ]


def _x11_screen_size() -> tuple[int, int] | None:
    try:
        from Xlib import display as xdisplay

        dpy = xdisplay.Display(os.environ.get("DISPLAY") or None)
        screen = dpy.screen()
        size = (int(screen.width_in_pixels), int(screen.height_in_pixels))
        dpy.close()
        return size
    except Exception:
        return None


def _try_ffmpeg(region: tuple[int, int, int, int] | None) -> FssPixelGrabResult:
    """XWayland grab. Pillow's root GetImage fails with BadMatch on this session."""
    import shutil
    import subprocess
    import tempfile

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return _try_grim(region)
    display = (os.environ.get("DISPLAY") or "").strip() or ":0"
    cmd = ffmpeg_grab_command(ffmpeg, display, "unused", region, _x11_screen_size())
    if cmd is None:
        return _try_grim(region)
    path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            path = handle.name
        cmd[-1] = path
        proc = subprocess.run(cmd, capture_output=True, timeout=6, check=False)
        if proc.returncode != 0 or not os.path.isfile(path) or os.path.getsize(path) == 0:
            err = (proc.stderr or b"").decode("utf-8", errors="replace")[-160:]
            gnome = _try_grim(region)
            if gnome.available:
                return gnome
            return FssPixelGrabResult(False, gnome.reason or f"ffmpeg x11grab failed: {err or proc.returncode}")
        from PIL import Image

        with Image.open(path) as img:
            w, h = img.size
        return FssPixelGrabResult(True, "ffmpeg", width=w, height=h, mode="ffmpeg")
    except Exception as exc:  # noqa: BLE001
        gnome = _try_grim(region)
        if gnome.available:
            return gnome
        return FssPixelGrabResult(False, gnome.reason or f"ffmpeg x11grab unavailable: {exc}")
    finally:
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass


def _try_grim(region: tuple[int, int, int, int] | None) -> FssPixelGrabResult:
    """Wayland portal screenshot via grim when it is installed. No sudo."""
    import shutil
    import subprocess
    import tempfile

    grim = shutil.which("grim")
    if not grim:
        return _try_gnome_shell(region)
    path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            path = handle.name
        cmd = [grim]
        if region is not None:
            left, top, width, height = region
            cmd.extend(["-g", f"{left},{top} {width}x{height}"])
        cmd.append(path)
        proc = subprocess.run(cmd, capture_output=True, timeout=4, check=False)
        if proc.returncode != 0 or not os.path.isfile(path) or os.path.getsize(path) == 0:
            err = (proc.stderr or b"").decode("utf-8", errors="replace")[:160]
            gnome = _try_gnome_shell(region)
            if gnome.available:
                return gnome
            return FssPixelGrabResult(False, gnome.reason or f"grim failed: {err or proc.returncode}")
        from PIL import Image

        with Image.open(path) as img:
            w, h = img.size
        return FssPixelGrabResult(True, "grim", width=w, height=h, mode="grim")
    except Exception as exc:  # noqa: BLE001
        gnome = _try_gnome_shell(region)
        if gnome.available:
            return gnome
        return FssPixelGrabResult(False, gnome.reason or f"grim unavailable: {exc}")
    finally:
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass


def gnome_area_command(
    busctl: str,
    path: str,
    region: tuple[int, int, int, int] | None,
) -> list[str]:
    """org.gnome.Shell.Screenshot on this session: ScreenshotArea(iiii bs) -> (b s)."""
    dest = "org.gnome.Shell.Screenshot"
    object_path = "/org/gnome/Shell/Screenshot"
    base = [busctl, "--user", "call", dest, object_path, dest]
    if region is None:
        return base + ["Screenshot", "bbs", "false", "false", path]
    left, top, width, height = region
    return base + [
        "ScreenshotArea",
        "iiiibs",
        str(int(left)),
        str(int(top)),
        str(int(width)),
        str(int(height)),
        "false",
        path,
    ]


def _try_gnome_shell(region: tuple[int, int, int, int] | None) -> FssPixelGrabResult:
    """Silent GNOME capture. This session currently returns Access denied."""
    import shutil
    import subprocess
    import tempfile

    busctl = shutil.which("busctl")
    if not busctl:
        return _try_screencast(region)
    path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            path = handle.name
        proc = subprocess.run(
            gnome_area_command(busctl, path, region),
            capture_output=True,
            timeout=4,
            check=False,
        )
        err = (proc.stderr or b"").decode("utf-8", errors="replace")
        out = (proc.stdout or b"").decode("utf-8", errors="replace")
        denied = "Access denied" in err or "Access denied" in out
        if proc.returncode != 0 or denied:
            reason = "gnome shell denied silent capture" if denied else (err or out or str(proc.returncode))[:160]
            cast = _try_screencast(region)
            if cast.available:
                return cast
            return FssPixelGrabResult(False, cast.reason or reason)
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            cast = _try_screencast(region)
            if cast.available:
                return cast
            return FssPixelGrabResult(False, cast.reason or "gnome screenshot wrote no image")
        from PIL import Image

        with Image.open(path) as img:
            w, h = img.size
        return FssPixelGrabResult(True, "gnome-shell", width=w, height=h, mode="gnome-shell")
    except Exception as exc:  # noqa: BLE001
        cast = _try_screencast(region)
        if cast.available:
            return cast
        return FssPixelGrabResult(False, cast.reason or f"gnome screenshot unavailable: {exc}")
    finally:
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass


_last_cast: tuple[float, FssPixelGrabResult] | None = None


def _try_screencast(region: tuple[int, int, int, int] | None) -> FssPixelGrabResult:
    """Portal ScreenCast. Does not block the HUD while the grant dialog is open."""
    import tempfile
    import time

    from screencast_grab import shared_grabber

    global _last_cast
    now = time.monotonic()
    if _last_cast is not None and now - _last_cast[0] < 1.0:
        return _last_cast[1]
    def _remember(result: FssPixelGrabResult) -> FssPixelGrabResult:
        global _last_cast
        _last_cast = (time.monotonic(), result)
        return result

    grabber = shared_grabber()
    grabber.ensure()
    if not grabber.ready:
        return _remember(FssPixelGrabResult(False, grabber.reason))
    path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            path = handle.name
        ok, reason = grabber.capture(path)
        if not ok:
            return _remember(FssPixelGrabResult(False, reason))
        from PIL import Image

        with Image.open(path) as img:
            if region is not None:
                left, top, width, height = region
                img = img.crop((left, top, left + width, top + height))
            w, h = img.size
        return _remember(FssPixelGrabResult(True, "screencast", width=w, height=h, mode="screencast"))
    except Exception as exc:  # noqa: BLE001
        return _remember(FssPixelGrabResult(False, f"screen cast unavailable: {exc}"))
    finally:
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass


def parity_note() -> str:
    """Short PARITY / About note for pixel-watch availability."""
    return (
        "pixel-watch uses X11 grab, then ffmpeg x11grab, then grim, then GNOME Shell, "
        "then a ScreenCast restore token. An ungranted capture stays journal-driven."
    )
