#!/usr/bin/env python3
"""Windows PlotPos.getPlotterLocation for the Linux presenter.

Reads SrvSurvey/plotters.json. Coordinates are game-local, matching PlotBase2
when the big overlay is on (game origin is zeroed). ``screen`` anchors stay
absolute pixels.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

_ENTRY = re.compile(r'"([^"]+)"\s*:\s*"([^"]+)"')
_HORIZONTAL = frozenset({"left", "center", "right", "os"})
_VERTICAL = frozenset({"top", "middle", "bottom", "os"})


def _plotters_path() -> Path:
    return Path(__file__).resolve().parents[2] / "SrvSurvey" / "plotters.json"


def user_anchors_path() -> Path:
    """Per-plotter overrides. The spec plotters.json in the repo is not rewritten."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "srvsurvey" / "plotter-anchors.json"


def _read_user_anchors() -> dict[str, tuple[str, int, str, int, float | None]]:
    path = user_anchors_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    anchors: dict[str, tuple[str, int, str, int, float | None]] = {}
    for name, row in data.items():
        if not isinstance(name, str) or not isinstance(row, list) or len(row) < 4:
            continue
        horizontal = str(row[0]).lower()
        vertical = str(row[2]).lower()
        if horizontal not in _HORIZONTAL or vertical not in _VERTICAL:
            continue
        opacity: float | None = None
        try:
            if len(row) >= 5 and row[4] is not None:
                opacity = float(row[4])
                if opacity < 0 or opacity > 1:
                    opacity = None
            anchors[name] = (horizontal, int(row[1]), vertical, int(row[3]), opacity)
        except (TypeError, ValueError):
            continue
    return anchors


def _write_user_anchors(anchors: dict[str, tuple[str, int, str, int, float | None]]) -> None:
    path = user_anchors_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, list[object]] = {}
    for name, row in sorted(anchors.items()):
        item: list[object] = [row[0], row[1], row[2], row[3]]
        if row[4] is not None:
            item.append(row[4])
        payload[name] = item
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    plotter_anchors.cache_clear()


@lru_cache(maxsize=1)
def plotter_anchors() -> dict[str, tuple[str, int, str, int]]:
    text = _plotters_path().read_text(encoding="utf-8")
    anchors: dict[str, tuple[str, int, str, int]] = {}
    for name, raw in _ENTRY.findall(text):
        body = raw.split("{", 1)[0]
        parts = [part.strip() for part in re.split(r"[:,]", body) if part.strip()]
        if len(parts) < 4:
            continue
        anchors[name] = (parts[0].lower(), int(parts[1]), parts[2].lower(), int(parts[3]))
    for name, row in _read_user_anchors().items():
        anchors[name] = (row[0], row[1], row[2], row[3])
    return anchors


_KEEP = object()


def plotter_opacity(name: str) -> float | None:
    """Custom opacity from the adjust window. None uses the normal bitmap."""
    row = _read_user_anchors().get(name)
    if row is None:
        return None
    return row[4]


def scale_rgba_alpha(rgba: bytes, factor: float) -> bytes:
    """Multiply straight alpha. factor 1 leaves the bitmap unchanged."""
    if factor >= 0.999:
        return rgba
    if factor <= 0:
        return bytes(len(rgba))
    raw = bytearray(rgba)
    for index in range(3, len(raw), 4):
        raw[index] = int(raw[index] * factor)
    return bytes(raw)


def snapshot_user_anchors() -> str | None:
    """FormAdjustOverlay backup. None when the user has no overrides yet."""
    path = user_anchors_path()
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def restore_user_anchors(text: str | None) -> None:
    """FormAdjustOverlay cancel. Puts the override file back."""
    path = user_anchors_path()
    if text is None:
        if path.is_file():
            path.unlink()
        plotter_anchors.cache_clear()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)
    plotter_anchors.cache_clear()


