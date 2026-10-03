#!/usr/bin/env python3
"""Raven Colonial scanning wizard — Windows FormRavenUpdater phases.

Decides the next instruction from journal survey fields and the system
payload already loaded by GET /api/v2/system. Body import and site submit
stay on the existing RCC client; this module only chooses the phase.
"""

from __future__ import annotations

from typing import Any

PHASES = (
    "preamble",
    "scanning",
    "noBodyInstallation",
    "noBodyOrbitalPorts",
    "allSurfaceSites",
    "allDone",
)

ORBITAL_BUILD_HINTS = ("outpost", "orbis", "ocellus", "coriolis", "asteroid", "dodec")
INSTALLATION_HINTS = ("installation",)
SURFACE_HINTS = ("settlement", "facility", "port")


def _as_int(raw: object) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    return None


def scan_instruction(
    *,
    fss_progress: float | None,
    fss_complete: bool,
    body_count: int | None,
    scanned_count: int,
    bodies_known: int,
) -> tuple[str, str]:
    """Return (phase, message) for the discovery half of the wizard."""
    if not fss_complete:
        if fss_progress is None:
            return ("scanning", "Discovery scan needed.")
        if fss_progress < 1:
            return ("scanning", "Complete system FSS.")
    total = body_count if body_count is not None else scanned_count
    if total and scanned_count < total:
        return ("scanning", "Scan the nav beacon.")
    if body_count is not None and bodies_known < body_count:
        return ("scanning", "Import system bodies.")
    return ("noBodyInstallation", "Review installations with no body.")


def _site_build(site: dict[str, Any]) -> str:
    raw = site.get("buildType") or site.get("build_type") or site.get("type") or ""
    return str(raw).lower()


def _site_body(site: dict[str, Any]) -> int | None:
    for key in ("bodyNum", "body_num", "bodyId", "bodyID"):
        value = _as_int(site.get(key))
        if value is not None:
            return value
    return None


def review_bucket(sites: list[dict[str, Any]], phase: str) -> list[dict[str, Any]]:
    """Sites the Windows wizard shows for one review phase."""
    picked: list[dict[str, Any]] = []
    for site in sites:
        if not isinstance(site, dict):
            continue
        build = _site_build(site)
        body = _site_body(site)
        missing_body = body is None or body < 0
        if phase == "noBodyInstallation":
            if missing_body and any(hint in build for hint in INSTALLATION_HINTS):
                picked.append(site)
        elif phase == "noBodyOrbitalPorts":
            if missing_body and any(hint in build for hint in ORBITAL_BUILD_HINTS):
                picked.append(site)
        elif phase == "allSurfaceSites":
            if any(hint in build for hint in SURFACE_HINTS):
                picked.append(site)
    return picked


def next_phase(
    current: str,
    sites: list[dict[str, Any]],
    *,
    scan_done: bool,
) -> tuple[str, str]:
    """Advance FormRavenUpdater.nextPhase once scanning is finished."""
    if not scan_done:
        return ("scanning", "Finish the system scan before reviewing sites.")
    order = ["noBodyInstallation", "noBodyOrbitalPorts", "allSurfaceSites", "allDone"]
    start = 0
    if current in order:
        start = order.index(current)
    for phase in order[start:]:
        if phase == "allDone":
            return ("allDone", "Scan review complete.")
        rows = review_bucket(sites, phase)
        if rows or phase == current:
            label = {
                "noBodyInstallation": "Confirm installations that have no body.",
                "noBodyOrbitalPorts": "Confirm orbital ports that have no body.",
                "allSurfaceSites": "Review surface sites.",
            }[phase]
            if current == phase:
                continue
            return (phase, f"{label} ({len(rows)})")
    return ("allDone", "Scan review complete.")
