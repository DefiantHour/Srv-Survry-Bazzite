#!/usr/bin/env python3
"""Ship cockpit offsets — Windows CanonnStation.mapShipCockpitOffsets.

Offsets are meters from the pad center to the cockpit. Landing lat/long from
the journal is the cockpit; surveys want the ship center. Values are read
from SrvSurvey/net/CanonnStation.cs so the table stays the Windows table.
Overrides persist under XDG, never in the main config.
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

_POINT = re.compile(
    r'\{\s*"([^"]+)"\s*,\s*new PointM\(\s*([^,]+)\s*,\s*([^)]+)\)',
)


def _parse_number(text: str) -> float:
    cleaned = text.strip().rstrip("dDmMfF")
    return float(cleaned)


def load_windows_offsets(cs_path: Path | None = None) -> dict[str, tuple[float, float]]:
    path = cs_path or (
        Path(__file__).resolve().parents[2] / "SrvSurvey" / "net" / "CanonnStation.cs"
    )
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    start = text.find("mapShipCockpitOffsets")
    end = text.find("mapShipSizes", start if start >= 0 else 0)
    block = text[start:end] if start >= 0 else text
    offsets: dict[str, tuple[float, float]] = {}
    for match in _POINT.finditer(block):
        offsets[match.group(1)] = (
            _parse_number(match.group(2)),
            _parse_number(match.group(3)),
        )
    return offsets


def offsets_path(home: Path | None = None, environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    root = Path.home() if home is None else home
    xdg = env.get("XDG_DATA_HOME") or str(root / ".local" / "share")
    return Path(xdg) / "srvsurvey" / "ship-offsets.json"


def merged_offsets(
    *,
    home: Path | None = None,
    environ: dict[str, str] | None = None,
    cs_path: Path | None = None,
) -> dict[str, tuple[float, float]]:
    table = load_windows_offsets(cs_path)
    path = offsets_path(home, environ)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            raw = None
        if isinstance(raw, dict):
            for key, value in raw.items():
                if (
                    isinstance(value, (list, tuple))
                    and len(value) == 2
                    and isinstance(value[0], (int, float))
                    and isinstance(value[1], (int, float))
                ):
                    table[str(key)] = (float(value[0]), float(value[1]))
    return table


def set_ship_offset(
    ship_type: str,
    x_m: float,
    y_m: float,
    *,
    home: Path | None = None,
    environ: dict[str, str] | None = None,
) -> Path:
    path = offsets_path(home, environ)
    current: dict[str, list[float]] = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            raw = None
        if isinstance(raw, dict):
            current = {
                str(k): [float(v[0]), float(v[1])]
                for k, v in raw.items()
                if isinstance(v, (list, tuple)) and len(v) == 2
            }
    current[ship_type] = [float(x_m), float(y_m)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    return path


def _rotate(x_m: float, y_m: float, heading_deg: float) -> tuple[float, float]:
    """PointM.rotate: polar angle is atan2(x, y), then sin/cos of angle+heading."""
    length = math.hypot(x_m, y_m)
    if length == 0:
        return (0.0, 0.0)
    angle = math.degrees(math.atan2(x_m, y_m))
    if angle < 0:
        angle += 360.0
    rad = math.radians(angle + heading_deg)
    return (math.sin(rad) * length, math.cos(rad) * length)


def adjust_landing(
    ship_type: str | None,
    latitude: float,
    longitude: float,
    heading_deg: float,
    body_radius_m: float,
    *,
    offsets: dict[str, tuple[float, float]] | None = None,
) -> tuple[float, float]:
    """Move a cockpit lat/long to the ship center. Foot and unknown ships stay put."""
    if not ship_type or ship_type == "foot" or body_radius_m <= 0:
        return (latitude, longitude)
    table = offsets if offsets is not None else merged_offsets()
    offset = table.get(ship_type)
    if offset is None or (offset[0] == 0 and offset[1] == 0):
        return (latitude, longitude)
    rx, ry = _rotate(offset[0], offset[1], heading_deg)
    meters_per_degree = (2 * math.pi * body_radius_m) / 360.0
    if meters_per_degree == 0:
        return (latitude, longitude)
    degrees_per_meter = 1.0 / meters_per_degree
    return (latitude + ry * degrees_per_meter, longitude + rx * degrees_per_meter)
