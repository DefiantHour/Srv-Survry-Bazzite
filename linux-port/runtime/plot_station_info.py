"""Pillow renderer — 1-1 Linux port of PlotStationInfo.

Station rows prefer journal Docked events; when missing, optional Spansh
dump lookup via net_sys_data (honours SRVSURVEY_NET_OFFLINE /
SRVSURVEY_SPANSH_OFFLINE). Layout / colours match PlotStationInfo.cs.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
from dataclasses import dataclass
from pathlib import Path

from companion import StatusSnapshot
from game_settings import GameSettings
from journal import (
    LandingPads,
    StationInfo,
    SurveyState,
    normalize_station_service,
    station_from_docked,
)

try:
    from net_sys_data import find_station_in_dump
except ImportError:  # pragma: no cover
    find_station_in_dump = None  # type: ignore[assignment]

# GameColors
ORANGE = (255, 111, 0, 255)
ORANGE_DARK = (95, 48, 3, 255)
CYAN = (84, 223, 237, 255)
GREEN = (0, 200, 80, 255)
RED = (255, 40, 40, 255)
YELLOW = (255, 220, 40, 255)
STRIPE = (12, 12, 12, 255)

TITLE_PX = 12  # gothic_12B
BODY_PX = 9  # gothic_9
PAD = 8
DEFAULT_WIDTH = 200

# GuiFocus.ExternalPanel (left-hand nav panel)
_GUI_EXTERNAL_PANEL = 2

# Construction-site name prefixes (ColonyData.isConstructionSite)
_CONSTRUCTION_PREFIXES = (
    "Planetary Construction Site:",
    "Orbital Construction Site:",
    "$EXT_PANEL_ColonisationShip",
)

# Spansh / Windows display names for "relevant services"
_INTERESTING_SERVICES = (
    "Shipyard",
    "Outfitting",
    "Refuel",
    "Restock",
    "Repair",
    "Market",
    "Universal Cartographics",
    "Search and Rescue",
    "Interstellar Factors",
    "Material Trader",
    "Black Market",
    "Technology Broker",
)

# CanonnStation.mapShipSizes (pad size 1/2/3 = S/M/L)
_SHIP_SIZES: dict[str, int] = {
    "sidewinder": 1,
    "eagle": 1,
    "hauler": 1,
    "adder": 1,
    "empire_eagle": 1,
    "viper": 1,
    "cobramkiii": 2,
    "viper_mkiv": 2,
    "diamondback": 2,
    "cobramkiv": 1,
    "type6": 2,
    "dolphin": 1,
    "diamondbackxl": 1,
    "empire_courier": 1,
    "independant_trader": 2,
    "asp_scout": 2,
    "vulture": 1,
    "asp": 2,
    "federation_dropship": 2,
    "type7": 3,
    "typex": 2,
    "federation_dropship_mkii": 2,
    "empire_trader": 3,
    "typex_2": 2,
    "typex_3": 2,
    "federation_gunship": 2,
    "krait_light": 2,
    "krait_mkii": 2,
    "orca": 3,
    "ferdelance": 2,
    "mamba": 2,
    "python": 2,
    "python_nx": 2,
    "type8": 2,
    "type9": 3,
    "belugaliner": 3,
    "type9_military": 3,
    "anaconda": 3,
    "federation_corvette": 3,
    "cutter": 3,
    "mandalay": 2,
    "cobramkv": 1,
    "corsair": 2,
    "panthermkii": 3,
    "lakonminer": 2,
    "explorer_nx": 3,
    "smallcombat01_nx": 1,
    "mediumtransport01": 2,
}


@dataclass(frozen=True)
class FactionInfRep:
    """Optional faction influence / reputation (Windows getFactionInfRep)."""

    influence: float | None = None
    reputation: float | None = None
    state: str | None = None


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


def is_construction_site(station_name: str | None) -> bool:
    """ColonyData.isConstructionSite(string) — name prefixes only."""
    if not station_name:
        return False
    for prefix in _CONSTRUCTION_PREFIXES:
        if station_name.lower().startswith(prefix.lower()):
            return True
    return False


def normalize_service(raw: str) -> str:
    return normalize_station_service(raw)


def ship_pad_size(ship_type: str | None) -> int:
    if not ship_type:
        return 0
    return _SHIP_SIZES.get(ship_type.strip().lower(), 0)


def largest_pad(pads: LandingPads | None) -> tuple[str | None, int]:
    if pads is None:
        return None, 0
    if pads.large > 0:
        return "Large", 3
    if pads.medium > 0:
        return "Medium", 2
    if pads.small > 0:
        return "Small", 1
    return None, 0


def stations_from_survey(survey: SurveyState) -> tuple[StationInfo, ...]:
    """Prefer journal Docked stations; fall back to FSS IsStation name stubs."""
    by_name: dict[str, StationInfo] = {}
    for st in survey.stations:
        by_name[st.name] = st
    for sig in survey.fss_signals:
        if not sig.is_station:
            continue
        if sig.name in by_name:
            continue
        by_name[sig.name] = StationInfo(
            name=sig.name,
            station_type=sig.signal_type,
        )
    return tuple(by_name.values())


def find_station_for_destination(
    stations: tuple[StationInfo, ...] | list[StationInfo],
    destination_name: str | None,
    *,
    system_address: int | None = None,
    allow_spansh: bool = True,
) -> StationInfo | None:
    if not destination_name or is_construction_site(destination_name):
        return None
    for st in stations:
        if st.name == destination_name:
            return st
    if (
        allow_spansh
        and find_station_in_dump is not None
        and system_address is not None
        and system_address > 0
    ):
        try:
            return find_station_in_dump(int(system_address), destination_name)
        except Exception:
            return None
    return None


def station_info_allowed(
    game: GameSettings,
    survey: SurveyState,
    status: StatusSnapshot | None,
    *,
    force_show: bool = False,
) -> bool:
    """Match PlotStationInfo.allowed (+ destination/station presence)."""
    if not game.autoShowPlotStationInfo_TEST and not force_show:
        return False
    if survey.system is None and survey.system_address is None:
        return False
    if force_show:
        return True
    gui = status.gui_focus if status is not None else None
    if gui != _GUI_EXTERNAL_PANEL:
        return False
    # Destination must be in this system (Windows: Destination.System == address)
    if status is None or not status.destination:
        return False
    if (
        survey.system_address is not None
        and status.destination_system is not None
        and status.destination_system != survey.system_address
    ):
        return False
    if is_construction_site(status.destination):
        return False
    stations = stations_from_survey(survey)
    return (
        find_station_for_destination(
            stations,
            status.destination,
            system_address=survey.system_address,
        )
        is not None
    )


def reputation_text(rep: float) -> str:
    """Util.getReputationText — coarse English bands."""
    if rep <= -90:
        return "Hostile"
    if rep <= -35:
        return "Unfriendly"
    if rep < 35:
        return "Neutral"
    if rep < 90:
        return "Cordial"
    return "Allied"


def station_info_lines(
    station: StationInfo,
    *,
    ship_type: str | None = None,
    faction: FactionInfRep | None = None,
) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Pure layout rows for tests: (text, colour)."""
    rows: list[tuple[str, tuple[int, int, int, int]]] = []
    rows.append((station.name, ORANGE))

    if station.settlement_economy is not None and station.settlement_subtype is not None:
        rows.append(
            (
                f"{station.station_type or 'Settlement'}: "
                f"{station.settlement_economy} #{station.settlement_subtype}",
                ORANGE,
            )
        )
    elif station.station_type:
        rows.append((station.station_type, ORANGE))

    pad_label, pad_size = largest_pad(station.landing_pads)
    if pad_label is not None:
        ship_size = ship_pad_size(ship_type)
        fits = pad_size >= ship_size if ship_size else True
        mark = " OK" if fits else " NO"
        colour = GREEN if fits else RED
        rows.append((f"Pads: {pad_label}{mark}", colour))

    if station.economies:
        rows.append(("Economy:", ORANGE_DARK))
        for i, (key, pct) in enumerate(
            sorted(station.economies, key=lambda kv: kv[1], reverse=True)
        ):
            colour = CYAN if i < 2 else ORANGE
            rows.append((f"{key}: {pct:.0f}%", colour))
    elif station.primary_economy:
        rows.append((station.primary_economy, ORANGE))

    if station.controlling_faction:
        rows.append(("Faction:", ORANGE_DARK))
        rows.append((station.controlling_faction, ORANGE))
        state = (
            faction.state
            if faction and faction.state
            else station.controlling_faction_state
        )
        if state and state != "None":
            sc = YELLOW if state in ("War", "CivilWar") else ORANGE
            rows.append((f"State: {state}", sc))
        if faction is not None:
            parts: list[str] = []
            if faction.influence is not None:
                parts.append(f"Inf: {faction.influence:.0%}")
            if faction.reputation is not None:
                parts.append(f"Rep: {reputation_text(faction.reputation)}")
            if parts:
                rows.append((" | ".join(parts), ORANGE))

    interesting = [normalize_service(s) for s in station.services]
    shown = [s for s in interesting if s in _INTERESTING_SERVICES]
    if station.government == "Engineer" or "Engineer" in interesting:
        if "Engineer" not in shown:
            shown.append("Engineer")
    if shown:
        rows.append(("Relevant services:", ORANGE_DARK))
        for svc in shown:
            colour = (
                CYAN
                if svc
                in (
                    "Technology Broker",
                    "Material Trader",
                    "Interstellar Factors",
                    "Engineer",
                )
                else ORANGE
            )
            rows.append((f"- {svc}", colour))

    if station.prohibited_commodities:
        rows.append(("Prohibited:", ORANGE_DARK))
        for commodity in station.prohibited_commodities:
            rows.append((f"- {commodity}", ORANGE))

    rows.append(("Data: Spansh.co.uk", ORANGE_DARK))
    if station.update_time:
        # Show date portion of ISO timestamp when present
        updated = station.update_time[:10] if len(station.update_time) >= 10 else station.update_time
        rows.append((f"Updated: {updated}", ORANGE_DARK))
    return rows


