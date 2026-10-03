"""Build HUD bitmaps from commander / survey / ship / signals state.

Panels:
- location: system, body, commander
- survey: FSS / DSS progress for the current system
- bio: current-body bio detail, genus list, ScanOrganic progress, sales
- signals: bio/geo body detail, FSS signals, recent CodexEntry
- route: Status destination + NavRoute hops + carrier jump hint
- ship: fuel, cargo, legal state, mode from Status + Cargo
- materials: materials by category
- locker: ShipLocker / Backpack summary

Full BigOverlay plotters stay out of scope; the presenter maps one window
per panel.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from companion import (
    CargoSnapshot,
    NavRouteSnapshot,
    ShipLockerSnapshot,
    StatusSnapshot,
)
from journal import CommanderLocation, SurveyState
from theme import DEFAULT_CYAN, DEFAULT_ORANGE, DEFAULT_ORANGE_DIM

# Same stand-in and frame as PlotBuildCommodities (panel_build.py).
_HUD_FONT_CANDIDATES = (
    Path("/usr/share/fonts/urw-base35/URWGothic-Book.otf"),
    Path("/usr/share/fonts/urw-base35/URWGothic-Demi.otf"),
    Path("/usr/share/fonts/julietaula-montserrat-fonts/Montserrat-Regular.otf"),
)
_HUD_FONT_BOLD = (
    Path("/usr/share/fonts/urw-base35/URWGothic-Demi.otf"),
    Path("/usr/share/fonts/julietaula-montserrat-fonts/Montserrat-Bold.otf"),
)
_HUD_FONT_SIZE = 11
_SCALE = 2
_MIN_LOGICAL_WIDTH = 245
_STRIPE = (12, 12, 12, 255)

_COLOR_TITLE = DEFAULT_ORANGE
_COLOR_BODY = DEFAULT_ORANGE
_COLOR_DIM = DEFAULT_ORANGE_DIM
_COLOR_ALERT = (255, 0, 0, 255)
_COLOR_CYAN = DEFAULT_CYAN
_BG = (0, 0, 0, 255)

_MAX_BODY_SIGNAL_ROWS = 4
_MAX_FSS_SIGNAL_ROWS = 5
_MAX_CODEX_ROWS = 3
_MAX_MATERIAL_ROWS = 4
_MAX_GENUS_ROWS = 5
_MAX_ORGANIC_ROWS = 4
_MAX_ROUTE_HOPS = 4
_MAX_LOCKER_ROWS = 4


def set_hud_font_size(size: int) -> None:
    """Update the TrueType size used by subsequent bitmap renders."""
    global _HUD_FONT_SIZE
    _HUD_FONT_SIZE = max(10, min(72, int(size)))


def get_hud_font_size() -> int:
    return _HUD_FONT_SIZE


def _load_hud_font(size: int | None = None, *, bold: bool = False) -> ImageFont.ImageFont:
    """Point size is the size on screen. The 18px cap made font_size=28 a no-op."""
    if size is None:
        size = _HUD_FONT_SIZE
        if bold:
            size = int(round(size * 1.08))
    point = max(16, min(48, int(size))) * _SCALE
    candidates = _HUD_FONT_BOLD if bold else _HUD_FONT_CANDIDATES
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), point)
    return ImageFont.load_default()


def _paint_commercial_frame(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    """Black scanlines, orange rules, orange border — PlotBuildCommodities chrome."""
    draw.rectangle((0, 0, width - 1, height - 1), fill=_BG)
    step = 3 * _SCALE
    for y in range(0, height, step):
        draw.line((0, y, width - 1, y), fill=_STRIPE)
    for y, col in (
        (3 * _SCALE, _COLOR_DIM),
        (4 * _SCALE, _COLOR_TITLE),
        (5 * _SCALE, _COLOR_DIM),
    ):
        if y < height:
            draw.line((2 * _SCALE, y, width - 4 * _SCALE, y), fill=col)
    for y, col in (
        (height - 5 * _SCALE, _COLOR_DIM),
        (height - 4 * _SCALE, _COLOR_TITLE),
        (height - 3 * _SCALE, _COLOR_DIM),
    ):
        if y > 0:
            draw.line((2 * _SCALE, y, width - 4 * _SCALE, y), fill=col)
    draw.rectangle((0, 0, width - 1, height - 1), outline=_COLOR_TITLE, width=max(1, _SCALE // 2))


def _downscale(image: Image.Image) -> tuple[bytes, int, int]:
    if _SCALE != 1:
        width, height = image.size
        image = image.resize((max(1, width // _SCALE), max(1, height // _SCALE)), Image.Resampling.LANCZOS)
    width, height = image.size
    return image.tobytes(), width, height


def scale_nearest(rgba: bytes, width: int, height: int, factor: int) -> tuple[bytes, int, int]:
    """Integer nearest-neighbor upscale for HUD readability."""
    if factor <= 1:
        return rgba, width, height
    out_w = width * factor
    out_h = height * factor
    out = bytearray(out_w * out_h * 4)
    for y in range(out_h):
        sy = y // factor
        for x in range(out_w):
            sx = x // factor
            si = (sy * width + sx) * 4
            di = (y * out_w + x) * 4
            out[di : di + 4] = rgba[si : si + 4]
    return bytes(out), out_w, out_h


def _opaque_card(rgba: bytes, width: int, height: int) -> bool:
    """True when the tile already paints its own background (gothic plotter)."""
    if width < 1 or height < 1 or len(rgba) < 4:
        return False
    return rgba[3] > 200


def _paint_logical_frame(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    """Commercial-port chrome at the size the presenter maps."""
    draw.rectangle((0, 0, width - 1, height - 1), fill=_BG)
    for scan in range(0, height, 3):
        draw.line((0, scan, width - 1, scan), fill=_STRIPE)
    for y, col in ((3, _COLOR_DIM), (4, _COLOR_TITLE), (5, _COLOR_DIM)):
        if y < height:
            draw.line((2, y, max(2, width - 4), y), fill=col)
    for y, col in (
        (height - 5, _COLOR_DIM),
        (height - 4, _COLOR_TITLE),
        (height - 3, _COLOR_DIM),
    ):
        if 0 < y < height:
            draw.line((2, y, max(2, width - 4), y), fill=col)
    draw.rectangle((0, 0, width - 1, height - 1), outline=_COLOR_TITLE, width=1)


def compose_hud_stack(
    bitmaps: list[tuple[bytes, int, int]],
    *,
    gap: int = 8,
    divider: bool = True,
) -> tuple[bytes, int, int]:
    """One right-hand status panel in the commercial-port frame.

    Text sections are transparent and share that frame. A tile that already
    has its own background is not wrapped again.
    """
    if not bitmaps:
        return render_lines_bitmap([("—", _COLOR_DIM)], frame=True)
    if len(bitmaps) == 1 and _opaque_card(*bitmaps[0]):
        return bitmaps[0]

    width = max(w for _rgba, w, _h in bitmaps)
    gap_px = gap if divider else 0
    framed = any(_opaque_card(rgba, w, h) for rgba, w, h in bitmaps)
    height = sum(h for _rgba, _w, h in bitmaps) + gap_px * (max(0, len(bitmaps) - 1))
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if not framed:
        _paint_logical_frame(draw, width, height)
    y = 0
    for index, (rgba, w, h) in enumerate(bitmaps):
        tile = Image.frombytes("RGBA", (w, h), rgba)
        if framed and not _opaque_card(rgba, w, h):
            plate = Image.new("RGBA", (width, h), (0, 0, 0, 0))
            plate_draw = ImageDraw.Draw(plate)
            _paint_logical_frame(plate_draw, width, h)
            plate.paste(tile, (0, 0), tile)
            image.paste(plate, (0, y))
        else:
            image.paste(tile, (0, y), tile)
        y += h
        if index < len(bitmaps) - 1 and divider:
            if not framed:
                draw.line((8, y + gap_px // 2, width - 8, y + gap_px // 2), fill=_COLOR_DIM)
            y += gap_px
    return image.tobytes(), width, height


def render_lines_bitmap(
    lines: list[tuple[str, tuple[int, int, int, int]]],
    *,
    scale: int = 1,
    padding_x: int = 10,
    padding_y: int = 8,
    line_gap: int = 4,
    font_size: int | None = None,
    frame: bool = False,
) -> tuple[bytes, int, int]:
    """Gothic orange lines at commercial-port density.

    ``frame`` is for a standalone card. The status stack leaves it off and
    ``compose_hud_stack`` paints one shared frame.
    """
    del font_size  # Body size is set_hud_font_size(); the box is measured from that face.
    if not lines:
        lines = [("—", _COLOR_DIM)]
    title_font = _load_hud_font(bold=True)
    body_font = _load_hud_font(bold=False)
    # Padding and row pitch follow the face so a larger font gets a larger card.
    fit = max(1.0, _HUD_FONT_SIZE / 16)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    heights: list[int] = []
    widths: list[int] = []
    for index, (text, _fill) in enumerate(lines):
        font = title_font if index == 0 else body_font
        box = probe.textbbox((0, 0), text, font=font)
        widths.append(box[2] - box[0])
        heights.append(max(box[3] - box[1], int(16 * fit) * _SCALE))
    pad_x = int(round(padding_x * fit)) * _SCALE
    pad_y = int(round(max(padding_y, 12) * fit)) * _SCALE
    gap = int(round(max(line_gap, 6) * fit)) * _SCALE
    width = max(max(widths) + pad_x * 2, int(_MIN_LOGICAL_WIDTH * fit) * _SCALE)
    height = sum(heights) + gap * (max(0, len(lines) - 1)) + pad_y * 2
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if frame:
        _paint_commercial_frame(draw, width, height)
    y = pad_y
    for index, (text, fill) in enumerate(lines):
        font = title_font if index == 0 else body_font
        draw.text((pad_x, y), text, font=font, fill=fill)
        y += heights[index] + gap
    rgba, out_w, out_h = _downscale(image)
    if scale > 1:
        return scale_nearest(rgba, out_w, out_h, scale)
    return rgba, out_w, out_h


def render_status_bitmap(
    location: CommanderLocation,
    *,
    scale: int = 1,
    font_size: int | None = None,
) -> tuple[bytes, int, int]:
    system = location.system or "Unknown system"
    commander = location.commander or ""
    body = location.body or ""
    lines: list[tuple[str, tuple[int, int, int, int]]] = [(system, _COLOR_TITLE)]
    if body and body != system:
        lines.append((body, _COLOR_BODY))
    if commander:
        lines.append((commander, _COLOR_BODY))
    return render_lines_bitmap(lines, scale=scale, font_size=font_size)


def _short_body_name(body_name: str, system: str | None) -> str:
    short = body_name
    if system and short.startswith(system):
        short = short[len(system) :].strip() or short
    return short


def survey_panel_lines(survey: SurveyState) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Pure line layout for the survey panel (unit-testable)."""
    lines: list[tuple[str, tuple[int, int, int, int]]] = [("Survey", _COLOR_TITLE)]
    if not survey.system:
        lines.append(("No system yet", _COLOR_DIM))
        return lines

    if survey.fss_complete:
        lines.append(("FSS complete", _COLOR_BODY))
    elif survey.fss_progress is not None:
        pct = int(round(survey.fss_progress * 100))
        if survey.body_count:
            lines.append(
                (f"FSS {pct}% · {survey.scanned_count}/{survey.body_count} bodies", _COLOR_BODY)
            )
        else:
            lines.append((f"FSS {pct}%", _COLOR_BODY))
    elif survey.body_count:
        lines.append(
            (f"Bodies scanned {survey.scanned_count}/{survey.body_count}", _COLOR_BODY)
        )
    else:
        lines.append((f"Bodies scanned {survey.scanned_count}", _COLOR_DIM))

    if survey.non_body_count:
        lines.append((f"Non-body signals {survey.non_body_count}", _COLOR_DIM))

    if survey.mapped_count:
        lines.append((f"DSS mapped {survey.mapped_count}", _COLOR_BODY))

    if survey.total_bio_signals:
        lines.append(
            (
                f"Bio {survey.total_bio_signals} on {survey.bio_body_count} bodies",
                _COLOR_BODY,
            )
        )
    else:
        lines.append(("Bio signals —", _COLOR_DIM))

    if survey.total_geo_signals:
        lines.append(
            (
                f"Geo {survey.total_geo_signals} on {survey.geo_body_count} bodies",
                _COLOR_BODY,
            )
        )
    else:
        lines.append(("Geo signals —", _COLOR_DIM))

    if survey.organic_scans:
        lines.append((f"Organic scans {survey.organic_scans}", _COLOR_BODY))

    return lines


