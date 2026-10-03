"""Pillow renderer — 1-1 Linux port of PlotGuardianSystem.

Faithful to PlotGuardianSystem.cs + GameColors (orange / cyan / gothic stand-in).
Renders at 2× then LANCZOS-downscales so AA approximates GDI ClearType.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
from pathlib import Path

from companion import StatusSnapshot
from game_settings import GameSettings
from journal import GuardianSiteSummary, SurveyState

# GameColors defaults
ORANGE = (255, 111, 0, 255)
ORANGE_DIM = (95, 48, 3, 255)
CYAN = (84, 223, 237, 255)
STRIPE = (12, 12, 12, 255)

# GuiFocus matching GameMode for PlotGuardianSystem.allowed
_GUI_EXTERNAL_PANEL = 2
_GUI_SYSTEM_MAP = 7
_GUI_ORRERY = 8

TITLE_PX = 9  # fontSmall
BODY_PX = 11  # fontMiddle
PAD = 8
ROW = 14
DEFAULT_WIDTH = 300


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


def _background(draw, w: int, h: int) -> None:
    draw.rectangle((0, 0, w - 1, h - 1), fill=(0, 0, 0, 255))
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


def _finish(img):
    from PIL import Image

    if SCALE != 1:
        w, h = img.size
        img = img.resize((w // AA, h // AA), Image.Resampling.LANCZOS)
    w, h = img.size
    return img.tobytes("raw", "RGBA"), w, h


def guardian_sites_for_display(survey: SurveyState) -> list[GuardianSiteSummary]:
    """Prefer approached Guardian sites; fall back to FSS guardian signals."""
    if survey.guardian_sites:
        return list(survey.guardian_sites)
    return [
        GuardianSiteSummary(name=sig, display_text=sig)
        for sig in survey.guardian_signals
    ]


def guardian_system_allowed(
    game: GameSettings,
    survey: SurveyState,
    status: StatusSnapshot | None,
) -> bool:
    """Match PlotGuardianSystem.allowed (minus Canonn-only settlement source)."""
    if not game.autoShowGuardianSummary:
        return False
    if game.buildProjectsSuppressOtherOverlays:
        return False
    if not game.enableGuardianSites:
        return False
    sites = guardian_sites_for_display(survey)
    if not sites:
        return False
    if status is None:
        return False
    if status.supercruise:
        return True
    gui = status.gui_focus
    return gui in (_GUI_EXTERNAL_PANEL, _GUI_SYSTEM_MAP, _GUI_ORRERY)


def guardian_system_lines(
    survey: SurveyState,
    status: StatusSnapshot | None = None,
) -> list[tuple[str, tuple[int, int, int, int], int]]:
    """Pure layout rows: (text, colour, indent_px). Unit-testable."""
    sites = guardian_sites_for_display(survey)
    rows: list[tuple[str, tuple[int, int, int, int], int]] = []
    rows.append((f"Guardian sites: {len(sites)}", ORANGE, 0))
    dest_body = status.destination_body if status is not None else None
    dest_name = status.destination if status is not None else None
    for site in sites:
        highlight = (
            dest_body is not None
            and site.body_id is not None
            and dest_body == site.body_id
        )
        if (
            highlight
            and isinstance(dest_name, str)
            and dest_name.startswith("$Ancient")
            and dest_name != site.name
        ):
            highlight = False
        col = CYAN if highlight else ORANGE
        rows.append((site.display_text, col, 8))
        if site.blue_print:
            rows.append((f"► Blue print: {site.blue_print}", col, 20))
        if site.status:
            rows.append((f"► Survey: {site.status}", col, 20))
        if site.extra:
            rows.append((f"► {site.extra}", col, 20))
    return rows


def render_guardian_system_bitmap(
    survey: SurveyState,
    *,
    game: GameSettings | None = None,
    status: StatusSnapshot | None = None,
    force_show: bool = False,
    max_width: int = DEFAULT_WIDTH,
) -> tuple[bytes, int, int] | None:
    """Render PlotGuardianSystem. Returns None when not allowed / nothing to show."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    if not force_show and not guardian_system_allowed(gs, survey, status):
        return None

    sites = guardian_sites_for_display(survey)
    if not sites and not force_show:
        return None

    font_small = _font(TITLE_PX)
    font_body = _font(BODY_PX)
    rows = guardian_system_lines(survey, status)

    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    content_w = max((_tw(probe, t, font_body) + _s(indent + 12) for t, _, indent in rows), default=_s(120))
    width = max(_s(170), min(_s(max_width), content_w))

    height = _s(10) + len(rows) * _s(ROW) + _s(12)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height)

    y = _s(10)
    for text, colour, indent in rows:
        font = font_small if indent == 0 or indent >= 20 else font_body
        draw.text((_s(PAD + indent), y), text, font=font, fill=colour)
        y += _s(ROW)

    used = min(height, y + _s(10))
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
            (0, 0, width - 1, height - 1), outline=ORANGE, width=max(1, SCALE // 2)
        )

    return _finish(img)
