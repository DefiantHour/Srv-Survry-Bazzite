#!/usr/bin/env python3
"""PlotMassacre — Linux port of SrvSurvey/plotters/PlotMassacre.cs."""

from __future__ import annotations

from hud_scale import AA, SCALE
from pathlib import Path

from companion import (
    GUI_FOCUS_EXTERNAL_PANEL,
    StatusSnapshot,
)
from game_settings import GameSettings
from journal import SurveyState, TrackMassacre

ORANGE = (255, 111, 0, 255)
ORANGE_DIM = (95, 48, 3, 255)
CYAN = (84, 223, 237, 255)
DARK_CYAN = (40, 120, 130, 255)
STRIPE = (12, 12, 12, 255)
BLACK = (0, 0, 0, 255)

TITLE_PX = 8
BODY_PX = 8
GIVER_PX = 7
COUNT_PX = 16
PAD = 8
DEFAULT_WIDTH = 180

_HEADER = "Massacre kills remaining:"


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


def massacre_mode_ok(status: StatusSnapshot | None) -> bool:
    """Match Flying / ExternalPanel / SuperCruising / StationServices."""
    if status is None:
        return False
    if status.supercruise:
        return True
    if status.gui_focus == GUI_FOCUS_EXTERNAL_PANEL:
        return True
    if status.docked:
        return True  # StationServices stand-in
    if status.on_foot or status.in_srv or status.in_fighter or status.landed:
        return False
    return bool(status.in_main_ship)


def massacre_allowed(
    game: GameSettings,
    survey: SurveyState,
    status: StatusSnapshot | None,
    *,
    force_show: bool = False,
) -> bool:
    """Match PlotMassacre.allowed (minus buildProjects suppress)."""
    if force_show:
        return True
    if not game.autoShowPlotMassacre_TEST:
        return False
    if game.buildProjectsSuppressOtherOverlays:
        return False
    if not survey.track_massacres:
        return False
    return massacre_mode_ok(status)


def _sorted_massacres(rows: tuple[TrackMassacre, ...]) -> list[TrackMassacre]:
    return sorted(rows, key=lambda m: f"{m.target_faction}{m.mission_giver}")


def render_massacre_bitmap(
    survey: SurveyState,
    status: StatusSnapshot | None = None,
    *,
    game: GameSettings | None = None,
    force_show: bool = False,
) -> tuple[bytes, int, int] | None:
    """Draw PlotMassacre. Returns None when not allowed."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    rows = _sorted_massacres(survey.track_massacres)
    if force_show and not rows:
        rows = [
            TrackMassacre(
                mission_id=1,
                mission_giver="Demo Giver",
                target_faction="Demo Target",
                kill_count=10,
                remaining=7,
            )
        ]
    if not massacre_allowed(gs, survey, status, force_show=force_show):
        return None
    if not rows:
        return None

    font_header = _font(TITLE_PX)
    font_body = _font(BODY_PX, bold=True)
    font_giver = _font(GIVER_PX)
    font_count = _font(COUNT_PX, bold=True)

    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    content_w = _tw(probe, _HEADER, font_header)
    for m in rows:
        content_w = max(
            content_w,
            _tw(probe, f"► {m.target_faction}:", font_body)
            + _s(40)
            + _tw(probe, str(m.remaining or 0), font_count),
        )
        content_w = max(content_w, _tw(probe, m.mission_giver, font_giver) + _s(50))
    width = max(_s(DEFAULT_WIDTH), content_w + _s(PAD * 2))
    row_h = _s(28)
    height = _s(12) + _s(16) + len(rows) * row_h + _s(12)

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height)

    y = _s(10)
    draw.text((_s(PAD), y), _HEADER, font=font_header, fill=ORANGE)
    y += _s(16)

    for m in rows:
        done = m.remaining == 0
        col = ORANGE if done else CYAN
        giver_col = ORANGE_DIM if done else DARK_CYAN
        label = f"► {m.target_faction}:"
        draw.text((_s(PAD), y), label, font=font_body, fill=col)
        if done:
            tw = _tw(draw, label, font_body)
            mid = y + _s(6)
            draw.line(
                (_s(PAD), mid, _s(PAD) + tw, mid),
                fill=col,
                width=max(1, SCALE),
            )
        count_txt = "0" if done else str(m.remaining)
        cw = _tw(draw, count_txt, font_count)
        draw.text((width - _s(PAD) - cw, y - _s(2)), count_txt, font=font_count, fill=col)
        draw.text((_s(PAD + 12), y + _s(12)), m.mission_giver, font=font_giver, fill=giver_col)
        y += row_h

    used = min(height, y + _s(8))
    if used < height:
        img = img.crop((0, 0, width, used))
        height = used
        draw = ImageDraw.Draw(img)
        for yy, col in (
            (height - _s(5), ORANGE_DIM),
            (height - _s(4), ORANGE),
            (height - _s(3), ORANGE_DIM),
        ):
            draw.line((_s(2), yy, width - _s(4), yy), fill=col)
        draw.rectangle(
            (0, 0, width - 1, height - 1),
            outline=ORANGE,
            width=max(1, SCALE // 2),
        )
    return _finish(img)