def bio_panel_lines(
    survey: SurveyState,
    location: CommanderLocation,
) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Detailed bio for the current body + genus / ScanOrganic progress."""
    lines: list[tuple[str, tuple[int, int, int, int]]] = [("Bio", _COLOR_TITLE)]
    body = location.body
    if not survey.system:
        lines.append(("No system yet", _COLOR_DIM))
        return lines

    match = None
    if body:
        for row in survey.body_signals:
            if row.body_name == body:
                match = row
                break
        lines.append((_short_body_name(body, survey.system), _COLOR_BODY))
    else:
        lines.append(("No body approached", _COLOR_DIM))

    if match:
        if match.bio_count:
            lines.append((f"Bio signals {match.bio_count}", _COLOR_BODY))
        else:
            lines.append(("Bio signals —", _COLOR_DIM))
        if match.geo_count:
            lines.append((f"Geo signals {match.geo_count}", _COLOR_BODY))
        if match.genuses:
            lines.append(("Genuses", _COLOR_BODY))
            for genus in match.genuses[:_MAX_GENUS_ROWS]:
                lines.append((f"  {genus}", _COLOR_DIM))
            extra = len(match.genuses) - _MAX_GENUS_ROWS
            if extra > 0:
                lines.append((f"  +{extra} more", _COLOR_DIM))
    elif body:
        lines.append(("No bio/geo on body yet", _COLOR_DIM))

    if survey.organic_progress:
        lines.append(("Genus progress", _COLOR_BODY))
        for item in list(survey.organic_progress)[-_MAX_ORGANIC_ROWS:]:
            step = item.scan_type or "?"
            species = item.species or item.genus
            if len(species) > 28:
                species = species[:25] + "…"
            lines.append((f"  {species} · {step}", _COLOR_DIM))
    elif survey.organic_scans:
        lines.append((f"Organic scans {survey.organic_scans}", _COLOR_BODY))

    if survey.organic_sales:
        value = survey.organic_sale_value
        if value:
            lines.append((f"Sold {survey.organic_sales} · {value:,} cr", _COLOR_BODY))
        else:
            lines.append((f"Sold organics {survey.organic_sales}", _COLOR_BODY))

    return lines


def signals_panel_lines(survey: SurveyState) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Bio/geo per body, FSS signals, and recent Codex finds."""
    lines: list[tuple[str, tuple[int, int, int, int]]] = [("Signals", _COLOR_TITLE)]
    if not survey.system:
        lines.append(("No system yet", _COLOR_DIM))
        return lines

    body_rows = [b for b in survey.body_signals if b.bio_count or b.geo_count]
    if body_rows:
        lines.append(("Bio / Geo", _COLOR_BODY))
        for body in body_rows[:_MAX_BODY_SIGNAL_ROWS]:
            short = _short_body_name(body.body_name, survey.system)
            bits: list[str] = []
            if body.bio_count:
                bits.append(f"bio {body.bio_count}")
            if body.geo_count:
                bits.append(f"geo {body.geo_count}")
            lines.append((f"  {short}: {', '.join(bits)}", _COLOR_DIM))
        extra = len(body_rows) - _MAX_BODY_SIGNAL_ROWS
        if extra > 0:
            lines.append((f"  +{extra} more bodies", _COLOR_DIM))
    else:
        lines.append(("Bio / Geo —", _COLOR_DIM))

    if survey.fss_signals:
        lines.append((f"FSS signals {len(survey.fss_signals)}", _COLOR_BODY))
        for sig in reversed(survey.fss_signals[-_MAX_FSS_SIGNAL_ROWS:]):
            label = sig.name
            if len(label) > 36:
                label = label[:33] + "…"
            suffix = ""
            if sig.signal_type:
                suffix = f" · {sig.signal_type}"
            elif sig.is_station:
                suffix = " · Station"
            if sig.threat_level is not None and sig.threat_level > 0:
                suffix += f" T{sig.threat_level}"
            fill = _COLOR_ALERT if (sig.threat_level or 0) > 0 else _COLOR_DIM
            lines.append((f"  {label}{suffix}", fill))
    else:
        lines.append(("FSS signals —", _COLOR_DIM))

    if survey.codex_entries:
        lines.append((f"Codex {len(survey.codex_entries)}", _COLOR_BODY))
        for find in reversed(survey.codex_entries[-_MAX_CODEX_ROWS:]):
            label = find.name
            if len(label) > 34:
                label = label[:31] + "…"
            prefix = "★ " if find.is_new else "  "
            detail = find.subcategory or find.category or ""
            if detail and len(detail) > 22:
                detail = detail[:19] + "…"
            text = f"{prefix}{label}"
            if detail:
                text = f"{text} · {detail}"
            lines.append((text, _COLOR_DIM))
    else:
        lines.append(("Codex —", _COLOR_DIM))

    return lines


