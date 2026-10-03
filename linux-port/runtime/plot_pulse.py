#!/usr/bin/env python3
"""PlotPulse — journal-write pulse indicator (Windows timer + bitmap).

Intensity follows recency of journal writes (``last_journal_write_monotonic``)
with a short decay, matching Windows ``pulseTick`` countdown behaviour. A light
sine shimmer rides on top while the pulse is still warm.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
import math
import time
from pathlib import Path

from companion import GUI_FOCUS_GALAXY_MAP, GUI_FOCUS_SYSTEM_MAP, StatusSnapshot
from game_settings import GameSettings

ORANGE = (255, 111, 0, 255)
ORANGE_DIM = (95, 48, 3, 255)
BLACK = (0, 0, 0, 255)

SIZE = 32
# Windows: pulseTick=20 at 500ms → ~10s decay.
_PULSE_DECAY_SEC = 10.0
_SHIMMER_PERIOD = 1.4


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


def pulse_intensity(
    now: float | None = None,
    *,
    last_journal_write_monotonic: float | None = None,
) -> float:
    """Return 0..1 pulse level from journal-write recency (+ light shimmer)."""
    t = time.monotonic() if now is None else float(now)
    if last_journal_write_monotonic is None:
        # Idle: keep a faint breathing shimmer so the disc is not dead.
        wave = 0.5 * (1.0 + math.sin(2.0 * math.pi * t / _SHIMMER_PERIOD))
        return 0.15 + 0.15 * wave

    age = max(0.0, t - float(last_journal_write_monotonic))
    freshness = max(0.0, 1.0 - age / _PULSE_DECAY_SEC)
    # Map freshness → [0.25, 1.0]; add a small shimmer while still warm.
    base = 0.25 + 0.75 * freshness
    if freshness > 0.02:
        shimmer = 0.08 * math.sin(2.0 * math.pi * t / _SHIMMER_PERIOD)
        return max(0.0, min(1.0, base + shimmer * freshness))
    return 0.25


def _blend_orange(level: float) -> tuple[int, int, int, int]:
    level = max(0.0, min(1.0, level))
    r = int(ORANGE_DIM[0] + (ORANGE[0] - ORANGE_DIM[0]) * level)
    g = int(ORANGE_DIM[1] + (ORANGE[1] - ORANGE_DIM[1]) * level)
    b = int(ORANGE_DIM[2] + (ORANGE[2] - ORANGE_DIM[2]) * level)
    return (r, g, b, 255)


def pulse_allowed(
    game: GameSettings,
    status: StatusSnapshot | None,
    *,
    force_show: bool = False,
) -> bool:
    """Match PlotPulse.allowed, except while docked.

    Windows shows this plotter in a station (``hideJournalWriteTimer`` is
    false and the commander is not in the galaxy or system map). The live
    HUD leaves it unmapped while ``Docked`` so that window is not what keeps
    Mutter compositing the game. ``force_show`` still draws it.
    """
    if force_show:
        return True
    if game.hideJournalWriteTimer:
        return False
    if status is not None and status.docked:
        return False
    if status is not None and status.gui_focus in (
        GUI_FOCUS_GALAXY_MAP,
        GUI_FOCUS_SYSTEM_MAP,
    ):
        return False
    return True


def render_pulse_bitmap(
    status: StatusSnapshot | None = None,
    *,
    game: GameSettings | None = None,
    force_show: bool = False,
    now: float | None = None,
    last_journal_write_monotonic: float | None = None,
) -> tuple[bytes, int, int] | None:
    """Small pulsing indicator driven by journal-write recency."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    if not pulse_allowed(gs, status, force_show=force_show):
        return None

    level = pulse_intensity(
        now, last_journal_write_monotonic=last_journal_write_monotonic
    )
    fill = _blend_orange(level)

    width = height = _s(SIZE)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, width - 1, height - 1), fill=BLACK, outline=ORANGE)
    inset = _s(6)
    draw.ellipse(
        (inset, inset, width - inset, height - inset),
        outline=ORANGE,
        fill=fill,
    )
    # Windows-style bar height from freshness (pulseTick analogue).
    bar_h = max(1, int(round((_s(SIZE) - inset * 2) * level)))
    bar_x0 = _s(11)
    bar_x1 = _s(21)
    bar_y1 = height - inset
    bar_y0 = bar_y1 - bar_h
    draw.rectangle((bar_x0, bar_y0, bar_x1, bar_y1), fill=ORANGE)

    if SCALE != 1:
        img = img.resize((width // AA, height // AA), Image.Resampling.LANCZOS)
    w, h = img.size
    return img.tobytes("raw", "RGBA"), w, h
