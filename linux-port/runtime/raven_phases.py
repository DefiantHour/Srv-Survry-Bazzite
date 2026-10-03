#!/usr/bin/env python3
"""FormRavenUpdater site buckets.

Installation and orbital-port names come from colonization-costs2.json the
same way the Windows form builds them, plus the seed names installation,
outpost, and orbis. Surface review is every other site, including a blank
build type.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


def _costs_path() -> Path:
    return Path(__file__).resolve().parents[2] / "SrvSurvey" / "colonization-costs2.json"


@lru_cache(maxsize=1)
def build_type_sets() -> tuple[frozenset[str], frozenset[str]]:
    installation = {"installation"}
    orbital = {"outpost", "orbis"}
    path = _costs_path()
    if path.is_file():
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            rows = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict) or str(row.get("location") or "") != "orbital":
                    continue
                display = str(row.get("displayName") or "")
                category = str(row.get("category") or "")
                layouts = row.get("layouts")
                if not isinstance(layouts, list):
                    continue
                install = "Installation" in display or "Tourist" in category or "Bar" in category
                target = installation if install else orbital
                for name in layouts:
                    text = str(name or "").strip()
                    if text:
                        target.add(text.lower())
    return frozenset(installation), frozenset(orbital)


def normalize_build(build_type: str | None) -> str:
    return (build_type or "").strip().rstrip("?").lower()


def site_in_phase(phase: str, body_num: int | None, build_type: str | None) -> bool:
    """Windows setFilter. body_num below zero means the site has no body."""
    installation, orbital = build_type_sets()
    build = normalize_build(build_type)
    missing = body_num is None or body_num < 0
    if phase == "noBodyInstallation":
        return missing and build in installation
    if phase == "noBodyOrbitalPorts":
        return missing and build in orbital
    if phase == "allSurfaceSites":
        return build == "" or (build not in orbital and build not in installation)
    return False