def route_panel_lines(
    survey: SurveyState,
    status: StatusSnapshot | None,
    nav_route: NavRouteSnapshot | None,
) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Destination / NavRoute / carrier jump hints."""
    lines: list[tuple[str, tuple[int, int, int, int]]] = [("Route", _COLOR_TITLE)]
    if status is not None and status.destination:
        lines.append((f"Dest {status.destination}", _COLOR_BODY))
    else:
        lines.append(("Dest —", _COLOR_DIM))

    if nav_route is not None and nav_route.hops:
        lines.append(
            (f"Plot {len(nav_route.hops)} hops · {nav_route.remaining} remaining", _COLOR_BODY)
        )
        for hop in nav_route.hops[:_MAX_ROUTE_HOPS]:
            label = hop if len(hop) <= 34 else hop[:31] + "…"
            lines.append((f"  {label}", _COLOR_DIM))
        extra = len(nav_route.hops) - _MAX_ROUTE_HOPS
        if extra > 0:
            lines.append((f"  +{extra} more", _COLOR_DIM))
    else:
        lines.append(("Nav route —", _COLOR_DIM))

    if survey.last_carrier_jump:
        carrier = survey.carrier_name or "Carrier"
        lines.append((f"{carrier} → {survey.last_carrier_jump}", _COLOR_BODY))

    return lines


def materials_panel_lines(survey: SurveyState) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Materials broken out by Raw / Manufactured / Encoded."""
    lines: list[tuple[str, tuple[int, int, int, int]]] = [("Materials", _COLOR_TITLE)]
    mats = survey.materials
    if mats is None:
        lines.append(("No Materials event yet", _COLOR_DIM))
        return lines

    for label, stacks in (
        ("Raw", mats.raw),
        ("Manufactured", mats.manufactured),
        ("Encoded", mats.encoded),
    ):
        if not stacks:
            lines.append((f"{label} —", _COLOR_DIM))
            continue
        total = sum(s.count for s in stacks)
        lines.append((f"{label} ({total})", _COLOR_BODY))
        ranked = sorted(stacks, key=lambda item: item.count, reverse=True)[:_MAX_MATERIAL_ROWS]
        for stack in ranked:
            lines.append((f"  {stack.name}: {stack.count}", _COLOR_DIM))
    return lines


