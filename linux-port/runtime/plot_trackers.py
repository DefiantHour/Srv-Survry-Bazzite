#!/usr/bin/env python3
"""PlotTrackers + PlotTrackTarget — Linux port (journal / Status as far as possible).

Bookmarks come from CodexEntry organics with lat/long (Windows autoTrackCompBioScans)
plus any SurveyState.bookmarks already populated. Track target uses GameSettings
targetLat / targetLong when targetLatLongActive.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
from collections import defaultdict
from pathlib import Path

from companion import StatusSnapshot
from game_settings import GameSettings
from geo import draw_bearing_to, get_bearing, get_distance, meters_to_string, relative_bearing
from journal import CommanderLocation, SurveyState, TrackerBookmark

ORANGE = (255, 111, 0, 255)
ORANGE_DIM = (95, 48, 3, 255)
CYAN = (84, 223, 237, 255)
CYAN_DARK = (40, 120, 130, 255)
STRIPE = (12, 12, 12, 255)
BLACK = (0, 0, 0, 255)

TITLE_PX = 9
BODY_PX = 10
PAD = 8
DEFAULT_WIDTH = 380
TRACK_TARGET_SIZE = (128, 108)
HIGHLIGHT_DISTANCE = 150

_HEADER = "Tracking {0} targets:"
_BEARING = "Bearing: {0}"
_DISTANCE = "Distance: {0}"


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


def _finish(img):
    from PIL import Image

    if SCALE != 1:
        w, h = img.size
        img = img.resize((w // AA, h // AA), Image.Resampling.LANCZOS)
    w, h = img.size
    return img.tobytes("raw", "RGBA"), w, h


def _active_genus(survey: SurveyState) -> str | None:
    for row in survey.organic_progress:
        if row.scan_type in ("Log", "Sample") and row.genus:
            return row.genus
    return None


def bookmarks_for_body(
    survey: SurveyState,
    body_name: str | None,
    *,
    skip_quick: bool = False,
) -> dict[str, list[tuple[float, float]]]:
    """Group TrackerBookmark rows for the current body."""
    grouped: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for bm in survey.bookmarks:
        if body_name and bm.body_name and bm.body_name != body_name:
            continue
        if skip_quick and bm.name[:1] == "#":
            continue
        grouped[bm.name].append((bm.latitude, bm.longitude))
    return dict(grouped)


def trackers_allowed(
    game: GameSettings,
    status: StatusSnapshot | None,
    survey: SurveyState,
    location: CommanderLocation,
) -> bool:
    """Match PlotTrackers.allowed without PlotGrounded (journal-limited)."""
    if status is None or not status.has_lat_long:
        return False
    if status.docked:
        return False
    if status.altitude is not None and status.altitude >= 10_000:
        return False
    body = location.body or status.body_name
    marks = bookmarks_for_body(
        survey,
        body,
        skip_quick=bool(game.autoShowPlotMiniTrack),
    )
    return len(marks) > 0


def track_target_allowed(
    game: GameSettings,
    status: StatusSnapshot | None,
    survey: SurveyState,
) -> bool:
    """Match PlotTrackTarget.allowed."""
    if not game.targetLatLongActive:
        return False
    if status is None or not status.has_lat_long:
        return False
    if status.in_taxi:
        return False
    if survey.system is None and status.body_name is None:
        return False
    return True


def render_trackers_bitmap(
    survey: SurveyState,
    location: CommanderLocation,
    status: StatusSnapshot | None,
    *,
    game: GameSettings | None = None,
    force_show: bool = False,
    max_width: int = DEFAULT_WIDTH,
) -> tuple[bytes, int, int] | None:
    """Draw PlotTrackers bookmark list with bearings."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    if not force_show and not trackers_allowed(gs, status, survey, location):
        return None
    if status is None or not status.has_lat_long:
        return None
    body = location.body or status.body_name
    marks = bookmarks_for_body(
        survey,
        body,
        skip_quick=bool(gs.autoShowPlotMiniTrack),
    )
    if not marks and not force_show:
        return None

    radius = float(status.planet_radius or 0.0)
    here_lat = float(status.latitude or 0.0)
    here_lon = float(status.longitude or 0.0)
    heading = float(status.heading or 0.0)
    active = _active_genus(survey)

    font_small = _font(TITLE_PX)
    font_body = _font(BODY_PX)
    width = min(_s(DEFAULT_WIDTH), _s(max_width))
    row_h = _s(18)
    height = _s(12) + row_h + len(marks) * row_h + _s(12)

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height)

    y = _s(10)
    draw.text(
        (_s(PAD), y),
        _HEADER.format(len(marks)),
        font=font_small,
        fill=ORANGE,
    )
    y += row_h + _s(4)

    # Measure name column
    names = list(marks.keys())
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    max_name = max((_tw(probe, n, font_body) for n in names), default=_s(40))
    indent = max(_s(60), max_name + _s(10))
    bearing_w = _s(75)

    for name, positions in marks.items():
        is_active = active is None or active == name or name in (active or "")
        # Distances
        deltas: list[tuple[float, float, float, float]] = []
        for lat, lon in positions:
            dist = get_distance(here_lat, here_lon, lat, lon, radius) if radius else 0.0
            bearing = get_bearing(here_lat, here_lon, lat, lon)
            deltas.append((dist, bearing, lat, lon))
        deltas.sort(key=lambda d: d[0])

        is_close = any(d[0] < HIGHLIGHT_DISTANCE for d in deltas)
        name_col = ORANGE if is_active else ORANGE_DIM
        if is_close:
            name_col = CYAN if is_active else CYAN_DARK

        x = indent + _s(8)
        for dist, bearing, _lat, _lon in deltas:
            if x > width - bearing_w + _s(10):
                break
            close = dist < HIGHLIGHT_DISTANCE
            col = (CYAN if is_active else CYAN_DARK) if close else (
                ORANGE if is_active else ORANGE_DIM
            )
            deg = relative_bearing(bearing, heading)
            draw_bearing_to(
                draw,
                x,
                y + _s(2),
                _s(5),
                deg,
                outline=col,
                msg=meters_to_string(dist),
                font=font_small,
                msg_fill=col,
            )
            x += bearing_w

        # Name right-aligned into indent
        tw = _tw(draw, name, font_body)
        draw.text((indent - tw, y), name, font=font_body, fill=name_col)
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


