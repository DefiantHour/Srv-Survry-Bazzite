#!/usr/bin/env python3
"""PlotSysStatus — 1-1 Linux port of SrvSurvey/plotters/PlotSysStatus.cs."""

from __future__ import annotations

from hud_scale import AA, SCALE
from pathlib import Path

from companion import (
    GUI_FOCUS_EXTERNAL_PANEL,
    GUI_FOCUS_FSS,
    GUI_FOCUS_ORRERY,
    GUI_FOCUS_SAA,
    GUI_FOCUS_SYSTEM_MAP,
    StatusSnapshot,
)
from journal import SurveyState
from game_settings import GameSettings
from theme import cyan as theme_cyan
from theme import orange as theme_orange
from theme import orange_dim as theme_orange_dim

# theme.json / GameColors.Defaults (overridable via GameSettings)
ORANGE = theme_orange()
ORANGE_DIM = theme_orange_dim()
CYAN = theme_cyan()
STRIPE = (12, 12, 12, 255)

TITLE_PX = 9
BODY_PX = 11


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


def _th(draw, text: str, font) -> int:
    b = draw.textbbox((0, 0), text, font=font)
    return int(b[3] - b[1])


def sys_status_allowed(
    game: GameSettings,
    survey: SurveyState,
    status: StatusSnapshot | None,
    *,
    force_show: bool = False,
) -> bool:
    """PlotSysStatus.allowed — not shown while docked or in station services."""
    if force_show:
        return True
    if not game.autoShowPlotSysStatus:
        return False
    if status is not None and status.in_taxi:
        return False
    if survey.system is None:
        return False
    honked = (
        survey.fss_progress is not None
        or survey.fss_complete
        or (survey.body_count or 0) > 0
    )
    # Windows: honked || game.canonnPoi != null. Cache only — no fetch here.
    if not honked and game.useExternalData and survey.system:
        from canonn import peek_cached_poi

        honked = peek_cached_poi(survey.system) is not None
    if not honked:
        return False
    if status is None:
        return False
    if status.supercruise:
        return True
    return status.gui_focus in (
        GUI_FOCUS_EXTERNAL_PANEL,
        GUI_FOCUS_SYSTEM_MAP,
        GUI_FOCUS_ORRERY,
        GUI_FOCUS_FSS,
        GUI_FOCUS_SAA,
    )


def render_sys_status_bitmap(
    survey: SurveyState,
    status: StatusSnapshot | None,
    *,
    show_bio_inline: bool = True,
    show_non_body: bool = False,
    max_width: int = 280,
    game: GameSettings | None = None,
    frame: bool = True,
) -> tuple[bytes, int, int]:
    """Draw PlotSysStatus. Strings match PlotSysStatus.resx English."""
    global ORANGE, ORANGE_DIM, CYAN
    saved = (ORANGE, ORANGE_DIM, CYAN)
    ORANGE = theme_orange(game)
    ORANGE_DIM = theme_orange_dim(game)
    CYAN = theme_cyan(game)
    try:
        return _render_sys_status_bitmap(
            survey,
            status,
            show_bio_inline=show_bio_inline,
            show_non_body=show_non_body,
            max_width=max_width,
            frame=frame,
        )
    finally:
        ORANGE, ORANGE_DIM, CYAN = saved