def locker_panel_lines(
    locker: ShipLockerSnapshot | None,
) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Ship locker / backpack category summary."""
    lines: list[tuple[str, tuple[int, int, int, int]]] = [("Locker", _COLOR_TITLE)]
    if locker is None:
        lines.append(("ShipLocker.json missing", _COLOR_DIM))
        return lines
    if locker.total_count == 0:
        lines.append(("Empty", _COLOR_DIM))
        return lines
    lines.append((f"Total {locker.total_count}", _COLOR_BODY))
    for label, count in locker.category_totals():
        if count:
            lines.append((f"{label} {count}", _COLOR_BODY))
    # Show a few of the largest stacks across categories.
    all_stacks = sorted(
        locker.items + locker.components + locker.consumables + locker.data,
        key=lambda item: item.count,
        reverse=True,
    )
    for stack in all_stacks[:_MAX_LOCKER_ROWS]:
        name = stack.name if len(stack.name) <= 28 else stack.name[:25] + "…"
        lines.append((f"  {name}: {stack.count}", _COLOR_DIM))
    return lines


def guardian_panel_lines(survey: SurveyState) -> list[tuple[str, tuple[int, int, int, int]]]:
    lines: list[tuple[str, tuple[int, int, int, int]]] = [("Guardian", _COLOR_TITLE)]
    if not survey.system:
        lines.append(("No system yet", _COLOR_DIM))
        return lines
    if survey.guardian_codex:
        lines.append((f"Codex finds {survey.guardian_codex}", _COLOR_BODY))
    else:
        lines.append(("Codex finds —", _COLOR_DIM))
    sites = list(survey.guardian_sites)
    if sites:
        lines.append((f"Sites {len(sites)}", _COLOR_BODY))
        for site in sites[-5:]:
            label = site.display_text
            if len(label) > 34:
                label = label[:31] + "…"
            lines.append((f"  {label}", _COLOR_DIM))
            if site.blue_print:
                lines.append((f"    ► Blue print: {site.blue_print}", _COLOR_DIM))
    elif survey.guardian_signals:
        lines.append((f"Signals {len(survey.guardian_signals)}", _COLOR_BODY))
        for name in survey.guardian_signals[-5:]:
            label = name if len(name) <= 34 else name[:31] + "…"
            lines.append((f"  {label}", _COLOR_DIM))
    else:
        lines.append(("Sites / signals —", _COLOR_DIM))
    return lines


def human_panel_lines(survey: SurveyState) -> list[tuple[str, tuple[int, int, int, int]]]:
    lines: list[tuple[str, tuple[int, int, int, int]]] = [("Human Sites", _COLOR_TITLE)]
    if not survey.system:
        lines.append(("No system yet", _COLOR_DIM))
        return lines
    if survey.settlements:
        for name in survey.settlements[-6:]:
            label = name if len(name) <= 36 else name[:33] + "…"
            lines.append((label, _COLOR_BODY))
    else:
        lines.append(("No settlements approached", _COLOR_DIM))
    return lines


def colonisation_panel_lines(survey: SurveyState) -> list[tuple[str, tuple[int, int, int, int]]]:
    lines: list[tuple[str, tuple[int, int, int, int]]] = [("Colonisation", _COLOR_TITLE)]
    if survey.colonisation_body:
        body = survey.colonisation_body
        if len(body) > 34:
            body = body[:31] + "…"
        lines.append((body, _COLOR_BODY))
    else:
        lines.append(("No claim / depot yet", _COLOR_DIM))
    if survey.colonisation_progress is not None:
        pct = int(round(survey.colonisation_progress * 100))
        lines.append((f"Progress {pct}%", _COLOR_BODY))
    if survey.colonisation_status:
        lines.append((survey.colonisation_status, _COLOR_DIM))
    return lines


def render_survey_bitmap(
    survey: SurveyState,
    *,
    scale: int = 1,
    font_size: int | None = None,
) -> tuple[bytes, int, int]:
    return render_lines_bitmap(survey_panel_lines(survey), scale=scale, font_size=font_size)


def render_bio_bitmap(
    survey: SurveyState,
    location: CommanderLocation,
    *,
    scale: int = 1,
    font_size: int | None = None,
) -> tuple[bytes, int, int]:
    return render_lines_bitmap(
        bio_panel_lines(survey, location),
        scale=scale,
        font_size=font_size,
    )


def render_signals_bitmap(
    survey: SurveyState,
    *,
    scale: int = 1,
    font_size: int | None = None,
) -> tuple[bytes, int, int]:
    return render_lines_bitmap(signals_panel_lines(survey), scale=scale, font_size=font_size)


def render_route_bitmap(
    survey: SurveyState,
    status: StatusSnapshot | None,
    nav_route: NavRouteSnapshot | None,
    *,
    scale: int = 1,
    font_size: int | None = None,
) -> tuple[bytes, int, int]:
    return render_lines_bitmap(
        route_panel_lines(survey, status, nav_route),
        scale=scale,
        font_size=font_size,
    )


def ship_panel_lines(
    survey: SurveyState,
    status: StatusSnapshot | None,
    cargo: CargoSnapshot | None,
) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Pure line layout for the ship / cargo panel (unit-testable)."""
    lines: list[tuple[str, tuple[int, int, int, int]]] = [("Ship", _COLOR_TITLE)]

    ship = survey.ship or "Unknown ship"
    if survey.ship_ident:
        lines.append((f"{ship} [{survey.ship_ident}]", _COLOR_BODY))
    else:
        lines.append((ship, _COLOR_BODY))

    if status is not None:
        mode = status.mode_label()
        legal = status.legal_state or "—"
        mode_fill = _COLOR_ALERT if status.in_danger else _COLOR_BODY
        lines.append((f"{mode} · {legal}", mode_fill))
        if status.low_fuel:
            lines.append(("Low fuel", _COLOR_ALERT))

        fuel_main = status.fuel_main
        cap = survey.fuel_capacity
        if fuel_main is not None:
            if cap:
                lines.append((f"Fuel {fuel_main:.1f} / {cap:.1f} t", _COLOR_BODY))
            else:
                lines.append((f"Fuel {fuel_main:.1f} t", _COLOR_BODY))

        if status.destination:
            lines.append((f"Dest {status.destination}", _COLOR_DIM))
    else:
        lines.append(("Status.json missing", _COLOR_DIM))

    if cargo is not None:
        lines.append((f"Cargo {cargo.count} t · {len(cargo.inventory)} types", _COLOR_BODY))
        top = sorted(cargo.inventory, key=lambda item: item.count, reverse=True)[:4]
        for item in top:
            label = item.name.replace("_", " ")
            lines.append((f"  {label}: {item.count}", _COLOR_DIM))
    elif status is not None and status.cargo_mass is not None:
        lines.append((f"Cargo {status.cargo_mass:.0f} t", _COLOR_BODY))

    return lines