def render_track_target_bitmap(
    survey: SurveyState,
    status: StatusSnapshot | None,
    *,
    game: GameSettings | None = None,
    force_show: bool = False,
) -> tuple[bytes, int, int] | None:
    """Draw PlotTrackTarget compass (fixed size)."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    if not force_show and not track_target_allowed(gs, status, survey):
        return None
    if status is None or not status.has_lat_long:
        return None

    t_lat = float(gs.targetLat)
    t_lon = float(gs.targetLong)
    radius = float(status.planet_radius or 0.0)
    here_lat = float(status.latitude or 0.0)
    here_lon = float(status.longitude or 0.0)
    dist = get_distance(here_lat, here_lon, t_lat, t_lon, radius) if radius else 0.0
    if status.altitude_from_average_radius and status.altitude is not None:
        dist += float(status.altitude)
    bearing = get_bearing(here_lat, here_lon, t_lat, t_lon)
    heading = float(status.heading or 0.0)
    rel = relative_bearing(bearing, heading)

    font_small = _font(TITLE_PX)
    width, height = _s(TRACK_TARGET_SIZE[0]), _s(TRACK_TARGET_SIZE[1])
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height)

    dist_txt = _DISTANCE.format(meters_to_string(dist))
    bearing_txt = _BEARING.format(f"{bearing:.0f}")
    draw.text((_s(4), _s(10)), dist_txt, font=font_small, fill=ORANGE)
    # Angle-of-attack stand-in: large bearing dial
    draw_bearing_to(
        draw,
        _s(40),
        _s(36),
        _s(18),
        rel,
        outline=CYAN,
        fill=CYAN_DARK,
    )
    ty = height - _s(18)
    draw.text((_s(4), ty), bearing_txt, font=font_small, fill=ORANGE)
    return _finish(img)


def render_trackers_panel_bitmap(
    survey: SurveyState,
    location: CommanderLocation,
    status: StatusSnapshot | None,
    *,
    game: GameSettings | None = None,
    force_show: bool = False,
) -> tuple[bytes, int, int] | None:
    """Panel ``trackers``: bookmark list and/or track-target compass."""
    gs = game if game is not None else GameSettings()
    trackers = render_trackers_bitmap(
        survey, location, status, game=gs, force_show=force_show
    )
    target = render_track_target_bitmap(
        survey, status, game=gs, force_show=force_show
    )
    if trackers is None and target is None:
        return None
    if trackers is None:
        return target
    if target is None:
        return trackers
    # Stack target under trackers
    from PIL import Image

    t_rgba, tw, th = trackers
    g_rgba, gw, gh = target
    t_img = Image.frombytes("RGBA", (tw, th), t_rgba)
    g_img = Image.frombytes("RGBA", (gw, gh), g_rgba)
    gap = 6
    width = max(tw, gw)
    height = th + gap + gh
    out = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    out.paste(t_img, (width - tw, 0))
    out.paste(g_img, (width - gw, th + gap))
    return out.tobytes("raw", "RGBA"), width, height


def _quick_tracker_keys(survey: SurveyState, body_name: str | None) -> list[str]:
    marks = bookmarks_for_body(survey, body_name, skip_quick=False)
    return sorted(k for k in marks if k[:1] == "#")


def mini_track_in_rhino(game: GameSettings, survey: SurveyState, status: StatusSnapshot | None) -> bool:
    if not game.autoShowPlotMiniTrackRhino:
        return False
    if status is None or not status.in_srv:
        return False
    srv = (survey.srv_type or "").lower()
    return "rhino" in srv or srv == "mev_rhino"


def mini_track_allowed(
    game: GameSettings,
    survey: SurveyState,
    location: CommanderLocation,
    status: StatusSnapshot | None,
    *,
    force_show: bool = False,
) -> bool:
    """Match PlotMiniTrack.allowed (journal-limited)."""
    if force_show:
        return True
    if not (game.autoShowPlotMiniTrack or game.autoShowPlotMiniTrackRhino):
        return False
    if status is None or not status.has_lat_long:
        return False
    body = location.body or status.body_name
    quick = _quick_tracker_keys(survey, body)
    in_rhino = mini_track_in_rhino(game, survey, status)
    if not quick and not in_rhino:
        return False
    # Modes: SuperCruising, Flying, Landed, InSrv, OnFoot, Glide, InFighter, Comms, Role
    if status.supercruise or status.glide_mode or status.landed:
        return True
    if status.in_srv or status.on_foot or status.in_fighter:
        return True
    if status.gui_focus in (2, 4):  # External / Role panel stand-ins
        return True
    if status.docked:
        return False
    return bool(status.in_main_ship)


def render_mini_track_bitmap(
    survey: SurveyState,
    location: CommanderLocation,
    status: StatusSnapshot | None,
    cargo: object | None = None,
    *,
    game: GameSettings | None = None,
    force_show: bool = False,
) -> tuple[bytes, int, int] | None:
    """Draw PlotMiniTrack quick-bookmark bearings (+ Rhino cargo bar)."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    if not mini_track_allowed(gs, survey, location, status, force_show=force_show):
        return None
    if status is None or not status.has_lat_long:
        return None

    body = location.body or status.body_name
    marks = bookmarks_for_body(survey, body, skip_quick=False)
    in_rhino = mini_track_in_rhino(gs, survey, status)
    keys = (
        ["#1", "#2", "#3", "#4", "#5", "#6"]
        if in_rhino
        else _quick_tracker_keys(survey, body)
    )
    if force_show and not keys:
        keys = ["#1"]
    if not keys:
        return None

    radius = float(status.planet_radius or 0.0)
    here_lat = float(status.latitude or 0.0)
    here_lon = float(status.longitude or 0.0)
    heading = float(status.heading or 0.0)

    font = _font(TITLE_PX)
    block = _s(52)
    width = max(_s(240), block * len(keys) + _s(16))
    height = _s(80 if not in_rhino else 100)

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height)

    x = _s(8)
    for key in keys:
        draw.text((x, _s(10)), key, font=font, fill=ORANGE if key in marks else ORANGE_DIM)
        positions = marks.get(key) or []
        if in_rhino and not positions:
            # Empty Rhino slot
            draw.ellipse(
                (x + _s(12), _s(28), x + _s(32), _s(48)),
                outline=ORANGE_DIM,
            )
            draw.text((x, _s(60)), "--", font=font, fill=ORANGE_DIM)
        elif positions:
            lat, lon = positions[0]
            dist = (
                get_distance(here_lat, here_lon, lat, lon, radius) if radius else 0.0
            )
            bearing = get_bearing(here_lat, here_lon, lat, lon)
            deg = relative_bearing(bearing, heading)
            if deg < 0:
                deg += 360
            outline = ORANGE
            fill = ORANGE_DIM
            if in_rhino and dist < 5:
                outline = CYAN
                fill = CYAN_DARK
            elif in_rhino and dist < 78:
                outline = (220, 40, 40, 255)
                fill = (120, 20, 20, 255)
            draw_bearing_to(
                draw,
                x + _s(12),
                _s(28),
                _s(10),
                deg,
                outline=outline,
                fill=fill,
            )
            draw.text(
                (x, _s(60)),
                meters_to_string(dist),
                font=font,
                fill=outline,
            )
        x += block

    if in_rhino:
        used = 0
        if cargo is not None and hasattr(cargo, "count"):
            try:
                used = int(getattr(cargo, "count") or 0)
            except (TypeError, ValueError):
                used = 0
        y = _s(78)
        label = f"Cargo capacity: {used} of 72"
        draw.text((_s(10), y), label, font=font, fill=ORANGE)
        bar_x = _s(10) + _tw(draw, label, font) + _s(12)
        bar_w = max(_s(40), width - bar_x - _s(12))
        fill_w = int(bar_w * min(1.0, used / 72.0))
        draw.rectangle(
            (bar_x, y, bar_x + fill_w, y + _s(12)),
            fill=ORANGE_DIM,
        )
        draw.rectangle(
            (bar_x - 1, y - 1, bar_x + bar_w + 1, y + _s(12) + 1),
            outline=ORANGE,
        )

    return _finish(img)


# Re-export for tests / journal typing convenience
__all__ = [
    "HIGHLIGHT_DISTANCE",
    "TrackerBookmark",
    "bookmarks_for_body",
    "mini_track_allowed",
    "render_mini_track_bitmap",
    "render_track_target_bitmap",
    "render_trackers_bitmap",
    "render_trackers_panel_bitmap",
    "track_target_allowed",
    "trackers_allowed",
]
