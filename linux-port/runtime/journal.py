"""Read the bits of an Elite journal the overlay needs. No window, no Wine."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

from body_value import get_body_value_from_scan


LOCATION_EVENTS = frozenset({"Location", "FSDJump", "CarrierJump"})
BIO_SIGNAL_TYPE = "$SAA_SignalType_Biological;"
GEO_SIGNAL_TYPE = "$SAA_SignalType_Geological;"
# Cap how many live FSS / codex rows we keep for HUD panels.
MAX_FSS_SIGNALS = 12
MAX_CODEX_ENTRIES = 8
MAX_GUARDIAN_SITES = 8

_CONSTRUCTION_PREFIXES = (
    "planetary construction site:",
    "orbital construction site:",
    "$ext_panel_colonisationship",
)


def is_construction_station_name(name: str | None) -> bool:
    """ColonyData.isConstructionSite(string) — name prefixes only."""
    if not isinstance(name, str) or not name:
        return False
    lower = name.lower()
    return any(lower.startswith(prefix) for prefix in _CONSTRUCTION_PREFIXES)


def _is_human_settlement_entry(entry: dict) -> bool:
    """Match Game.onJournalEntry(ApproachSettlement) Odyssey site filters."""
    raw = entry.get("Name")
    if not isinstance(raw, str) or not raw:
        return False
    if raw.startswith("$Ancient"):
        return False
    market = entry.get("MarketID")
    if not isinstance(market, (int, float)) or int(market) <= 0:
        return False
    services = entry.get("StationServices")
    if not isinstance(services, list) or len(services) == 0:
        return False
    if "socialspace" in services:
        return False
    if entry.get("StationGovernment") == "$government_Engineer;":
        return False
    name_l = raw.lower()
    if "colonisationcontribution" in services and any(
        name_l.startswith(p) for p in _CONSTRUCTION_PREFIXES
    ):
        return False
    lat = entry.get("Latitude")
    lon = entry.get("Longitude")
    return isinstance(lat, (int, float)) and isinstance(lon, (int, float))


def _human_station_from_approach(
    entry: dict,
    faction_stats: dict[str, tuple[float | None, float | None]],
) -> HumanStation | None:
    if not _is_human_settlement_entry(entry):
        return None
    name = entry.get("Name_Localised") or entry.get("Name")
    if not isinstance(name, str) or not name:
        return None
    faction = entry.get("StationFaction")
    faction_name = None
    faction_state = None
    if isinstance(faction, dict):
        fn = faction.get("Name")
        if isinstance(fn, str):
            faction_name = fn
        fs = faction.get("FactionState")
        if isinstance(fs, str):
            faction_state = fs
    services_raw = entry.get("StationServices")
    services: list[str] = []
    if isinstance(services_raw, list):
        services = [s for s in services_raw if isinstance(s, str)]
    influence = None
    reputation = None
    if faction_name and faction_name in faction_stats:
        reputation, influence = faction_stats[faction_name]
    addr = entry.get("SystemAddress")
    body_id = entry.get("BodyID")
    body_name = entry.get("BodyName")
    return HumanStation(
        name=name,
        market_id=int(entry["MarketID"]),
        latitude=float(entry["Latitude"]),
        longitude=float(entry["Longitude"]),
        system_address=int(addr) if isinstance(addr, (int, float)) else None,
        body_id=int(body_id) if isinstance(body_id, (int, float)) else None,
        body_name=body_name if isinstance(body_name, str) else None,
        economy=entry.get("StationEconomy")
        if isinstance(entry.get("StationEconomy"), str)
        else None,
        economy_localized=entry.get("StationEconomy_Localised")
        if isinstance(entry.get("StationEconomy_Localised"), str)
        else None,
        government=entry.get("StationGovernment")
        if isinstance(entry.get("StationGovernment"), str)
        else None,
        government_localized=entry.get("StationGovernment_Localised")
        if isinstance(entry.get("StationGovernment_Localised"), str)
        else None,
        faction_name=faction_name,
        faction_state=faction_state,
        influence=influence,
        reputation=reputation,
        station_services=tuple(services),
    )


def _ingest_faction_stats(
    entry: dict,
    system_address: int | None,
    faction_stats: dict[str, tuple[float | None, float | None]],
) -> None:
    addr = entry.get("SystemAddress")
    if system_address is not None and isinstance(addr, (int, float)):
        if int(addr) != system_address:
            return
    factions = entry.get("Factions")
    if not isinstance(factions, list):
        return
    for row in factions:
        if not isinstance(row, dict):
            continue
        name = row.get("Name")
        if not isinstance(name, str) or not name:
            continue
        rep = row.get("MyReputation")
        inf = row.get("Influence")
        faction_stats[name] = (
            float(rep) if isinstance(rep, (int, float)) else None,
            float(inf) if isinstance(inf, (int, float)) else None,
        )


# Guardian structure settlement Name → (SiteType, blue print label)
_STRUCTURE_FROM_NAME: dict[str, tuple[str, str | None]] = {
    "$Ancient_Tiny_001": ("Lacrosse", None),
    "$Ancient_Tiny_002": ("Crossroads", None),
    "$Ancient_Tiny_003": ("Fistbump", None),
    "$Ancient_Small_001": ("Hammerbot", "Weapon"),
    "$Ancient_Small_002": ("Bear", "Weapon"),
    "$Ancient_Small_003": ("Bowl", "Weapon"),
    "$Ancient_Small_005": ("Turtle", "Module"),
    "$Ancient_Medium_001": ("Robolobster", "Fighter"),
    "$Ancient_Medium_002": ("Squid", "Fighter"),
    "$Ancient_Medium_003": ("Stickyhand", "Fighter"),
}


@dataclass(frozen=True)
class GuardianSiteSummary:
    """SystemSettlementSummary stand-in for PlotGuardianSystem / Status."""

    name: str
    display_text: str
    body_name: str | None = None
    body_id: int | None = None
    is_ruins: bool = False
    index: int | None = None
    site_type: str | None = None
    blue_print: str | None = None
    status: str | None = None
    extra: str | None = None


def _parse_guardian_settlement(
    raw_name: str,
    localised: str | None,
    body_name: str | None,
    body_id: int | None,
    system_name: str | None,
) -> GuardianSiteSummary | None:
    """Build a summary from ApproachSettlement Name ($Ancient…)."""
    if not raw_name.startswith("$Ancient"):
        return None
    body_short = body_name or ""
    if system_name and body_short.startswith(system_name):
        body_short = body_short[len(system_name) :].strip() or body_short

    # Ruins: $Ancient:#index=2;
    if raw_name.startswith("$Ancient:#") or raw_name.startswith("$Ancient:#index="):
        idx = None
        if "index=" in raw_name:
            try:
                idx = int(raw_name.split("index=", 1)[1].split(";", 1)[0])
            except ValueError:
                idx = None
        label = localised or "Ruins"
        display = f"{body_short}: Ruins #{idx}" if idx else f"{body_short}: {label}"
        return GuardianSiteSummary(
            name=raw_name,
            display_text=display.strip(": ") if not body_short else display,
            body_name=body_name,
            body_id=body_id,
            is_ruins=True,
            index=idx,
            site_type=None,
            status="Not started",
        )

    # Structure: $Ancient_Tiny_001:#index=1;
    key = raw_name.split(":#", 1)[0]
    site_type, blue = _STRUCTURE_FROM_NAME.get(key, (None, None))
    type_label = site_type or (localised or key.replace("$", "").replace("_", " "))
    display = f"{body_short}: {type_label}" if body_short else str(type_label)
    return GuardianSiteSummary(
        name=raw_name,
        display_text=display,
        body_name=body_name,
        body_id=body_id,
        is_ruins=False,
        index=1,
        site_type=site_type,
        blue_print=blue,
        status="Not started",
    )


@dataclass(frozen=True)
class CommanderLocation:
    system: str | None
    commander: str | None
    body: str | None
    fid: str | None = None


@dataclass(frozen=True)
class OrganicProgress:
    """ScanOrganic progress for one genus on a body (Log → Sample → Analyse)."""

    genus: str
    species: str | None = None
    scan_type: str | None = None  # Log | Sample | Analyse
    body_name: str | None = None

    @property
    def step(self) -> int:
        order = {"Log": 1, "Sample": 2, "Analyse": 3}
        return order.get(self.scan_type or "", 0)


@dataclass(frozen=True)
class BodySignals:
    body_name: str
    bio_count: int
    geo_count: int
    genuses: tuple[str, ...] = ()


@dataclass(frozen=True)
class FssBodyEntry:
    """One scanned body for PlotFSSInfo / PlotBodyInfo (newest scans first)."""

    body_id: int
    body_name: str
    short_name: str
    body_type: str  # Star | Giant | LandableBody | SolidBody | Asteroid | …
    planet_class: str | None = None
    star_type: str | None = None
    terraformable: bool = False
    landable: bool = False
    was_discovered: bool = True
    was_mapped: bool = True
    first_footfall: bool = False
    distance_from_arrival_ls: float = 0.0
    reward: int = 0
    dss_reward: int = 0
    dss_complete: bool = False
    bio_signal_count: int = 0
    geo_signal_count: int = 0
    analyzed_bio_count: int = 0
    geo_analyzed: bool = False
    scanned: bool = True
    is_main_star: bool = False
    # PlotBodyInfo Scan fields (absent until a Detailed Scan is seen)
    mass: float = 0.0
    surface_gravity: float = 0.0
    surface_temperature: float = 0.0
    surface_pressure: float = 0.0
    atmosphere: str | None = None
    atmosphere_type: str | None = None
    atmosphere_composition: tuple[tuple[str, float], ...] = ()
    volcanism: str | None = None
    materials: tuple[tuple[str, float], ...] = ()
    rings: tuple[tuple[str, str], ...] = ()  # (ring name, ring class)


@dataclass(frozen=True)
class SystemSignal:
    """One FSSSignalDiscovered row for the current system."""

    name: str
    signal_type: str | None = None
    threat_level: int | None = None
    is_station: bool = False


@dataclass(frozen=True)
class CodexFind:
    """Recent CodexEntry for the current system (newest last in the tuple)."""

    name: str
    category: str | None = None
    subcategory: str | None = None
    is_new: bool = False


@dataclass(frozen=True)
class TrackerBookmark:
    """Surface bookmark from CodexEntry organics (PlotTrackers / autoTrackCompBioScans)."""

    name: str
    latitude: float
    longitude: float
    body_name: str | None = None
    entry_id: int | None = None


MASSACRE_MISSION_NAMES = frozenset({"Mission_Massacre", "Mission_MassacreWing"})


@dataclass(frozen=True)
class TrackMassacre:
    """Active massacre mission (PlotMassacre / CommanderSettings.trackMassacres)."""

    mission_id: int
    mission_giver: str
    target_faction: str
    expires: str | None = None
    kill_count: int = 0
    remaining: int = 0


@dataclass(frozen=True)
class MaterialStack:
    name: str
    count: int
    category: str  # Raw | Manufactured | Encoded


@dataclass(frozen=True)
class MaterialsSnapshot:
    """Commander materials from the journal Materials event (startup)."""

    raw: tuple[MaterialStack, ...] = ()
    manufactured: tuple[MaterialStack, ...] = ()
    encoded: tuple[MaterialStack, ...] = ()

    @property
    def all_stacks(self) -> tuple[MaterialStack, ...]:
        return self.raw + self.manufactured + self.encoded

    def top(self, limit: int = 5) -> tuple[MaterialStack, ...]:
        ranked = sorted(self.all_stacks, key=lambda item: item.count, reverse=True)
        return tuple(ranked[:limit])


def _material_bucket(category: object) -> str:
    text = str(category or "").lower()
    if "manufact" in text:
        return "Manufactured"
    if "encoded" in text or "data" in text:
        return "Encoded"
    return "Raw"


def bump_materials(
    snapshot: MaterialsSnapshot | None,
    name: str,
    delta: int,
    category: object = "Raw",
) -> MaterialsSnapshot:
    """Apply MaterialCollected / MaterialDiscarded onto a Materials snapshot."""
    snap = snapshot or MaterialsSnapshot()
    bucket = _material_bucket(category)
    rows = {
        "Raw": list(snap.raw),
        "Manufactured": list(snap.manufactured),
        "Encoded": list(snap.encoded),
    }
    stacks = rows[bucket]
    key = name.strip().lower()
    found = False
    updated: list[MaterialStack] = []
    for stack in stacks:
        if stack.name.strip().lower() == key:
            found = True
            count = max(0, stack.count + delta)
            if count:
                updated.append(MaterialStack(stack.name, count, bucket))
        else:
            updated.append(stack)
    if not found and delta > 0 and name.strip():
        updated.append(MaterialStack(_pretty_material_name(name), delta, bucket))
    rows[bucket] = updated
    return MaterialsSnapshot(
        raw=tuple(rows["Raw"]),
        manufactured=tuple(rows["Manufactured"]),
        encoded=tuple(rows["Encoded"]),
    )


@dataclass(frozen=True)
class LandingPads:
    small: int = 0
    medium: int = 0
    large: int = 0


@dataclass(frozen=True)
class StationInfo:
    """Spansh Station subset + journal Docked fields (PlotStationInfo)."""

    name: str
    station_id: int = 0
    station_type: str | None = None
    primary_economy: str | None = None
    economies: tuple[tuple[str, float], ...] = ()
    controlling_faction: str | None = None
    controlling_faction_state: str | None = None
    government: str | None = None
    services: tuple[str, ...] = ()
    landing_pads: LandingPads | None = None
    prohibited_commodities: tuple[str, ...] = ()
    update_time: str | None = None
    settlement_economy: str | None = None
    settlement_subtype: int | None = None


@dataclass(frozen=True)
class HumanStation:
    """Odyssey settlement for PlotHumanSite (CanonnStation subset + approach UI)."""

    name: str
    market_id: int
    latitude: float
    longitude: float
    system_address: int | None = None
    body_id: int | None = None
    body_name: str | None = None
    economy: str | None = None
    economy_localized: str | None = None
    government: str | None = None
    government_localized: str | None = None
    faction_name: str | None = None
    faction_state: str | None = None
    influence: float | None = None
    reputation: float | None = None
    station_services: tuple[str, ...] = ()
    heading: float = -1.0
    sub_type: int = 0
    template_name: str | None = None
    docking_state: str = "none"  # none|requested|denied|approved|landed
    granted_pad: int = 0
    denied_reason: str | None = None
    has_landed: bool = False
    docking_in_progress: bool = False
    music_track: str | None = None


# Journal Docked StationServices → Spansh-style labels
_SERVICE_ALIASES: dict[str, str] = {
    "shipyard": "Shipyard",
    "outfitting": "Outfitting",
    "refuel": "Refuel",
    "rearm": "Restock",
    "restock": "Restock",
    "repair": "Repair",
    "commodities": "Market",
    "market": "Market",
    "exploration": "Universal Cartographics",
    "searchrescue": "Search and Rescue",
    "facilitator": "Interstellar Factors",
    "materialtrader": "Material Trader",
    "blackmarket": "Black Market",
    "techbroker": "Technology Broker",
    "engineer": "Engineer",
}


def normalize_station_service(raw: str) -> str:
    key = raw.strip()
    if not key:
        return key
    return _SERVICE_ALIASES.get(key.lower(), key)


def station_from_docked(entry: dict) -> StationInfo | None:
    """Build StationInfo from a journal Docked event dict."""
    name = entry.get("StationName")
    if not isinstance(name, str) or not name:
        return None
    market_id = entry.get("MarketID")
    sid = int(market_id) if isinstance(market_id, (int, float)) else 0
    stype = entry.get("StationType")
    eco = entry.get("StationEconomy_Localised") or entry.get("StationEconomy")
    if isinstance(eco, str) and eco.startswith("$") and eco.endswith(";"):
        eco = eco[1:-1].replace("economy_", "").replace("_", " ")
    gov = entry.get("StationGovernment_Localised") or entry.get("StationGovernment")
    if isinstance(gov, str) and gov.startswith("$") and gov.endswith(";"):
        gov = gov[1:-1].replace("government_", "").replace("_", " ")

    faction = None
    faction_state = None
    fac = entry.get("StationFaction")
    if isinstance(fac, dict):
        fname = fac.get("Name")
        if isinstance(fname, str) and fname:
            faction = fname
        fstate = fac.get("FactionState")
        if isinstance(fstate, str) and fstate and fstate != "None":
            faction_state = fstate

    economies: list[tuple[str, float]] = []
    for row in entry.get("StationEconomies") or []:
        if not isinstance(row, dict):
            continue
        label = row.get("Name_Localised") or row.get("Name")
        prop = row.get("Proportion")
        if not isinstance(label, str):
            continue
        if label.startswith("$") and label.endswith(";"):
            label = label[1:-1].replace("economy_", "").replace("_", " ")
        pct = float(prop) * 100.0 if isinstance(prop, (int, float)) else 0.0
        economies.append((label, pct))

    services: list[str] = []
    for svc in entry.get("StationServices") or []:
        if isinstance(svc, str) and svc:
            services.append(normalize_station_service(svc))

    pads = None
    raw_pads = entry.get("LandingPads")
    if isinstance(raw_pads, dict):
        pads = LandingPads(
            small=int(raw_pads.get("Small") or 0),
            medium=int(raw_pads.get("Medium") or 0),
            large=int(raw_pads.get("Large") or 0),
        )

    ts = entry.get("timestamp")
    return StationInfo(
        name=name,
        station_id=sid,
        station_type=stype if isinstance(stype, str) else None,
        primary_economy=eco if isinstance(eco, str) else None,
        economies=tuple(economies),
        controlling_faction=faction,
        controlling_faction_state=faction_state,
        government=gov if isinstance(gov, str) else None,
        services=tuple(dict.fromkeys(services)),
        landing_pads=pads,
        update_time=ts if isinstance(ts, str) else None,
    )


@dataclass(frozen=True)
class SurveyState:
    """Exploration progress for the current system, from journal events alone."""

    system: str | None = None
    system_address: int | None = None
    star_pos: tuple[float, float, float] | None = None
    fss_progress: float | None = None
    body_count: int | None = None
    non_body_count: int | None = None
    fss_complete: bool = False
    scanned_body_ids: frozenset[int] = field(default_factory=frozenset)
    mapped_body_ids: frozenset[int] = field(default_factory=frozenset)
    body_signals: tuple[BodySignals, ...] = ()
    fss_bodies: tuple[FssBodyEntry, ...] = ()
    organic_scans: int = 0
    organic_progress: tuple[OrganicProgress, ...] = ()
    organic_sales: int = 0
    organic_sale_value: int = 0
    fss_signals: tuple[SystemSignal, ...] = ()
    codex_entries: tuple[CodexFind, ...] = ()
    # PlotTrackers — CodexEntry organics with lat/long (Windows bookmarks)
    bookmarks: tuple[TrackerBookmark, ...] = ()
    materials: MaterialsSnapshot | None = None
    ship: str | None = None
    ship_type: str | None = None  # internal Ship id for pad-size lookup
    ship_ident: str | None = None
    cargo_capacity: int | None = None
    fuel_capacity: float | None = None
    last_carrier_jump: str | None = None
    carrier_name: str | None = None
    guardian_signals: tuple[str, ...] = ()
    guardian_codex: int = 0
    guardian_sites: tuple[GuardianSiteSummary, ...] = ()
    current_guardian_site: GuardianSiteSummary | None = None
    settlements: tuple[str, ...] = ()
    stations: tuple[StationInfo, ...] = ()
    system_station: HumanStation | None = None
    colonisation_body: str | None = None
    colonisation_progress: float | None = None
    colonisation_status: str | None = None
    # PlotJumpInfo — FSDTarget / StartJump / FSDJump from journal
    fsd_jumping: bool = False
    fsd_target_name: str | None = None
    fsd_target_address: int | None = None
    fsd_target_star_class: str | None = None
    fsd_remaining_jumps: int | None = None
    # PlotMassacre — commander-scoped (survives system changes)
    track_massacres: tuple[TrackMassacre, ...] = ()
    # PlotMiniTrack Rhino — last LaunchSRV type
    srv_type: str | None = None
    # PlotFootCombat — FactionKillBond while at War / CivilWar settlement
    foot_combat_kills: int = 0
    foot_combat_credits: int = 0
    # Docked / Undocked / Liftoff / Touchdown / Supercruise / Died
    docked: bool = False
    docked_station: str | None = None
    # Windows Game.lastDocked — name survives Undocked until the next Docked.
    last_docked_station: str | None = None
    # Last construction-site name; not overwritten by a later Fleet Carrier dock.
    last_construction_station: str | None = None
    last_docking_station: str | None = None
    docking_in_progress: bool = False
    in_supercruise: bool = False
    landed: bool = False
    died: bool = False
    barycentre_ids: frozenset[int] = field(default_factory=frozenset)

    @property
    def scanned_count(self) -> int:
        return len(self.scanned_body_ids)

    @property
    def mapped_count(self) -> int:
        return len(self.mapped_body_ids)

    @property
    def total_bio_signals(self) -> int:
        return sum(b.bio_count for b in self.body_signals)

    @property
    def total_geo_signals(self) -> int:
        return sum(b.geo_count for b in self.body_signals)

    @property
    def bio_body_count(self) -> int:
        return sum(1 for b in self.body_signals if b.bio_count > 0)

    @property
    def geo_body_count(self) -> int:
        return sum(1 for b in self.body_signals if b.geo_count > 0)


@dataclass(frozen=True)
class SessionSnapshot:
    location: CommanderLocation
    survey: SurveyState


def latest_journal_file(folder: Path) -> Path | None:
    files = [path for path in folder.glob("Journal.*.log") if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda path: path.name)


def read_location(text: str) -> CommanderLocation:
    return read_session(text).location


def read_location_file(path: Path) -> CommanderLocation:
    return read_location(path.read_text(encoding="utf-8", errors="replace"))


def _pretty_material_name(name: str) -> str:
    return name.replace("_", " ").strip() or name


def _parse_material_list(rows: object, category: str) -> list[MaterialStack]:
    items: list[MaterialStack] = []
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
            MaterialStack(
                name=_pretty_material_name(name),
                count=int(count),
                category=category,
            )
        )
    return items


def _signal_display_name(entry: dict) -> str | None:
    name = entry.get("SignalName_Localised") or entry.get("SignalName")
    if isinstance(name, str) and name:
        return name
    return None


def _codex_display_name(entry: dict) -> str | None:
    name = entry.get("Name_Localised") or entry.get("Name")
    if isinstance(name, str) and name:
        return name
    return None


def _body_type_from(
    star_type: str | None,
    planet_class: str | None,
    landable: bool,
    body_name: str,
) -> str:
    if landable:
        return "LandableBody"
    if star_type:
        return "Star"
    lower = body_name.lower()
    if "cluster" in lower:
        return "Asteroid"
    if body_name.endswith("Ring"):
        return "PlanetaryRing"
    if not star_type and not planet_class:
        return "Barycentre"
    if planet_class and "giant" in planet_class.lower():
        return "Giant"
    return "SolidBody"


def _short_body_name(body_name: str, system: str | None) -> str:
    if system and body_name.startswith(system):
        short = body_name[len(system) :].replace(" ", "")
        return short or "0"
    return body_name.replace(" ", "")


def _replace_fss_body(bodies: list[FssBodyEntry], updated: FssBodyEntry) -> None:
    """Pull updated body to front (PlotFSSInfo Insert(0) behaviour)."""
    bodies[:] = [b for b in bodies if b.body_id != updated.body_id]
    bodies.insert(0, updated)


def _parse_star_pos(raw: object) -> tuple[float, float, float] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return None
    try:
        return (float(raw[0]), float(raw[1]), float(raw[2]))
    except (TypeError, ValueError):
        return None


def _parse_named_percents(rows: object) -> tuple[tuple[str, float], ...]:
    out: list[tuple[str, float]] = []
    if not isinstance(rows, list):
        return ()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("Name")
        pct = row.get("Percent")
        if not isinstance(name, str) or not name:
            continue
        if not isinstance(pct, (int, float)):
            continue
        out.append((name, float(pct)))
    return tuple(out)


def _parse_rings(rows: object) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    if not isinstance(rows, list):
        return ()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("Name")
        ring_class = row.get("RingClass")
        if not isinstance(name, str) or not name:
            continue
        if not isinstance(ring_class, str) or not ring_class:
            continue
        out.append((name, ring_class))
    return tuple(out)


def read_session(text: str) -> SessionSnapshot:
    """Walk a journal text and return location + survey for the active system."""
    system: str | None = None
    commander: str | None = None
    fid: str | None = None
    body: str | None = None
    system_address: int | None = None
    star_pos: tuple[float, float, float] | None = None

    fss_progress: float | None = None
    honked = False
    body_count: int | None = None
    non_body_count: int | None = None
    fss_complete = False
    scanned: set[int] = set()
    mapped: set[int] = set()
    signals: dict[str, BodySignals] = {}
    fss_bodies: list[FssBodyEntry] = []
    organic_scans = 0
    organic_progress: dict[str, OrganicProgress] = {}
    organic_sales = 0
    organic_sale_value = 0
    fss_signals: list[SystemSignal] = []
    codex_entries: list[CodexFind] = []
    bookmarks: list[TrackerBookmark] = []
    materials: MaterialsSnapshot | None = None
    ship: str | None = None
    ship_type: str | None = None
    ship_ident: str | None = None
    cargo_capacity: int | None = None
    fuel_capacity: float | None = None
    last_carrier_jump: str | None = None
    carrier_name: str | None = None
    guardian_signals: list[str] = []
    guardian_codex = 0
    guardian_sites: list[GuardianSiteSummary] = []
    current_guardian_site: GuardianSiteSummary | None = None
    settlements: list[str] = []
    stations: list[StationInfo] = []
    system_station: HumanStation | None = None
    faction_stats: dict[str, tuple[float | None, float | None]] = {}
    colonisation_body: str | None = None
    colonisation_progress: float | None = None
    colonisation_status: str | None = None
    fsd_jumping = False
    fsd_target_name: str | None = None
    fsd_target_address: int | None = None
    fsd_target_star_class: str | None = None
    fsd_remaining_jumps: int | None = None
    track_massacres: list[TrackMassacre] = []
    srv_type: str | None = None
    foot_combat_kills = 0
    foot_combat_credits = 0
    docked = False
    docked_station: str | None = None
    last_docked_station: str | None = None
    last_construction_station: str | None = None
    last_docking_station: str | None = None
    docking_in_progress = False
    in_supercruise = False
    landed = False
    died = False
    barycentres: set[int] = set()

    def reset_system(new_system: str | None, address: int | None) -> None:
        nonlocal system, system_address, star_pos, fss_progress, honked, body_count, non_body_count
        nonlocal fss_complete, organic_scans
        nonlocal colonisation_body, colonisation_progress, colonisation_status
        nonlocal guardian_codex, current_guardian_site, system_station
        nonlocal foot_combat_kills, foot_combat_credits
        nonlocal docked, docked_station, in_supercruise, landed, died
        system = new_system
        system_address = address
        star_pos = None
        fss_progress = None
        honked = False
        body_count = None
        non_body_count = None
        fss_complete = False
        scanned.clear()
        mapped.clear()
        signals.clear()
        fss_bodies.clear()
        organic_scans = 0
        organic_progress.clear()
        fss_signals.clear()
        codex_entries.clear()
        bookmarks.clear()
        guardian_signals.clear()
        guardian_codex = 0
        guardian_sites.clear()
        current_guardian_site = None
        settlements.clear()
        stations.clear()
        system_station = None
        faction_stats.clear()
        colonisation_body = None
        colonisation_progress = None
        colonisation_status = None
        # Massacre missions are commander-scoped — do not clear on jump.
        foot_combat_kills = 0
        foot_combat_credits = 0
        docked = False
        docked_station = None
        in_supercruise = False
        landed = False
        died = False
        barycentres.clear()

    def _remove_massacre(mission_id: int) -> None:
        track_massacres[:] = [m for m in track_massacres if m.mission_id != mission_id]

    def find_fss_body(
        body_id: int | None = None, body_name: str | None = None
    ) -> FssBodyEntry | None:
        if body_id is not None:
            for item in fss_bodies:
                if item.body_id == body_id:
                    return item
        if body_name is not None:
            for item in fss_bodies:
                if item.body_name == body_name:
                    return item
        return None

    def patch_fss_body(existing: FssBodyEntry, **kwargs: object) -> FssBodyEntry:
        data = {
            "body_id": existing.body_id,
            "body_name": existing.body_name,
            "short_name": existing.short_name,
            "body_type": existing.body_type,
            "planet_class": existing.planet_class,
            "star_type": existing.star_type,
            "terraformable": existing.terraformable,
            "landable": existing.landable,
            "was_discovered": existing.was_discovered,
            "was_mapped": existing.was_mapped,
            "first_footfall": existing.first_footfall,
            "distance_from_arrival_ls": existing.distance_from_arrival_ls,
            "reward": existing.reward,
            "dss_reward": existing.dss_reward,
            "dss_complete": existing.dss_complete,
            "bio_signal_count": existing.bio_signal_count,
            "geo_signal_count": existing.geo_signal_count,
            "analyzed_bio_count": existing.analyzed_bio_count,
            "geo_analyzed": existing.geo_analyzed,
            "scanned": existing.scanned,
            "is_main_star": existing.is_main_star,
            "mass": existing.mass,
            "surface_gravity": existing.surface_gravity,
            "surface_temperature": existing.surface_temperature,
            "surface_pressure": existing.surface_pressure,
            "atmosphere": existing.atmosphere,
            "atmosphere_type": existing.atmosphere_type,
            "atmosphere_composition": existing.atmosphere_composition,
            "volcanism": existing.volcanism,
            "materials": existing.materials,
            "rings": existing.rings,
        }
        data.update(kwargs)
        updated = FssBodyEntry(**data)  # type: ignore[arg-type]
        _replace_fss_body(fss_bodies, updated)
        return updated

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        event = entry.get("event")

        if event == "LoadGame":
            name = entry.get("Commander")
            if isinstance(name, str) and name:
                commander = name
            raw_fid = entry.get("FID")
            if isinstance(raw_fid, str) and raw_fid:
                fid = raw_fid
            ship_name = entry.get("Ship_Localised") or entry.get("Ship")
            if isinstance(ship_name, str) and ship_name:
                ship = ship_name
            raw_ship = entry.get("Ship")
            if isinstance(raw_ship, str) and raw_ship:
                ship_type = raw_ship.lower()
            ident = entry.get("ShipIdent")
            if isinstance(ident, str) and ident:
                ship_ident = ident
            cap = entry.get("FuelCapacity")
            if isinstance(cap, (int, float)):
                fuel_capacity = float(cap)

        if event == "Commander":
            name = entry.get("Name")
            if isinstance(name, str) and name:
                commander = name
            raw_fid = entry.get("FID")
            if isinstance(raw_fid, str) and raw_fid:
                fid = raw_fid

        if event == "Materials":
            raw = _parse_material_list(entry.get("Raw"), "Raw")
            manufactured = _parse_material_list(entry.get("Manufactured"), "Manufactured")
            encoded = _parse_material_list(entry.get("Encoded"), "Encoded")
            materials = MaterialsSnapshot(
                raw=tuple(raw),
                manufactured=tuple(manufactured),
                encoded=tuple(encoded),
            )

        if event in LOCATION_EVENTS:
            star = entry.get("StarSystem")
            address = entry.get("SystemAddress")
            addr = int(address) if isinstance(address, (int, float)) else None
            if isinstance(star, str) and star:
                if star != system or (addr is not None and addr != system_address):
                    reset_system(star, addr)
                else:
                    system = star
                    if addr is not None:
                        system_address = addr
            pos = _parse_star_pos(entry.get("StarPos"))
            if pos is not None:
                star_pos = pos
            here = entry.get("Body")
            body = here if isinstance(here, str) and here else None
            # FSDJump / Location end witch-space (StartJump Hyperspace sets fsd_jumping)
            if event in ("FSDJump", "Location", "CarrierJump"):
                fsd_jumping = False
            if event == "Location":
                if entry.get("Docked") is True:
                    docked = True
                    in_supercruise = False
                    name = entry.get("StationName")
                    if isinstance(name, str) and name:
                        docked_station = name
                        last_docked_station = name
                        if is_construction_station_name(name):
                            last_construction_station = name
                elif entry.get("Docked") is False:
                    docked = False
                    docked_station = None
            if event == "CarrierJump" and isinstance(star, str) and star:
                last_carrier_jump = star
                station = entry.get("StationName")
                if isinstance(station, str) and station:
                    carrier_name = station
            _ingest_faction_stats(entry, system_address, faction_stats)
            if system_station is not None and system_station.faction_name:
                rep, inf = faction_stats.get(
                    system_station.faction_name, (None, None)
                )
                if rep is not None or inf is not None:
                    system_station = replace(
                        system_station,
                        reputation=rep if rep is not None else system_station.reputation,
                        influence=inf if inf is not None else system_station.influence,
                    )

        if event == "StartJump":
            jump_type = entry.get("JumpType")
            if jump_type == "Hyperspace":
                fsd_jumping = True
                # Capture target star class early when present on StartJump
                star_cls = entry.get("StarClass")
                if isinstance(star_cls, str) and star_cls:
                    fsd_target_star_class = star_cls
                name = entry.get("StarSystem")
                if isinstance(name, str) and name:
                    fsd_target_name = name
                address = entry.get("SystemAddress")
                if isinstance(address, (int, float)):
                    fsd_target_address = int(address)

        if event == "FSDTarget":
            name = entry.get("Name")
            if isinstance(name, str) and name:
                fsd_target_name = name
            address = entry.get("SystemAddress")
            if isinstance(address, (int, float)):
                fsd_target_address = int(address)
            star_cls = entry.get("StarClass")
            if isinstance(star_cls, str) and star_cls:
                fsd_target_star_class = star_cls
            remaining = entry.get("RemainingJumpsInRoute")
            if isinstance(remaining, (int, float)):
                fsd_remaining_jumps = int(remaining)

        if event == "NavRouteClear":
            fsd_target_name = None
            fsd_target_address = None
            fsd_target_star_class = None
            fsd_remaining_jumps = None

        if event == "ApproachBody":
            here = entry.get("Body")
            if isinstance(here, str) and here:
                body = here

        if event == "LeaveBody":
            body = None

        if event == "FSSDiscoveryScan":
            name = entry.get("SystemName")
            address = entry.get("SystemAddress")
            addr = int(address) if isinstance(address, (int, float)) else None
            if isinstance(name, str) and name and name != system:
                reset_system(name, addr)
            progress = entry.get("Progress")
            honked = True
            if isinstance(progress, (int, float)):
                fss_progress = float(progress)
            bc = entry.get("BodyCount")
            if isinstance(bc, (int, float)):
                body_count = int(bc)
            nbc = entry.get("NonBodyCount")
            if isinstance(nbc, (int, float)):
                non_body_count = int(nbc)

        if event == "FSSAllBodiesFound":
            name = entry.get("SystemName")
            address = entry.get("SystemAddress")
            addr = int(address) if isinstance(address, (int, float)) else None
            if isinstance(name, str) and name and name != system:
                reset_system(name, addr)
            fss_complete = True
            fss_progress = 1.0
            count = entry.get("Count")
            if isinstance(count, (int, float)):
                body_count = int(count)

        if event == "Scan":
            address = entry.get("SystemAddress")
            addr = int(address) if isinstance(address, (int, float)) else None
            if system_address is not None and addr is not None and addr != system_address:
                continue
            body_id_raw = entry.get("BodyID")
            body_name = entry.get("BodyName")
            if not isinstance(body_id_raw, (int, float)):
                continue
            if not isinstance(body_name, str) or not body_name:
                continue
            if "Belt Cluster" in body_name:
                continue
            body_id = int(body_id_raw)
            scanned.add(body_id)

            star_type = entry.get("StarType")
            planet_class = entry.get("PlanetClass")
            star = star_type if isinstance(star_type, str) else None
            planet = planet_class if isinstance(planet_class, str) else None
            landable = entry.get("Landable") is True
            body_type = _body_type_from(star, planet, landable, body_name)
            dist = entry.get("DistanceFromArrivalLS")
            distance = float(dist) if isinstance(dist, (int, float)) else 0.0
            was_discovered = entry.get("WasDiscovered") is True
            was_mapped = entry.get("WasMapped") is True
            was_foot = entry.get("WasFootfalled")
            existing = find_fss_body(body_id=body_id, body_name=body_name)
            reward = get_body_value_from_scan(entry, False)
            dss_reward = get_body_value_from_scan(entry, True)
            if existing is not None:
                reward = max(reward, existing.reward)
                dss_reward = max(dss_reward, existing.dss_reward)
            sys_name = entry.get("StarSystem") if isinstance(entry.get("StarSystem"), str) else system
            short = _short_body_name(body_name, sys_name)
            is_main = bool(sys_name and body_name == sys_name) or (
                body_type == "Star" and distance == 0.0
            )
            first_ff = False
            if was_foot is True:
                first_ff = False
            elif existing is not None:
                first_ff = existing.first_footfall
            mass_em = entry.get("MassEM")
            stellar = entry.get("StellarMass")
            mass = 0.0
            if isinstance(mass_em, (int, float)) and mass_em > 0:
                mass = float(mass_em)
            elif isinstance(stellar, (int, float)):
                mass = float(stellar)
            grav = entry.get("SurfaceGravity")
            temp = entry.get("SurfaceTemperature")
            pressure = entry.get("SurfacePressure")
            atmos = entry.get("Atmosphere")
            atmos_type = entry.get("AtmosphereType")
            volc = entry.get("Volcanism")
            updated = FssBodyEntry(
                body_id=body_id,
                body_name=body_name,
                short_name=short,
                body_type=body_type,
                planet_class=planet,
                star_type=star,
                terraformable=entry.get("TerraformState") == "Terraformable",
                landable=landable,
                was_discovered=was_discovered,
                was_mapped=was_mapped,
                first_footfall=first_ff,
                distance_from_arrival_ls=distance,
                reward=reward,
                dss_reward=dss_reward,
                dss_complete=existing.dss_complete if existing else False,
                bio_signal_count=existing.bio_signal_count if existing else 0,
                geo_signal_count=existing.geo_signal_count if existing else 0,
                analyzed_bio_count=existing.analyzed_bio_count if existing else 0,
                geo_analyzed=existing.geo_analyzed if existing else False,
                scanned=True,
                is_main_star=is_main,
                mass=mass,
                surface_gravity=float(grav) if isinstance(grav, (int, float)) else 0.0,
                surface_temperature=float(temp) if isinstance(temp, (int, float)) else 0.0,
                surface_pressure=float(pressure)
                if isinstance(pressure, (int, float))
                else 0.0,
                atmosphere=atmos if isinstance(atmos, str) else None,
                atmosphere_type=atmos_type if isinstance(atmos_type, str) else None,
                atmosphere_composition=_parse_named_percents(
                    entry.get("AtmosphereComposition")
                ),
                volcanism=volc if isinstance(volc, str) else None,
                materials=_parse_named_percents(entry.get("Materials")),
                rings=_parse_rings(entry.get("Rings")),
            )
            # Prefer signal counts already known under this body name
            sig = signals.get(body_name)
            if sig is not None:
                updated = FssBodyEntry(
                    **{
                        **updated.__dict__,
                        "bio_signal_count": sig.bio_count or updated.bio_signal_count,
                        "geo_signal_count": sig.geo_count or updated.geo_signal_count,
                    }
                )
            _replace_fss_body(fss_bodies, updated)

        if event == "ScanBaryCentre":
            address = entry.get("SystemAddress")
            addr = int(address) if isinstance(address, (int, float)) else None
            if system_address is not None and addr is not None and addr != system_address:
                continue
            body_id = entry.get("BodyID")
            if isinstance(body_id, (int, float)):
                bid = int(body_id)
                barycentres.add(bid)
                scanned.add(bid)
                star = system or ""
                label = f"{star} barycentre {bid}".strip()
                _replace_fss_body(
                    fss_bodies,
                    FssBodyEntry(
                        body_id=bid,
                        body_name=label,
                        short_name=f"BC {bid}",
                        body_type="Barycentre",
                        scanned=True,
                    ),
                )

        if event == "SAAScanComplete":
            address = entry.get("SystemAddress")
            addr = int(address) if isinstance(address, (int, float)) else None
            if system_address is not None and addr is not None and addr != system_address:
                continue
            body_id = entry.get("BodyID")
            if isinstance(body_id, (int, float)):
                mapped.add(int(body_id))
                existing = find_fss_body(body_id=int(body_id))
                if existing is not None:
                    patch_fss_body(
                        existing,
                        dss_complete=True,
                        reward=max(existing.reward, existing.dss_reward),
                    )

        if event in ("FSSBodySignals", "SAASignalsFound"):
            address = entry.get("SystemAddress")
            addr = int(address) if isinstance(address, (int, float)) else None
            if system_address is not None and addr is not None and addr != system_address:
                continue
            body_name = entry.get("BodyName")
            if not isinstance(body_name, str) or not body_name:
                continue
            bio = 0
            geo = 0
            for sig in entry.get("Signals") or []:
                if not isinstance(sig, dict):
                    continue
                sig_type = sig.get("Type")
                count = sig.get("Count")
                n = int(count) if isinstance(count, (int, float)) else 0
                if sig_type == BIO_SIGNAL_TYPE:
                    bio += n
                elif sig_type == GEO_SIGNAL_TYPE:
                    geo += n
            genuses: list[str] = []
            for row in entry.get("Genuses") or []:
                if not isinstance(row, dict):
                    continue
                gname = row.get("Genus_Localised") or row.get("Genus")
                if isinstance(gname, str) and gname:
                    pretty = gname
                    if pretty.startswith("$") and pretty.endswith(";"):
                        pretty = pretty[1:-1].replace("_", " ")
                    genuses.append(pretty)
            if bio or geo or genuses:
                prev = signals.get(body_name)
                signals[body_name] = BodySignals(
                    body_name=body_name,
                    bio_count=bio or (prev.bio_count if prev else 0),
                    geo_count=geo or (prev.geo_count if prev else 0),
                    genuses=tuple(genuses) if genuses else (prev.genuses if prev else ()),
                )
                bid = entry.get("BodyID")
                existing = find_fss_body(
                    body_id=int(bid) if isinstance(bid, (int, float)) else None,
                    body_name=body_name,
                )
                if existing is not None:
                    patch_fss_body(
                        existing,
                        bio_signal_count=signals[body_name].bio_count,
                        geo_signal_count=signals[body_name].geo_count,
                    )

        if event == "FSSSignalDiscovered":
            address = entry.get("SystemAddress")
            addr = int(address) if isinstance(address, (int, float)) else None
            if system_address is not None and addr is not None and addr != system_address:
                continue
            display = _signal_display_name(entry)
            if display is None:
                continue
            sig_type = entry.get("SignalType")
            threat = entry.get("ThreatLevel")
            is_station = entry.get("IsStation") is True
            item = SystemSignal(
                name=display,
                signal_type=sig_type if isinstance(sig_type, str) else None,
                threat_level=int(threat) if isinstance(threat, (int, float)) else None,
                is_station=is_station,
            )
            # Prefer latest unique names; keep order stable for HUD.
            fss_signals[:] = [s for s in fss_signals if s.name != item.name]
            fss_signals.append(item)
            if len(fss_signals) > MAX_FSS_SIGNALS:
                del fss_signals[0 : len(fss_signals) - MAX_FSS_SIGNALS]
            blob = f"{display} {sig_type or ''}".lower()
            if "guardian" in blob:
                if display not in guardian_signals:
                    guardian_signals.append(display)
                    if len(guardian_signals) > 8:
                        del guardian_signals[0 : len(guardian_signals) - 8]

        if event == "CodexEntry":
            address = entry.get("SystemAddress")
            addr = int(address) if isinstance(address, (int, float)) else None
            if system_address is not None and addr is not None and addr != system_address:
                continue
            display = _codex_display_name(entry)
            if display is None:
                continue
            category = entry.get("Category_Localised") or entry.get("Category")
            subcategory = entry.get("SubCategory_Localised") or entry.get("SubCategory")
            find = CodexFind(
                name=display,
                category=category if isinstance(category, str) else None,
                subcategory=subcategory if isinstance(subcategory, str) else None,
                is_new=entry.get("IsNewEntry") is True,
            )
            codex_entries.append(find)
            if len(codex_entries) > MAX_CODEX_ENTRIES:
                del codex_entries[0 : len(codex_entries) - MAX_CODEX_ENTRIES]
            cat_blob = f"{category or ''} {subcategory or ''} {display}".lower()
            if "guardian" in cat_blob:
                guardian_codex += 1
            # Auto-track organic structures with lat/long (Windows autoTrackCompBioScans)
            sub_raw = entry.get("SubCategory")
            lat = entry.get("Latitude")
            lon = entry.get("Longitude")
            if (
                isinstance(sub_raw, str)
                and "Organic_Structures" in sub_raw
                and isinstance(lat, (int, float))
                and isinstance(lon, (int, float))
            ):
                nearest = entry.get("NearestDestination")
                if nearest not in (
                    "$Fixed_Event_Life_Cloud;",
                    "$Fixed_Event_Life_Ring;",
                ):
                    genus = entry.get("Genus_Localised") or entry.get("Genus")
                    track_name = genus if isinstance(genus, str) and genus else display
                    if track_name.startswith("$") and track_name.endswith(";"):
                        track_name = track_name[1:-1].replace("_", " ")
                    eid = entry.get("EntryID")
                    bookmarks.append(
                        TrackerBookmark(
                            name=track_name,
                            latitude=float(lat),
                            longitude=float(lon),
                            body_name=body if isinstance(body, str) else None,
                            entry_id=int(eid) if isinstance(eid, (int, float)) else None,
                        )
                    )

        if event == "ApproachSettlement":
            raw = entry.get("Name")
            localised = entry.get("Name_Localised")
            body_name = entry.get("BodyName")
            body_id_raw = entry.get("BodyID")
            body_id = int(body_id_raw) if isinstance(body_id_raw, (int, float)) else None
            if isinstance(raw, str) and raw.startswith("$Ancient"):
                site = _parse_guardian_settlement(
                    raw,
                    localised if isinstance(localised, str) else None,
                    body_name if isinstance(body_name, str) else None,
                    body_id,
                    system,
                )
                if site is not None:
                    guardian_sites[:] = [s for s in guardian_sites if s.name != site.name]
                    guardian_sites.append(site)
                    if len(guardian_sites) > MAX_GUARDIAN_SITES:
                        del guardian_sites[0 : len(guardian_sites) - MAX_GUARDIAN_SITES]
                    current_guardian_site = site
            else:
                name = localised or raw
                if isinstance(name, str) and name:
                    settlements[:] = [s for s in settlements if s != name]
                    settlements.append(name)
                    if len(settlements) > 8:
                        del settlements[0 : len(settlements) - 8]
                hs = _human_station_from_approach(entry, faction_stats)
                if hs is not None:
                    # Preserve docking / heading state when re-approaching same market
                    if (
                        system_station is not None
                        and system_station.market_id == hs.market_id
                    ):
                        system_station = replace(
                            hs,
                            heading=system_station.heading,
                            sub_type=system_station.sub_type,
                            template_name=system_station.template_name,
                            docking_state=system_station.docking_state,
                            granted_pad=system_station.granted_pad,
                            denied_reason=system_station.denied_reason,
                            has_landed=system_station.has_landed,
                            docking_in_progress=system_station.docking_in_progress,
                            music_track=system_station.music_track,
                        )
                    else:
                        system_station = hs

        if event == "SupercruiseEntry":
            system_station = None
            in_supercruise = True
            landed = False

        if event == "SupercruiseExit":
            in_supercruise = False
            here = entry.get("Body")
            if isinstance(here, str) and here:
                body = here

        if event == "Music":
            track = entry.get("MusicTrack")
            if system_station is not None and isinstance(track, str):
                system_station = replace(system_station, music_track=track)

        if event == "DockingRequested":
            docking_in_progress = True
            req_name = entry.get("StationName")
            if isinstance(req_name, str) and req_name:
                last_docking_station = req_name
                if is_construction_station_name(req_name):
                    last_construction_station = req_name
            if (
                entry.get("StationType") == "OnFootSettlement"
                and system_station is not None
                and system_station.market_id == int(entry.get("MarketID") or 0)
            ):
                system_station = replace(
                    system_station,
                    docking_state="requested",
                    docking_in_progress=True,
                    denied_reason=None,
                )

        if event == "DockingGranted":
            docking_in_progress = True
            granted_name = entry.get("StationName")
            if isinstance(granted_name, str) and granted_name:
                last_docking_station = granted_name
                if is_construction_station_name(granted_name):
                    last_construction_station = granted_name
            pad = entry.get("LandingPad")
            if (
                entry.get("StationType") == "OnFootSettlement"
                and system_station is not None
                and system_station.market_id == int(entry.get("MarketID") or 0)
            ):
                system_station = replace(
                    system_station,
                    docking_state="approved",
                    granted_pad=int(pad) if isinstance(pad, (int, float)) else 0,
                    docking_in_progress=True,
                )

        if event == "DockingDenied":
            docking_in_progress = False
            reason = entry.get("Reason")
            if (
                system_station is not None
                and system_station.market_id == int(entry.get("MarketID") or 0)
            ):
                system_station = replace(
                    system_station,
                    docking_state="denied",
                    denied_reason=reason if isinstance(reason, str) else None,
                    docking_in_progress=False,
                )

        if event == "DockingCancelled":
            docking_in_progress = False
            if system_station is not None:
                system_station = replace(
                    system_station,
                    docking_state="none",
                    docking_in_progress=False,
                )

        if event in (
            "ColonisationConstructionDepot",
            "ColonisationBeaconDeployed",
            "ColonisationSystemClaim",
            "ColonisationContribution",
        ):
            body_name = entry.get("BodyName") or entry.get("Body")
            if isinstance(body_name, str) and body_name:
                colonisation_body = body_name
            progress = entry.get("ConstructionProgress") or entry.get("Progress")
            if isinstance(progress, (int, float)):
                colonisation_progress = float(progress)
                if colonisation_progress > 1.0:
                    colonisation_progress = colonisation_progress / 100.0
            colonisation_status = event.replace("Colonisation", "")

        if event == "ScanOrganic":
            address = entry.get("SystemAddress")
            addr = int(address) if isinstance(address, (int, float)) else None
            if system_address is not None and addr is not None and addr != system_address:
                continue
            organic_scans += 1
            genus = entry.get("Genus_Localised") or entry.get("Genus")
            species = entry.get("Species_Localised") or entry.get("Species")
            scan_type = entry.get("ScanType")
            body_label = entry.get("Body")
            if isinstance(body_label, (int, float)):
                body_label = body if body else str(int(body_label))
            if isinstance(genus, str) and genus:
                pretty_genus = genus
                if pretty_genus.startswith("$") and pretty_genus.endswith(";"):
                    pretty_genus = pretty_genus[1:-1].replace("_", " ")
                pretty_species = species if isinstance(species, str) else None
                if (
                    isinstance(pretty_species, str)
                    and pretty_species.startswith("$")
                    and pretty_species.endswith(";")
                ):
                    pretty_species = pretty_species[1:-1].replace("_", " ")
                organic_progress[pretty_genus] = OrganicProgress(
                    genus=pretty_genus,
                    species=pretty_species,
                    scan_type=scan_type if isinstance(scan_type, str) else None,
                    body_name=body_label if isinstance(body_label, str) else body,
                )
                if scan_type == "Analyse":
                    target = None
                    if isinstance(entry.get("Body"), (int, float)):
                        target = find_fss_body(body_id=int(entry["Body"]))
                    if target is None and isinstance(body_label, str):
                        target = find_fss_body(body_name=body_label)
                    if target is None and body:
                        target = find_fss_body(body_name=body)
                    if target is not None:
                        patch_fss_body(
                            target,
                            analyzed_bio_count=min(
                                target.bio_signal_count,
                                target.analyzed_bio_count + 1,
                            )
                            if target.bio_signal_count
                            else target.analyzed_bio_count + 1,
                        )

        if event == "Disembark":
            if entry.get("OnPlanet") is True and entry.get("OnStation") is not True:
                here = body
                if isinstance(here, str) and here:
                    existing = find_fss_body(body_name=here)
                    if existing is not None and not existing.first_footfall:
                        patch_fss_body(existing, first_footfall=True)

        if event == "SellOrganicData":
            biodata = entry.get("BioData")
            if isinstance(biodata, list):
                organic_sales += len(biodata)
                for row in biodata:
                    if not isinstance(row, dict):
                        continue
                    value = row.get("Value")
                    bonus = row.get("Bonus")
                    if isinstance(value, (int, float)):
                        organic_sale_value += int(value)
                    if isinstance(bonus, (int, float)):
                        organic_sale_value += int(bonus)

        if event == "LaunchSRV":
            raw_srv = entry.get("SRVType") or entry.get("SRVType_Localised")
            if isinstance(raw_srv, str) and raw_srv:
                srv_type = raw_srv

        if event == "MissionAccepted":
            mname = entry.get("Name")
            mid = entry.get("MissionID")
            if (
                isinstance(mname, str)
                and mname in MASSACRE_MISSION_NAMES
                and isinstance(mid, (int, float))
            ):
                mission_id = int(mid)
                if not any(m.mission_id == mission_id for m in track_massacres):
                    giver = entry.get("Faction")
                    target = entry.get("TargetFaction")
                    kills = entry.get("KillCount")
                    expiry = entry.get("Expiry")
                    kc = int(kills) if isinstance(kills, (int, float)) else 0
                    track_massacres.append(
                        TrackMassacre(
                            mission_id=mission_id,
                            mission_giver=giver if isinstance(giver, str) else "",
                            target_faction=target if isinstance(target, str) else "",
                            expires=expiry if isinstance(expiry, str) else None,
                            kill_count=kc,
                            remaining=kc,
                        )
                    )

        if event in ("MissionCompleted", "MissionFailed", "MissionAbandoned"):
            mid = entry.get("MissionID")
            if isinstance(mid, (int, float)):
                _remove_massacre(int(mid))

        if event == "Missions":
            active_ids: set[int] = set()
            for key in ("Active", "Complete"):
                rows = entry.get(key)
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    mid = row.get("MissionID")
                    if isinstance(mid, (int, float)):
                        active_ids.add(int(mid))
            if track_massacres and active_ids:
                track_massacres[:] = [
                    m for m in track_massacres if m.mission_id in active_ids
                ]

        if event == "Bounty":
            victim = entry.get("VictimFaction")
            if isinstance(victim, str) and track_massacres:
                seen_givers: set[str] = set()
                updated: list[TrackMassacre] = []
                for mission in track_massacres:
                    if (
                        mission.target_faction == victim
                        and mission.remaining > 0
                        and mission.mission_giver not in seen_givers
                    ):
                        seen_givers.add(mission.mission_giver)
                        updated.append(
                            TrackMassacre(
                                mission_id=mission.mission_id,
                                mission_giver=mission.mission_giver,
                                target_faction=mission.target_faction,
                                expires=mission.expires,
                                kill_count=mission.kill_count,
                                remaining=mission.remaining - 1,
                            )
                        )
                    else:
                        updated.append(mission)
                track_massacres[:] = updated

        if event == "FactionKillBond":
            st = system_station
            if (
                st is not None
                and st.faction_state in ("War", "CivilWar")
            ):
                foot_combat_kills += 1
                reward = entry.get("Reward")
                if isinstance(reward, (int, float)):
                    foot_combat_credits += int(reward)

        if event == "MaterialCollected" or event == "MaterialDiscarded":
            raw_name = entry.get("Name_Localised") or entry.get("Name")
            if isinstance(raw_name, str) and raw_name.strip():
                count = entry.get("Count")
                delta = int(count) if isinstance(count, (int, float)) else 1
                if event == "MaterialDiscarded":
                    delta = -abs(delta)
                materials = bump_materials(
                    materials, raw_name, delta, entry.get("Category")
                )

        if event == "Died":
            died = True
            docked = False
            landed = False

        if event == "Resurrect":
            died = False

        if event == "Undocked":
            docked = False
            docked_station = None
            docking_in_progress = False

        if event == "Liftoff":
            landed = False

        if event == "DockSRV":
            srv_type = None

        if event == "Docked":
            address = entry.get("SystemAddress")
            addr = int(address) if isinstance(address, (int, float)) else None
            if system_address is not None and addr is not None and addr != system_address:
                continue
            station = station_from_docked(entry)
            if station is not None:
                stations[:] = [s for s in stations if s.name != station.name]
                stations.append(station)
                if len(stations) > 24:
                    del stations[0 : len(stations) - 24]
                docked = True
                docked_station = station.name
                last_docked_station = station.name
                docking_in_progress = False
                if is_construction_station_name(station.name):
                    last_construction_station = station.name
                in_supercruise = False
            if (
                entry.get("StationType") == "OnFootSettlement"
                and system_station is not None
                and system_station.market_id == int(entry.get("MarketID") or 0)
            ):
                system_station = replace(
                    system_station,
                    has_landed=True,
                    docking_state="landed",
                    docking_in_progress=False,
                )

        if event == "Touchdown":
            landed = True
            in_supercruise = False
            if system_station is not None:
                system_station = replace(system_station, has_landed=True)

        if event == "ShipyardSwap" or event == "Loadout":
            ship_name = entry.get("Ship_Localised") or entry.get("Ship")
            if isinstance(ship_name, str) and ship_name:
                ship = ship_name
            raw_ship = entry.get("Ship")
            if isinstance(raw_ship, str) and raw_ship:
                ship_type = raw_ship.lower()
            raw_cargo = entry.get("CargoCapacity")
            if isinstance(raw_cargo, (int, float)):
                cargo_capacity = int(raw_cargo)

    location = CommanderLocation(
        system=system, commander=commander, body=body, fid=fid
    )
    if honked and fss_bodies:
        from body_value import main_star_honk_reward

        counted = body_count if isinstance(body_count, int) else 0
        adjusted = main_star_honk_reward(fss_bodies, counted)
        if adjusted is not None:
            star, reward = adjusted
            _replace_fss_body(fss_bodies, replace(star, reward=int(reward)))

    survey = SurveyState(
        system=system,
        system_address=system_address,
        star_pos=star_pos,
        fss_progress=fss_progress,
        body_count=body_count,
        non_body_count=non_body_count,
        fss_complete=fss_complete,
        scanned_body_ids=frozenset(scanned),
        mapped_body_ids=frozenset(mapped),
        body_signals=tuple(sorted(signals.values(), key=lambda b: b.body_name)),
        fss_bodies=tuple(fss_bodies),
        organic_scans=organic_scans,
        organic_progress=tuple(organic_progress.values()),
        organic_sales=organic_sales,
        organic_sale_value=organic_sale_value,
        fss_signals=tuple(fss_signals),
        codex_entries=tuple(codex_entries),
        bookmarks=tuple(bookmarks),
        materials=materials,
        ship=ship,
        ship_type=ship_type,
        ship_ident=ship_ident,
        cargo_capacity=cargo_capacity,
        fuel_capacity=fuel_capacity,
        last_carrier_jump=last_carrier_jump,
        carrier_name=carrier_name,
        guardian_signals=tuple(guardian_signals),
        guardian_codex=guardian_codex,
        guardian_sites=tuple(guardian_sites),
        current_guardian_site=current_guardian_site,
        settlements=tuple(settlements),
        stations=tuple(stations),
        system_station=system_station,
        colonisation_body=colonisation_body,
        colonisation_progress=colonisation_progress,
        colonisation_status=colonisation_status,
        fsd_jumping=fsd_jumping,
        fsd_target_name=fsd_target_name,
        fsd_target_address=fsd_target_address,
        fsd_target_star_class=fsd_target_star_class,
        fsd_remaining_jumps=fsd_remaining_jumps,
        track_massacres=tuple(track_massacres),
        srv_type=srv_type,
        foot_combat_kills=foot_combat_kills,
        foot_combat_credits=foot_combat_credits,
        docked=docked,
        docked_station=docked_station,
        last_docked_station=last_docked_station,
        last_construction_station=last_construction_station,
        last_docking_station=last_docking_station,
        docking_in_progress=docking_in_progress,
        in_supercruise=in_supercruise,
        landed=landed,
        died=died,
        barycentre_ids=frozenset(barycentres),
    )
    return SessionSnapshot(location=location, survey=survey)


def read_session_file(path: Path) -> SessionSnapshot:
    return read_session(path.read_text(encoding="utf-8", errors="replace"))
