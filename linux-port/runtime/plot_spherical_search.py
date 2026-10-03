"""Pillow renderer — Linux port of PlotSphericalSearch (distance / boxel slice).

Shows sphere distance from gs.sphereLimit* and/or boxel search status from
gs.boxelSearch* strings. COPY_NEXT_BOXEL copies the next system via boxel_search.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
import math
from pathlib import Path

from boxel_search import boxel_current, boxel_prefix, next_boxel_system
from companion import StatusSnapshot
from game_settings import GameSettings
from journal import SurveyState

ORANGE = (255, 111, 0, 255)
ORANGE_DIM = (95, 48, 3, 255)
CYAN = (84, 223, 237, 255)
RED = (220, 40, 40, 255)
STRIPE = (12, 12, 12, 255)

# GuiFocus.GalaxyMap
_GUI_GAL_MAP = 6

TITLE_PX = 10
BODY_PX = 11
PAD = 8
DEFAULT_WIDTH = 240


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


def _dist(
    a: tuple[float, float, float], b: tuple[float, float, float]
) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


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


def sphere_center(game: GameSettings) -> tuple[float, float, float] | None:
    if not game.sphereLimitActive:
        return None
    return (
        float(game.sphereLimitX),
        float(game.sphereLimitY),
        float(game.sphereLimitZ),
    )


def spherical_search_allowed(
    game: GameSettings,
    status: StatusSnapshot | None,
    *,
    force_show: bool = False,
) -> bool:
    if force_show:
        return True
    if not game.sphereLimitActive and not game.boxelSearchActive:
        return False
    gui = status.gui_focus if status is not None else None
    return gui == _GUI_GAL_MAP


def _append_boxel_lines(
    lines: list[tuple[str, tuple[int, int, int, int]]],
    gs: GameSettings,
) -> None:
    """Append boxel status / next-system lines per notification toggles."""
    prefix = boxel_prefix(gs)
    current = boxel_current(gs)
    next_sys = next_boxel_system(gs)

    if gs.currentBoxelSearchStatus:
        if prefix:
            lines.append((f"Boxel: {prefix} …", ORANGE))
        else:
            lines.append(("Boxel search active", ORANGE))
        if current and prefix and current != prefix:
            lines.append((f"Current: {current} …", ORANGE_DIM))
    elif not gs.showNextBoxelToSearch:
        lines.append(("Boxel search active", ORANGE))

    if gs.showNextBoxelToSearch:
        if next_sys:
            hint = " ?" if next_sys in {prefix, current} else ""
            lines.append((f"Next: {next_sys}{hint}", CYAN))
        else:
            lines.append(("Next: (set gs.boxelSearchNextSystem)", ORANGE_DIM))


def render_spherical_search_bitmap(
    survey: SurveyState,
    *,
    status: StatusSnapshot | None = None,
    nav_route=None,
    game: GameSettings | None = None,
    force_show: bool = False,
) -> tuple[bytes, int, int] | None:
    """Render PlotSphericalSearch distance / boxel panel."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    if not spherical_search_allowed(gs, status, force_show=force_show):
        return None

    center = sphere_center(gs)
    here = survey.star_pos
    dest_name = None
    dest_pos = None
    if nav_route is not None and getattr(nav_route, "hops", None):
        hops = list(nav_route.hops)
        if hops:
            last = hops[-1]
            dest_name = getattr(last, "system", None) or getattr(last, "name", None)
            pos = getattr(last, "star_pos", None) or getattr(last, "pos", None)
            if isinstance(pos, (list, tuple)) and len(pos) == 3:
                dest_pos = (float(pos[0]), float(pos[1]), float(pos[2]))

    font_title = _font(TITLE_PX, bold=True)
    font_body = _font(BODY_PX)
    lines: list[tuple[str, tuple[int, int, int, int]]] = []

    if gs.sphereLimitActive and center is not None:
        radius = float(gs.sphereLimitRadiusLy)
        lines.append((f"Sphere ≤ {radius:g} ly", ORANGE))
        if here is not None:
            d_here = _dist(center, here)
            over = d_here > radius
            lines.append(
                (
                    f"Here: {d_here:,.1f} ly",
                    RED if over else CYAN,
                )
            )
        if dest_name:
            if dest_pos is not None:
                d_dest = _dist(center, dest_pos)
                over = d_dest > radius
                lines.append(
                    (
                        f"→ {dest_name}: {d_dest:,.1f} ly",
                        RED if over else ORANGE,
                    )
                )
            else:
                lines.append((f"→ {dest_name}", ORANGE_DIM))
        elif here is None:
            lines.append(("(no star pos yet)", ORANGE_DIM))
        if gs.boxelSearchActive:
            _append_boxel_lines(lines, gs)
    elif gs.boxelSearchActive:
        _append_boxel_lines(lines, gs)
    else:
        lines.append(("Spherical search", ORANGE))
        lines.append(("Set gs.sphereLimitActive", ORANGE_DIM))

    if not lines:
        lines.append(("Spherical search", ORANGE))

    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    width = max(
        _s(DEFAULT_WIDTH),
        max(_tw(probe, t, font_body) for t, _ in lines) + _s(PAD * 2),
    )
    height = _s(PAD) + len(lines) * _s(16) + _s(PAD)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height)
    y = _s(PAD)
    for i, (text, colour) in enumerate(lines):
        font = font_title if i == 0 else font_body
        draw.text((_s(PAD), y), text, font=font, fill=colour)
        y += _th(draw, text, font) + _s(4)
    return _finish(img)
