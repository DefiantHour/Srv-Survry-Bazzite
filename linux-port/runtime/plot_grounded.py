#!/usr/bin/env python3
"""PlotGrounded — circular surface radar (Linux port of PlotGrounded.cs).

Windows draws a zoomable heading-up radar with bio/bookmark dots. Linux plots
bookmarks + organic-linked marks relative to Status lat/long via haversine
offset (geo.offset_meters), range rings, and a ship/SRV glyph at centre.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
import math
from pathlib import Path

from companion import StatusSnapshot
from game_settings import GameSettings
from geo import meters_to_string, offset_meters
from journal import CommanderLocation, SurveyState, TrackerBookmark
from theme import cyan, orange, orange_dim

STRIPE = (12, 12, 12, 255)
BLACK = (0, 0, 0, 255)
RED = (255, 48, 0, 255)

TITLE_PX = 9
BODY_PX = 8
PAD = 8

# bioPlotSize → window (logical px), matching PlotGrounded.getWindowSize
_PLOT_SIZES = (
    (250, 400),
    (250, 500),
    (320, 440),
    (380, 500),
    (440, 600),
)

# Default map scale: pixels per meter (Windows starts at 0.25)
_DEFAULT_MAP_SCALE = 0.25
_DEFAULT_RADIUS_M = 1_800_000.0


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


def grounded_allowed(
    game: GameSettings,
    survey: SurveyState,
    status: StatusSnapshot | None,
    *,
    force_show: bool = False,
) -> bool:
    """Match PlotGrounded.allowed core gates (journal-limited)."""
    if force_show:
        return True
    if not game.autoShowBioPlot:
        return False
    if game.buildProjectsSuppressOtherOverlays:
        return False
    if status is None or not status.has_lat_long:
        return False
    if status.docked or status.in_taxi or status.fsd_charging_jump:
        return False
    if status.altitude is not None and status.altitude >= 10_000:
        return False
    has_marks = bool(survey.bookmarks) or bool(survey.organic_progress)
    if not has_marks:
        return False
    return True


def _window_size(game: GameSettings) -> tuple[int, int]:
    idx = int(getattr(game, "bioPlotSize", 2) or 2)
    idx = max(0, min(len(_PLOT_SIZES) - 1, idx))
    return _PLOT_SIZES[idx]


def _map_scale(game: GameSettings) -> float:
    """Pixels per meter; plotterScale nudges the default Windows 0.25."""
    base = _DEFAULT_MAP_SCALE
    bump = float(getattr(game, "plotterScale", 0.0) or 0.0)
    scale = base * (1.0 + 0.15 * bump)
    return max(0.05, min(2.0, scale))


def _fmt_coord(value: float | None, hemi_pos: str, hemi_neg: str) -> str:
    if value is None:
        return "—"
    hemi = hemi_pos if value >= 0 else hemi_neg
    return f"{abs(value):.3f}°{hemi}"


def _marks_for_body(
    survey: SurveyState, body_name: str | None
) -> list[TrackerBookmark]:
    marks: list[TrackerBookmark] = []
    for bm in survey.bookmarks:
        if body_name and bm.body_name:
            if bm.body_name != body_name and not (
                bm.body_name.endswith(body_name) or body_name.endswith(bm.body_name)
            ):
                continue
        marks.append(bm)
    return marks


def _organic_genus_set(survey: SurveyState, body_name: str | None) -> set[str]:
    out: set[str] = set()
    for prog in survey.organic_progress:
        if body_name and prog.body_name:
            if prog.body_name != body_name and not (
                prog.body_name.endswith(body_name)
                or body_name.endswith(prog.body_name)
            ):
                continue
        if prog.genus:
            out.add(prog.genus)
    return out


def _range_rings(radius_px: float, map_scale: float) -> list[float]:
    """Ring radii in meters that fit inside the radar circle."""
    max_m = radius_px / max(map_scale, 1e-6)
    candidates = (100.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0)
    rings = [r for r in candidates if r < max_m * 0.95]
    if not rings and max_m > 50:
        rings = [max_m * 0.5]
    return rings


def render_grounded_bitmap(
    survey: SurveyState,
    location: CommanderLocation | None = None,
    status: StatusSnapshot | None = None,
    *,
    game: GameSettings | None = None,
    force_show: bool = False,
) -> tuple[bytes, int, int] | None:
    """Circular surface radar — bookmarks + organic marks, heading-up when known."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    if not grounded_allowed(gs, survey, status, force_show=force_show):
        return None

    orange_c = orange(gs)
    orange_d = orange_dim(gs)
    cyan_c = cyan(gs)

    body = (location.body if location else None) or (
        status.body_name if status else None
    ) or "Surface"
    lat = status.latitude if status is not None else None
    lon = status.longitude if status is not None else None
    alt = status.altitude if status is not None else None
    heading = status.heading if status is not None else None
    radius_m = (
        float(status.planet_radius)
        if status is not None and status.planet_radius
        else _DEFAULT_RADIUS_M
    )

    logical_w, logical_h = _window_size(gs)
    width = _s(logical_w)
    height = _s(logical_h)
    map_scale = _map_scale(gs) * SCALE

    font_title = _font(TITLE_PX, bold=True)
    font_body = _font(BODY_PX)

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

    # Header strip
    y = _s(6)
    draw.text((_s(PAD), y), body, font=font_title, fill=orange_c)
    y += _s(14)
    coord = f"{_fmt_coord(lat, 'N', 'S')}  {_fmt_coord(lon, 'E', 'W')}"
    if alt is not None:
        coord += f"  ·  {alt:,.0f} m"
    mode = "HDG-UP" if heading is not None else "N-UP"
    hdr = f"{coord}  ·  {mode}"
    draw.text((_s(PAD), y), hdr, font=font_body, fill=cyan_c)
    y += _s(12)

    # Radar circle region
    footer_h = _s(28)
    radar_top = y + _s(4)
    radar_bottom = height - footer_h
    radar_h = max(_s(80), radar_bottom - radar_top)
    cx = width // 2
    cy = radar_top + radar_h // 2
    r_px = max(_s(40), min(width, radar_h) // 2 - _s(10))

    # Clip disk background
    draw.ellipse(
        (cx - r_px, cy - r_px, cx + r_px, cy + r_px),
        fill=(8, 8, 8, 255),
        outline=orange_d,
        width=max(1, SCALE // 2),
    )

    # Crosshairs (compass axes in current orientation)
    draw.line((cx - r_px, cy, cx + r_px, cy), fill=orange_d, width=1)
    draw.line((cx, cy - r_px, cx, cy + r_px), fill=orange_d, width=1)

    # Range rings
    for ring_m in _range_rings(float(r_px), map_scale):
        rr = int(round(ring_m * map_scale))
        if rr < 4 or rr > r_px - 2:
            continue
        draw.ellipse(
            (cx - rr, cy - rr, cx + rr, cy + rr),
            outline=orange_d,
            width=1,
        )
        label = meters_to_string(ring_m)
        draw.text(
            (cx + _s(2), cy - rr + _s(1)),
            label,
            font=font_body,
            fill=orange_d,
        )

    # North tick (absolute) when heading-up; else label N at top
    if heading is not None:
        # North direction relative to heading-up frame
        north_bearing = (-float(heading)) % 360.0
        nrad = math.radians(north_bearing)
        nx = cx + math.sin(nrad) * (r_px - _s(6))
        ny = cy - math.cos(nrad) * (r_px - _s(6))
        draw.text(
            (nx - _s(3), ny - _s(5)),
            "N",
            font=font_body,
            fill=cyan_c,
        )
    else:
        draw.text((cx - _s(3), cy - r_px + _s(2)), "N", font=font_body, fill=cyan_c)

    marks = _marks_for_body(survey, body if body != "Surface" else None)
    organic_names = _organic_genus_set(
        survey, body if body != "Surface" else None
    )

    plotted = 0
    if lat is not None and lon is not None:
        hdg = float(heading) if heading is not None else None
        for bm in marks:
            try:
                dx, dy = offset_meters(
                    lat,
                    lon,
                    bm.latitude,
                    bm.longitude,
                    radius_m,
                    heading=hdg,
                )
            except Exception:
                continue
            px = cx + int(round(dx * map_scale))
            py = cy - int(round(dy * map_scale))
            # Outside circle → clamp to rim
            dist_px = math.hypot(px - cx, py - cy)
            if dist_px > r_px - _s(4):
                if dist_px <= 0:
                    continue
                scale_rim = (r_px - _s(4)) / dist_px
                px = cx + int(round((px - cx) * scale_rim))
                py = cy + int(round((py - cy) * scale_rim))
            is_bio = bm.name in organic_names
            col = cyan_c if is_bio else orange_c
            dot = _s(4) if is_bio else _s(3)
            draw.ellipse(
                (px - dot, py - dot, px + dot, py + dot),
                fill=col,
                outline=orange_d,
            )
            plotted += 1

    # Commander / ship glyph at centre (triangle pointing up = ahead)
    tip = _s(8)
    base = _s(5)
    draw.polygon(
        [
            (cx, cy - tip),
            (cx - base, cy + base),
            (cx + base, cy + base),
        ],
        fill=orange_c,
        outline=cyan_c,
    )
    # SRV diamond when in SRV
    if status is not None and status.in_srv:
        d = _s(3)
        draw.polygon(
            [
                (cx, cy - tip - d * 2),
                (cx + d, cy - tip - d),
                (cx, cy - tip),
                (cx - d, cy - tip - d),
            ],
            fill=cyan_c,
        )

    # Footer counts
    n_bio = len(survey.organic_progress)
    n_marks = len(marks)
    foot = f"{n_marks} mark(s) · {n_bio} bio · {plotted} on radar"
    draw.text((_s(PAD), height - _s(22)), foot, font=font_body, fill=orange_d)

    if SCALE != 1:
        img = img.resize((width // AA, height // AA), Image.Resampling.LANCZOS)
    w, h = img.size
    return img.tobytes("raw", "RGBA"), w, h
