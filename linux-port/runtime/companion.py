"""Read Elite companion files next to the journals (Status.json, Cargo.json).

These rewrite often while playing. No window, no Wine — plain JSON files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


# StatusFlags bits we surface on the ship HUD (elite-journal Status File).
FLAG_DOCKED = 0x0000_0001
FLAG_LANDED = 0x0000_0002
FLAG_SHIELDS_UP = 0x0000_0008
FLAG_SUPERCRUISE = 0x0000_0010
FLAG_FSD_CHARGING = 0x0002_0000
FLAG_LOW_FUEL = 0x0008_0000
FLAG_HAS_LAT_LONG = 0x0020_0000
FLAG_IN_DANGER = 0x0040_0000
FLAG_IN_MAIN_SHIP = 0x0100_0000
FLAG_IN_FIGHTER = 0x0200_0000
FLAG_IN_SRV = 0x0400_0000
FLAG_HUD_ANALYSIS = 0x0800_0000
FLAG_FSD_JUMP = 0x4000_0000
FLAG_ALTITUDE_FROM_AVERAGE_RADIUS = 0x2000_0000

FLAG2_ON_FOOT = 0x0000_0001
FLAG2_IN_TAXI = 0x0000_0002
FLAG2_GLIDE_MODE = 0x0000_1000
FLAG2_FSD_CHARGING_JUMP = 0x0008_0000

# GuiFocus values used by plotter allow() checks (elite-journal Status.GuiFocus)
GUI_FOCUS_INTERNAL_PANEL = 1
GUI_FOCUS_EXTERNAL_PANEL = 2
GUI_FOCUS_ROLE_PANEL = 4
GUI_FOCUS_STATION_SERVICES = 5
GUI_FOCUS_GALAXY_MAP = 6
GUI_FOCUS_SYSTEM_MAP = 7
GUI_FOCUS_ORRERY = 8
GUI_FOCUS_FSS = 9
GUI_FOCUS_SAA = 10


@dataclass(frozen=True)
class StatusSnapshot:
    flags: int
    flags2: int
    fuel_main: float | None
    fuel_reservoir: float | None
    cargo_mass: float | None
    legal_state: str | None
    balance: int | None
    destination: str | None
    body_name: str | None
    gui_focus: int | None
    destination_system: int | None = None
    destination_body: int | None = None
    fire_group: int = 0
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None
    heading: float | None = None
    planet_radius: float | None = None

    @property
    def docked(self) -> bool:
        return bool(self.flags & FLAG_DOCKED)

    @property
    def landed(self) -> bool:
        return bool(self.flags & FLAG_LANDED)

    @property
    def supercruise(self) -> bool:
        return bool(self.flags & FLAG_SUPERCRUISE)

    @property
    def fsd_charging(self) -> bool:
        return bool(self.flags & FLAG_FSD_CHARGING)

    @property
    def fsd_charging_jump(self) -> bool:
        return bool(self.flags2 & FLAG2_FSD_CHARGING_JUMP)

    @property
    def low_fuel(self) -> bool:
        return bool(self.flags & FLAG_LOW_FUEL)

    @property
    def in_danger(self) -> bool:
        return bool(self.flags & FLAG_IN_DANGER)

    @property
    def shields_up(self) -> bool:
        return bool(self.flags & FLAG_SHIELDS_UP)

    @property
    def in_srv(self) -> bool:
        return bool(self.flags & FLAG_IN_SRV)

    @property
    def in_fighter(self) -> bool:
        return bool(self.flags & FLAG_IN_FIGHTER)

    @property
    def on_foot(self) -> bool:
        return bool(self.flags2 & FLAG2_ON_FOOT)

    @property
    def in_taxi(self) -> bool:
        return bool(self.flags2 & FLAG2_IN_TAXI)

    @property
    def in_main_ship(self) -> bool:
        return bool(self.flags & FLAG_IN_MAIN_SHIP)

    @property
    def has_lat_long(self) -> bool:
        return bool(self.flags & FLAG_HAS_LAT_LONG)

    @property
    def altitude_from_average_radius(self) -> bool:
        return bool(self.flags & FLAG_ALTITUDE_FROM_AVERAGE_RADIUS)

    @property
    def hud_in_analysis_mode(self) -> bool:
        return bool(self.flags & FLAG_HUD_ANALYSIS)

    @property
    def glide_mode(self) -> bool:
        return bool(self.flags2 & FLAG2_GLIDE_MODE)

    @property
    def fsd_jumping(self) -> bool:
        return bool(self.flags & FLAG_FSD_JUMP)

    @property
    def in_system_map(self) -> bool:
        return self.gui_focus in (GUI_FOCUS_SYSTEM_MAP, GUI_FOCUS_ORRERY)

    @property
    def in_saa(self) -> bool:
        return self.gui_focus == GUI_FOCUS_SAA

    def is_flying_or_supercruise(self) -> bool:
        """Match Windows GameMode.Flying / SuperCruising for PlotJumpInfo.allowed."""
        if self.supercruise:
            return True
        if self.docked or self.landed or self.on_foot or self.in_srv or self.in_fighter:
            return False
        return self.in_main_ship

    def mode_label(self) -> str:
        if self.on_foot:
            return "On Foot"
        if self.in_srv:
            return "SRV"
        if self.in_fighter:
            return "Fighter"
        if self.docked:
            return "Docked"
        if self.landed:
            return "Landed"
        if self.supercruise:
            return "Supercruise"
        if self.flags & FLAG_IN_MAIN_SHIP:
            return "Ship"
        return "Unknown"


@dataclass(frozen=True)
class CargoItem:
    name: str
    count: int
    stolen: int = 0
    key: str = ""


@dataclass(frozen=True)
class CargoSnapshot:
    vessel: str | None
    count: int
    inventory: tuple[CargoItem, ...]


def parse_status(text: str) -> StatusSnapshot | None:
    try:
        entry = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(entry, dict):
        return None
    fuel = entry.get("Fuel") if isinstance(entry.get("Fuel"), dict) else {}
    dest = entry.get("Destination") if isinstance(entry.get("Destination"), dict) else {}
    dest_name = dest.get("Name")
    dest_system = dest.get("System")
    dest_body = dest.get("Body")
    fuel_main = fuel.get("FuelMain")
    fuel_res = fuel.get("FuelReservoir")
    cargo = entry.get("Cargo")
    balance = entry.get("Balance")
    gui = entry.get("GuiFocus")
    fire = entry.get("FireGroup")
    lat = entry.get("Latitude")
    lon = entry.get("Longitude")
    alt = entry.get("Altitude")
    heading = entry.get("Heading")
    radius = entry.get("PlanetRadius")
    return StatusSnapshot(
        flags=int(entry.get("Flags") or 0),
        flags2=int(entry.get("Flags2") or 0),
        fuel_main=float(fuel_main) if isinstance(fuel_main, (int, float)) else None,
        fuel_reservoir=float(fuel_res) if isinstance(fuel_res, (int, float)) else None,
        cargo_mass=float(cargo) if isinstance(cargo, (int, float)) else None,
        legal_state=entry.get("LegalState") if isinstance(entry.get("LegalState"), str) else None,
        balance=int(balance) if isinstance(balance, (int, float)) else None,
        destination=dest_name if isinstance(dest_name, str) and dest_name else None,
        body_name=entry.get("BodyName") if isinstance(entry.get("BodyName"), str) else None,
        gui_focus=int(gui) if isinstance(gui, (int, float)) else None,
        destination_system=int(dest_system)
        if isinstance(dest_system, (int, float)) and int(dest_system) > 0
        else None,
        destination_body=int(dest_body) if isinstance(dest_body, (int, float)) else None,
        fire_group=int(fire) if isinstance(fire, (int, float)) else 0,
        latitude=float(lat) if isinstance(lat, (int, float)) else None,
        longitude=float(lon) if isinstance(lon, (int, float)) else None,
        altitude=float(alt) if isinstance(alt, (int, float)) else None,
        heading=float(heading) if isinstance(heading, (int, float)) else None,
        planet_radius=float(radius) if isinstance(radius, (int, float)) else None,
    )


def read_status_file(path: Path) -> StatusSnapshot | None:
    if not path.is_file():
        return None
    return parse_status(path.read_text(encoding="utf-8", errors="replace"))


def parse_cargo(text: str) -> CargoSnapshot | None:
    try:
        entry = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(entry, dict):
        return None
    inventory_raw = entry.get("Inventory")
    items: list[CargoItem] = []
    if isinstance(inventory_raw, list):
        for row in inventory_raw:
            if not isinstance(row, dict):
                continue
            raw = row.get("Name")
            local = row.get("Name_Localised")
            display = local if isinstance(local, str) and local else raw
            key = raw if isinstance(raw, str) and raw else display
            count = row.get("Count")
            if not isinstance(display, str) or not display:
                continue
            if not isinstance(count, (int, float)):
                continue
            stolen = row.get("Stolen")
            items.append(
                CargoItem(
                    name=display,
                    count=int(count),
                    stolen=int(stolen) if isinstance(stolen, (int, float)) else 0,
                    key=str(key) if isinstance(key, str) else display,
                )
            )
    vessel = entry.get("Vessel") if isinstance(entry.get("Vessel"), str) else None
    count = entry.get("Count")
    return CargoSnapshot(
        vessel=vessel,
        count=int(count) if isinstance(count, (int, float)) else sum(i.count for i in items),
        inventory=tuple(items),
    )


def read_cargo_file(path: Path) -> CargoSnapshot | None:
    if not path.is_file():
        return None
    return parse_cargo(path.read_text(encoding="utf-8", errors="replace"))


@dataclass(frozen=True)
class LockerItem:
    name: str
    count: int
    category: str  # Items | Components | Consumables | Data


@dataclass(frozen=True)
class ShipLockerSnapshot:
    """Odyssey ship locker / backpack summary from companion JSON."""

    items: tuple[LockerItem, ...]
    components: tuple[LockerItem, ...]
    consumables: tuple[LockerItem, ...]
    data: tuple[LockerItem, ...]

    @property
    def total_count(self) -> int:
        return sum(
            stack.count
            for stack in self.items + self.components + self.consumables + self.data
        )

    def category_totals(self) -> tuple[tuple[str, int], ...]:
        return (
            ("Items", sum(i.count for i in self.items)),
            ("Components", sum(i.count for i in self.components)),
            ("Consumables", sum(i.count for i in self.consumables)),
            ("Data", sum(i.count for i in self.data)),
        )


@dataclass(frozen=True)
class RouteHop:
    """One NavRoute.json Route[] row — enough for PlotJumpInfo hop distances."""

    star_system: str
    system_address: int | None = None
    star_class: str | None = None
    star_pos: tuple[float, float, float] | None = None


@dataclass(frozen=True)
class NavRouteSnapshot:
    """Galactic route from NavRoute.json (empty when no plot)."""

    route: tuple[RouteHop, ...] = ()

    @property
    def hops(self) -> tuple[str, ...]:
        """System names only (legacy panel.py consumers)."""
        return tuple(hop.star_system for hop in self.route)

    @property
    def remaining(self) -> int:
        return max(0, len(self.route) - 1)


def _parse_locker_list(rows: object, category: str) -> list[LockerItem]:
    items: list[LockerItem] = []
    if not isinstance(rows, list):
        return items
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("Name_Localised") or row.get("Name")
        count = row.get("Count")
        if not isinstance(name, str) or not name:
            continue
        if not isinstance(count, (int, float)):
            continue
        items.append(
            LockerItem(
                name=str(name).replace("_", " "),
                count=int(count),
                category=category,
            )
        )
    return items


def parse_ship_locker(text: str) -> ShipLockerSnapshot | None:
    try:
        entry = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(entry, dict):
        return None
    return ShipLockerSnapshot(
        items=tuple(_parse_locker_list(entry.get("Items"), "Items")),
        components=tuple(_parse_locker_list(entry.get("Components"), "Components")),
        consumables=tuple(_parse_locker_list(entry.get("Consumables"), "Consumables")),
        data=tuple(_parse_locker_list(entry.get("Data"), "Data")),
    )


def read_ship_locker_file(path: Path) -> ShipLockerSnapshot | None:
    if not path.is_file():
        return None
    return parse_ship_locker(path.read_text(encoding="utf-8", errors="replace"))


def _parse_star_pos(raw: object) -> tuple[float, float, float] | None:
    if not isinstance(raw, list) or len(raw) < 3:
        return None
    try:
        return (float(raw[0]), float(raw[1]), float(raw[2]))
    except (TypeError, ValueError):
        return None


def parse_nav_route(text: str) -> NavRouteSnapshot | None:
    try:
        entry = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(entry, dict):
        return None
    hops: list[RouteHop] = []
    route = entry.get("Route")
    if isinstance(route, list):
        for row in route:
            if not isinstance(row, dict):
                continue
            name = row.get("StarSystem")
            if not isinstance(name, str) or not name:
                continue
            addr = row.get("SystemAddress")
            star_class = row.get("StarClass")
            hops.append(
                RouteHop(
                    star_system=name,
                    system_address=int(addr) if isinstance(addr, (int, float)) else None,
                    star_class=star_class if isinstance(star_class, str) else None,
                    star_pos=_parse_star_pos(row.get("StarPos")),
                )
            )
    return NavRouteSnapshot(route=tuple(hops))


def read_nav_route_file(path: Path) -> NavRouteSnapshot | None:
    if not path.is_file():
        return None
    return parse_nav_route(path.read_text(encoding="utf-8", errors="replace"))


def companion_paths(journal_folder: Path) -> tuple[Path, Path]:
    return journal_folder / "Status.json", journal_folder / "Cargo.json"


def extended_companion_paths(journal_folder: Path) -> dict[str, Path]:
    return {
        "status": journal_folder / "Status.json",
        "cargo": journal_folder / "Cargo.json",
        "locker": journal_folder / "ShipLocker.json",
        "backpack": journal_folder / "Backpack.json",
        "navroute": journal_folder / "NavRoute.json",
    }