def set_plotter_anchor(
    name: str,
    horizontal: str,
    x: int,
    vertical: str,
    y: int,
    opacity: float | None | object = _KEEP,
) -> None:
    """FormAdjustOverlay writes horiz, x, vert, y, and optional opacity."""
    plotter = (name or "").strip()
    if not plotter:
        raise ValueError("plotter name is required")
    horiz = (horizontal or "").strip().lower()
    vert = (vertical or "").strip().lower()
    if horiz not in _HORIZONTAL:
        raise ValueError(f"horizontal must be one of {sorted(_HORIZONTAL)}")
    if vert not in _VERTICAL:
        raise ValueError(f"vertical must be one of {sorted(_VERTICAL)}")
    current = dict(_read_user_anchors())
    previous = current.get(plotter)
    kept: float | None = previous[4] if previous is not None else None
    if opacity is not _KEEP:
        if opacity is None:
            kept = None
        else:
            kept = float(opacity)
            if kept < 0 or kept > 1:
                raise ValueError("Opacity must be a decimal number between 0 and 1")
    current[plotter] = (horiz, int(x), vert, int(y), kept)
    _write_user_anchors(current)


def reset_plotter_anchor(name: str) -> None:
    current = dict(_read_user_anchors())
    current.pop(name, None)
    _write_user_anchors(current)


def plotter_origin(
    plotter_name: str,
    width: int,
    height: int,
    game_width: int,
    game_height: int,
) -> tuple[int, int] | None:
    """Return game-local x, y. None when plotters.json has no entry."""
    anchor = plotter_anchors().get(plotter_name)
    if anchor is None:
        return None
    horizontal, hx, vertical, hy = anchor
    if horizontal == "left":
        x = hx
    elif horizontal == "center":
        x = (game_width // 2) - (width // 2) + hx
    elif horizontal == "right":
        x = game_width - width - hx
    else:
        x = hx
    if vertical == "top":
        y = hy
    elif vertical == "middle":
        y = (game_height // 2) - (height // 2) + hy
    elif vertical == "bottom":
        y = game_height - height - hy
    else:
        y = hy
    return max(0, x), max(0, y)


def trackers_origin(
    width: int,
    height: int,
    game_width: int,
    game_height: int,
    grounded: tuple[int, int, int, int] | None = None,
) -> tuple[int, int] | None:
    """PlotTrackers.setPosition.

    PlotTrackers is not in plotters.json. Windows parks it under PlotGrounded
    when that plotter is open, otherwise on PlotGrounded's own anchor
    (right:8, middle:0).
    """
    if grounded is not None:
        gx, gy, _gw, gh = grounded
        return max(0, gx), max(0, gy + gh + 4)
    return plotter_origin("PlotGrounded", width, height, game_width, game_height)


# Linux panel id → Windows plotter name in plotters.json.
PLOT_NAME = {
    "sysstatus": "PlotSysStatus",
    "biostatus": "PlotBioStatus",
    "biosystem": "PlotBioSystem",
    "fss": "PlotFSSInfo",
    "fsslast": "PlotFSS",
    "jumpinfo": "PlotJumpInfo",
    "galmap": "PlotGalMap",
    "bodyinfo": "PlotBodyInfo",
    "guardians": "PlotGuardians",
    "guardiansystem": "PlotGuardianSystem",
    "guardianstatus": "PlotGuardianStatus",
    "ramtah": "PlotRamTah",
    "humansite": "PlotHumanSite",
    "priorscans": "PlotPriorScans",
    "tracktarget": "PlotTrackTarget",
    "minitrack": "PlotMiniTrack",
    "massacre": "PlotMassacre",
    "floatie": "PlotFloatie",
    "footcombat": "PlotFootCombat",
    "grounded": "PlotGrounded",
    "adjustvr": "PlotAdjustVR",
    "pulse": "PlotPulse",
    "questmini": "PlotQuestMini",
    "spherical": "PlotSphericalSearch",
    "station": "PlotStationInfo",
    "flightwarn": "PlotFlightWarning",
    "colonisation": "PlotBuildCommodities",
}

# Sections the Linux status box invented. Windows has no plotter by these names.
LINUX_ONLY_PANELS = frozenset(
    {
        "location",
        "survey",
        "bio",
        "signals",
        "route",
        "ship",
        "materials",
        "locker",
        "human",
        "guardian",
    }
)
