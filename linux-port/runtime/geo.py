#!/usr/bin/env python3
"""Lat/long distance + bearing helpers — Linux port of Util.getDistance / getBearing."""

from __future__ import annotations

import math


def meters_to_string(meters: float, *, as_delta: bool = False) -> str:
    """Match Util.metersToString (4 significant digits, m / km / Mm)."""
    prefix = ""
    m = float(meters)
    if as_delta:
        prefix = "-" if m < 0 else "+"
    if m < 0:
        m = -m
    if m < 1:
        return "0m"
    if m < 1000:
        return f"{prefix}{m:.0f}m"
    m = m / 1000.0
    if m < 10:
        txt = f"{m:.2f}".rstrip("0").rstrip(".")
        return f"{prefix}{txt}km"
    if m < 1000:
        txt = f"{m:.1f}".rstrip("0").rstrip(".")
        return f"{prefix}{txt}km"
    m = m / 1000.0
    txt = f"{m:.2f}".rstrip("0").rstrip(".")
    return f"{prefix}{txt}Mm"


def get_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    radius_m: float,
) -> float:
    """Great-circle distance in meters (Util.getDistance)."""
    if lat1 == lat2 and lon1 == lon2:
        return 0.0
    if radius_m <= 0:
        return 0.0
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    z = math.sin(rlat1) * math.sin(rlat2) + math.cos(rlat1) * math.cos(rlat2) * math.cos(
        math.radians(lon2 - lon1)
    )
    z = max(-1.0, min(1.0, z))
    return math.acos(z) * radius_m


def get_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Bearing degrees 0–360 from point 1 toward point 2 (Util.getBearing)."""
    rlat1 = math.radians(lat1)
    rlon1 = math.radians(lon1)
    rlat2 = math.radians(lat2)
    rlon2 = math.radians(lon2)
    x = math.cos(rlat2) * math.sin(rlon2 - rlon1)
    y = math.cos(rlat1) * math.sin(rlat2) - math.sin(rlat1) * math.cos(rlat2) * math.cos(
        rlon2 - rlon1
    )
    rad = math.atan2(x, y)
    if rad < 0:
        rad += 2.0 * math.pi
    deg = math.degrees(rad)
    if deg < 0:
        deg += 360.0
    return deg


def relative_bearing(target_bearing: float, heading: float) -> float:
    """Bearing relative to ship heading (may be negative)."""
    return float(target_bearing) - float(heading)


def offset_meters(
    lat_here: float,
    lon_here: float,
    lat_target: float,
    lon_target: float,
    radius_m: float,
    *,
    heading: float | None = None,
) -> tuple[float, float]:
    """Relative east/north offset in meters from here → target (TrackingDelta).

    When ``heading`` is set, rotate so +Y is ahead (heading-up radar).
    Returns ``(dx_east_or_right, dy_north_or_ahead)``.
    """
    dist = get_distance(lat_here, lon_here, lat_target, lon_target, radius_m)
    if dist <= 0:
        return 0.0, 0.0
    bearing = get_bearing(lat_here, lon_here, lat_target, lon_target)
    if heading is not None:
        bearing = (bearing - float(heading)) % 360.0
    rad = math.radians(bearing)
    return math.sin(rad) * dist, math.cos(rad) * dist


def draw_bearing_to(
    draw,
    x: float,
    y: float,
    radius: float,
    deg: float,
    *,
    outline,
    fill=None,
    msg: str | None = None,
    font=None,
    msg_fill=None,
) -> None:
    """Approximate BaseWidget.renderBearingTo — circle + pointing hand + optional label."""
    r = float(radius)
    bbox = [x, y, x + 2 * r, y + 2 * r]
    draw.ellipse(bbox, outline=outline, fill=fill)
    cx = x + r
    cy = y + r
    if deg != -1000:
        rad = math.radians(deg)
        # Windows: rotateLine then y - pt.Y (screen Y down)
        px = math.sin(rad) * r * 1.8
        py = math.cos(rad) * r * 1.8
        draw.line((cx, cy, cx + px, cy - py), fill=outline, width=max(1, int(r // 4) or 1))
    if msg and font is not None:
        mx = cx + r + 4
        my = y
        draw.text((mx, my), msg, font=font, fill=msg_fill or outline)
