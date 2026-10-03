#!/usr/bin/env python3
"""PlotGalMap — 1-1 Linux port of SrvSurvey/plotters/PlotGalMap.cs.

Uses journal + NavRoute + Status, with optional NetSysData (EDSM / Spansh)
for remote hop discovery lines. Faction column needs Spansh dump — optional.
Strings match PlotGalMap.resx / Misc.resx English. Orange theme + gothic fonts.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from companion import (
    GUI_FOCUS_GALAXY_MAP,
    NavRouteSnapshot,
    RouteHop,
    StatusSnapshot,
)
from game_settings import GameSettings
from journal import SurveyState

try:
    from net_sys_data import get_net_sys_data
except ImportError:  # pragma: no cover
    get_net_sys_data = None  # type: ignore[assignment]

# GameColors / theme.json
ORANGE = (255, 111, 0, 255)
ORANGE_DARK = (95, 48, 3, 255)
CYAN = (84, 223, 237, 255)
BLACK = (0, 0, 0, 255)
STRIPE = (12, 12, 12, 255)

BODY_PX = 9  # fontSmall2
PAD = 8
ROW = 14
DEFAULT_WIDTH = 240

# PlotGalMap.resx
_HDR_SELECTED = "Selected:"
_HDR_CURRENT = "Current:"
_HDR_DESTINATION = "Destination:"
_HDR_NEXT_JUMP = "Next jump:"
_NO_ROUTE = "No route set"
_DATA_FROM = "Data from: EDSM + Spansh + Canonn"
_ROUTE_FOOTER = "Total: ► {0} jumps ► Distance: {1} ly"
_COUNT_GENUS = "{0}x Genus"

# Misc.resx NetSysData_*
_UNSCANNED = "Unscanned system"
_DISCOVERED_ALL = "Discovered, {0} bodies"
_DISCOVERED_PARTIAL = "Discovered ({0} of {1})"
_DISCOVERED_BY = "By {0}, {1}"
_LAST_UPDATED = "Last updated: {0}"


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


def _background(draw, w: int, h: int) -> None:
    draw.rectangle((0, 0, w - 1, h - 1), fill=BLACK)
    step = _s(3)
    for y in range(0, h, step):
        draw.line((0, y, w - 1, y), fill=STRIPE)
    for y, col in ((_s(3), ORANGE_DARK), (_s(4), ORANGE), (_s(5), ORANGE_DARK)):
        draw.line((_s(2), y, w - _s(4), y), fill=col)
    for y, col in (
        (h - _s(5), ORANGE_DARK),
        (h - _s(4), ORANGE),
        (h - _s(3), ORANGE_DARK),
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


def _system_distance(
    a: tuple[float, float, float] | None,
    b: tuple[float, float, float] | None,
) -> float:
    if a is None or b is None:
        return -1.0
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def gal_map_allowed(
    game: GameSettings,
    status: StatusSnapshot | None,
    *,
    force_show: bool = False,
) -> bool:
    """Match PlotGalMap.allowed (not suppressed by buildProjectsSuppressOtherOverlays)."""
    if not game.autoShowPlotGalMap:
        return False
    if force_show:
        return True
    return status is not None and status.gui_focus == GUI_FOCUS_GALAXY_MAP


@dataclass(frozen=True)
class GalMapSystemRow:
    """One destination / next / current / selected summary block."""

    header: str
    system_name: str
    system_address: int | None
    discovery_status: str
    highlight: bool
    genus_count: int = 0
    discovered_by_line: str | None = None
    last_updated_line: str | None = None


def _discovery_for_current(survey: SurveyState) -> tuple[str, bool]:
    """NetSysData.discoveryStatus approximation from journal for the system we are in."""
    total = survey.body_count
    scanned = survey.scanned_count
    if total is None or total == 0:
        return _UNSCANNED, True
    if scanned >= total or survey.fss_complete:
        return _DISCOVERED_ALL.format(total), False
    return _DISCOVERED_PARTIAL.format(scanned, total), True


def _optional_net(
    name: str,
    address: int | None,
    game: GameSettings | None,
) -> Any:
    if get_net_sys_data is None or not name:
        return None
    gs = game if game is not None else GameSettings()
    try:
        return get_net_sys_data(
            name,
            int(address or 0),
            use_spansh_last_updated=bool(gs.useLastUpdatedFromSpanshNotEDSM),
        )
    except Exception:
        return None


def _discovery_from_net(net: Any) -> tuple[str, bool, int, str | None, str | None]:
    """Return status, highlight, genus, discovered-by line, last-updated line."""
    if net is None:
        return "...", False, 0, None, None
    status = getattr(net, "discovery_status", None) or "..."
    discovered = getattr(net, "discovered", None)
    scan = int(getattr(net, "scan_body_count", 0) or 0)
    total = int(getattr(net, "total_body_count", 0) or 0)
    highlight = (
        discovered is False
        or scan < total
        or (total == 0 and discovered is not None)
    )
    genus = int(getattr(net, "genus_count", 0) or 0)
    by_line = None
    cmdr = getattr(net, "discovered_by", None)
    when = getattr(net, "discovered_date", None)
    if cmdr and when:
        by_line = _DISCOVERED_BY.format(cmdr, when)
    last = getattr(net, "last_updated", None)
    last_line = None
    if last and (when is None or str(last) > str(when)):
        last_line = _LAST_UPDATED.format(last)
    return status, highlight, genus, by_line, last_line


def _is_same_system(
    name: str,
    address: int | None,
    survey: SurveyState,
) -> bool:
    if address is not None and survey.system_address is not None:
        return address == survey.system_address
    return bool(name) and name == survey.system


def _row_for_hop(
    hop: RouteHop,
    header: str,
    survey: SurveyState,
    *,
    game: GameSettings | None = None,
    net_data: Any = None,
) -> GalMapSystemRow:
    if _is_same_system(hop.star_system, hop.system_address, survey):
        status, highlight = _discovery_for_current(survey)
        genus = survey.total_bio_signals
        by_line = last_line = None
    else:
        net = net_data
        if net is None:
            net = _optional_net(hop.star_system, hop.system_address, game)
        status, highlight, genus, by_line, last_line = _discovery_from_net(net)
    return GalMapSystemRow(
        header=header,
        system_name=hop.star_system,
        system_address=hop.system_address,
        discovery_status=status,
        highlight=highlight,
        genus_count=genus,
        discovered_by_line=by_line,
        last_updated_line=last_line,
    )


def _header_for(
    name: str,
    address: int | None,
    survey: SurveyState,
    nav_route: NavRouteSnapshot | None,
) -> str:
    if _is_same_system(name, address, survey):
        return _HDR_CURRENT
    if nav_route is not None and nav_route.route:
        last = nav_route.route[-1]
        if address is not None and last.system_address is not None:
            if address == last.system_address:
                return _HDR_DESTINATION
        elif name == last.star_system:
            return _HDR_DESTINATION
    return _HDR_SELECTED


def gal_map_rows(
    survey: SurveyState,
    nav_route: NavRouteSnapshot | None,
    *,
    game: GameSettings | None = None,
    net_lookup: bool = True,
) -> tuple[list[GalMapSystemRow], float, int]:
    """Build summary rows + (distance_ly, jump_count). Pure / unit-testable."""
    rows: list[GalMapSystemRow] = []
    distance = 0.0
    jumps = 0
    gs = game if game is not None else GameSettings()

    def _net_for(name: str, addr: int | None) -> Any:
        if not net_lookup:
            return None
        return _optional_net(name, addr, gs)

    route = nav_route.route if nav_route is not None else ()
    if len(route) >= 2:
        last = route[-1]
        first_hop = route[1]
        next_hop = None if first_hop is last else first_hop

        header = (
            _HDR_CURRENT
            if _is_same_system(last.star_system, last.system_address, survey)
            else _HDR_DESTINATION
        )
        rows.append(
            _row_for_hop(
                last,
                header,
                survey,
                game=gs,
                net_data=_net_for(last.star_system, last.system_address),
            )
        )

        if next_hop is not None:
            rows.append(
                _row_for_hop(
                    next_hop,
                    _HDR_NEXT_JUMP,
                    survey,
                    game=gs,
                    net_data=_net_for(next_hop.star_system, next_hop.system_address),
                )
            )

        jumps = len(route) - 1
        for n in range(1, len(route)):
            d = _system_distance(route[n - 1].star_pos, route[n].star_pos)
            if d > 0:
                distance += d
        return rows, distance, jumps

    # No multi-hop route: FSDTarget selection, else current system (Windows ctor path)
    if survey.fsd_target_name:
        addr = survey.fsd_target_address
        header = _header_for(survey.fsd_target_name, addr, survey, nav_route)
        if _is_same_system(survey.fsd_target_name, addr, survey):
            status, highlight = _discovery_for_current(survey)
            genus = survey.total_bio_signals
            by_line = last_line = None
        else:
            net = _net_for(survey.fsd_target_name, addr)
            status, highlight, genus, by_line, last_line = _discovery_from_net(net)
        rows.append(
            GalMapSystemRow(
                header=header,
                system_name=survey.fsd_target_name,
                system_address=addr,
                discovery_status=status,
                highlight=highlight,
                genus_count=genus,
                discovered_by_line=by_line,
                last_updated_line=last_line,
            )
        )
        return rows, 0.0, 0

    if survey.system:
        status, highlight = _discovery_for_current(survey)
        rows.append(
            GalMapSystemRow(
                header=_HDR_CURRENT,
                system_name=survey.system,
                system_address=survey.system_address,
                discovery_status=status,
                highlight=highlight,
                genus_count=survey.total_bio_signals,
            )
        )
        return rows, 0.0, 0

    return rows, 0.0, 0


def render_gal_map_bitmap(
    survey: SurveyState,
    *,
    status: StatusSnapshot | None = None,
    nav_route: NavRouteSnapshot | None = None,
    game: GameSettings | None = None,
    force_show: bool = False,
    max_width: int = DEFAULT_WIDTH,
) -> tuple[bytes, int, int] | None:
    """Render PlotGalMap. Returns None when not allowed."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    if not gal_map_allowed(gs, status, force_show=force_show):
        return None

    font = _font(BODY_PX)
    font_bold = _font(BODY_PX, bold=True)

    left_width = (
        max(
            _measure(font, _HDR_SELECTED),
            _measure(font, _HDR_CURRENT),
            _measure(font, _HDR_DESTINATION),
            _measure(font, _HDR_NEXT_JUMP),
        )
        + _s(12)
    )

    rows, distance, jumps = gal_map_rows(survey, nav_route, game=gs)

    samples = [
        _NO_ROUTE,
        _DATA_FROM,
        _ROUTE_FOOTER.format(99, "9999.9"),
        _DISCOVERED_PARTIAL.format(12, 24),
        _COUNT_GENUS.format(9),
        _DISCOVERED_BY.format("Cmdr", "2020-01-01"),
        _LAST_UPDATED.format("2020-01-01"),
    ]
    for row in rows:
        samples.append(f"► {row.system_name}")
        samples.append(row.discovery_status)
        if row.discovered_by_line:
            samples.append(row.discovered_by_line)
        if row.last_updated_line:
            samples.append(row.last_updated_line)
    content_w = max((_measure(font, t) for t in samples if t), default=_s(DEFAULT_WIDTH))
    if rows:
        content_w = max(
            content_w,
            left_width
            + max(_measure(font_bold, f"► {r.system_name}") for r in rows),
        )
    width = max(_s(DEFAULT_WIDTH), content_w + _s(18))
    width = min(width, _s(max(max_width, DEFAULT_WIDTH) + 80))

    height = _s(12)
    if not rows:
        height += _s(ROW) + _s(10)
    else:
        for row in rows:
            height += _s(ROW)  # header + name
            height += _s(ROW)  # discovery
            if row.discovered_by_line:
                height += _s(ROW)
            if row.last_updated_line:
                height += _s(ROW)
            if row.genus_count > 0:
                height += _s(ROW)
            height += _s(10)
        if distance > 0 and jumps > 0:
            height += _s(ROW)
        height += _s(2) + _s(ROW)
    height += _s(10)

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height)

    y = _s(10)
    if not rows:
        draw.text((_s(PAD), y), _NO_ROUTE, font=font, fill=ORANGE)
        y += _s(ROW) + _s(10)
    else:
        for row in rows:
            draw.text((_s(PAD), y), row.header, font=font, fill=ORANGE)
            draw.text(
                (left_width, y),
                f"► {row.system_name}",
                font=font_bold,
                fill=ORANGE,
            )
            y += _s(ROW)
            disc_colour = CYAN if row.highlight else ORANGE
            disc_font = font_bold if row.highlight else font
            draw.text(
                (left_width, y),
                row.discovery_status,
                font=disc_font,
                fill=disc_colour,
            )
            y += _s(ROW)
            if row.discovered_by_line:
                draw.text(
                    (left_width, y),
                    row.discovered_by_line,
                    font=font,
                    fill=ORANGE,
                )
                y += _s(ROW)
            if row.last_updated_line:
                draw.text(
                    (left_width, y),
                    row.last_updated_line,
                    font=font,
                    fill=ORANGE,
                )
                y += _s(ROW)
            if row.genus_count > 0:
                draw.text(
                    (left_width, y),
                    _COUNT_GENUS.format(row.genus_count),
                    font=font_bold,
                    fill=CYAN,
                )
                y += _s(ROW)
            y += _s(10)

        if distance > 0 and jumps > 0:
            footer = _ROUTE_FOOTER.format(jumps, f"{distance:,.1f}")
            draw.text((_s(PAD), y), footer, font=font, fill=ORANGE)
            y += _s(ROW)

        y += _s(2)
        draw.text((_s(PAD), y), _DATA_FROM, font=font, fill=ORANGE_DARK)
        y += _s(ROW)

    used = min(height, y + _s(10))
    if used < height:
        img = img.crop((0, 0, width, used))
        height = used
        draw = ImageDraw.Draw(img)
        for yy, col in (
            (height - _s(5), ORANGE_DARK),
            (height - _s(4), ORANGE),
            (height - _s(3), ORANGE_DARK),
        ):
            draw.line((_s(2), yy, width - _s(4), yy), fill=col)
        draw.rectangle(
            (0, 0, width - 1, height - 1), outline=ORANGE, width=max(1, SCALE // 2)
        )

    return _finish(img)