def render_station_info_bitmap(
    survey: SurveyState,
    *,
    status: StatusSnapshot | None = None,
    game: GameSettings | None = None,
    ship_type: str | None = None,
    faction: FactionInfRep | None = None,
    force_show: bool = False,
    station: StationInfo | None = None,
    max_width: int = 280,
) -> tuple[bytes, int, int] | None:
    """Render PlotStationInfo. Returns None when not allowed / no station."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    if not station_info_allowed(gs, survey, status, force_show=force_show):
        # force_show with explicit station still renders
        if not (force_show and station is not None):
            return None

    use_station = station
    if use_station is None:
        dest = status.destination if status is not None else None
        use_station = find_station_for_destination(
            stations_from_survey(survey),
            dest,
            system_address=survey.system_address,
        )
    if use_station is None:
        return None

    ship = ship_type or getattr(survey, "ship_type", None) or survey.ship
    rows = station_info_lines(use_station, ship_type=ship, faction=faction)

    font_title = _font(TITLE_PX, bold=True)
    font_body = _font(BODY_PX)
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    content_w = max(
        (_tw(probe, text, font_title if i == 0 else font_body) for i, (text, _) in enumerate(rows)),
        default=_s(DEFAULT_WIDTH),
    )
    width = min(_s(max_width), max(_s(DEFAULT_WIDTH), content_w + _s(24)))
    row_h = _s(14)
    height = _s(12) + len(rows) * row_h + _s(18)

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height)

    y = _s(10)
    for i, (text, colour) in enumerate(rows):
        font = font_title if i == 0 else font_body
        indent = _s(PAD) if i == 0 else _s(18)
        # Section headers at 8px (Faction / Economy / services labels)
        if text.endswith(":") and colour == ORANGE_DARK:
            indent = _s(PAD)
        if text.startswith("- "):
            indent = _s(10)
        if text.startswith("Data:") or text.startswith("Updated:"):
            indent = _s(PAD)
        draw.text((indent, y), text, font=font, fill=colour)
        y += row_h
        # Extra gap after economy block / before services (approx Windows +10)
        if text == use_station.primary_economy or (
            use_station.economies and text.endswith("%") and i + 1 < len(rows)
            and rows[i + 1][0] in ("Faction:", "Relevant services:", "Prohibited:", "Data: Spansh.co.uk")
        ):
            y += _s(6)
        if text in ("Relevant services:", "Prohibited:") or text.startswith("Data:"):
            pass

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
