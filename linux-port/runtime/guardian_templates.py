#!/usr/bin/env python3
"""Guardian site templates + pub JSON — Linux port of GuardianSiteTemplate / GuardianSitePub.

Loads ``SrvSurvey/guardianSiteTemplates.json`` (or ``settlementTemplates.json``)
and per-site pub files under ``data/guardian/``. Fail-soft: missing files
return empty / None without raising into the present loop.
"""

from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE_CANDIDATES = (
    _REPO_ROOT / "SrvSurvey" / "guardianSiteTemplates.json",
    _REPO_ROOT / "SrvSurvey" / "settlementTemplates.json",
)
_PUB_DIRS = (
    _REPO_ROOT / "data" / "guardian",
    _REPO_ROOT / "SrvSurvey" / "guardian",
)

_lock = threading.Lock()
_templates: dict[str, dict[str, Any]] | None = None
_templates_path: Path | None = None


@dataclass(frozen=True)
class SitePoi:
    name: str
    poi_type: str
    angle: float
    dist: float
    rot: float = 0.0


@dataclass(frozen=True)
class ActiveObelisk:
    name: str
    msg: str
    scanned: bool = False
    items_hint: tuple[str, ...] = ()


@dataclass
class GuardianPub:
    body_name: str
    index: int
    is_ruins: bool
    site_type: str | None = None
    site_heading: int = -1
    relic_heading: int = -1
    latitude: float | None = None
    longitude: float | None = None
    site_id: str | None = None
    obelisk_groups: str = ""
    present: frozenset[str] = field(default_factory=frozenset)
    absent: frozenset[str] = field(default_factory=frozenset)
    empty: frozenset[str] = field(default_factory=frozenset)
    active_obelisks: tuple[ActiveObelisk, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)
    # Pub ``rth`` string, ``t11:123,t12:40``.
    relic_tower_headings: dict[str, int] = field(default_factory=dict)


def reset_cache() -> None:
    """Test helper."""
    global _templates, _templates_path
    with _lock:
        _templates = None
        _templates_path = None


def _repo_paths() -> tuple[Path, ...]:
    return _TEMPLATE_CANDIDATES


