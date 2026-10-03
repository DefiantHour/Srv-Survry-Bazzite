"""Exploration body value formulas — port of Util.GetBodyValue / Util.credits.

Source: forums.frontier.co.uk exploration-value-formulae (as used by Windows SrvSurvey).
"""

from __future__ import annotations

import math


def is_star_class(planet_class: str | None) -> bool:
    if planet_class is None:
        return False
    return (
        len(planet_class) < 8
        or (len(planet_class) > 1 and planet_class[1] == "_")
        or planet_class in {"SupermassiveBlackHole", "Nebula", "StellarRemnantNebula"}
    )


def star_k_value(star_class: str) -> float:
    kk = 1200.0
    if star_class in {"NS", "BH", "SupermassiveBlackHole"}:
        kk = 22628.0
    elif star_class and star_class[0] == "W":
        kk = 14057.0
    return kk


def body_k_value(planet_class: str, is_terraformable: bool) -> float:
    if planet_class == "Metal rich body":
        return 21790.0
    if planet_class == "Ammonia world":
        return 96932.0
    if planet_class == "Sudarsky class I gas giant":
        return 1656.0
    if planet_class in {"Sudarsky class II gas giant", "High metal content body"}:
        return 9654.0 + (100677.0 if is_terraformable else 0.0)
    if planet_class == "Water world":
        return 64831.0 + (116295.0 if is_terraformable else 0.0)
    if planet_class.startswith("Earth"):
        return 64831.0 + 116295.0
    return 300.0 + (93328.0 if is_terraformable else 0.0)


def get_body_value(
    planet_class: str | None,
    is_terraformable: bool,
    mass: float,
    is_first_discoverer: bool,
    is_mapped: bool,
    is_first_mapped: bool,
    *,
    with_efficiency_bonus: bool = True,
    is_odyssey: bool = True,
    is_fleet_carrier_sale: bool = False,
) -> int:
    if is_star_class(planet_class):
        kk = star_k_value(planet_class or "")
        return int(round(kk + (mass * kk / 66.25)))

    k = body_k_value(planet_class or "", is_terraformable)
    q = 0.56591828
    mapping_multiplier = 1.0
    if is_mapped:
        if is_first_discoverer and is_first_mapped:
            mapping_multiplier = 3.699622554
        elif is_first_mapped:
            mapping_multiplier = 8.0956
        else:
            mapping_multiplier = 3.3333333333
    value = (k + k * q * math.pow(mass, 0.2)) * mapping_multiplier
    if is_mapped:
        if is_odyssey:
            value += (value * 0.3) if (value * 0.3) > 555 else 555
        if with_efficiency_bonus:
            value *= 1.25
    value = max(500.0, value)
    value *= 2.6 if is_first_discoverer else 1.0
    value *= 0.75 if is_fleet_carrier_sale else 1.0
    return int(round(value))


def get_body_value_from_scan(scan: dict, cmdr_mapped: bool) -> int:
    """Scan journal event → FSS (cmdr_mapped=False) or DSS (True) value."""
    planet_class = scan.get("PlanetClass") or scan.get("StarType")
    if not isinstance(planet_class, str):
        planet_class = None
    terraform = scan.get("TerraformState") == "Terraformable"
    mass_em = scan.get("MassEM")
    stellar = scan.get("StellarMass")
    mass = 0.0
    if isinstance(mass_em, (int, float)) and mass_em > 0:
        mass = float(mass_em)
    elif isinstance(stellar, (int, float)):
        mass = float(stellar)
    was_discovered = scan.get("WasDiscovered") is True
    was_mapped = scan.get("WasMapped") is True
    return get_body_value(
        planet_class,
        terraform,
        mass,
        not was_discovered,
        cmdr_mapped,
        not was_mapped,
    )


def _is_main_star(body) -> bool:
    if getattr(body, "body_type", "") != "Star":
        return False
    if getattr(body, "is_main_star", False):
        return True
    if getattr(body, "body_id", None) == 0:
        return True
    name = str(getattr(body, "body_name", "") or "")
    return name.endswith("A")


def main_star_honk_reward(bodies, body_count: int) -> tuple[object, int] | None:
    """Windows ``applyMainStarHonkBonus``.

    Returns the main-star body and its replacement reward. Unscanned
    bodies implied by ``body_count`` add 500 each. Stars use 30 percent
    of the base value. Planets use one third of the unmapped base, with
    a 500 floor, then 2.6 when the body was not discovered.
    """
    q = 0.56591828
    bonus = 0.0
    uncounted = int(body_count) - 1
    main = None
    for body in bodies:
        if _is_main_star(body):
            if main is None:
                main = body
            continue
        if getattr(body, "body_type", "") == "Asteroid":
            continue
        uncounted -= 1
        kind = getattr(body, "body_type", "")
        mass = float(getattr(body, "mass", 0.0) or 0.0)
        discovered = bool(getattr(body, "was_discovered", True))
        if kind == "Star":
            star_class = getattr(body, "star_type", None) or getattr(body, "planet_class", None)
            value = get_body_value(star_class, False, mass, False, False, False) * 0.3
            if not discovered:
                value *= 2.6
            bonus += value
        elif kind in {"LandableBody", "SolidBody", "Giant"}:
            planet = getattr(body, "planet_class", None) or ""
            k = body_k_value(planet, bool(getattr(body, "terraformable", False)))
            raw = (k + k * q * math.pow(max(mass, 0.0), 0.2)) / 3.0
            value = max(500.0, raw)
            if not discovered:
                value *= 2.6
            bonus += value
    if uncounted > 0:
        bonus += uncounted * 500
    if main is None:
        return None
    star_class = getattr(main, "star_type", None) or getattr(main, "planet_class", None)
    base = get_body_value(
        star_class,
        False,
        float(getattr(main, "mass", 0.0) or 0.0),
        False,
        False,
        False,
    )
    return main, base + int(bonus)


def format_credits(amount: int | float, *, hide_units: bool = False) -> str:
    """Match Util.credits formatting."""
    credits = int(amount)
    if credits < 1_000:
        txt = f"{credits:,}"
    elif credits < 100_000:
        txt = f"{credits / 1_000:.2f}".rstrip("0").rstrip(".") + " K"
    elif credits < 1_000_000:
        txt = f"{credits // 1_000} K"
    elif credits < 100_000_000:
        txt = f"{credits / 1_000_000:.2f}".rstrip("0").rstrip(".") + " M"
    elif credits < 1_000_000_000:
        txt = f"{credits // 1_000_000} M"
    else:
        txt = f"{credits / 1_000_000_000:.3f}".rstrip("0").rstrip(".") + " B"
    if not hide_units:
        txt += " CR"
    return txt
