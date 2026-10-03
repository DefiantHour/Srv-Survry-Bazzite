#!/usr/bin/env python3
"""Galactic region id from star position — Windows EliteDangerousRegionMap.RegionMap.

Reads RegionNames and RegionMapLines from the Windows RegionMapData.cs so the
map stays the same file the Windows build ships.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_X0 = -49985
_Z0 = -24105


def _data_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "SrvSurvey"
        / "EliteDangerousRegionMap"
        / "RegionMapData.cs"
    )


@lru_cache(maxsize=1)
def _load() -> tuple[tuple[str, ...], tuple[tuple[tuple[int, int], ...], ...]]:
    text = _data_path().read_text(encoding="utf-8")
    name_block = text.split("RegionMapLines", 1)[0]
    names = tuple(re.findall(r'"([^"]+)"', name_block))
    line_block = text.split("RegionMapLines", 1)[1]
    rows: list[tuple[tuple[int, int], ...]] = []
    for line in line_block.splitlines():
        if "new[]" not in line:
            continue
        pairs = tuple(
            (int(a), int(b)) for a, b in re.findall(r"\((\d+)\s*,\s*(\d+)\)", line)
        )
        rows.append(pairs)
    return names, tuple(rows)


def find_region(x: float, y: float, z: float) -> tuple[int, str] | None:
    """Return (region id, name). y is unused, matching Windows FindRegion."""
    del y
    names, rows = _load()
    px = int((x - _X0) * 83 / 4096)
    pz = int((z - _Z0) * 83 / 4096)
    if px < 0 or pz < 0 or pz >= len(rows):
        return None
    rx = 0
    pv = 0
    for run, value in rows[pz]:
        if px < rx + run:
            pv = value
            break
        rx += run
    if pv <= 0 or pv > len(names):
        return None
    return pv, names[pv - 1]


def closest_nebula_ly(star_pos: tuple[float, float, float] | None) -> float:
    """Minimum distance to docs/nebulae.json. Large value when unknown."""
    if star_pos is None or len(star_pos) != 3:
        return 99999.0
    points = _nebulae()
    if not points:
        return 99999.0
    sx, sy, sz = float(star_pos[0]), float(star_pos[1]), float(star_pos[2])
    best = 99999.0
    for x, y, z in points:
        dist = ((sx - x) ** 2 + (sy - y) ** 2 + (sz - z) ** 2) ** 0.5
        if dist < best:
            best = dist
    return best


@lru_cache(maxsize=1)
def _nebulae() -> tuple[tuple[float, float, float], ...]:
    path = Path(__file__).resolve().parents[2] / "docs" / "nebulae.json"
    try:
        import json

        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    if not isinstance(raw, list):
        return ()
    out: list[tuple[float, float, float]] = []
    for row in raw:
        if isinstance(row, list) and len(row) >= 3:
            out.append((float(row[0]), float(row[1]), float(row[2])))
    return tuple(out)
