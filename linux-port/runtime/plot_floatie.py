#!/usr/bin/env python3
"""PlotFloatie — Linux port of SrvSurvey/plotters/PlotFloatie.cs.

Transient toast messages (~6s). Call ``show_message(msg)``; the panel renders
while messages remain. No WinForms timer — expiry checked on each render.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from game_settings import GameSettings
from theme import cyan as theme_cyan
from theme import orange as theme_orange
from theme import orange_dim as theme_orange_dim

ORANGE = theme_orange()
ORANGE_DIM = theme_orange_dim()
CYAN = theme_cyan()
STRIPE = (12, 12, 12, 255)
BLACK = (0, 0, 0, 255)

TITLE_PX = 12
PAD = 10
DURATION_SECONDS = 6


@dataclass
class FloatieMessage:
    msg: str
    expires: datetime


_messages: list[FloatieMessage] = []
_close_time: datetime | None = None


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


def clear_messages() -> None:
    """Drop all floatie messages (tests)."""
    global _messages, _close_time
    _messages = []
    _close_time = None


def show_message(msg: str, *, duration_seconds: int = DURATION_SECONDS) -> None:
    """Queue a floatie message (PlotFloatie.showMessage)."""
    global _messages, _close_time
    text = (msg or "").strip()
    if not text:
        return
    now = datetime.now()
    expires = now + timedelta(seconds=max(1, int(duration_seconds)))
    _messages = [m for m in _messages if m.msg != text and m.expires > now]
    _messages.append(FloatieMessage(text, expires))
    _close_time = expires


def active_messages(*, now: datetime | None = None) -> list[FloatieMessage]:
    """Prune expired messages and return the live list."""
    global _messages
    t = now if now is not None else datetime.now()
    _messages = [m for m in _messages if m.expires > t]
    return list(_messages)


def floatie_allowed(game: GameSettings, *, force_show: bool = False) -> bool:
    if not game.autoShowFloatie_TEST:
        return False
    if force_show:
        return True
    return len(active_messages()) > 0


def render_floatie_bitmap(
    *,
    game: GameSettings | None = None,
    force_show: bool = False,
    now: datetime | None = None,
) -> tuple[bytes, int, int] | None:
    """Draw PlotFloatie. Returns None when disabled or nothing to show."""
    global ORANGE, ORANGE_DIM, CYAN
    saved = (ORANGE, ORANGE_DIM, CYAN)
    ORANGE = theme_orange(game)
    ORANGE_DIM = theme_orange_dim(game)
    CYAN = theme_cyan(game)
    try:
        return _render_floatie_bitmap(game=game, force_show=force_show, now=now)
    finally:
        ORANGE, ORANGE_DIM, CYAN = saved


def _render_floatie_bitmap(
    *,
    game: GameSettings | None = None,
    force_show: bool = False,
    now: datetime | None = None,
) -> tuple[bytes, int, int] | None:
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    msgs = active_messages(now=now)
    if force_show and not msgs:
        msgs = [FloatieMessage("Floatie ready", datetime.now() + timedelta(seconds=6))]
    if not floatie_allowed(gs, force_show=force_show) and not (force_show and msgs):
        return None
    if not msgs:
        return None

    font = _font(TITLE_PX, bold=True)
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    content_w = max(_tw(probe, f"► {m.msg}", font) for m in msgs)
    width = max(_s(200), content_w + _s(PAD * 2 + 20))
    row_h = _s(18)
    height = _s(10) + len(msgs) * row_h + _s(12)

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, width - 1, height - 1), fill=BLACK)
    step = _s(3)
    for y in range(0, height, step):
        draw.line((0, y, width - 1, y), fill=STRIPE)
    for y, col in ((_s(3), ORANGE_DIM), (_s(4), ORANGE), (_s(5), ORANGE_DIM)):
        draw.line((_s(2), y, width - _s(4), y), fill=col)
    for y, col in (
        (height - _s(5), ORANGE_DIM),
        (height - _s(4), ORANGE),
        (height - _s(3), ORANGE_DIM),
    ):
        draw.line((_s(2), y, width - _s(4), y), fill=col)
    draw.rectangle((0, 0, width - 1, height - 1), outline=ORANGE, width=max(1, SCALE // 2))

    y = _s(10)
    for msg in msgs:
        draw.text((_s(PAD), y), f"► {msg.msg}", font=font, fill=CYAN)
        y += row_h

    # Timer bars slide out from center (Windows drawTimerBar)
    close = _close_time or (msgs[-1].expires if msgs else datetime.now())
    t = now if now is not None else datetime.now()
    remaining_ms = max(0.0, (close - t).total_seconds() * 1000.0)
    ratio = remaining_ms / (DURATION_SECONDS * 1000.0)
    bar_y_top = _s(1)
    bar_y_bot = height - _s(1)
    full_w = width - _s(4)
    ww = full_w - full_w * ratio
    x0 = _s(2) + (full_w - ww) / 2.0
    draw.line((x0, bar_y_top, x0 + ww, bar_y_top), fill=ORANGE_DIM, width=max(1, SCALE))
    draw.line((x0, bar_y_bot, x0 + ww, bar_y_bot), fill=ORANGE_DIM, width=max(1, SCALE))

    if SCALE != 1:
        img = img.resize((width // AA, height // AA), Image.Resampling.LANCZOS)
    w, h = img.size
    return img.tobytes("raw", "RGBA"), w, h
