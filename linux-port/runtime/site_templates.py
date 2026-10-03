#!/usr/bin/env python3
"""Load Guardian + human settlement site templates from the Windows data files.

Paths resolve under the repo ``SrvSurvey/`` tree (dev) or overrides via env:
``SRVSURVEY_GUARDIAN_TEMPLATES``, ``SRVSURVEY_HUMAN_SITE_TEMPLATES``.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

_REPO_SRV = Path(__file__).resolve().parents[2] / "SrvSurvey"
_DEFAULT_GUARDIAN = _REPO_SRV / "guardianSiteTemplates.json"
_DEFAULT_HUMAN = _REPO_SRV / "settlements" / "humanSiteTemplates.json"


@dataclass(frozen=True)
class GuardianPoi:
    name: str
    poi_type: str
    angle_deg: float
    dist: float
    rot: float = 0.0

    def xy(self, scale: float = 1.0) -> tuple[float, float]:
        """Polar (angle from north, dist) → cartesian; Windows style."""
        rad = math.radians(self.angle_deg)
        # Match typical map: angle clockwise from north → x east, y south-up flipped later
        x = self.dist * math.sin(rad) * scale
        y = -self.dist * math.cos(rad) * scale
        return x, y


@dataclass(frozen=True)
class GuardianTemplate:
    name: str
    scale_factor: float = 1.0
    image_offset: tuple[float, float] = (0.0, 0.0)
    poi: tuple[GuardianPoi, ...] = ()


@dataclass(frozen=True)
class HumanPoi:
    name: str
    x: float
    y: float
    kind: str = "poi"


@dataclass(frozen=True)
class HumanSiteTemplate:
    name: str
    economy: str = ""
    sub_type: int = 0
    landing_pads: tuple[HumanPoi, ...] = ()
    named_poi: tuple[HumanPoi, ...] = ()
    buildings: tuple[tuple[str, tuple[tuple[float, float], ...]], ...] = ()
    data_terminals: tuple[HumanPoi, ...] = ()


def _guardian_path() -> Path:
    override = (os.environ.get("SRVSURVEY_GUARDIAN_TEMPLATES") or "").strip()
    return Path(override) if override else _DEFAULT_GUARDIAN


def _human_path() -> Path:
    override = (os.environ.get("SRVSURVEY_HUMAN_SITE_TEMPLATES") or "").strip()
    return Path(override) if override else _DEFAULT_HUMAN


def clear_template_caches() -> None:
    load_guardian_templates.cache_clear()
    load_human_site_templates.cache_clear()
    get_guardian_template.cache_clear()
    find_human_site_template.cache_clear()


@lru_cache(maxsize=1)
def load_guardian_templates() -> dict[str, GuardianTemplate]:
    path = _guardian_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, GuardianTemplate] = {}
    for key, val in raw.items():
        if not isinstance(val, dict):
            continue
        pois: list[GuardianPoi] = []
        for p in val.get("poi") or []:
            if not isinstance(p, dict):
                continue
            name = p.get("name")
            ptype = p.get("type")
            if not isinstance(name, str) or not isinstance(ptype, str):
                continue
            try:
                angle = float(p.get("angle") or 0.0)
                dist = float(p.get("dist") or 0.0)
                rot = float(p.get("rot") or 0.0)
            except (TypeError, ValueError):
                continue
            pois.append(GuardianPoi(name=name, poi_type=ptype, angle_deg=angle, dist=dist, rot=rot))
        offset = val.get("imageOffset") or [0, 0]
        ox = float(offset[0]) if isinstance(offset, (list, tuple)) and offset else 0.0
        oy = float(offset[1]) if isinstance(offset, (list, tuple)) and len(offset) > 1 else 0.0
        try:
            scale = float(val.get("scaleFactor") or 1.0)
        except (TypeError, ValueError):
            scale = 1.0
        name = val.get("name") if isinstance(val.get("name"), str) else str(key)
        out[str(key)] = GuardianTemplate(
            name=name,
            scale_factor=scale,
            image_offset=(ox, oy),
            poi=tuple(pois),
        )
    return out


@lru_cache(maxsize=64)
def get_guardian_template(site_type: str | None) -> GuardianTemplate | None:
    if not site_type:
        return None
    templates = load_guardian_templates()
    key = str(site_type).strip()
    if key in templates:
        return templates[key]
    # Case-insensitive / partial (e.g. "beta ruins" → Beta)
    lower = key.lower()
    for name, tmpl in templates.items():
        if name.lower() == lower or name.lower() in lower or lower in name.lower():
            return tmpl
    return None


def _xy_from_offset(offset: Any) -> tuple[float, float] | None:
    if not isinstance(offset, dict):
        return None
    try:
        return float(offset.get("X") or 0.0), float(offset.get("Y") or 0.0)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def load_human_site_templates() -> tuple[HumanSiteTemplate, ...]:
    path = _human_path()
    if not path.is_file():
        return ()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(raw, list):
        return ()
    out: list[HumanSiteTemplate] = []
    for val in raw:
        if not isinstance(val, dict):
            continue
        name = val.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        pads: list[HumanPoi] = []
        for pad in val.get("landingPads") or []:
            if not isinstance(pad, dict):
                continue
            xy = _xy_from_offset(pad.get("offset"))
            if xy is None:
                continue
            size = pad.get("size") if isinstance(pad.get("size"), str) else "Pad"
            pads.append(HumanPoi(name=size, x=xy[0], y=xy[1], kind="pad"))
        named: list[HumanPoi] = []
        for poi in val.get("namedPoi") or []:
            if not isinstance(poi, dict):
                continue
            xy = _xy_from_offset(poi.get("offset"))
            if xy is None:
                continue
            pname = poi.get("name") if isinstance(poi.get("name"), str) else "POI"
            named.append(HumanPoi(name=pname, x=xy[0], y=xy[1], kind="named"))
        terminals: list[HumanPoi] = []
        for poi in val.get("dataTerminals") or []:
            if not isinstance(poi, dict):
                continue
            xy = _xy_from_offset(poi.get("offset"))
            if xy is None:
                continue
            terminals.append(HumanPoi(name="Data", x=xy[0], y=xy[1], kind="terminal"))
        buildings: list[tuple[str, tuple[tuple[float, float], ...]]] = []
        for b in val.get("buildings") or []:
            if not isinstance(b, dict):
                continue
            bname = b.get("name") if isinstance(b.get("name"), str) else "Bldg"
            pts: list[tuple[float, float]] = []
            for path in b.get("paths") or []:
                if not isinstance(path, dict):
                    continue
                for pt in path.get("PathPoints") or []:
                    if not isinstance(pt, dict):
                        continue
                    try:
                        pts.append((float(pt.get("X") or 0.0), float(pt.get("Y") or 0.0)))
                    except (TypeError, ValueError):
                        continue
            if pts:
                buildings.append((bname, tuple(pts)))
        try:
            sub = int(val.get("subType") or 0)
        except (TypeError, ValueError):
            sub = 0
        economy = val.get("economy") if isinstance(val.get("economy"), str) else ""
        out.append(
            HumanSiteTemplate(
                name=name.strip(),
                economy=economy,
                sub_type=sub,
                landing_pads=tuple(pads),
                named_poi=tuple(named),
                buildings=tuple(buildings),
                data_terminals=tuple(terminals),
            )
        )
    return tuple(out)


@lru_cache(maxsize=64)
def find_human_site_template(
    name: str | None = None,
    economy: str | None = None,
    sub_type: int | None = None,
) -> HumanSiteTemplate | None:
    templates = load_human_site_templates()
    if not templates:
        return None
    if name:
        needle = name.strip().lower()
        for t in templates:
            if t.name.lower() == needle or needle in t.name.lower():
                return t
    if economy is not None and sub_type is not None:
        econ = economy.strip().lower()
        for t in templates:
            if t.economy.lower() == econ and t.sub_type == sub_type:
                return t
    if economy is not None:
        econ = economy.strip().lower()
        for t in templates:
            if t.economy.lower() == econ:
                return t
    return templates[0] if templates else None
