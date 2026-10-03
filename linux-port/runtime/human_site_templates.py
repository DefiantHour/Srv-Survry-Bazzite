#!/usr/bin/env python3
"""Human settlement templates — Linux port of HumanSiteTemplate.

Loads ``SrvSurvey/settlements/humanSiteTemplates.json`` (also accepts the
copy inside ``data/settlements.zip`` when extracted). Fail-soft.
"""

from __future__ import annotations

import json
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE_PATHS = (
    _REPO_ROOT / "SrvSurvey" / "settlements" / "humanSiteTemplates.json",
    _REPO_ROOT / "data" / "settlements" / "humanSiteTemplates.json",
)
_ZIP_PATH = _REPO_ROOT / "data" / "settlements.zip"

_lock = threading.Lock()
_templates: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class SiteOffset:
    x: float
    y: float


@dataclass(frozen=True)
class LandingPad:
    size: str
    offset: SiteOffset
    rot: float = 0.0


@dataclass(frozen=True)
class NamedPoi:
    name: str
    offset: SiteOffset
    floor: int = 0
    level: int = 0
    rot: float = 0.0


@dataclass(frozen=True)
class BuildingPath:
    points: tuple[SiteOffset, ...]


@dataclass(frozen=True)
class Building:
    name: str
    paths: tuple[BuildingPath, ...] = ()


@dataclass
class HumanTemplate:
    economy: str
    sub_type: int
    name: str | None = None
    landing_pads: tuple[LandingPad, ...] = ()
    named_poi: tuple[NamedPoi, ...] = ()
    data_terminals: tuple[NamedPoi, ...] = ()
    secure_doors: tuple[NamedPoi, ...] = ()
    buildings: tuple[Building, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)


def reset_cache() -> None:
    global _templates
    with _lock:
        _templates = None


def _offset(raw: Any) -> SiteOffset | None:
    if not isinstance(raw, dict):
        return None
    try:
        return SiteOffset(float(raw.get("X", 0)), float(raw.get("Y", 0)))
    except (TypeError, ValueError):
        return None


def _landing_pad(row: dict) -> LandingPad | None:
    off = _offset(row.get("offset"))
    if off is None:
        return None
    size = row.get("size") or "Medium"
    try:
        rot = float(row.get("rot") or 0)
    except (TypeError, ValueError):
        rot = 0.0
    return LandingPad(size=str(size), offset=off, rot=rot)


def _named(row: dict) -> NamedPoi | None:
    off = _offset(row.get("offset"))
    if off is None:
        return None
    name = row.get("name") or row.get("type") or "POI"
    try:
        floor = int(row.get("floor") or 0)
        level = int(row.get("level") or 0)
        rot = float(row.get("rot") or 0)
    except (TypeError, ValueError):
        floor = level = 0
        rot = 0.0
    return NamedPoi(
        name=str(name), offset=off, floor=floor, level=level, rot=rot
    )


def _building(row: dict) -> Building | None:
    name = row.get("name")
    if not isinstance(name, str) or not name:
        return None
    paths: list[BuildingPath] = []
    for path in row.get("paths") or []:
        if not isinstance(path, dict):
            continue
        pts_raw = path.get("PathPoints") or []
        pts: list[SiteOffset] = []
        for p in pts_raw:
            off = _offset(p)
            if off is not None:
                pts.append(off)
        if len(pts) >= 2:
            paths.append(BuildingPath(points=tuple(pts)))
    return Building(name=name, paths=tuple(paths))