def _render_sys_status_bitmap(
    survey: SurveyState,
    status: StatusSnapshot | None,
    *,
    show_bio_inline: bool = True,
    show_non_body: bool = False,
    max_width: int = 280,
    frame: bool = True,
) -> tuple[bytes, int, int]:
    from PIL import Image, ImageDraw

    font_small = _font(TITLE_PX)
    font_body = _font(BODY_PX)
    font_bold = _font(BODY_PX, bold=True)

    destination = None
    if status is not None and status.destination:
        system = survey.system or ""
        destination = status.destination.replace(system, "").replace(" ", "")

    # Approximate getDssRemainingNames / bio remaining from SurveyState
    dss_remaining: list[str] = []
    bio_remaining: list[str] = []
    if survey.body_signals:
        for row in survey.body_signals:
            short = row.body_name
            if survey.system and short.startswith(survey.system):
                short = short[len(survey.system) :].strip() or short
            # Bodies still needing DSS: not mapped; we only know scanned/mapped counts
            # Use unscanned bio bodies as bio remaining names.
            if row.bio_count and short:
                bio_remaining.append(short)

    lines_prep: list[tuple] = []
    # Header
    lines_prep.append(("text", "DSS survey:", font_small, ORANGE))

    honked = survey.fss_progress is not None or survey.fss_complete or (survey.body_count or 0) > 0
    fss_complete = bool(survey.fss_complete)
    body_count = int(survey.body_count or 0)
    scanned = int(survey.scanned_count or 0)
    mapped = int(survey.mapped_count or 0)

    if not honked and survey.system:
        lines_prep.append(("text", "FSS not started", font_body, CYAN))
    elif not fss_complete and body_count:
        pct = int(round(100.0 / body_count * scanned)) if body_count else 0
        lines_prep.append(("text", f"FSS {pct}% complete", font_body, CYAN))

    dss_left = max(0, scanned - mapped) if scanned else 0
    if dss_left > 0:
        lines_prep.append(("dss", dss_left, dss_remaining[:12]))
    elif fss_complete and honked:
        lines_prep.append(("text", "None", font_body, ORANGE))

    if show_bio_inline and (survey.total_bio_signals or 0):
        lines_prep.append(
            ("bio", survey.total_bio_signals, bio_remaining[:12])
        )

    if show_non_body and (survey.non_body_count or 0):
        lines_prep.append(
            ("text", f"► {survey.non_body_count} non-body signals", font_small, ORANGE)
        )

    # Measure
    width = _s(170)
    for kind, *rest in lines_prep:
        if kind == "text":
            width = max(width, _s(6) + _measure(rest[0], rest[1]) + _s(12))
        elif kind in ("dss", "bio"):
            count, names = rest
            label = (
                f"DSS remaining: {count}" if kind == "dss" else f"Bio signals: {count}"
            )
            w = _s(6) + _measure(label, font_body)
            for name in names:
                w += _measure(name, font_body) + _s(4)
            width = max(width, w + _s(12))
    width = min(width, _s(max_width))

    text_h = max(_measure_height("Ag", font_small), _measure_height("Ag", font_body))
    row_h = max(_s(16), text_h + _s(4))
    height = _s(8) + len(lines_prep) * row_h + _s(10)
    # Extra height if body name chips wrap — keep single line for now
    img = Image.new("RGBA", (width, height), (0, 0, 0, 255 if frame else 0))
    draw = ImageDraw.Draw(img)
    if frame:
        for y, col in ((_s(3), ORANGE_DIM), (_s(4), ORANGE), (_s(5), ORANGE_DIM)):
            draw.line((_s(2), y, width - _s(4), y), fill=col)
        for y, col in (
            (height - _s(5), ORANGE_DIM),
            (height - _s(4), ORANGE),
            (height - _s(3), ORANGE_DIM),
        ):
            draw.line((_s(2), y, width - _s(4), y), fill=col)
        draw.rectangle((0, 0, width - 1, height - 1), outline=ORANGE)

    y = _s(8)
    for kind, *rest in lines_prep:
        x = _s(6)
        if kind == "text":
            text, font, color = rest
            draw.text((x, y), text, font=font, fill=color)
            y += row_h
            continue
        if kind == "dss":
            count, names = rest
            draw.text((x, y), f"{count}x bodies: ", font=font_body, fill=ORANGE)
            x += _tw(draw, f"{count}x bodies: ", font_body)
            for name in names:
                dest = destination or ""
                is_local = not dest or (name and dest and name[0] == dest[0])
                use_font = font_bold if dest == name else font_body
                use_color = CYAN if is_local else ORANGE
                draw.text((x, y), name, font=use_font, fill=use_color)
                x += _tw(draw, name, use_font) + _s(4)
            y += row_h
            continue
        if kind == "bio":
            count, names = rest
            draw.text((x, y), f"| {count}x Bio signals on: ", font=font_body, fill=ORANGE)
            x += _tw(draw, f"| {count}x Bio signals on: ", font_body)
            for name in names:
                dest = destination or ""
                is_local = not dest or (name and dest and name[0] == dest[0])
                use_font = font_bold if dest == name else font_body
                use_color = CYAN if is_local else ORANGE
                draw.text((x, y), name, font=use_font, fill=use_color)
                x += _tw(draw, name, use_font) + _s(4)
            y += row_h
            continue

    if SCALE != 1:
        img = img.resize((width // AA, height // AA), Image.Resampling.NEAREST)
    w, h = img.size
    return img.tobytes("raw", "RGBA"), w, h


def _measure(text: str, font) -> int:
    from PIL import Image, ImageDraw

    return _tw(ImageDraw.Draw(Image.new("RGBA", (4, 4))), text, font)


def _measure_height(text: str, font) -> int:
    from PIL import Image, ImageDraw

    box = ImageDraw.Draw(Image.new("RGBA", (4, 4))).textbbox((0, 0), text, font=font)
    return int(box[3] - box[1])
