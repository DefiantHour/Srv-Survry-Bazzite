"""Pillow renderer — 1-1 Linux port of PlotFSS (last-scan value panel).

Windows WatchFssPixelSettings (GDI screen grab) is best-effort on Linux:
when ``gs.watchFssPixel_TEST`` is on and an X11 grab is available (mss /
Pillow ImageGrab), ``fss_pixel_watch.try_grab_screen`` may succeed. Wayland
and missing grabbers fail soft — this panel stays journal-driven.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
from pathlib import Path

from companion import GUI_FOCUS_FSS, StatusSnapshot
from game_settings import GameSettings
from journal import FssBodyEntry, SurveyState

ORANGE = (255, 111, 0, 255)
CYAN = (84, 223, 237, 255)
STRIPE = (12, 12, 12, 255)

TITLE_PX = 10  # fontSmaller
BODY_PX = 12  # fontMiddle
PAD = 8
DEFAULT_WIDTH = 420
DEFAULT_HEIGHT = 100


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


def _background(draw, w: int, h: int) -> None:
    draw.rectangle((0, 0, w - 1, h - 1), fill=(0, 0, 0, 255))
    step = _s(3)
    for y in range(0, h, step):
        draw.line((0, y, w - 1, y), fill=STRIPE)
    for y, col in ((_s(3), (95, 48, 3, 255)), (_s(4), ORANGE), (_s(5), (95, 48, 3, 255))):
        draw.line((_s(2), y, w - _s(4), y), fill=col)
    for y, col in (
        (h - _s(5), (95, 48, 3, 255)),
        (h - _s(4), ORANGE),
        (h - _s(3), (95, 48, 3, 255)),
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


def fss_allowed(
    game: GameSettings,
    status: StatusSnapshot | None,
    survey: SurveyState,
    *,
    force_show: bool = False,
) -> bool:
    """Match PlotFSS.allowed (FSS GuiFocus only; no suppress-other-overlays)."""
    if not game.autoShowPlotFSS:
        return False
    if force_show:
        return True
    if not survey.system:
        return False
    gui = status.gui_focus if status is not None else None
    return gui == GUI_FOCUS_FSS


def _last_fss_body(survey: SurveyState) -> FssBodyEntry | None:
    """Newest non-asteroid / non-belt planetary scan (PlotFSS lastFssBody)."""
    for body in survey.fss_bodies:
        if body.body_type == "Asteroid":
            continue
        if "Belt Cluster" in body.body_name:
            continue
        if body.body_type == "Star":
            continue
        return body
    return None


def _body_display_name(body: FssBodyEntry) -> str:
    name = body.body_name
    if not body.was_discovered:
        name = f"* {name}"
    suffixes: list[str] = []
    if body.terraformable or (body.planet_class or "").startswith("Earth"):
        suffixes.append("(T)")
    if body.landable or body.body_type == "LandableBody":
        suffixes.append("(L)")
    if suffixes:
        name += "  " + " ".join(suffixes)
    return name


def maybe_pixel_watch(game: GameSettings) -> str | None:
    """Soft-try X11 grab when enabled; return status tag or None."""
    if not getattr(game, "watchFssPixel_TEST", False):
        return None
    try:
        from fss_pixel_watch import try_grab_screen

        result = try_grab_screen(game)
        if result.available:
            return f"pixel-watch:{result.mode}"
        return f"pixel-watch:off ({result.reason})"
    except Exception:  # noqa: BLE001
        return "pixel-watch:unavailable"


def render_fss_bitmap(
    survey: SurveyState,
    *,
    game: GameSettings | None = None,
    status: StatusSnapshot | None = None,
    force_show: bool = False,
) -> tuple[bytes, int, int] | None:
    """Render PlotFSS last-scan panel. Returns None when not allowed."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    if not fss_allowed(gs, status, survey, force_show=force_show):
        return None

    # Best-effort pixel watch; failures are ignored (journal path remains).
    maybe_pixel_watch(gs)

    body = _last_fss_body(survey)
    font_title = _font(TITLE_PX)
    font_body = _font(BODY_PX)

    w = _s(DEFAULT_WIDTH)
    h = _s(DEFAULT_HEIGHT)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, w, h)

    if body is None:
        header = "Last scan: (scan to populate)"
        draw.text((_s(4), _s(PAD)), header, font=font_title, fill=ORANGE)
        return _finish(img)

    col = ORANGE if body.was_discovered else CYAN
    header = f"Last scan: {_body_display_name(body)}"
    dist = f"{body.distance_from_arrival_ls:,.0f} LS"
    y = _s(PAD)
    draw.text((_s(4), y), header, font=font_title, fill=col)
    dist_w = _tw(draw, dist, font_title)
    draw.text((w - _s(8) - dist_w, y), dist, font=font_title, fill=col)
    y += _th(draw, header, font_title) + _s(4)

    label_est = "► Estimated value:"
    label_dss = "► With surface scan:"
    label_w = max(_tw(draw, label_est, font_body), _tw(draw, label_dss, font_body)) + _s(18)

    draw.text((_s(18), y), label_est, font=font_body, fill=ORANGE)
    draw.text((_s(18) + label_w, y), f"{body.reward:,} cr", font=font_body, fill=ORANGE)
    y += _th(draw, label_est, font_body) + _s(2)

    draw.text((_s(18), y), label_dss, font=font_body, fill=ORANGE)
    draw.text(
        (_s(18) + label_w, y),
        f"{body.dss_reward:,} cr",
        font=font_body,
        fill=ORANGE,
    )
    y += _th(draw, label_dss, font_body) + _s(2)

    if body.bio_signal_count > 0:
        notes = f"► {body.bio_signal_count} bio signals:"
        draw.text((_s(18), y), notes, font=font_body, fill=CYAN)

    return _finish(img)