def render_ship_bitmap(
    survey: SurveyState,
    status: StatusSnapshot | None,
    cargo: CargoSnapshot | None,
    *,
    scale: int = 1,
    font_size: int | None = None,
) -> tuple[bytes, int, int]:
    return render_lines_bitmap(
        ship_panel_lines(survey, status, cargo),
        scale=scale,
        font_size=font_size,
    )


def render_materials_bitmap(
    survey: SurveyState,
    *,
    scale: int = 1,
    font_size: int | None = None,
) -> tuple[bytes, int, int]:
    return render_lines_bitmap(materials_panel_lines(survey), scale=scale, font_size=font_size)


def render_locker_bitmap(
    locker: ShipLockerSnapshot | None,
    *,
    scale: int = 1,
    font_size: int | None = None,
) -> tuple[bytes, int, int]:
    return render_lines_bitmap(locker_panel_lines(locker), scale=scale, font_size=font_size)


def render_guardian_bitmap(
    survey: SurveyState,
    *,
    scale: int = 1,
    font_size: int | None = None,
) -> tuple[bytes, int, int]:
    return render_lines_bitmap(guardian_panel_lines(survey), scale=scale, font_size=font_size)


def render_human_bitmap(
    survey: SurveyState,
    *,
    scale: int = 1,
    font_size: int | None = None,
) -> tuple[bytes, int, int]:
    return render_lines_bitmap(human_panel_lines(survey), scale=scale, font_size=font_size)


def render_colonisation_bitmap(
    survey: SurveyState,
    *,
    scale: int = 1,
    font_size: int | None = None,
) -> tuple[bytes, int, int]:
    # Legacy thin panel — prefer render_build_list via host when depot exists.
    return render_lines_bitmap(
        colonisation_panel_lines(survey),
        scale=scale,
        font_size=font_size,
    )
