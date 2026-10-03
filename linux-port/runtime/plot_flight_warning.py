"""Pillow renderer — 1-1 Linux port of PlotFlightWarning.

Windows hatch brush (WideUpwardDiagonal red/black) approximated with
diagonal red stripes on a black panel. English string from PlotFlightWarning.resx.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
from pathlib import Path

from companion import StatusSnapshot
from game_settings import GameSettings
from journal import CommanderLocation, FssBodyEntry, SurveyState

# GameColors
ORANGE = (255, 111, 0, 255)
RED = (255, 40, 40, 255)
BLACK = (0, 0, 0, 255)
STRIPE_RED = (180, 20, 20, 255)

BODY_PX = 10  # fontSmall
PAD = 15
DEFAULT_WIDTH = 300

_WARN_FMT = "Warning: Surface gravity {0}g"


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


def _finish(img):
    from PIL import Image

    if SCALE != 1:
        w, h = img.size
        img = img.resize((w // AA, h // AA), Image.Resampling.LANCZOS)
    w, h = img.size
    return img.tobytes("raw", "RGBA"), w, h


def resolve_system_body(
    survey: SurveyState,
    location: CommanderLocation | None = None,
    status: StatusSnapshot | None = None,
) -> FssBodyEntry | None:
    """Current body for PlotFlightWarning / PlotBodyInfo (name match)."""
    name: str | None = None
    if status is not None and status.body_name:
        name = status.body_name
    elif location is not None and location.body:
        name = location.body
    if not name:
        return None
    for body in survey.fss_bodies:
        if body.body_name == name:
            return body
    return None


def flight_warning_mode_ok(status: StatusSnapshot | None) -> bool:
    """Match GameMode.Landed / SuperCruising / GlideMode / Flying / InFighter / InSrv."""
    if status is None:
        return False
    if status.landed or status.supercruise or status.glide_mode:
        return True
    if status.in_fighter or status.in_srv:
        return True
    if status.docked or status.on_foot:
        return False
    # Flying: main ship underway (not SC / landed / docked)
    return bool(status.in_main_ship)


def flight_warning_allowed(
    game: GameSettings,
    survey: SurveyState,
    *,
    location: CommanderLocation | None = None,
    status: StatusSnapshot | None = None,
    force_show: bool = False,
) -> bool:
    """Match PlotFlightWarning.allowed (minus buildProjects suppress)."""
    if force_show:
        return True
    if not game.autoShowFlightWarnings:
        return False
    body = resolve_system_body(survey, location, status)
    if body is None:
        return False
    if body.body_type != "LandableBody" and not body.landable:
        return False
    if body.surface_gravity <= 0:
        return False
    if body.surface_gravity < game.highGravityWarningLevel * 10:
        return False
    return flight_warning_mode_ok(status)


def warning_text(surface_gravity: float) -> str:
    """Windows: (surfaceGravity / 10).ToString(\"N2\") into SurfaceGravityWarning."""
    body_grav = f"{surface_gravity / 10.0:.2f}"
    return _WARN_FMT.format(body_grav)


def render_flight_warning_bitmap(
    survey: SurveyState,
    *,
    location: CommanderLocation | None = None,
    status: StatusSnapshot | None = None,
    game: GameSettings | None = None,
    force_show: bool = False,
) -> tuple[bytes, int, int] | None:
    """Render PlotFlightWarning. Returns None when not allowed."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    if not flight_warning_allowed(
        gs, survey, location=location, status=status, force_show=force_show
    ):
        return None
    body = resolve_system_body(survey, location, status)
    if body is None and force_show:
        # force_show with no body: still need a gravity value — refuse
        return None
    assert body is not None
    txt = warning_text(body.surface_gravity)

    font = _font(BODY_PX)
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    text_w = _tw(probe, txt, font)
    text_h = _th(probe, txt, font)
    pad = _s(PAD)
    width = max(_s(DEFAULT_WIDTH), text_w + pad + _s(10))
    height = text_h + pad * 2

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Outer hatch (approximate WideUpwardDiagonal red/black)
    draw.rectangle((0, 0, width - 1, height - 1), fill=BLACK)
    step = max(_s(6), 4)
    for offset in range(-height, width + height, step):
        draw.line(
            (offset, height - 1, offset + height, 0),
            fill=STRIPE_RED,
            width=max(1, SCALE // 2),
        )

    # Inner black rect (Windows Inflate -10)
    inset = _s(10)
    draw.rectangle(
        (inset, inset, width - 1 - inset, height - 1 - inset),
        fill=BLACK,
    )

    draw.text((_s(PAD + 1), _s(PAD + 1)), txt, font=font, fill=RED)
    return _finish(img)
