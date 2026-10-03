#!/usr/bin/env python3
"""PlotAdjustVR — Linux opacity/scale adjust panel (OpenVR headset N/A).

Headset/OpenVR inject is not available on typical Linux Wayland sessions.
When ``displayVR`` is on, this panel shows guidance and current
``plotterOpacity`` / ``plotterScale``. Chords (ALT V open; zoom chords nudge
while open) persist via AppSettings.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
from dataclasses import replace
from pathlib import Path

from game_settings import GameSettings
from theme import cyan, orange, orange_dim

STRIPE = (12, 12, 12, 255)
BLACK = (0, 0, 0, 255)

TITLE_PX = 10
BODY_PX = 9
PAD = 10
DEFAULT_WIDTH = 320
DEFAULT_HEIGHT = 110

_OPACITY_STEP = 5.0
_SCALE_STEP = 1.0


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    paths = (
        (
            "/usr/share/fonts/urw-base35/URWGothic-Demi.otf"
            if bold
            else "/usr/share/fonts/urw-base35/URWGothic-Book.otf"
        ),
        (
            "/usr/share/fonts/julietaula-montserrat-fonts/Montserrat-Bold.otf"
            if bold
            else "/usr/share/fonts/julietaula-montserrat-fonts/Montserrat-Regular.otf"
        ),
    )
    for path in paths:
        if Path(path).is_file():
            return ImageFont.truetype(path, size * SCALE)
    return ImageFont.load_default()


def _s(n: float) -> int:
    return int(round(n * SCALE))


def _tw(draw, text: str, font) -> int:
    b = draw.textbbox((0, 0), text, font=font)
    return int(b[2] - b[0])


def adjust_vr_allowed(
    game: GameSettings,
    *,
    force_show: bool = False,
) -> bool:
    """Show when displayVR is on (or force)."""
    if force_show:
        return True
    return bool(game.displayVR)


def nudge_plotter_opacity(game: GameSettings, delta: float) -> GameSettings:
    """Clamp opacity 0..100 and return a replaced GameSettings."""
    current = float(getattr(game, "plotterOpacity", 50.0) or 0.0)
    nxt = max(0.0, min(100.0, current + float(delta)))
    return replace(game, plotterOpacity=nxt)


def nudge_plotter_scale(game: GameSettings, delta: float) -> GameSettings:
    """Clamp scale nudge 0..4 and return a replaced GameSettings."""
    current = float(getattr(game, "plotterScale", 0.0) or 0.0)
    nxt = max(0.0, min(4.0, current + float(delta)))
    return replace(game, plotterScale=nxt)


def opacity_step() -> float:
    return _OPACITY_STEP


def scale_step() -> float:
    return _SCALE_STEP


def render_adjust_vr_bitmap(
    *,
    game: GameSettings | None = None,
    force_show: bool = False,
) -> tuple[bytes, int, int] | None:
    """Calibration panel: opacity/scale readouts + chord guidance."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    if not adjust_vr_allowed(gs, force_show=force_show):
        return None

    orange_c = orange(gs)
    orange_d = orange_dim(gs)
    cyan_c = cyan(gs)

    opacity = int(getattr(gs, "plotterOpacity", 100) or 100)
    scale_nudge = float(getattr(gs, "plotterScale", 0.0) or 0.0)

    title = "VR Adjust"
    line1 = "OpenVR / headset inject: N/A on Wayland"
    line2 = f"Opacity {opacity}%  ·  Scale nudge {scale_nudge:+.0f}"
    line3 = "ALT V toggle · CTRL+/- opacity · CTRL SHIFT Bksp scale"

    font_title = _font(TITLE_PX, bold=True)
    font_body = _font(BODY_PX)
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    width = max(
        _s(DEFAULT_WIDTH),
        max(
            _tw(probe, title, font_title),
            _tw(probe, line1, font_body),
            _tw(probe, line2, font_body),
            _tw(probe, line3, font_body),
        )
        + _s(PAD * 2),
    )
    height = _s(DEFAULT_HEIGHT)

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, width - 1, height - 1), fill=BLACK)
    step = _s(3)
    for yy in range(0, height, step):
        draw.line((0, yy, width - 1, yy), fill=STRIPE)
    for yy, col in ((_s(3), orange_d), (_s(4), orange_c), (_s(5), orange_d)):
        draw.line((_s(2), yy, width - _s(4), yy), fill=col)
    for yy, col in (
        (height - _s(5), orange_d),
        (height - _s(4), orange_c),
        (height - _s(3), orange_d),
    ):
        draw.line((_s(2), yy, width - _s(4), yy), fill=col)
    draw.rectangle(
        (0, 0, width - 1, height - 1),
        outline=orange_c,
        width=max(1, SCALE // 2),
    )

    y = _s(10)
    draw.text((_s(PAD), y), title, font=font_title, fill=orange_c)
    y += _s(16)
    draw.text((_s(PAD), y), line1, font=font_body, fill=cyan_c)
    y += _s(14)
    draw.text((_s(PAD), y), line2, font=font_body, fill=orange_c)
    y += _s(14)
    draw.text((_s(PAD), y), line3, font=font_body, fill=orange_d)

    if SCALE != 1:
        img = img.resize((width // AA, height // AA), Image.Resampling.LANCZOS)
    w, h = img.size
    return img.tobytes("raw", "RGBA"), w, h