def load_templates(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load site-type → template dict. Cached."""
    global _templates, _templates_path
    with _lock:
        if path is None and _templates is not None:
            return _templates
        target: Path | None = path
        if target is None:
            for cand in _repo_paths():
                if cand.is_file():
                    target = cand
                    break
        data: dict[str, dict[str, Any]] = {}
        if target is not None and target.is_file():
            try:
                raw = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for key, val in raw.items():
                        if isinstance(val, dict):
                            data[str(key)] = val
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                data = {}
        _templates = data
        _templates_path = target
        return data


def template_for(site_type: str | None) -> dict[str, Any] | None:
    if not site_type:
        return None
    templates = load_templates()
    hit = templates.get(site_type)
    if hit is not None:
        return hit
    # Case-insensitive
    key = site_type.strip().lower()
    for name, tmpl in templates.items():
        if name.lower() == key:
            return tmpl
    return None


def parse_relic_tower_headings(raw: object) -> dict[str, int]:
    """Windows ``rth`` string: ``t11:123,t2:40``."""
    if not isinstance(raw, str) or not raw.strip():
        return {}
    out: dict[str, int] = {}
    for tower in raw.split(","):
        piece = tower.strip()
        if not piece:
            continue
        parts = [part.strip() for part in piece.split(":") if part.strip()]
        if len(parts) != 2:
            raise ValueError("Corrupt rth")
        out[parts[0]] = int(parts[1])
    return out


def relic_heading_for(
    name: str | None,
    *,
    local: dict[str, int] | None = None,
    pub: GuardianPub | None = None,
    raw_rot: int | None = None,
) -> int | None:
    """Windows ``getRelicHeading``: local, then raw POI rot, then pub ``rth``."""
    if not name:
        return None
    if local is not None and name in local:
        return int(local[name])
    if raw_rot is not None:
        return int(raw_rot)
    if pub is not None and name in pub.relic_tower_headings:
        return int(pub.relic_tower_headings[name])
    return None


def obelisk_group_name_locations(
    site_type: str | None,
) -> list[tuple[str, float, float]]:
    """Template group labels. Windows stores angle in X and distance in Y."""
    tmpl = template_for(site_type)
    if not tmpl:
        return []
    raw = tmpl.get("obeliskGroupNameLocations")
    if not isinstance(raw, dict):
        return []
    out: list[tuple[str, float, float]] = []
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        if value.get("IsEmpty") is True:
            continue
        try:
            angle = float(value["X"])
            dist = float(value["Y"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append((key, angle, dist))
    return out


def template_pois(site_type: str | None) -> list[SitePoi]:
    tmpl = template_for(site_type)
    if not tmpl:
        return []
    out: list[SitePoi] = []
    for row in tmpl.get("poi") or []:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        ptype = row.get("type") or "unknown"
        try:
            angle = float(row.get("angle") or 0)
            dist = float(row.get("dist") or 0)
            rot = float(row.get("rot") or 0)
        except (TypeError, ValueError):
            continue
        if not isinstance(name, str) or not name:
            continue
        out.append(
            SitePoi(
                name=name,
                poi_type=str(ptype),
                angle=angle,
                dist=dist,
                rot=rot,
            )
        )
    return out


def rotate_line(angle_deg: float, length: float) -> tuple[float, float]:
    """Match Util.rotateLine — angle degrees → (dx, dy) meters."""
    rad = math.radians(angle_deg)
    return math.sin(rad) * length, math.cos(rad) * length


def poi_xy(poi: SitePoi, site_heading: float) -> tuple[float, float]:
    """Match PlotGuardians: deg = 180 - siteHeading - poi.angle."""
    deg = 180.0 - float(site_heading) - poi.angle
    return rotate_line(deg, poi.dist)


def pub_filename(body_name: str, index: int, is_ruins: bool) -> str:
    kind = "ruins" if is_ruins else "structure"
    return f"{body_name}-{kind}-{index}.json"


def _parse_csv_set(raw: Any) -> frozenset[str]:
    if not isinstance(raw, str) or not raw.strip():
        return frozenset()
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def parse_active_obelisk(text: str) -> ActiveObelisk | None:
    """Parse pub ``ao`` string: ``B09-to,ur-C4-`` / ``F07!-ca,to-H15-``."""
    if not text or not isinstance(text, str):
        return None
    parts = text.strip().split("-")
    if len(parts) < 3:
        return None
    name_raw = parts[0]
    scanned = name_raw.endswith("!")
    name = name_raw[:-1] if scanned else name_raw
    if not name:
        return None
    items_hint = tuple(
        p.strip() for p in parts[1].split(",") if p.strip()
    )
    msg = parts[2].strip()
    if not msg:
        return None
    return ActiveObelisk(
        name=name, msg=msg, scanned=scanned, items_hint=items_hint
    )


def load_pub(
    body_name: str | None,
    index: int | None,
    is_ruins: bool = True,
    *,
    pub_dir: Path | None = None,
) -> GuardianPub | None:
    """Load one guardian pub JSON. Returns None if missing / invalid."""
    if not body_name or not index or index < 1:
        return None
    filename = pub_filename(body_name, int(index), is_ruins)
    candidates: list[Path] = []
    if pub_dir is not None:
        candidates.append(pub_dir / filename)
    for d in _PUB_DIRS:
        candidates.append(d / filename)
    path: Path | None = None
    for cand in candidates:
        if cand.is_file():
            path = cand
            break
    if path is None:
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None

    site_type = raw.get("t")
    if not isinstance(site_type, str):
        site_type = None
    sh = raw.get("sh")
    rh = raw.get("rh")
    try:
        site_heading = int(sh) if sh is not None else -1
    except (TypeError, ValueError):
        site_heading = -1
    try:
        relic_heading = int(rh) if rh is not None else -1
    except (TypeError, ValueError):
        relic_heading = -1

    lat = lon = None
    ll = raw.get("ll")
    if isinstance(ll, dict):
        try:
            if ll.get("lat") is not None:
                lat = float(ll["lat"])
            if ll.get("long") is not None:
                lon = float(ll["long"])
        except (TypeError, ValueError):
            lat = lon = None

    obelisks: list[ActiveObelisk] = []
    ao = raw.get("ao")
    if isinstance(ao, list):
        for row in ao:
            if isinstance(row, str):
                parsed = parse_active_obelisk(row)
                if parsed is not None:
                    obelisks.append(parsed)

    og = raw.get("og")
    sid = raw.get("sid")
    return GuardianPub(
        body_name=body_name,
        index=int(index),
        is_ruins=is_ruins,
        site_type=site_type,
        site_heading=site_heading,
        relic_heading=relic_heading,
        latitude=lat,
        longitude=lon,
        site_id=sid if isinstance(sid, str) else None,
        obelisk_groups=og if isinstance(og, str) else "",
        present=_parse_csv_set(raw.get("pa")),
        absent=_parse_csv_set(raw.get("pp")),
        empty=_parse_csv_set(raw.get("pe")),
        active_obelisks=tuple(obelisks),
        raw=raw,
        relic_tower_headings=parse_relic_tower_headings(raw.get("rth")),
    )


def find_pub_for_site(
    body_name: str | None,
    index: int | None,
    is_ruins: bool,
    *,
    pub_dir: Path | None = None,
) -> GuardianPub | None:
    return load_pub(body_name, index, is_ruins, pub_dir=pub_dir)


def poi_status(pub: GuardianPub | None, name: str) -> str:
    """present | absent | empty | unknown."""
    if pub is None:
        return "unknown"
    if name in pub.present:
        return "present"
    if name in pub.absent:
        return "absent"
    if name in pub.empty:
        return "empty"
    return "unknown"


def filter_pois_for_site(
    pois: list[SitePoi],
    pub: GuardianPub | None,
) -> list[SitePoi]:
    """Skip obelisks whose group letter is not in pub.og (when og set)."""
    if pub is None or not pub.obelisk_groups:
        return pois
    groups = set(pub.obelisk_groups)
    out: list[SitePoi] = []
    for poi in pois:
        if poi.poi_type in ("obelisk", "brokeObelisk") and poi.name:
            if poi.name[0] not in groups:
                continue
        out.append(poi)
    return out
