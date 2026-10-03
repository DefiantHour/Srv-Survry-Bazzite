#!/usr/bin/env python3
"""PlotHumanSite — 1-1 Linux port of SrvSurvey/plotters/PlotHumanSite.cs.

Approach / docking overlay (orange theme). When a settlement template matches
(economy + subtype or template name), draws a top-down pad/POI/building map
from ``humanSiteTemplates.json``. Heading from ``.settlement`` persists in
``cmdr_state`` (by marketId) and is applied when rendering.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
import math
from pathlib import Path

from companion import (
    GUI_FOCUS_EXTERNAL_PANEL,
    GUI_FOCUS_ROLE_PANEL,
    StatusSnapshot,
)
from game_settings import GameSettings
from human_site_templates import (
    HumanTemplate,
    get_template,
    pad_summary,
    templates_for_economy,
)
from journal import HumanStation, SurveyState
from theme import orange, orange_dim

# GameColors extras
ORANGE_MID = (160, 70, 0, 255)
LIME = (163, 255, 47, 255)
RED = (255, 60, 40, 255)
BLACK = (0, 0, 0, 255)
STRIPE = (12, 12, 12, 255)
FADE = (0, 0, 0, 180)
SADDLE = (139, 69, 19, 255)
PAD_COL = (255, 180, 60, 255)
POI_COL = (84, 223, 237, 255)
DOOR_COL = (200, 80, 80, 255)
TERM_COL = (163, 255, 47, 255)

TITLE_PX = 9
BODY_PX = 11
PAD = 8
ROW = 16
DEFAULT_WIDTH = 320

_ZOOM_AUTO = "Zoom: {0} (Auto)"
_UNKNOWN_TYPE_HEADING = "Unknown settlement type and heading"
_UNKNOWN_HEADING = "Unknown settlement heading"
_KNOWN_SETTLEMENT = "Known settlement"
_ON_APPROACH = "On approach"
_FACTION = "Faction"
_INFLUENCE = "Influence"
_YOUR_REP = "Your reputation: {0}"
_GOVERNMENT = "Government"
_HAS_INTERSTELLAR = "Interstellar Factors available"
_DOCKING_REQUESTED = "Docking requested"
_DOCKING_APPROVED = "Docking approved: pad #{0}"
_DOCKING_DENIED = "Docking denied"
_UNKNOWN = "Unknown"
_AUTO_DOCK_1 = "Auto dock in progress"
_AUTO_DOCK_2 = "Settlement auto-identification supported"
_AUTO_DOCK_3 = "Do not switch to external camera"
_MANUAL_DOCK_1 = "Manual docking in progress"
_MANUAL_DOCK_2 = "Settlement identification will be delayed"
_MANUAL_DOCK_3 = "Auto dock recommended"
_HELP_SHIP_1 = "Settlement will be identified after next action"
_HELP_SHIP_2 = "To manually identify"
_HELP_SHIP_3 = "Send '{0}' when docked"
_HELP_FOOT_0 = "To manually identify:"
_HELP_FOOT_1 = "1. Walk to the center of any landing pad and crouch"
_HELP_FOOT_2 = "2. Place your left foot over the the center grooves"
_HELP_FOOT_3 = "3. Face with the chevrons ahead to your left"
_HELP_FOOT_4 = "4. Aim at the end of the groove ahead of you"
_HELP_FOOT_5 = "5. Send message '{0}'"
_HELP_FOOT_6 = "See the wiki for more info"
_DENIED = {
    "Distance": "Too far away",
    "Hostile": "Hostile",
    "TooLarge": "Ship too large",
    "NoSpace": "No pads available",
    "Offenses": "Offenses",
    "ActiveFighter": "Fighter is active",
}
_DENIED_PREFIX = {
    "Distance": ">",
    "Hostile": "!",
    "TooLarge": "#",
    "NoSpace": "x",
    "Offenses": "*",
    "ActiveFighter": "^",
}

# Back-compat colour aliases used by tests / rows
ORANGE = (255, 111, 0, 255)
ORANGE_DIM = (95, 48, 3, 255)
CYAN = (84, 223, 237, 255)


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


def _measure(font, text: str) -> int:
    from PIL import Image, ImageDraw

    return _tw(ImageDraw.Draw(Image.new("RGBA", (4, 4))), text, font)


def _background(draw, w: int, h: int, col=None) -> None:
    col = col or orange()
    dim = orange_dim()
    draw.rectangle((0, 0, w - 1, h - 1), fill=BLACK)
    step = _s(3)
    for y in range(0, h, step):
        draw.line((0, y, w - 1, y), fill=STRIPE)
    for y, c in ((_s(3), dim), (_s(4), col), (_s(5), dim)):
        draw.line((_s(2), y, w - _s(4), y), fill=c)
    for y, c in (
        (h - _s(5), dim),
        (h - _s(4), col),
        (h - _s(3), dim),
    ):
        draw.line((_s(2), y, w - _s(4), y), fill=c)
    draw.rectangle((0, 0, w - 1, h - 1), outline=col, width=max(1, SCALE // 2))


def _finish(img):
    from PIL import Image

    if SCALE != 1:
        w, h = img.size
        img = img.resize((w // AA, h // AA), Image.Resampling.LANCZOS)
    w, h = img.size
    return img.tobytes("raw", "RGBA"), w, h


def meters_to_string(meters: float) -> str:
    """Match Util.metersToString (positive distance)."""
    m = abs(meters)
    if m < 1:
        return "0m"
    if m < 1000:
        return f"{m:.0f}m"
    km = m / 1000.0
    if km < 10:
        return f"{km:.2f}km"
    if km < 1000:
        return f"{km:.1f}km"
    return f"{km / 1000.0:.2f}Mm"


def surface_distance_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    radius_m: float,
) -> float:
    """Match Util.getDistance (spherical cosines on planet radius)."""
    if lat1 == lat2 and lon1 == lon2:
        return 0.0
    a1 = math.radians(lat1)
    a2 = math.radians(lat2)
    z = math.sin(a1) * math.sin(a2) + math.cos(a1) * math.cos(a2) * math.cos(
        math.radians(lon2 - lon1)
    )
    z = max(-1.0, min(1.0, z))
    return math.acos(z) * radius_m


def reputation_text(reputation: float) -> str:
    """Match Util.getReputationText."""
    if reputation <= -90:
        return "Hostile"
    if reputation <= -35:
        return "Unfriendly"
    if reputation <= 4:
        return "Neutral"
    if reputation <= 35:
        return "Cordial"
    if reputation <= 90:
        return "Friendly"
    return "Allied"


def economy_label(station: HumanStation) -> str:
    if station.economy_localized:
        return station.economy_localized
    eco = station.economy or ""
    if eco.startswith("$economy_") and eco.endswith(";"):
        return eco[len("$economy_") : -1]
    return eco or "?"


def resolve_template(station: HumanStation) -> HumanTemplate | None:
    """Match by template_name, else economy + sub_type."""
    return get_template(
        station.economy or station.economy_localized,
        station.sub_type,
        name=station.template_name,
    )


def want_site_map(
    station: HumanStation,
    status: StatusSnapshot | None,
) -> bool:
    """Show template map when settlement is identified or subtype set on foot."""
    tmpl = resolve_template(station)
    if tmpl is None:
        return False
    if station.heading >= 0:
        return True
    if station.sub_type > 0 and status is not None:
        if status.on_foot or status.in_srv or status.landed or status.docked:
            return True
    return False


def station_info_allowed(game: GameSettings, status: StatusSnapshot | None) -> bool:
    """Match PlotStationInfo.allowed — hides PlotHumanSite when true."""
    if not game.autoShowPlotStationInfo_TEST:
        return False
    return status is not None and status.gui_focus == GUI_FOCUS_EXTERNAL_PANEL


def human_site_mode_visible(status: StatusSnapshot | None) -> bool:
    """Inverse of PlotHumanSite.onStatusChange hidden modes."""
    if status is None:
        return False
    if status.on_foot or status.in_srv or status.in_taxi:
        return True
    if status.docked or status.landed or status.glide_mode:
        return True
    if status.gui_focus in (GUI_FOCUS_EXTERNAL_PANEL, GUI_FOCUS_ROLE_PANEL):
        return True
    if status.supercruise:
        return False
    if status.in_main_ship and not status.docked and not status.landed:
        return True
    return False


def human_site_allowed(
    game: GameSettings,
    status: StatusSnapshot | None,
    survey: SurveyState,
    *,
    force_show: bool = False,
) -> bool:
    """Match PlotHumanSite.allowed (+ mode visibility / station-info hide)."""
    if not game.autoShowHumanSitesTest:
        return False
    if game.buildProjectsSuppressOtherOverlays and not force_show:
        return False
    if force_show:
        return survey.system_station is not None
    if status is None or not status.has_lat_long:
        return False
    if survey.system_station is None:
        return False
    if station_info_allowed(game, status):
        return False
    return human_site_mode_visible(status)


def _zoom_for(game: GameSettings, status: StatusSnapshot | None) -> float:
    if status is None:
        return float(game.humanSiteZoomShip or 1.0)
    if status.on_foot:
        return float(game.humanSiteZoomFoot or 2.0)
    if status.in_srv:
        return float(game.humanSiteZoomSRV or 1.5)
    return float(game.humanSiteZoomShip or 1.0)


def _approach_rows(
    station: HumanStation,
    status: StatusSnapshot | None,
    *,
    scale_zoom: float = 1.0,
) -> list[tuple[str, tuple[int, int, int, int], bool]]:
    """Pure layout rows for unit tests: (text, colour, bold)."""
    rows: list[tuple[str, tuple[int, int, int, int], bool]] = []
    header = station.name
    if station.government == "$government_Anarchy;":
        header = "[A] " + header
    rows.append((header, ORANGE, True))
    rows.append((_ZOOM_AUTO.format(f"{scale_zoom:.1f}"), ORANGE_DIM, False))

    has_landed = station.has_landed or (
        status is not None and (status.docked or status.landed)
    )
    heading = station.heading
    sub_type = station.sub_type

    show_approach = (
        heading < 0
        or (status is not None and status.glide_mode)
        or (
            status is not None
            and status.in_main_ship
            and not has_landed
            and not status.docked
            and not status.landed
            and not status.supercruise
        )
    )
    if not show_approach and heading >= 0:
        eco = economy_label(station)
        footer = f"{eco}"
        if sub_type > 0:
            footer += f" #{sub_type}"
        if station.template_name:
            footer += f" | {station.template_name}"
        rows.append((footer, ORANGE, False))
        tmpl = resolve_template(station)
        if tmpl is not None:
            rows.append(
                (
                    f"Map: {tmpl.name or tmpl.economy} · "
                    f"{len(tmpl.landing_pads)} pads · "
                    f"{len(tmpl.named_poi)} POI",
                    ORANGE_DIM,
                    False,
                )
            )
        return rows

    if sub_type == 0 and heading < 0:
        rows.append(("? " + _UNKNOWN_TYPE_HEADING, CYAN, False))
    elif heading < 0:
        rows.append(("? " + _UNKNOWN_HEADING, CYAN, False))
    elif not has_landed:
        txt = f"{_KNOWN_SETTLEMENT}\n{economy_label(station)}"
        if sub_type > 0:
            txt += f" #{sub_type}"
        if station.template_name:
            txt += f"\n{station.template_name}"
        for line in txt.splitlines():
            rows.append(("> " + line, LIME, False))

    if heading < 0 and sub_type == 0:
        ecos = templates_for_economy(station.economy or station.economy_localized)
        if ecos:
            rows.append(
                (f"Economy templates: {len(ecos)} subtypes", ORANGE_DIM, False)
            )
            summary = pad_summary(ecos)
            if summary:
                rows.append((summary, ORANGE_DIM, False))

    if not has_landed:
        if (
            status is not None
            and status.latitude is not None
            and status.longitude is not None
            and status.planet_radius
            and status.planet_radius > 0
        ):
            dist2d = surface_distance_m(
                station.latitude,
                station.longitude,
                status.latitude,
                status.longitude,
                status.planet_radius,
            )
            alt = status.altitude or 0.0
            dist = math.hypot(dist2d, alt)
            dist_txt = f"{_ON_APPROACH}: {meters_to_string(dist)}"
        else:
            dist_txt = f"{_ON_APPROACH}: —"
        rows.append(("> " + dist_txt, ORANGE, False))

        if station.faction_name:
            rows.append((f"{_FACTION}: {station.faction_name}", ORANGE, True))
            if station.influence is not None:
                pct = f"{station.influence:.0%}"
                line = f"{_INFLUENCE}: {pct}"
                if station.faction_state:
                    line += f" | {station.faction_state}"
                rows.append((line, ORANGE, False))

        if station.reputation is not None:
            col = ORANGE
            prefix = "*"
            if station.reputation <= -35:
                col = RED
                prefix = "!"
            elif station.reputation > 35:
                col = LIME
                prefix = "+"
            rows.append(
                (
                    f"{prefix} {_YOUR_REP.format(reputation_text(station.reputation))}",
                    col,
                    False,
                )
            )

        if station.government == "$government_Anarchy;":
            gov = station.government_localized or "Anarchy"
            rows.append((f"[A] {_GOVERNMENT}: {gov}", ORANGE, False))

        if "facilitator" in station.station_services:
            rows.append((":) " + _HAS_INTERSTELLAR, ORANGE, False))

        interesting = [
            s
            for s in station.station_services
            if s.lower()
            in {
                "commodities",
                "outfitting",
                "shipyard",
                "refuel",
                "repair",
                "rearm",
                "restock",
                "materialtrader",
                "techbroker",
                "blackmarket",
            }
        ]
        if interesting:
            rows.append(
                ("Services: " + ", ".join(interesting[:6]), ORANGE_DIM, False)
            )

    if station.docking_in_progress:
        if station.docking_state in ("requested", "approved", "denied"):
            rows.append(("> " + _DOCKING_REQUESTED, ORANGE, False))
        if station.docking_state == "approved" and station.granted_pad:
            rows.append(
                ("> " + _DOCKING_APPROVED.format(station.granted_pad), ORANGE, False)
            )
    elif station.docking_state == "denied":
        rows.append(("X " + _DOCKING_DENIED, ORANGE, False))
        reason = station.denied_reason or ""
        label = _DENIED.get(reason, _UNKNOWN)
        prefix = _DENIED_PREFIX.get(reason, "?")
        rows.append((f"  {prefix} {label}", ORANGE, False))

    if station.docking_in_progress and heading < 0:
        if station.music_track == "DockingComputer":
            rows.append((_AUTO_DOCK_1, LIME, False))
            rows.append((_AUTO_DOCK_2, LIME, False))
            rows.append((_AUTO_DOCK_3, LIME, True))
        else:
            rows.append((_MANUAL_DOCK_1, ORANGE, False))
            rows.append((_MANUAL_DOCK_2, ORANGE, False))
            rows.append((_MANUAL_DOCK_3, ORANGE, True))
    elif has_landed and heading < 0:
        if status is not None and status.docked:
            rows.append(("> " + _HELP_SHIP_1, ORANGE, False))
            rows.append((f"{_HELP_SHIP_2}:", ORANGE, True))
            rows.append(
                ("> " + _HELP_SHIP_3.format(".settlement"), ORANGE, False)
            )
        elif status is not None and (status.on_foot or status.in_srv or status.landed):
            rows.append((_HELP_FOOT_0, ORANGE, True))
            rows.append((_HELP_FOOT_1, ORANGE, False))
            rows.append((_HELP_FOOT_2, ORANGE, False))
            rows.append((_HELP_FOOT_3, ORANGE, False))
            rows.append((_HELP_FOOT_4, ORANGE, False))
            rows.append((_HELP_FOOT_5.format(".settlement"), ORANGE, False))
            rows.append((_HELP_FOOT_6, ORANGE, False))

    return rows


def human_site_lines(
    survey: SurveyState,
    status: StatusSnapshot | None = None,
    *,
    scale_zoom: float = 1.0,
) -> list[tuple[str, tuple[int, int, int, int], bool]]:
    station = survey.system_station
    if station is None:
        return []
    return _approach_rows(station, status, scale_zoom=scale_zoom)


def _pad_rect(size: str) -> tuple[float, float, float, float]:
    if size == "Small":
        return (-25, -35, 25, 35)
    if size == "Medium":
        return (-35, -67.5, 35, 67.5)
    return (-45, -85, 45, 85)


def _draw_site_map(
    draw,
    tmpl: HumanTemplate,
    *,
    ox: float,
    oy: float,
    scale_m: float,
    site_heading: float,
    game: GameSettings,
    map_box: tuple[float, float, float, float],
    font_small,
) -> None:
    """Top-down template: buildings, pads, named POI, terminals."""
    rad = math.radians(-site_heading) if site_heading >= 0 else 0.0
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)

    def world_to_screen(x: float, y: float) -> tuple[float, float]:
        rx = x * cos_a - y * sin_a
        ry = x * sin_a + y * cos_a
        return ox + rx * scale_m, oy - ry * scale_m

    for bld in tmpl.buildings:
        for path in bld.paths:
            if len(path.points) < 2:
                continue
            pts = [world_to_screen(p.x, p.y) for p in path.points]
            if pts[0] != pts[-1]:
                pts.append(pts[0])
            draw.polygon(pts, outline=SADDLE, fill=(60, 30, 10, 180))

    for i, pad in enumerate(tmpl.landing_pads):
        left, top, right, bottom = _pad_rect(pad.size)
        corners = [
            (pad.offset.x + left, pad.offset.y + top),
            (pad.offset.x + right, pad.offset.y + top),
            (pad.offset.x + right, pad.offset.y + bottom),
            (pad.offset.x + left, pad.offset.y + bottom),
        ]
        prad = math.radians(pad.rot or 0)
        pc, ps = math.cos(prad), math.sin(prad)
        rotated = []
        for px, py in corners:
            dx, dy = px - pad.offset.x, py - pad.offset.y
            rotated.append(
                (
                    pad.offset.x + dx * pc - dy * ps,
                    pad.offset.y + dx * ps + dy * pc,
                )
            )
        screen = [world_to_screen(x, y) for x, y in rotated]
        draw.polygon(screen, outline=PAD_COL)
        cx, cy = world_to_screen(pad.offset.x, pad.offset.y)
        draw.ellipse(
            (cx - _s(2), cy - _s(2), cx + _s(2), cy + _s(2)), outline=PAD_COL
        )
        draw.text((cx + _s(4), cy - _s(6)), str(i + 1), fill=PAD_COL, font=font_small)

    show_med = getattr(game, "humanSiteShow_Medkit", True)
    show_bat = getattr(game, "humanSiteShow_Battery", True)
    _MAX = 2000.0
    for poi in tmpl.named_poi:
        if abs(poi.offset.x) > _MAX or abs(poi.offset.y) > _MAX:
            continue
        if poi.name == "Medkit" and not show_med:
            continue
        if poi.name == "Battery" and not show_bat:
            continue
        sx, sy = world_to_screen(poi.offset.x, poi.offset.y)
        if not (map_box[0] <= sx <= map_box[2] and map_box[1] <= sy <= map_box[3]):
            continue
        r = _s(3)
        draw.ellipse(
            (sx - r, sy - r, sx + r, sy + r), fill=POI_COL, outline=orange()
        )

    if getattr(game, "humanSiteShow_DataTerminal", True):
        for term in tmpl.data_terminals:
            if abs(term.offset.x) > _MAX or abs(term.offset.y) > _MAX:
                continue
            sx, sy = world_to_screen(term.offset.x, term.offset.y)
            if not (map_box[0] <= sx <= map_box[2] and map_box[1] <= sy <= map_box[3]):
                continue
            r = _s(3)
            draw.rectangle(
                (sx - r, sy - r, sx + r, sy + r), fill=TERM_COL, outline=orange()
            )

    for door in tmpl.secure_doors:
        sx, sy = world_to_screen(door.offset.x, door.offset.y)
        if not (map_box[0] <= sx <= map_box[2] and map_box[1] <= sy <= map_box[3]):
            continue
        r = _s(2)
        draw.rectangle(
            (sx - r, sy - r, sx + r, sy + r), outline=DOOR_COL, fill=DOOR_COL
        )

    draw.line(
        (ox - _s(6), oy, ox + _s(6), oy), fill=orange(), width=max(1, SCALE // 2)
    )
    draw.line(
        (ox, oy - _s(6), ox, oy + _s(6)), fill=orange(), width=max(1, SCALE // 2)
    )


def render_human_site_bitmap(
    survey: SurveyState,
    status: StatusSnapshot | None = None,
    *,
    game: GameSettings | None = None,
    force_show: bool = False,
    max_width: int | None = None,
    cmdr=None,
) -> tuple[bytes, int, int] | None:
    """Render PlotHumanSite approach overlay and/or template map."""
    from PIL import Image, ImageDraw

    from cmdr_state import apply_cmdr_to_survey

    gs = game if game is not None else GameSettings()
    survey = apply_cmdr_to_survey(survey, cmdr)
    if not human_site_allowed(gs, status, survey, force_show=force_show):
        return None
    station = survey.system_station
    if station is None:
        return None

    col = orange(gs)
    dim = orange_dim(gs)

    width_logical = max_width or gs.plotHumanSiteWidth or DEFAULT_WIDTH
    width_logical = max(200, min(800, int(width_logical)))
    height_cap = max(200, min(900, int(gs.plotHumanSiteHeight or 440)))

    font_title = _font(TITLE_PX)
    font_body = _font(BODY_PX)
    font_bold = _font(BODY_PX, bold=True)

    zoom = _zoom_for(gs, status)
    rows = human_site_lines(survey, status, scale_zoom=zoom)
    if not rows:
        return None

    tmpl = resolve_template(station) if want_site_map(station, status) else None
    if tmpl is None and force_show:
        tmpl = resolve_template(station)

    probe_w = max(_measure(font_body, r[0]) for r in rows)
    width = max(_s(width_logical), min(_s(width_logical + 40), probe_w + _s(24)))
    if width > _s(width_logical + 80):
        width = _s(width_logical + 80)

    header_rows = rows if tmpl is None else rows[:4]
    text_h = _s(12) + len(header_rows) * _s(ROW) + _s(8)
    map_h = _s(280) if tmpl is not None else 0
    height = min(text_h + map_h + _s(10), _s(height_cap))
    if tmpl is None:
        height = min(_s(12) + len(rows) * _s(ROW) + _s(14), _s(height_cap))

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height, col)

    draw.rectangle(
        (_s(4), _s(26), width - _s(4), height - _s(10)),
        fill=FADE,
    )

    y = _s(10)
    draw_rows = header_rows if tmpl is not None else rows
    for text, colour, bold in draw_rows:
        font = font_bold if bold else (font_title if y < _s(28) else font_body)
        max_chars_w = width - _s(PAD * 2)
        for line in text.split("\n"):
            if _measure(font, line) <= max_chars_w:
                draw.text((_s(PAD), y), line, font=font, fill=colour)
                y += _s(ROW)
            else:
                words = line.split(" ")
                cur = ""
                for word in words:
                    trial = (cur + " " + word).strip()
                    if _measure(font, trial) > max_chars_w and cur:
                        draw.text((_s(PAD), y), cur, font=font, fill=colour)
                        y += _s(ROW)
                        cur = word
                    else:
                        cur = trial
                if cur:
                    draw.text((_s(PAD), y), cur, font=font, fill=colour)
                    y += _s(ROW)
        if y > height - _s(12):
            break

    if tmpl is not None:
        map_top = y + _s(4)
        map_box = (_s(4), float(map_top), width - _s(4), height - _s(6))
        draw.rectangle(map_box, fill=(8, 8, 8, 255), outline=dim)
        xs: list[float] = [0.0]
        ys: list[float] = [0.0]
        # Ignore corrupt pub outliers (some templates have huge bogus offsets)
        _MAX_SITE_M = 2000.0

        def _ok(x: float, y: float) -> bool:
            return abs(x) < _MAX_SITE_M and abs(y) < _MAX_SITE_M

        for pad in tmpl.landing_pads:
            if _ok(pad.offset.x, pad.offset.y):
                xs.append(pad.offset.x)
                ys.append(pad.offset.y)
        for poi in tmpl.named_poi:
            if _ok(poi.offset.x, poi.offset.y):
                xs.append(poi.offset.x)
                ys.append(poi.offset.y)
        for bld in tmpl.buildings:
            for path in bld.paths:
                for p in path.points:
                    if _ok(p.x, p.y):
                        xs.append(p.x)
                        ys.append(p.y)
        span = max(abs(max(xs) - min(xs)), abs(max(ys) - min(ys)), 80.0)
        map_px = min(map_box[2] - map_box[0], map_box[3] - map_box[1])
        scale_m = (map_px * 0.42 / span) * max(0.25, zoom)
        ox = (map_box[0] + map_box[2]) / 2.0
        oy = (map_box[1] + map_box[3]) / 2.0
        heading = station.heading if station.heading >= 0 else 0.0
        _draw_site_map(
            draw,
            tmpl,
            ox=ox,
            oy=oy,
            scale_m=scale_m,
            site_heading=heading,
            game=gs,
            map_box=map_box,
            font_small=font_title,
        )
        label = (
            f"{tmpl.economy} #{tmpl.sub_type}"
            + (f" · {tmpl.name}" if tmpl.name else "")
            + f" · z{zoom:.1f}"
        )
        draw.text((_s(PAD), height - _s(16)), label, font=font_title, fill=dim)
    else:
        used = min(height, y + _s(10))
        if used < height:
            img = img.crop((0, 0, width, used))
            height = used
            draw = ImageDraw.Draw(img)
            for yy, c in (
                (height - _s(5), dim),
                (height - _s(4), col),
                (height - _s(3), dim),
            ):
                draw.line((_s(2), yy, width - _s(4), yy), fill=c)
            draw.rectangle(
                (0, 0, width - 1, height - 1),
                outline=col,
                width=max(1, SCALE // 2),
            )

    return _finish(img)


def render_human_site_map_bitmap(
    survey: SurveyState,
    status: StatusSnapshot | None = None,
    *,
    game: GameSettings | None = None,
    force_show: bool = True,
) -> tuple[bytes, int, int] | None:
    """Force the settlement template map when a matching template exists."""
    station = survey.system_station
    if station is None:
        return None
    # Ensure subtype/heading so want_site_map / resolve succeed for tests
    if station.sub_type <= 0 and station.economy:
        from human_site_templates import templates_for_economy

        ecos = templates_for_economy(station.economy or station.economy_localized)
        if ecos and station.sub_type <= 0:
            # leave station as-is; resolve_template needs subtype
            pass
    return render_human_site_bitmap(
        survey, status, game=game, force_show=force_show
    )
