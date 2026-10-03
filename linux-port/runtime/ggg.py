#!/usr/bin/env python3
"""Gas Giant Goldilocks (GGG) temp-table match + upload hook.

Linux port of ``SystemData.getTagForGGG`` / Scan upload path in SystemData.cs.
Loads local ``ggg.json`` when present; otherwise ``get_tag_for_ggg`` returns None.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from paths import srvsurvey_data_dir

_log = logging.getLogger("srvsurvey.ggg")

# Cached table — path → (mtime, data) or None when missing.
_table_cache: dict[str, tuple[float, dict[str, Any]] | None] = {}


def clear_cache() -> None:
    _table_cache.clear()


def resolve_ggg_path(
    *,
    explicit: Path | str | None = None,
    home: Path | None = None,
    environ: dict[str, str] | None = None,
) -> Path | None:
    """Find ggg.json: override → env → XDG pub → repo SrvSurvey/ggg.json."""
    env = os.environ if environ is None else environ
    if explicit is not None:
        path = Path(explicit)
        return path if path.is_file() else None
    override = (env.get("SRVSURVEY_GGG_PATH") or "").strip()
    if override:
        path = Path(override)
        return path if path.is_file() else None

    data = srvsurvey_data_dir(environ=dict(env), home=home)
    candidates = [
        data / "pub" / "ggg.json",
        data / "ggg.json",
    ]
    # Repo checkout: linux-port/runtime → ../../SrvSurvey/ggg.json
    here = Path(__file__).resolve()
    repo_ggg = here.parent.parent.parent / "SrvSurvey" / "ggg.json"
    candidates.append(repo_ggg)

    for path in candidates:
        if path.is_file():
            return path
    return None


def load_ggg_table(path: Path | str | None = None) -> dict[str, Any] | None:
    """Load / cache GGG JSON. Returns None if missing or invalid."""
    resolved = resolve_ggg_path(explicit=path) if path is not None else resolve_ggg_path()
    if resolved is None:
        return None
    key = str(resolved)
    try:
        mtime = resolved.stat().st_mtime
    except OSError:
        return None
    hit = _table_cache.get(key)
    if hit is not None and hit[0] == mtime:
        return hit[1]
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("GGG load failed %s: %s", resolved, exc)
        _table_cache[key] = None
        return None
    if not isinstance(raw, dict):
        _table_cache[key] = None
        return None
    _table_cache[key] = (mtime, raw)
    return raw


def get_tag_for_ggg(
    planet_class: str,
    surface_temp: float,
    *,
    table: dict[str, Any] | None = None,
    path: Path | str | None = None,
) -> str | None:
    """Match Windows ``SystemData.getTagForGGG`` (with theorized exact-match fix).

    Windows checks ``knownTemps`` again for the ``potential`` branch (dead code).
    Linux uses ``theorizedTemps`` for that exact match so theorized Goldilocks work.
    """
    data = table if table is not None else load_ggg_table(path)
    if data is None:
        return None
    try:
        delta = float(data.get("delta", 0.001))
    except (TypeError, ValueError):
        delta = 0.001
    known_map = data.get("knownGGGTemps")
    theorized_map = data.get("theorizedGGGTemps")
    known: list[float] = []
    theorized: list[float] = []
    if isinstance(known_map, dict):
        raw = known_map.get(planet_class)
        if isinstance(raw, list):
            known = [float(t) for t in raw if isinstance(t, (int, float))]
    if isinstance(theorized_map, dict):
        raw = theorized_map.get(planet_class)
        if isinstance(raw, list):
            theorized = [float(t) for t in raw if isinstance(t, (int, float))]

    if surface_temp in known:
        return "likely"
    if any(surface_temp > t - delta and surface_temp < t + delta for t in known):
        return "likely-approx"
    if surface_temp in theorized:
        return "potential"
    if any(surface_temp > t - delta and surface_temp < t + delta for t in theorized):
        return "potential-approx"
    return None


def maybe_upload_from_scan(
    entry: dict[str, Any],
    *,
    upload_ggg_enabled: bool,
    commander: str | None,
    star_pos: tuple[float, float, float] | list[float] | None,
    table: dict[str, Any] | None = None,
    svc_uri: str | None = None,
) -> str | None:
    """If Scan is a gas-giant GGG match, upload via RavenColonial. Returns tag or None.

    Fail-soft: never raises into the HUD loop.
    """
    if not upload_ggg_enabled:
        return None
    if not isinstance(entry, dict) or entry.get("event") != "Scan":
        return None
    planet = entry.get("PlanetClass")
    if not isinstance(planet, str) or "giant" not in planet.lower():
        return None
    temp_raw = entry.get("SurfaceTemperature")
    if not isinstance(temp_raw, (int, float)):
        return None
    cmdr = (commander or "").strip()
    if not cmdr:
        return None
    if star_pos is None or len(star_pos) != 3:
        return None

    try:
        tag = get_tag_for_ggg(planet, float(temp_raw), table=table)
    except Exception as exc:
        _log.warning("GGG tag match failed: %s", exc)
        return None
    if tag is None:
        return None

    try:
        from raven_colonial import upload_ggg

        body_json = json.dumps(entry, separators=(",", ":"))
        pos = [float(star_pos[0]), float(star_pos[1]), float(star_pos[2])]
        upload_ggg(cmdr, tag, pos, body_json, svc_uri=svc_uri)
        _log.info(
            "GGG match: %s! body: %s, temp: %s",
            tag,
            entry.get("BodyName"),
            temp_raw,
        )
        return tag
    except Exception as exc:
        _log.warning("GGG upload failed: %s", exc)
        return None
