#!/usr/bin/env python3
"""PlotJumpInfo — 1-1 Linux port of SrvSurvey/plotters/PlotJumpInfo.cs.

Uses journal + NavRoute + Status, with optional NetSysData (EDSM / Spansh)
enrichment when online. Strings match PlotJumpInfo.resx English.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
import math
from pathlib import Path
from typing import Any

from companion import (
    GUI_FOCUS_FSS,
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
ORANGE_DIM = (160, 70, 0, 255)
CYAN = (84, 223, 237, 255)
CYAN_DARK = (20, 80, 90, 255)
BLACK = (0, 0, 0, 255)
STRIPE = (12, 12, 12, 255)

TITLE_PX = 9  # fontSmall
BODY_PX = 11  # fontMiddleBold-ish
PAD = 8
DEFAULT_WIDTH = 300
SCOOPABLE = frozenset("KGBFOAM")
# Without ship maxJump from Loadout, treat > this as a neutron-style hop highlight.
DEFAULT_MAX_JUMP_LY = 50.0
LIMIT_EXCESS_DISTANCE = 1000.0
LIMIT_PIXELS_PER_LY = 0.25


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


def _play(draw, x: int, y: int, color) -> int:
    h = _s(8)
    draw.polygon([(x, y + _s(1)), (x + _s(5), y + h // 2), (x, y + h)], fill=color)
    return _s(9)


def _system_distance(
    a: tuple[float, float, float], b: tuple[float, float, float]
) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def destination_is_next_route_hop(
    status: StatusSnapshot | None,
    survey: SurveyState,
    nav_route: NavRouteSnapshot | None,
) -> bool:
    """Windows Game.destinationNextRouteHop — destination is the hop after current."""
    if status is None or nav_route is None or not nav_route.route:
        return False
    dest_addr = status.destination_system
    if not dest_addr or dest_addr <= 0:
        return False
    if status.destination_body not in (None, 0):
        return False
    cur = survey.system_address
    if cur is None:
        return False
    idx_cur = next(
        (i for i, h in enumerate(nav_route.route) if h.system_address == cur),
        None,
    )
    idx_dest = next(
        (i for i, h in enumerate(nav_route.route) if h.system_address == dest_addr),
        None,
    )
    if idx_cur is None or idx_dest is None:
        return False
    return idx_dest == idx_cur + 1


def jump_info_allowed(
    game: GameSettings,
    status: StatusSnapshot | None,
    survey: SurveyState,
    nav_route: NavRouteSnapshot | None,
    *,
    force_show: bool = False,
) -> bool:
    """Match PlotJumpInfo.allowed (no buildProjectsSuppressOtherOverlays check)."""
    if not game.autoShowPlotJumpInfo:
        return False
    if force_show and (status is None or status.gui_focus != GUI_FOCUS_FSS):
        return True
    if status is not None and status.fsd_charging_jump and status.is_flying_or_supercruise():
        return True
    if survey.fsd_jumping:
        return True
    if (
        game.showPlotJumpInfoIfNextHop
        and status is not None
        and status.supercruise
        and destination_is_next_route_hop(status, survey, nav_route)
    ):
        return True
    return False


def _resolve_next_name(
    survey: SurveyState,
    status: StatusSnapshot | None,
    nav_route: NavRouteSnapshot | None,
) -> tuple[str | None, int | None, str | None]:
    """Return (systemName, systemAddress, starClass) for the next jump."""
    if survey.fsd_target_name:
        return (
            survey.fsd_target_name,
            survey.fsd_target_address,
            survey.fsd_target_star_class,
        )
    if (
        status is not None
        and status.destination
        and status.destination_system
        and status.destination_system > 0
        and status.destination_body in (None, 0)
    ):
        star_class = None
        if nav_route is not None:
            for hop in nav_route.route:
                if hop.system_address == status.destination_system:
                    star_class = hop.star_class
                    break
                if hop.star_system == status.destination:
                    star_class = hop.star_class
                    break
        return status.destination, status.destination_system, star_class
    if nav_route is not None and nav_route.route:
        # Next hop after current system when charged / next-hop mode
        cur = survey.system_address
        if cur is not None:
            for i, hop in enumerate(nav_route.route):
                if hop.system_address == cur and i + 1 < len(nav_route.route):
                    nxt = nav_route.route[i + 1]
                    return nxt.star_system, nxt.system_address, nxt.star_class
        if len(nav_route.route) >= 2:
            nxt = nav_route.route[1]
            return nxt.star_system, nxt.system_address, nxt.star_class
    return None, None, None


def _build_route_hops(
    survey: SurveyState,
    nav_route: NavRouteSnapshot | None,
    next_name: str,
    next_addr: int | None,
    next_class: str | None,
) -> tuple[list[RouteHop], int]:
    """Match Windows initFromRoute hop list + nextHopIdx (indexes hopDistances)."""
    full = list(nav_route.route) if nav_route is not None else []
    route_start = full[0] if full else None
    if route_start is None and survey.system:
        route_start = RouteHop(
            star_system=survey.system,
            system_address=survey.system_address,
        )
    route = list(full[1:]) if full else []

    def _is_next(hop: RouteHop) -> bool:
        if next_addr is not None and hop.system_address == next_addr:
            return True
        return hop.star_system == next_name

    nxt = next((h for h in route if _is_next(h)), None)
    if nxt is None:
        nxt = RouteHop(
            star_system=next_name,
            system_address=next_addr,
            star_class=next_class,
        )
        if (
            route_start is None
            or (
                survey.system_address is not None
                and route_start.system_address != survey.system_address
            )
        ):
            route_start = next(
                (h for h in route if h.system_address == survey.system_address),
                None,
            )
            if route_start is None and survey.system:
                route_start = RouteHop(
                    star_system=survey.system,
                    system_address=survey.system_address,
                )
        route = [nxt]

    next_hop_idx = route.index(nxt) if nxt in route else 0
    if route_start is not None:
        route = [route_start] + route
    return route, next_hop_idx


def _calc_hop_distances(
    route: list[RouteHop],
) -> tuple[list[float], list[bool], float]:
    distances: list[float] = []
    scoops: list[bool] = []
    total = 0.0
    for n in range(1, len(route)):
        prev_pos = route[n - 1].star_pos
        pos = route[n].star_pos
        if prev_pos is None or pos is None:
            continue
        d = _system_distance(prev_pos, pos)
        distances.append(d)
        total += d
        cls = route[n].star_class
        scoops.append(bool(cls and cls[0] in SCOOPABLE))
    return distances, scoops, total


def _optional_net(
    system_name: str,
    system_address: int | None,
    game: GameSettings,
) -> Any:
    if get_net_sys_data is None:
        return None
    try:
        return get_net_sys_data(
            system_name,
            int(system_address or 0),
            use_spansh_last_updated=bool(game.useLastUpdatedFromSpanshNotEDSM),
        )
    except Exception:
        return None


def _enrich_route_from_net(
    route: list[RouteHop],
    next_name: str,
    next_addr: int | None,
    net: Any,
) -> list[RouteHop]:
    """Fill missing star_class / star_pos on the next hop from NetSysData."""
    if net is None:
        return route
    out: list[RouteHop] = []
    for hop in route:
        is_next = (
            (next_addr is not None and hop.system_address == next_addr)
            or hop.star_system == next_name
        )
        if not is_next:
            out.append(hop)
            continue
        star_class = hop.star_class or getattr(net, "star_class", None)
        star_pos = hop.star_pos or getattr(net, "star_pos", None)
        if star_class == hop.star_class and star_pos == hop.star_pos:
            out.append(hop)
            continue
        out.append(
            RouteHop(
                star_system=hop.star_system,
                system_address=hop.system_address,
                star_class=star_class,
                star_pos=star_pos,
            )
        )
    return out


def _net_detail_lines(net: Any) -> list[tuple[str, tuple]]:
    """PlotJumpInfo non-minimal discovery / traffic / POI lines from NetSysData."""
    lines: list[tuple[str, tuple]] = []
    if net is None:
        return lines
    status = getattr(net, "discovery_status", None)
    total = int(getattr(net, "total_body_count", 0) or 0)
    discovered_by = getattr(net, "discovered_by", None)
    discovered_date = getattr(net, "discovered_date", None)
    last_updated = getattr(net, "last_updated", None)

    if total == 0 and status:
        lines.append((status, CYAN))
    elif discovered_by and discovered_date:
        lines.append((f"Discovered by {discovered_by} {discovered_date}", ORANGE))

    if last_updated and (
        discovered_date is None or str(last_updated) > str(discovered_date)
    ):
        lines.append((f"Last updated: {last_updated}", ORANGE))

    traffic = getattr(net, "traffic", None)
    if traffic is not None and int(getattr(traffic, "total", 0) or 0) > 0:
        day = int(getattr(traffic, "day", 0) or 0)
        week = int(getattr(traffic, "week", 0) or 0)
        total_t = int(getattr(traffic, "total", 0) or 0)
        lines.append(
            (
                f"Traffic last 24 hours: {day:,}, week: {week:,}, ever: {total_t:,}",
                ORANGE,
            )
        )

    poi_fn = getattr(net, "poi_summary_parts", None)
    if callable(poi_fn):
        parts = poi_fn()
        if parts:
            lines.append((", ".join(parts), ORANGE))

    special = getattr(net, "special", None) or {}
    if isinstance(special, dict):
        for key, values in special.items():
            if not values:
                continue
            joined = " · ".join(str(v) for v in values)
            lines.append((f"{key}: {joined}", CYAN))
    return lines


def render_jump_info_bitmap(
    survey: SurveyState,
    status: StatusSnapshot | None,
    nav_route: NavRouteSnapshot | None,
    *,
    game: GameSettings | None = None,
    max_width: int = DEFAULT_WIDTH,
    max_jump_ly: float = DEFAULT_MAX_JUMP_LY,
    force_show: bool = False,
    net_data: Any = None,
) -> tuple[bytes, int, int] | None:
    """Draw PlotJumpInfo. Returns None when there is nothing to show."""
    from PIL import Image, ImageDraw

    _ = force_show  # host may pass; allow gate is checked by caller
    gs = game if game is not None else GameSettings()
    next_name, next_addr, next_class = _resolve_next_name(survey, status, nav_route)
    if not next_name:
        return None
    if next_class is None and survey.fsd_target_star_class:
        next_class = survey.fsd_target_star_class

    net = net_data
    if net is None:
        net = _optional_net(next_name, next_addr, gs)
    if net is not None and next_class is None and getattr(net, "star_class", None):
        next_class = net.star_class

    route, next_hop_idx = _build_route_hops(
        survey, nav_route, next_name, next_addr, next_class
    )
    route = _enrich_route_from_net(route, next_name, next_addr, net)
    hop_distances, hop_scoops, total_distance = _calc_hop_distances(route)
    # Recompute next_hop_idx against distance list when some hops lack StarPos
    if hop_distances and next_hop_idx >= len(hop_distances):
        next_hop_idx = len(hop_distances) - 1

    font_small = _font(TITLE_PX)
    font_bold = _font(BODY_PX, bold=True)

    # Measure content width
    class_txt = f"class: {next_class}" if next_class else ""
    jump_counts = (
        f"#{next_hop_idx + 1} of {len(hop_distances)}" if hop_distances else ""
    )
    jump_dist = f"{total_distance:,.1f}ly" if total_distance else ""
    width = max(
        _s(DEFAULT_WIDTH),
        _s(PAD)
        + _measure(font_small, "Next jump:")
        + _measure(font_bold, " " + next_name)
        + (_measure(font_small, class_txt) + _s(16) if class_txt else 0)
        + _s(16),
    )
    if jump_counts and jump_dist:
        width = max(
            width,
            _s(PAD)
            + _measure(font_small, jump_counts)
            + _s(24)
            + _measure(font_small, jump_dist)
            + _s(PAD),
        )
    width = min(width, _s(max_width))

    # Extra detail lines when not minimal (journal + optional NetSysData)
    detail_lines: list[tuple[str, tuple]] = []
    if not gs.plotJumpInfoMinimal:
        if survey.fsd_remaining_jumps is not None:
            detail_lines.append(
                (
                    f"Remaining jumps in route: {survey.fsd_remaining_jumps}",
                    CYAN,
                )
            )
        # Scoopable hint for next star (journal / net class)
        if next_class and next_class[0] in SCOOPABLE:
            detail_lines.append((f"Scoopable {next_class}-class star", ORANGE))
        elif next_class == "N":
            detail_lines.append(("Neutron star", CYAN))
        detail_lines.extend(_net_detail_lines(net))

    row_h = _s(14)
    line_block = _s(28) if hop_distances and total_distance else 0
    height = (
        _s(10)
        + row_h
        + line_block
        + len(detail_lines) * row_h
        + _s(14)
    )

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height)

    y = _s(10)
    x = _s(PAD)
    draw.text((x, y + _s(2)), "Next jump:", font=font_small, fill=ORANGE)
    x += _tw(draw, "Next jump:", font_small)
    draw.text((x, y), " " + next_name, font=font_bold, fill=ORANGE)
    if class_txt:
        tw = _tw(draw, class_txt, font_small)
        col = CYAN if next_class == "N" else ORANGE
        draw.text((width - _s(PAD) - tw, y + _s(2)), class_txt, font=font_small, fill=col)
    y += row_h + _s(2)

    if hop_distances and total_distance > 0:
        y = _draw_jump_line(
            draw,
            width,
            y,
            hop_distances,
            hop_scoops,
            total_distance,
            next_hop_idx,
            font_small,
            max_jump_ly=max_jump_ly,
        )

    for text, color in detail_lines:
        x = _s(PAD)
        x += _play(draw, x, y + _s(2), color)
        draw.text((x, y), text, font=font_small, fill=color)
        y += row_h

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
            (0, 0, width - 1, height - 1),
            outline=ORANGE,
            width=max(1, SCALE // 2),
        )

    if SCALE != 1:
        img = img.resize((width // AA, height // AA), Image.Resampling.LANCZOS)
    w, h = img.size
    return img.tobytes("raw", "RGBA"), w, h


def _draw_jump_line(
    draw,
    width: int,
    y: int,
    hop_distances: list[float],
    hop_scoops: list[bool],
    total_distance: float,
    next_hop_idx: int,
    font,
    *,
    max_jump_ly: float,
) -> int:
    """Draw #n of m, total ly, and the route line (Windows drawJumpLine)."""
    left_txt = f"#{next_hop_idx + 1} of {len(hop_distances)}"
    right_txt = f"{total_distance:,.1f}ly"
    draw.text((_s(PAD), y), left_txt, font=font, fill=ORANGE)
    tw_left = _tw(draw, left_txt, font)
    tw_right = _tw(draw, right_txt, font)
    draw.text((width - _s(PAD) - tw_right, y), right_txt, font=font, fill=ORANGE)

    left = tw_left + _s(18)
    line_width = width - left - tw_right - _s(16)
    if line_width <= 0 or total_distance <= 0:
        return y + _s(20)

    pixels_per_ly = line_width / total_distance
    x = float(left + line_width)
    line_y = y + _th(draw, right_txt, font) // 2
    pen_w = max(1, _s(2))
    pen_next = max(2, _s(4))

    if total_distance > LIMIT_EXCESS_DISTANCE and len(hop_distances) > 1:
        draw.line(
            (int(x), line_y, int(x - line_width), line_y),
            fill=ORANGE_DIM,
            width=pen_w,
        )

    dot_r = _s(5)
    x_now = float(left)

    for n in range(len(hop_distances) - 1, -1, -1):
        if pixels_per_ly < LIMIT_PIXELS_PER_LY:
            tick_h = _s(6) if (n < len(hop_scoops) and hop_scoops[n]) else _s(3)
            col = ORANGE_DIM if n < next_hop_idx else ORANGE
            draw.line(
                (int(x) - 1, line_y - tick_h, int(x) - 1, line_y + tick_h),
                fill=col,
                width=max(1, SCALE // 2),
            )

        d = hop_distances[n]
        w = d * pixels_per_ly
        if n == next_hop_idx:
            draw.line(
                (int(x) - 1, line_y, int(x - w), line_y),
                fill=CYAN,
                width=pen_next,
            )
        elif n < next_hop_idx:
            draw.line(
                (int(x), line_y, int(x - w), line_y),
                fill=ORANGE_DIM,
                width=pen_w,
            )
        elif d > max_jump_ly:
            draw.line(
                (int(x) - 2, line_y, int(x - w), line_y),
                fill=CYAN,
                width=pen_w,
            )
        elif total_distance < LIMIT_EXCESS_DISTANCE:
            draw.line(
                (int(x), line_y, int(x - w), line_y),
                fill=ORANGE,
                width=pen_w,
            )

        if pixels_per_ly > LIMIT_PIXELS_PER_LY:
            cx, cy = int(x), line_y
            r0 = [
                cx - dot_r + 1,
                cy - dot_r + 1,
                cx + dot_r - 1,
                cy + dot_r - 1,
            ]
            if n < next_hop_idx - 1:
                draw.ellipse(r0, fill=BLACK, outline=ORANGE_DARK)
            elif n >= next_hop_idx:
                draw.ellipse(
                    [cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
                    fill=ORANGE,
                )
            if n < len(hop_scoops) and hop_scoops[n]:
                arc = [
                    cx - dot_r * 2,
                    cy - dot_r * 2,
                    cx + dot_r * 2,
                    cy + dot_r * 2,
                ]
                if n + 1 == next_hop_idx:
                    arc_col = CYAN
                elif n < next_hop_idx:
                    arc_col = ORANGE_DIM
                else:
                    arc_col = ORANGE
                # Approximate scoop arc as a short chord above the dot
                draw.arc(arc, start=230, end=310, fill=arc_col, width=max(1, _s(2)))

        if n == next_hop_idx:
            if pixels_per_ly < LIMIT_PIXELS_PER_LY:
                draw.line(
                    (int(x) - 2, line_y, int(x) - _s(6), line_y - _s(4)),
                    fill=CYAN,
                    width=max(1, _s(2)),
                )
                draw.line(
                    (int(x) - 2, line_y, int(x) - _s(6), line_y + _s(4)),
                    fill=CYAN,
                    width=max(1, _s(2)),
                )
            else:
                draw.line(
                    (int(x) - dot_r, line_y, int(x) - _s(10) - dot_r, line_y - _s(10)),
                    fill=CYAN,
                    width=max(1, _s(2)),
                )
                draw.line(
                    (int(x) - dot_r, line_y, int(x) - _s(10) - dot_r, line_y + _s(10)),
                    fill=CYAN,
                    width=max(1, _s(2)),
                )
        elif n + 1 == next_hop_idx:
            x_now = x

        x -= w

    # Leftmost start dot
    if total_distance > LIMIT_EXCESS_DISTANCE:
        draw.line(
            (int(x) - 1, line_y - _s(4), int(x) - 1, line_y + _s(4)),
            fill=ORANGE,
            width=max(1, SCALE // 2),
        )
    elif next_hop_idx == 0:
        r0 = [int(x) - dot_r + 1, line_y - dot_r + 1, int(x) + dot_r - 1, line_y + dot_r - 1]
        draw.ellipse(r0, fill=CYAN_DARK, outline=CYAN)
    elif next_hop_idx > 0:
        r0 = [int(x) - dot_r + 1, line_y - dot_r + 1, int(x) + dot_r - 1, line_y + dot_r - 1]
        draw.ellipse(r0, fill=BLACK, outline=ORANGE_DARK)

    # Redraw next-hop marker (was clipped)
    if pixels_per_ly < LIMIT_PIXELS_PER_LY:
        draw.line(
            (int(x_now), line_y - _s(6), int(x_now), line_y + _s(6)),
            fill=CYAN,
            width=max(1, _s(2)),
        )
    elif next_hop_idx > 0:
        r0 = [
            int(x_now) - dot_r + 1,
            line_y - dot_r + 1,
            int(x_now) + dot_r - 1,
            line_y + dot_r - 1,
        ]
        draw.ellipse(r0, fill=CYAN_DARK, outline=CYAN)

    return y + _s(20)
