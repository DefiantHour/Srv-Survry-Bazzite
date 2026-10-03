#!/usr/bin/env python3
"""PlotFootCombat — Linux port of SrvSurvey/plotters/PlotFootCombat.cs."""

from __future__ import annotations

from hud_scale import AA, SCALE
from pathlib import Path

from companion import StatusSnapshot
from game_settings import GameSettings
from journal import SurveyState

ORANGE = (255, 111, 0, 255)
ORANGE_DIM = (95, 48, 3, 255)
CYAN = (84, 223, 237, 255)
STRIPE = (12, 12, 12, 255)
BLACK = (0, 0, 0, 255)

BODY_PX = 8
PAD = 8
DEFAULT_WIDTH = 180


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


def _finish(img):
    from PIL import Image

    if SCALE != 1:
        w, h = img.size
        img = img.resize((w // AA, h // AA), Image.Resampling.LANCZOS)
    w, h = img.size
    return img.tobytes("raw", "RGBA"), w, h


def _background(draw, w: int, h: int) -> None:
    draw.rectangle((0, 0, w - 1, h - 1), fill=BLACK)
    step = _s(3)
    for y in range(0, h, step):
        draw.line((0, y, w - 1, y), fill=STRIPE)
    for y, col in ((_s(3), ORANGE_DIM), (_s(4), ORANGE), (_s(5), ORANGE_DIM)):
        draw.line((_s(2), y, w - _s(4), y), fill=col)
    for y, col in (
        (h - _s(5), ORANGE_DIM),
        (h - _s(4), ORANGE),
        (h - _s(3), ORANGE_DIM),
    ):
        draw.line((_s(2), y, w - _s(4), y), fill=col)
    draw.rectangle((0, 0, w - 1, h - 1), outline=ORANGE, width=max(1, SCALE // 2))


def foot_combat_allowed(
    game: GameSettings,
    survey: SurveyState,
    status: StatusSnapshot | None,
    *,
    force_show: bool = False,
) -> bool:
    """Match PlotFootCombat.allowed (minus buildProjects suppress)."""
    if force_show:
        return True
    if not game.autoShowFootCombat_TEST:
        return False
    if game.buildProjectsSuppressOtherOverlays:
        return False
    station = survey.system_station
    if station is None:
        return False
    if station.faction_state not in ("War", "CivilWar"):
        return False
    if status is None:
        return False
    if status.altitude is not None and status.altitude >= 100:
        return False
    if not (status.on_foot or status.in_srv):
        return False
    return True


def render_foot_combat_bitmap(
    survey: SurveyState,
    status: StatusSnapshot | None = None,
    *,
    game: GameSettings | None = None,
    force_show: bool = False,
) -> tuple[bytes, int, int] | None:
    """Draw PlotFootCombat. Returns None when not allowed."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    if not foot_combat_allowed(gs, survey, status, force_show=force_show):
        return None

    station = survey.system_station
    name = station.name if station is not None else "Ground CZ"
    kills = survey.foot_combat_kills

    font = _font(BODY_PX)
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    lines = (
        "Ground Combat Zone:",
        name,
        f"Kills: {kills}",
    )
    content_w = max(_tw(probe, line, font) for line in lines)
    width = max(_s(DEFAULT_WIDTH), content_w + _s(PAD * 2))
    row_h = _s(14)
    height = _s(12) + len(lines) * row_h + _s(14)

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height)

    y = _s(10)
    draw.text((_s(PAD), y), lines[0], font=font, fill=ORANGE_DIM)
    y += row_h
    draw.text((_s(PAD), y), lines[1], font=font, fill=ORANGE)
    y += row_h + _s(4)
    draw.text((_s(PAD), y), lines[2], font=font, fill=CYAN)
    return _finish(img)
