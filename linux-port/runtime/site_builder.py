#!/usr/bin/env python3
"""Human-site footprint builder — Windows FormBuilder without live shields.

Records polygon vertices and circles in site-local meters, then writes a
building into a template JSON file. Point entry is explicit (the Linux
client has no DirectX overlay to sample shield toggles from).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def new_building(name: str = "") -> dict[str, Any]:
    return {"name": name, "polygons": [], "circles": [], "open_polygon": []}


def add_point(building: dict[str, Any], x: float, y: float) -> dict[str, Any]:
    open_path = building.setdefault("open_polygon", [])
    if not isinstance(open_path, list):
        open_path = []
        building["open_polygon"] = open_path
    open_path.append({"x": float(x), "y": float(y)})
    return building


def end_polygon(building: dict[str, Any]) -> dict[str, Any]:
    open_path = building.get("open_polygon") or []
    if isinstance(open_path, list) and len(open_path) >= 2:
        building.setdefault("polygons", []).append(list(open_path))
    building["open_polygon"] = []
    return building


def add_circle(building: dict[str, Any], x: float, y: float, radius: float) -> dict[str, Any]:
    building.setdefault("circles", []).append(
        {"x": float(x), "y": float(y), "radius": float(radius)}
    )
    return building


def commit_building(template: dict[str, Any], building: dict[str, Any], name: str) -> dict[str, Any]:
    finished = {
        "name": name.strip() or building.get("name") or "Building",
        "polygons": list(building.get("polygons") or []),
        "circles": list(building.get("circles") or []),
    }
    open_path = building.get("open_polygon") or []
    if isinstance(open_path, list) and len(open_path) >= 2:
        finished["polygons"].append(list(open_path))
    template.setdefault("buildings", [])
    if not isinstance(template["buildings"], list):
        template["buildings"] = []
    template["buildings"].append(finished)
    return template


def save_template(template: dict[str, Any], path: Path | str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    return target


def load_template(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    if not target.is_file():
        return {"name": target.stem, "buildings": []}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {"name": target.stem, "buildings": []}
    if not isinstance(raw, dict):
        return {"name": target.stem, "buildings": []}
    raw.setdefault("buildings", [])
    return raw