def _parse_template(row: dict) -> HumanTemplate | None:
    eco = row.get("economy")
    sub = row.get("subType")
    if not isinstance(eco, str) or not isinstance(sub, (int, float)):
        return None
    pads = tuple(
        p
        for p in (_landing_pad(r) for r in (row.get("landingPads") or []) if isinstance(r, dict))
        if p is not None
    )
    named = tuple(
        p
        for p in (_named(r) for r in (row.get("namedPoi") or []) if isinstance(r, dict))
        if p is not None
    )
    terminals = tuple(
        p
        for p in (_named(r) for r in (row.get("dataTerminals") or []) if isinstance(r, dict))
        if p is not None
    )
    doors = tuple(
        p
        for p in (_named(r) for r in (row.get("secureDoors") or []) if isinstance(r, dict))
        if p is not None
    )
    buildings = tuple(
        b
        for b in (_building(r) for r in (row.get("buildings") or []) if isinstance(r, dict))
        if b is not None
    )
    tname = row.get("name")
    return HumanTemplate(
        economy=eco,
        sub_type=int(sub),
        name=tname if isinstance(tname, str) else None,
        landing_pads=pads,
        named_poi=named,
        data_terminals=terminals,
        secure_doors=doors,
        buildings=buildings,
        raw=row,
    )


def _load_raw_list() -> list[dict[str, Any]]:
    for path in _TEMPLATE_PATHS:
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    return [r for r in raw if isinstance(r, dict)]
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
    if _ZIP_PATH.is_file():
        try:
            with zipfile.ZipFile(_ZIP_PATH) as zf:
                if "humanSiteTemplates.json" in zf.namelist():
                    raw = json.loads(zf.read("humanSiteTemplates.json"))
                    if isinstance(raw, list):
                        return [r for r in raw if isinstance(r, dict)]
        except (OSError, json.JSONDecodeError, TypeError, ValueError, zipfile.BadZipFile):
            pass
    return []


def load_templates() -> list[HumanTemplate]:
    global _templates
    with _lock:
        if _templates is not None:
            return [
                t
                for t in (_parse_template(r) for r in _templates)
                if t is not None
            ]
        raw = _load_raw_list()
        _templates = raw
        return [t for t in (_parse_template(r) for r in raw) if t is not None]


def economy_key(economy: str | None) -> str | None:
    """Normalise journal ``$economy_Extraction;`` / ``Extraction`` → ``Extraction``."""
    if not economy:
        return None
    text = economy.strip()
    if text.startswith("$economy_") and text.endswith(";"):
        text = text[len("$economy_") : -1]
    if text.startswith("$") and text.endswith(";"):
        text = text[1:-1]
    # Title-case HighTech etc.
    aliases = {
        "hightech": "HighTech",
        "high tech": "HighTech",
        "extraction": "Extraction",
        "agriculture": "Agriculture",
        "industrial": "Industrial",
        "military": "Military",
        "tourist": "Tourist",
        "colony": "Colony",
        "refinery": "Refinery",
        "service": "Service",
        "terraforming": "Terraforming",
    }
    low = text.replace(" ", "").lower()
    if low in aliases:
        return aliases[low]
    # Already canonical?
    for t in load_templates():
        if t.economy.lower() == text.lower():
            return t.economy
    return text


def get_template(
    economy: str | None,
    sub_type: int | None,
    *,
    name: str | None = None,
) -> HumanTemplate | None:
    """Match HumanSiteTemplate.get(economy, subType); optional name fallback."""
    templates = load_templates()
    if name:
        for t in templates:
            if t.name and t.name.lower() == name.lower():
                return t
    eco = economy_key(economy)
    if eco is None or not sub_type or sub_type < 1:
        return None
    for t in templates:
        if t.economy.lower() == eco.lower() and t.sub_type == int(sub_type):
            return t
    return None


def templates_for_economy(economy: str | None) -> list[HumanTemplate]:
    eco = economy_key(economy)
    if not eco:
        return []
    return [t for t in load_templates() if t.economy.lower() == eco.lower()]


def pad_summary(templates: list[HumanTemplate]) -> str:
    """Short pad-size summary across subtype templates."""
    if not templates:
        return ""
    counts: dict[str, list[int]] = {}
    for t in templates:
        for pad in t.landing_pads:
            counts.setdefault(pad.size, []).append(1)
    if not counts:
        return "No pads in templates"
    parts = []
    for size in ("Small", "Medium", "Large"):
        if size in counts:
            n = sum(counts[size])
            # average per subtype
            avg = n / max(1, len(templates))
            parts.append(f"{size[0]}×{avg:.0f}")
    return "Pads ~ " + " ".join(parts) if parts else ""
