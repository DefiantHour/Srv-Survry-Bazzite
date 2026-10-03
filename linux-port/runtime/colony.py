#!/usr/bin/env python3
"""Colonisation shopping list — Linux port of PlotBuildCommodities.

Visual target: dark panel, orange border, Commodity / Need / Ship|FC columns,
category headers with collapsed green ✓ rows, footer remaining + trips.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Same grouping as SrvSurvey/game/ColonyData.mapCargoType
MAP_CARGO_TYPE: dict[str, tuple[str, ...]] = {
    "Chemicals": ("liquidoxygen", "pesticides", "surfacestabilisers", "water"),
    "Consumer Items": ("evacuationshelter", "survivalequipment"),
    "Foods": (
        "animalmeat", "coffee", "fish", "foodcartridges",
        "fruitandvegetables", "grain", "tea",
    ),
    "Industrial Materials": (
        "ceramiccomposites", "cmmcomposite", "insulatingmembrane",
        "polymers", "semiconductors", "superconductors",
    ),
    "Legal Drugs": ("beer", "liquor", "wine"),
    "Machinery": (
        "buildingfabricators", "cropharvesters", "emergencypowercells",
        "geologicalequipment", "microbialfurnaces", "heliostaticfurnaces",
        "mineralextractors", "powergenerators", "thermalcoolingunits",
        "waterpurifiers",
    ),
    "Medicines": (
        "agriculturalmedicines", "basicmedicines",
        "combatstabilisers", "combatstabilizers",
    ),
    "Metals": ("aluminium", "copper", "steel", "titanium"),
    "Technology": (
        "advancedcatalysers", "autofabricators", "bioreducinglichen",
        "computercomponents", "hazardousenvironmentsuits",
        "landenrichmentsystems", "terrainenrichmentsystems",
        "medicaldiagnosticequipment", "microcontrollers",
        "muonimager", "mutomimager", "resonatingseparators",
        "robotics", "structuralregulators",
    ),
    "Textiles": ("militarygradefabrics",),
    "Waste": ("biowaste",),
    "Weapons": ("battleweapons", "nonlethalweapons", "reactivearmour"),
}

DISPLAY_NAMES: dict[str, str] = {
    "liquidoxygen": "Liquid oxygen",
    "water": "Water",
    "pesticides": "Pesticides",
    "surfacestabilisers": "Surface Stabilisers",
    "ceramiccomposites": "Ceramic Composites",
    "cmmcomposite": "CMM Composite",
    "insulatingmembrane": "Insulating Membrane",
    "polymers": "Polymers",
    "semiconductors": "Semiconductors",
    "superconductors": "Superconductors",
    "foodcartridges": "Food Cartridges",
    "fruitandvegetables": "Fruit and Vegetables",
    "aluminium": "Aluminium",
    "copper": "Copper",
    "steel": "Steel",
    "titanium": "Titanium",
    "computercomponents": "Computer Components",
    "medicaldiagnosticequipment": "Medical Diagnostic Equipment",
    "nonlethalweapons": "Non-Lethal Weapons",
    "powergenerators": "Power Generators",
    "waterpurifiers": "Water Purifiers",
}


# Windows ColonyData cargo-name corrections (both spellings appear in journals).
CARGO_ALIASES: dict[str, str] = {
    "microbialfurnaces": "heliostaticfurnaces",
    "heliostaticfurnaces": "microbialfurnaces",
    "landenrichmentsystems": "terrainenrichmentsystems",
    "terrainenrichmentsystems": "landenrichmentsystems",
    "muonimager": "mutomimager",
    "mutomimager": "muonimager",
    "combatstabilizers": "combatstabilisers",
    "combatstabilisers": "combatstabilizers",
}


def commodity_key(name: str) -> str:
    """Normalize journal $foo_name; or Name_Localised into a mapCargoType key."""
    key = name.strip()
    if key.startswith("$") and key.endswith(";"):
        key = key[1:-1]
    if key.endswith("_name"):
        key = key[: -len("_name")]
    return key.replace(" ", "").replace("-", "").lower()


def display_name(key: str, localised: str | None = None) -> str:
    if localised:
        return localised
    return DISPLAY_NAMES.get(key, key.replace("_", " ").title())


@dataclass(frozen=True)
class DepotNeed:
    key: str
    label: str
    need: int  # remaining Required - Provided
    required: int
    provided: int


@dataclass(frozen=True)
class ConstructionDepot:
    market_id: int | None
    progress: float
    complete: bool
    failed: bool
    needs: tuple[DepotNeed, ...]
    title: str = "Construction Site"

    @property
    def sum_remaining(self) -> int:
        return sum(n.need for n in self.needs if n.need > 0)

    def need_map(self) -> dict[str, int]:
        return {n.key: n.need for n in self.needs if n.need > 0}


@dataclass
class BuildListModel:
    """Everything the shopping-list bitmap needs to draw."""

    header: str
    depot: ConstructionDepot | None
    ship_cargo: dict[str, int] = field(default_factory=dict)
    fc_cargo: dict[str, int] = field(default_factory=dict)
    fc_count: int = 0
    cargo_capacity: int = 0
    build_id: str | None = None
    assigned_me: frozenset[str] = field(default_factory=frozenset)
    assigned_others: frozenset[str] = field(default_factory=frozenset)
    warning: str | None = None
    sort_alpha: bool = False
    # Windows PlotBuildCommodities.pendingUpdates — show "Updating..." footer.
    pending_updates: int = 0
    pending_diff: dict[str, int] = field(default_factory=dict)

    @property
    def has_fc_column(self) -> bool:
        return self.fc_count > 0 or bool(self.fc_cargo)


def parse_depot_from_entry(entry: dict, *, title: str | None = None) -> ConstructionDepot | None:
    if entry.get("event") != "ColonisationConstructionDepot":
        return None
    resources = entry.get("ResourcesRequired")
    if not isinstance(resources, list):
        return None
    needs: list[DepotNeed] = []
    for row in resources:
        if not isinstance(row, dict):
            continue
        raw = row.get("Name")
        local = row.get("Name_Localised")
        if not isinstance(raw, str):
            continue
        key = commodity_key(raw)
        required = int(row.get("RequiredAmount") or 0)
        provided = int(row.get("ProvidedAmount") or 0)
        remaining = max(0, required - provided)
        if remaining <= 0 and required <= 0:
            continue
        needs.append(
            DepotNeed(
                key=key,
                label=display_name(key, local if isinstance(local, str) else None),
                need=remaining,
                required=required,
                provided=provided,
            )
        )
    market = entry.get("MarketID")
    progress = entry.get("ConstructionProgress")
    return ConstructionDepot(
        market_id=int(market) if isinstance(market, (int, float)) else None,
        progress=float(progress) if isinstance(progress, (int, float)) else 0.0,
        complete=entry.get("ConstructionComplete") is True,
        failed=entry.get("ConstructionFailed") is True,
        needs=tuple(needs),
        title=title or "Primary port",
    )


def latest_depot_from_journal(text: str, *, title: str | None = None) -> ConstructionDepot | None:
    """Walk journal text; last ColonisationConstructionDepot wins."""
    import json

    last: ConstructionDepot | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line or "ColonisationConstructionDepot" not in line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            parsed = parse_depot_from_entry(entry, title=title)
            if parsed is not None:
                last = parsed
    return last


# Cache depot parses so the present loop never re-reads multi-MB journals every tick.
_depot_file_cache: dict[str, tuple[int, int, ConstructionDepot | None]] = {}


def latest_depot_from_file(path: Path, *, title: str | None = None) -> ConstructionDepot | None:
    """Cached parse of one journal file (invalidates on mtime/size change)."""
    try:
        st = path.stat()
    except OSError:
        return None
    key = str(path)
    hit = _depot_file_cache.get(key)
    if hit is not None and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        _depot_file_cache[key] = (st.st_mtime_ns, st.st_size, None)
        return None
    depot = latest_depot_from_journal(text, title=title)
    _depot_file_cache[key] = (st.st_mtime_ns, st.st_size, depot)
    return depot


def latest_depot_from_folder(
    folder: Path | None,
    *,
    title: str | None = None,
    max_files: int = 8,
) -> ConstructionDepot | None:
    """Newest ColonisationConstructionDepot across recent journal files."""
    if folder is None or not folder.is_dir():
        return None
    journals = sorted(
        folder.glob("Journal*.log"),
        key=lambda p: p.stat().st_mtime if p.is_file() else 0,
        reverse=True,
    )[:max_files]
    # Prefer the most recently modified file that still contains a depot event.
    for path in journals:
        depot = latest_depot_from_file(path, title=title)
        if depot is not None:
            return depot
    return None


def cargo_qty(counts: dict[str, int], key: str) -> int:
    """Hold or FC tons for a depot key, including the Windows spelling alias."""
    qty = int(counts.get(key, 0) or 0)
    alias = CARGO_ALIASES.get(key)
    if alias:
        qty += int(counts.get(alias, 0) or 0)
    return qty


def cargo_counts(inventory: object) -> dict[str, int]:
    """Build key→count from CargoSnapshot.inventory or a list of dicts."""
    out: dict[str, int] = {}
    if inventory is None:
        return out
    rows = inventory
    if hasattr(inventory, "inventory"):
        rows = inventory.inventory  # type: ignore[assignment]
    if not isinstance(rows, (list, tuple)):
        return out
    for item in rows:
        name = None
        if hasattr(item, "key") or hasattr(item, "name"):
            name = getattr(item, "key", None) or getattr(item, "name", None)
        if name is None and isinstance(item, dict):
            name = item.get("Name") or item.get("key") or item.get("Name_Localised")
        count = getattr(item, "count", None)
        if count is None and isinstance(item, dict):
            count = item.get("Count")
        if not isinstance(name, str) or not isinstance(count, (int, float)):
            continue
        key = commodity_key(name)
        if not key:
            continue
        out[key] = out.get(key, 0) + int(count)
    return out
