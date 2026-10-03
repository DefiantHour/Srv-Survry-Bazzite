#!/usr/bin/env python3
"""PlotGuardians — Linux site-map overlay from guardianSiteTemplates + pub data.

Modes (Windows PlotGuardians.Mode): site | heading | map | aerial (origin).
State lives in ``cmdr_state.GuardianSurveyState``; chat (``.aerial`` / ``.map`` /
``.heading`` / ``.site`` / ``z`` / ``.to`` / ``.add`` / ``.remove`` / ``.empty``)
or ``GameSettings.forceGuardianSurveyMode`` drives the active mode.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
import math
from pathlib import Path
from companion import StatusSnapshot
from game_settings import GameSettings
from guardian_templates import (
    SitePoi,
    filter_pois_for_site,
    find_pub_for_site,
    obelisk_group_name_locations,
    poi_status,
    poi_xy,
    relic_heading_for,
    rotate_line,
    template_for,
    template_pois,
)
from journal import GuardianSiteSummary, SurveyState
from theme import cyan, orange, orange_dim

TITLE_PX = 9
BODY_PX = 11
HEADING_PX = 36
PAD = 8
DEFAULT_WIDTH = 320
DEFAULT_HEIGHT = 440
MAP_PAD = 28

STRIPE = (12, 12, 12, 255)
BLACK = (0, 0, 0, 255)
LIME = (163, 255, 47, 255)
RED = (255, 60, 40, 255)
GRAY = (128, 128, 128, 255)
YELLOW = (255, 220, 40, 255)
MAGENTA = (255, 80, 200, 255)

MODES = frozenset({"map", "aerial", "heading", "site"})

_POI_COLOUR = {
    "obelisk": (84, 223, 237, 255),
    "brokeObelisk": (60, 90, 100, 255),
    "relic": (255, 180, 40, 255),
    "pylon": (200, 100, 255, 255),
    "component": (255, 111, 0, 255),
    "casket": (180, 140, 60, 255),
    "orb": (100, 180, 255, 255),
    "tablet": (160, 200, 80, 255),
    "totem": (220, 120, 80, 255),
    "urn": (140, 100, 180, 255),
}

_RUINS_TYPES = ("Alpha", "Beta", "Gamma")
_STRUCTURE_TYPES = (
    "Bear",
    "Bowl",
    "Crossroads",
    "Fistbump",
    "Hammerbot",
    "Lacrosse",
    "Robolobster",
    "Squid",
    "Stickyhand",
    "Turtle",
)


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    paths = (
        (
            "/usr/share/fonts/urw-base35/URWGothic-Demi.otf"
            if bold
            else "/usr/share/fonts/urw-base35/URWGothic-Book.otf"
        ),
        (
            "/usr/share/fonts/julietaula-montserrat-fonts/Montserrat-Bold.otf"
            if bold
            else "/usr/share/fonts/julietaula-montserrat-fonts/Montserrat-Regular.otf"
        ),
    )
    for path in paths:
        if Path(path).is_file():
            return ImageFont.truetype(path, size * SCALE)
    return ImageFont.load_default()


def _s(n: float) -> int:
    return int(round(n * SCALE))


def _tw(draw, text: str, font) -> int:
    b = draw.textbbox((0, 0), text, font=font)
    return int(b[2] - b[0])


def _background(draw, w: int, h: int, col) -> None:
    draw.rectangle((0, 0, w - 1, h - 1), fill=BLACK)
    step = _s(3)
    for y in range(0, h, step):
        draw.line((0, y, w - 1, y), fill=STRIPE)
    dim = orange_dim()
    for y, c in ((_s(3), dim), (_s(4), col), (_s(5), dim)):
        draw.line((_s(2), y, w - _s(4), y), fill=c)
    for y, c in (
        (h - _s(5), dim),
        (h - _s(4), col),
        (h - _s(3), dim),
    ):
        draw.line((_s(2), y, w - _s(4), y), fill=c)
    draw.rectangle((0, 0, w - 1, h - 1), outline=col, width=max(1, SCALE // 2))


def _finish(img):
    from PIL import Image

    if SCALE != 1:
        w, h = img.size
        img = img.resize((w // AA, h // AA), Image.Resampling.LANCZOS)
    w, h = img.size
    return img.tobytes("raw", "RGBA"), w, h


def surface_distance_m(
    lat1: float, lon1: float, lat2: float, lon2: float, radius_m: float
) -> float:
    if lat1 == lat2 and lon1 == lon2:
        return 0.0
    a1 = math.radians(lat1)
    a2 = math.radians(lat2)
    z = math.sin(a1) * math.sin(a2) + math.cos(a1) * math.cos(a2) * math.cos(
        math.radians(lon2 - lon1)
    )
    z = max(-1.0, min(1.0, z))
    return math.acos(z) * radius_m


def bearing_deg(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Initial bearing from (lat1,lon1) to (lat2,lon2), degrees 0–360."""
    φ1 = math.radians(lat1)
    φ2 = math.radians(lat2)
    Δλ = math.radians(lon2 - lon1)
    y = math.sin(Δλ) * math.cos(φ2)
    x = math.cos(φ1) * math.sin(φ2) - math.sin(φ1) * math.cos(φ2) * math.cos(Δλ)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def heading_delta(current: float, target: float) -> float:
    """Signed shortest turn from current to target (−180…+180)."""
    return ((float(target) - float(current) + 540.0) % 360.0) - 180.0


def resolve_guardian_site(survey: SurveyState) -> GuardianSiteSummary | None:
    if survey.current_guardian_site is not None:
        return survey.current_guardian_site
    if survey.guardian_sites:
        return survey.guardian_sites[-1]
    return None


def guardian_site_key(site: GuardianSiteSummary | None) -> str | None:
    if site is None:
        return None
    return site.name or site.display_text or None


def target_altitude_for_site(
    site_type: str | None, game: GameSettings
) -> float:
    """Match Util.targetAltitudeForSite."""
    if not site_type:
        return 650.0
    key = site_type.strip().lower()
    if key == "alpha":
        return float(game.aerialAltAlpha)
    if key == "beta":
        return float(game.aerialAltBeta)
    if key == "gamma":
        return float(game.aerialAltGamma)
    if key == "robolobster":
        return 1000.0
    if key == "crossroads":
        return 500.0
    if key == "fistbump":
        return 450.0
    return 650.0


def guardians_allowed(
    game: GameSettings,
    survey: SurveyState,
    status: StatusSnapshot | None,
) -> bool:
    """Match PlotGuardians.allowed (minus Commander null check)."""
    if not game.enableGuardianSites:
        return False
    if game.buildProjectsSuppressOtherOverlays:
        return False
    if status is None or not status.has_lat_long:
        return False
    if status.fsd_charging_jump:
        return False
    if resolve_guardian_site(survey) is None:
        return False
    if status.docked or status.supercruise:
        return False
    if status.on_foot or status.in_srv or status.in_fighter or status.landed:
        return True
    return status.in_main_ship


def _guardian_state_for(cmdr, site_key: str | None):
    """Resolve survey state via ``guardian_for``; never call ``guardian`` as a method."""
    if cmdr is None:
        return None
    guard_for = getattr(cmdr, "guardian_for", None)
    if callable(guard_for):
        return guard_for(site_key)
    guard = getattr(cmdr, "guardian", None)
    if callable(guard):
        return guard(site_key)
    return guard


def load_guardian_survey(
    survey: SurveyState,
    *,
    commander: str | None = None,
    cmdr=None,
):
    """Return (CmdrState|None, GuardianSurveyState|None, site_key).

    ``CmdrState.guardian`` is the active-site **property**; keyed lookup uses
    ``guardian_for(site_key)``.
    """
    from cmdr_state import guardian_site_key as _key_fn

    site = resolve_guardian_site(survey)
    key = _key_fn(site) or guardian_site_key(site)
    if cmdr is not None:
        g = _guardian_state_for(cmdr, key)
        if g is None:
            return cmdr, None, key
        return cmdr, g, key or getattr(g, "site_key", None) or key
    name = (commander or "").strip()
    if not name:
        return None, None, key
    try:
        from cmdr_state import get_commander

        state = get_commander(commander=name)
    except Exception:
        return None, None, key
    g = _guardian_state_for(state, key)
    if g is None:
        return state, None, key
    return state, g, key or getattr(g, "site_key", None) or key


# Back-compat alias
_load_guardian_state = load_guardian_survey


def site_context(
    survey: SurveyState,
    *,
    pub_dir=None,
    guardian_state=None,
):
    """Resolve (site, pub, site_type, heading) for map / listing.

    Cmdr overlay type/heading override pub / journal when set.
    """
    site = resolve_guardian_site(survey)
    if site is None:
        return None, None, None, -1
    pub = find_pub_for_site(
        site.body_name,
        site.index or (1 if not site.is_ruins else None),
        site.is_ruins,
        pub_dir=pub_dir,
    )
    site_type = site.site_type or (pub.site_type if pub else None)
    heading = pub.site_heading if pub and pub.site_heading >= 0 else -1
    if guardian_state is not None:
        if guardian_state.site_type:
            site_type = guardian_state.site_type
        raw_h = getattr(guardian_state, "heading", -1)
        try:
            gh = float(raw_h) if raw_h is not None else -1.0
        except (TypeError, ValueError):
            gh = -1.0
        if gh >= 0:
            heading = int(round(gh)) % 360
    return site, pub, site_type, heading


def resolve_survey_mode(
    *,
    site_type: str | None,
    heading: int,
    guardian_state=None,
    game: GameSettings | None = None,
) -> str:
    """Windows nextMode / setMode prerequisites + force / explicit mode."""
    gs = game if game is not None else GameSettings()
    forced = (gs.forceGuardianSurveyMode or "").strip().lower()
    explicit = None
    if guardian_state is not None:
        explicit = str(
            getattr(guardian_state, "plot_mode", None)
            or getattr(guardian_state, "mode", None)
            or "map"
        ).strip().lower()
        if explicit == "sitetype":
            explicit = "site"
    if forced in MODES:
        chosen = forced
    elif explicit in MODES:
        chosen = explicit
    else:
        chosen = "map"

    if not site_type:
        return "site"
    if heading < 0:
        return "heading"
    if chosen == "site":
        return "site" if forced == "site" else "map"
    return chosen if chosen in MODES else "map"


def map_scale_for_pois(pois, *, map_px: int, zoom: float = 1.0) -> float:
    if not pois:
        return 0.4 * zoom
    max_d = max((p.dist for p in pois), default=200.0)
    if max_d <= 0:
        max_d = 200.0
    usable = max(40.0, map_px / 2.0 - MAP_PAD)
    return (usable / max_d) * max(0.25, float(zoom))


def overlay_pois_from_state(guardian_state) -> list[SitePoi]:
    if guardian_state is None:
        return []
    out: list[SitePoi] = []
    for row in guardian_state.extra_poi or []:
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


def effective_poi_status(pub, name: str, guardian_state) -> str:
    if guardian_state is not None and name in (guardian_state.empty_puddles or []):
        return "empty"
    return poi_status(pub, name)


def poi_placement_from_status(
    status: StatusSnapshot | None,
    *,
    origin_lat: float | None,
    origin_lon: float | None,
    site_heading: float,
) -> tuple[float, float, float] | None:
    """Return (angle, dist, rot) for .add at current position (Windows formula)."""
    if (
        status is None
        or status.latitude is None
        or status.longitude is None
        or origin_lat is None
        or origin_lon is None
        or not status.planet_radius
        or status.planet_radius <= 0
        or site_heading < 0
    ):
        return None
    dist = surface_distance_m(
        status.latitude,
        status.longitude,
        origin_lat,
        origin_lon,
        status.planet_radius,
    )
    brg = bearing_deg(
        status.latitude,
        status.longitude,
        origin_lat,
        origin_lon,
    )
    angle = (brg - float(site_heading)) % 360.0
    rot = 0.0
    if status.heading is not None:
        rot = (float(status.heading) - float(site_heading)) % 360.0
    return angle, dist, rot


def aerial_guidance_lines(
    *,
    site_type: str | None,
    altitude: float | None,
    game: GameSettings,
) -> list[tuple[str, tuple[int, int, int, int]]]:
    """PlotVerticalStripe altitude assist as text rows (unit-testable)."""
    col = orange(game)
    dim = orange_dim(game)
    cy = cyan(game)
    target = target_altitude_for_site(site_type, game)
    lines: list[tuple[str, tuple[int, int, int, int]]] = [
        (f"Aerial assist · {site_type or 'Unknown'}", col),
        (f"Target altitude {target:.0f}m", cy),
    ]
    if altitude is None:
        lines.append(("Altitude unknown", dim))
        return lines
    diff = float(altitude) - target
    if abs(diff) <= 50:
        tone = col
        hint = "On target"
    elif diff < -50:
        tone = cy
        hint = f"Climb {abs(diff):.0f}m"
    else:
        tone = RED
        hint = f"Descend {diff:.0f}m"
    lines.append((f"Altitude {altitude:.0f}m  ({hint})", tone))
    # Bar: fill ratio toward target band
    band = 220.0
    closeness = max(0.0, min(1.0, 1.0 - abs(diff) / band))
    fill = int(round(closeness * 20))
    bar = "[" + ("█" * fill) + ("·" * (20 - fill)) + "]"
    lines.append((bar, tone))
    return lines


def confirm_counts(pois: list[SitePoi], status_for) -> tuple[int, int, int, int]:
    """Relic and item totals from the Windows site-map draw loop.

    Obelisks are omitted. A relic or item counts as confirmed when its
    status is anything other than unknown.
    """
    count_relics = 0
    confirmed_relics = 0
    count_items = 0
    confirmed_items = 0
    for poi in pois:
        kind = _norm_poi_type(poi.poi_type)
        if kind in ("obelisk", "brokeObelisk"):
            continue
        status = status_for(poi.name)
        if kind == "relic":
            count_relics += 1
            if status != "unknown":
                confirmed_relics += 1
        else:
            count_items += 1
            if status != "unknown":
                confirmed_items += 1
    return count_relics, confirmed_relics, count_items, confirmed_items


def survey_progress(
    pois: list[SitePoi],
    status_for,
    *,
    site_heading: int,
    relic_heading: int,
    is_ruins: bool,
    relic_headings: dict[str, int] | None = None,
) -> int:
    """Windows ``getCompletionStatus().progress``.

    ``maxScore`` counts every non-obelisk template POI plus the site
    heading. Unknown POIs add to the maximum and not to the score.
    A ruins site adds the single relic-tower heading. A structure adds one
    point for each present relic that has its own tower heading.
    """
    surveyable = 0
    confirmed = 0
    relics_present = 0
    for poi in pois:
        kind = _norm_poi_type(poi.poi_type)
        if kind in ("obelisk", "brokeObelisk"):
            continue
        surveyable += 1
        status = status_for(poi.name)
        if status == "unknown":
            continue
        confirmed += 1
        if kind == "relic" and status == "present":
            relics_present += 1
    score = confirmed
    if site_heading != -1:
        score += 1
    max_score = surveyable + 1
    if is_ruins:
        max_score += 1
        if relic_heading != -1:
            score += 1
    else:
        max_score += relics_present
        known = relic_headings or {}
        for poi in pois:
            if _norm_poi_type(poi.poi_type) != "relic":
                continue
            if status_for(poi.name) == "present" and poi.name in known:
                score += 1
    if max_score <= 0:
        return 0
    return int(100.0 / max_score * score)


def survey_header(
    percent: int,
    confirmed_relics: int,
    count_relics: int,
    confirmed_items: int,
    count_items: int,
) -> str:
    """Windows ``HeaderGeneral``: Survey: {0} | {1}/{2} relics, {3}/{4} items."""
    return (
        f"Survey: {percent}% | {confirmed_relics}/{count_relics} relics, "
        f"{confirmed_items}/{count_items} items"
    )


def guardians_lines(
    survey: SurveyState,
    status: StatusSnapshot | None = None,
    *,
    pub_dir=None,
    guardian_state=None,
    mode: str | None = None,
    game: GameSettings | None = None,
) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Header / status lines above the map (unit-testable)."""
    gs = game if game is not None else GameSettings()
    col = orange(gs)
    dim = orange_dim(gs)
    cy = cyan(gs)
    site, pub, site_type, heading = site_context(
        survey, pub_dir=pub_dir, guardian_state=guardian_state
    )
    active_mode = mode or resolve_survey_mode(
        site_type=site_type, heading=heading, guardian_state=guardian_state, game=gs
    )
    lines: list[tuple[str, tuple[int, int, int, int]]] = []
    if site is None:
        lines.append(("No Guardian site", dim))
        return lines
    title = site.display_text
    if site_type:
        title = f"{title} · {site_type}"
    lines.append((title, col))
    lines.append((f"Mode {active_mode}", cy))
    if pub and pub.site_id:
        lines.append((f"Canonn {pub.site_id}", dim))
    if heading >= 0:
        lines.append((f"Heading {heading}°", cy))
    else:
        lines.append(("Heading unknown", dim))

    if active_mode == "aerial":
        lines.extend(
            aerial_guidance_lines(
                site_type=site_type,
                altitude=status.altitude if status else None,
                game=gs,
            )
        )
        return lines

    if active_mode == "heading":
        cmdr_hdg = status.heading if status is not None else None
        if cmdr_hdg is not None:
            lines.append((f"Ship {cmdr_hdg:.0f}°", YELLOW))
            if heading >= 0:
                delta = heading_delta(cmdr_hdg, heading)
                sign = "+" if delta >= 0 else ""
                lines.append((f"Δ site {sign}{delta:.0f}°", cy))
            else:
                lines.append(("Align buttress then .heading", dim))
        else:
            lines.append(("Need Status heading", dim))
        return lines

    if active_mode == "site":
        if site.is_ruins:
            lines.append(("Set type: Alpha / Beta / Gamma", cy))
            lines.append(("Chat: .site Alpha   (or a / b / g)", dim))
        else:
            lines.append(("Set structure type via .site <Name>", cy))
            lines.append((", ".join(_STRUCTURE_TYPES[:5]) + "…", dim))
        return lines

    pois = template_pois(site_type)

    def _status(name: str) -> str:
        return poi_status(pub, name)

    count_relics, confirmed_relics, count_items, confirmed_items = confirm_counts(pois, _status)
    if confirmed_relics < count_relics or confirmed_items < count_items:
        merged_headings = dict(pub.relic_tower_headings if pub is not None else {})
        if guardian_state is not None:
            merged_headings.update(guardian_state.relic_headings)
        percent = survey_progress(
            pois,
            _status,
            site_heading=pub.site_heading if pub is not None else -1,
            relic_heading=pub.relic_heading if pub is not None else -1,
            is_ruins=bool(site.is_ruins),
            relic_headings=merged_headings,
        )
        lines.append(
            (
                survey_header(
                    percent,
                    confirmed_relics,
                    count_relics,
                    confirmed_items,
                    count_items,
                ),
                cy,
            )
        )

    if pub:
        relics = sum(1 for p in template_pois(site_type) if p.poi_type == "relic")
        lines.append(
            (
                f"Survey POI  present {len(pub.present)}"
                f"  absent {len(pub.absent)}  empty {len(pub.empty)}",
                dim,
            )
        )
        if relics:
            lines.append((f"Relic towers (template) {relics}", dim))
        if pub.active_obelisks:
            lines.append((f"Active obelisks {len(pub.active_obelisks)}", cy))
    else:
        lines.append(("No pub site data — template map only", dim))
        if template_for(site_type) is None:
            lines.append(("No template for site type", dim))

    if guardian_state is not None and guardian_state.target_obelisk:
        lines.append((f"Target .to {guardian_state.target_obelisk}", MAGENTA))
    if guardian_state is not None and guardian_state.extra_poi:
        lines.append((f"Overlay POI {len(guardian_state.extra_poi)}", dim))
    if guardian_state is not None and guardian_state.empty_puddles:
        lines.append(
            (f"Empty puddles {len(guardian_state.empty_puddles)}", RED)
        )
    if active_mode == "map":
        lines.append(("Chat: .add <type>  .empty  .remove  .to  z", dim))

    if (
        status is not None
        and status.latitude is not None
        and status.longitude is not None
        and pub is not None
        and pub.latitude is not None
        and pub.longitude is not None
        and status.planet_radius
        and status.planet_radius > 0
    ):
        dist = surface_distance_m(
            status.latitude,
            status.longitude,
            pub.latitude,
            pub.longitude,
            status.planet_radius,
        )
        brg = bearing_deg(
            status.latitude,
            status.longitude,
            pub.latitude,
            pub.longitude,
        )
        lines.append((f"Origin {dist:.0f}m  brg {brg:.0f}°", col))
    return lines


def _norm_poi_type(poi_type: str) -> str:
    low = (poi_type or "").strip().lower()
    aliases = {
        "brokeobelisk": "brokeObelisk",
        "obelisk": "obelisk",
        "relic": "relic",
        "pylon": "pylon",
        "component": "component",
        "casket": "casket",
        "orb": "orb",
        "tablet": "tablet",
        "totem": "totem",
        "urn": "urn",
    }
    return aliases.get(low, poi_type or "unknown")


def should_label_poi(
    poi: SitePoi,
    *,
    status: str,
    highlight: bool,
    is_overlay: bool,
) -> bool:
    """Label overlay POIs, empty puddles, and .to targets on the map bitmap."""
    if is_overlay or highlight or status == "empty":
        return bool(poi.name)
    return False


def _draw_poi_dot(
    draw,
    cx: float,
    cy: float,
    poi_type: str,
    status: str,
    *,
    highlight: bool = False,
    label: str | None = None,
    font=None,
) -> None:
    ptype = _norm_poi_type(poi_type)
    r = _s(3) if ptype in ("obelisk", "brokeObelisk") else _s(4)
    if highlight:
        r = _s(7)
    fill = _POI_COLOUR.get(ptype, orange())
    if status == "absent":
        fill = GRAY
    elif status == "empty":
        fill = RED
    elif status == "unknown" and ptype not in ("obelisk", "brokeObelisk"):
        fill = (fill[0] // 2, fill[1] // 2, fill[2] // 2, 255)
    box = (cx - r, cy - r, cx + r, cy + r)
    if highlight:
        draw.ellipse(
            (cx - r - _s(3), cy - r - _s(3), cx + r + _s(3), cy + r + _s(3)),
            outline=MAGENTA,
            width=max(2, SCALE),
        )
    if status == "empty":
        draw.ellipse(
            (cx - r - _s(2), cy - r - _s(2), cx + r + _s(2), cy + r + _s(2)),
            outline=RED,
            width=max(1, SCALE),
        )
    if ptype == "relic":
        pts = [
            (cx, cy - r - 1),
            (cx - r, cy + r),
            (cx + r, cy + r),
        ]
        draw.polygon(pts, fill=fill, outline=orange())
    elif ptype in ("obelisk", "brokeObelisk"):
        draw.rectangle(box, fill=fill, outline=cyan() if status != "absent" else GRAY)
    elif ptype == "pylon":
        pts = [(cx, cy - r * 1.5), (cx + r * 2, cy), (cx, cy + r), (cx - r * 2, cy)]
        draw.line(pts + [pts[0]], fill=fill, width=max(1, SCALE))
        draw.line((cx, cy, cx, cy + r), fill=fill, width=max(1, SCALE))
    elif ptype == "component":
        outer = [(cx, cy + r * 2), (cx - r * 2, cy - r), (cx + r * 2, cy - r)]
        inner = [(cx, cy + r), (cx - r, cy - r // 2), (cx + r, cy - r // 2)]
        draw.line(outer + [outer[0]], fill=fill, width=max(1, SCALE))
        draw.line(inner + [inner[0]], fill=fill, width=max(1, SCALE))
    else:
        draw.ellipse(box, fill=fill, outline=orange_dim())
    if label and font is not None:
        tone = MAGENTA if highlight else (RED if status == "empty" else cyan())
        draw.text((cx + r + _s(2), cy - _s(5)), label, font=font, fill=tone)


def _draw_heading_mode(draw, width, height, status, heading, site_type, col, cy, dim):
    font_big = _font(HEADING_PX, bold=True)
    font_body = _font(BODY_PX)
    cmdr_hdg = status.heading if status is not None else None
    label = f"{cmdr_hdg:.0f}°" if cmdr_hdg is not None else "???°"
    lw = _tw(draw, label, font_big)
    draw.text(((width - lw) // 2, _s(80)), label, font=font_big, fill=YELLOW)
    sub = f"{site_type or 'Unknown'} · align buttress"
    if heading >= 0 and cmdr_hdg is not None:
        delta = heading_delta(cmdr_hdg, heading)
        sign = "+" if delta >= 0 else ""
        sub = f"Site {heading}°  Δ {sign}{delta:.0f}°"
    sw = _tw(draw, sub, font_body)
    draw.text(((width - sw) // 2, _s(130)), sub, font=font_body, fill=cy)
    tip = "Chat .heading  or  .heading <deg>"
    tw = _tw(draw, tip, font_body)
    draw.text(((width - tw) // 2, height - _s(28)), tip, font=font_body, fill=dim)


def _draw_site_mode(draw, width, height, site, col, cy, dim):
    font_title = _font(TITLE_PX, bold=True)
    font_body = _font(BODY_PX)
    draw.text((_s(PAD), _s(70)), "Identify site type", font=font_title, fill=cy)
    y = _s(95)
    if site is not None and site.is_ruins:
        for name in _RUINS_TYPES:
            draw.text((_s(PAD + 8), y), f"· {name}  (.{name[0].lower()} / .site {name})", font=font_body, fill=col)
            y += _s(16)
    else:
        for name in _STRUCTURE_TYPES:
            draw.text((_s(PAD + 8), y), f"· {name}", font=font_body, fill=col)
            y += _s(14)
            if y > height - _s(40):
                break
    tip = "Chat: .site Alpha"
    tw = _tw(draw, tip, font_body)
    draw.text(((width - tw) // 2, height - _s(28)), tip, font=font_body, fill=dim)


def _draw_aerial_mode(
    draw, width, height, status, site_type, heading, pub, gs, col, cy, dim
):
    font_title = _font(TITLE_PX, bold=True)
    font_body = _font(BODY_PX)
    font_big = _font(22, bold=True)
    target = target_altitude_for_site(site_type, gs)
    alt = status.altitude if status is not None else None
    mid_x = width // 2
    mid_y = height // 2

    # Compass / origin cross
    draw.line((mid_x, _s(60), mid_x, height - _s(40)), fill=RED, width=max(1, SCALE))
    draw.line((_s(20), mid_y, width - _s(20), mid_y), fill=(80, 0, 0, 255), width=max(1, SCALE))
    draw.ellipse(
        (mid_x - _s(18), mid_y - _s(18), mid_x + _s(18), mid_y + _s(18)),
        outline=col,
        width=max(1, SCALE),
    )

    # Ship offset blip when origin known
    if (
        status is not None
        and status.latitude is not None
        and status.longitude is not None
        and pub is not None
        and pub.latitude is not None
        and pub.longitude is not None
        and status.planet_radius
        and status.planet_radius > 0
        and heading >= 0
    ):
        dist = surface_distance_m(
            pub.latitude,
            pub.longitude,
            status.latitude,
            status.longitude,
            status.planet_radius,
        )
        brg = bearing_deg(
            pub.latitude,
            pub.longitude,
            status.latitude,
            status.longitude,
        )
        rel = (brg - heading + 360.0) % 360.0
        deg = 180.0 - rel
        scale = 2.0 if dist < 70 else (0.5 if dist > 170 else 1.0)
        sx = mid_x + math.sin(math.radians(deg)) * dist * scale
        sy = mid_y - math.cos(math.radians(deg)) * dist * scale
        r = _s(5)
        ship_col = cy if dist < 10 else LIME
        draw.ellipse((sx - r, sy - r, sx + r, sy + r), outline=ship_col, width=max(1, SCALE))
        if status.heading is not None:
            hrad = math.radians(status.heading - heading)
            draw.line(
                (sx, sy, sx + math.sin(hrad) * _s(12), sy - math.cos(hrad) * _s(12)),
                fill=ship_col,
                width=max(1, SCALE),
            )
        draw.text((_s(PAD), height - _s(44)), f"Offset {dist:.0f}m", font=font_body, fill=dim)

    alt_txt = f"{alt:.0f}m" if alt is not None else "— m"
    aw = _tw(draw, alt_txt, font_big)
    tone = col
    if alt is not None:
        diff = alt - target
        if diff < -50:
            tone = cy
        elif diff > 50:
            tone = RED
    draw.text(((width - aw) // 2, _s(55)), alt_txt, font=font_big, fill=tone)
    sub = f"Target {target:.0f}m · {site_type or '?'}"
    sw = _tw(draw, sub, font_title)
    draw.text(((width - sw) // 2, _s(90)), sub, font=font_title, fill=cy)

    # Vertical guidance bar (PlotVerticalStripe stand-in)
    if alt is not None and not gs.disableAerialAlignmentGrid:
        bar_x = width - _s(28)
        bar_top = _s(110)
        bar_bot = height - _s(50)
        bar_h = max(1, bar_bot - bar_top)
        draw.rectangle((bar_x, bar_top, bar_x + _s(10), bar_bot), outline=dim)
        # Map altitude so target is mid-bar
        span = 400.0
        frac = 0.5 - (alt - target) / (2 * span)
        frac = max(0.02, min(0.98, frac))
        mark_y = bar_top + int((1.0 - frac) * bar_h)
        draw.rectangle(
            (bar_x + 1, mark_y - _s(3), bar_x + _s(10) - 1, mark_y + _s(3)),
            fill=tone,
        )
        tgt_y = bar_top + bar_h // 2
        draw.line((bar_x - _s(4), tgt_y, bar_x + _s(14), tgt_y), fill=YELLOW, width=max(1, SCALE))


def _compass_offset(x: float, y: float, heading: float) -> tuple[float, float]:
    """GDI+ clockwise rotation of ``360 - heading``, with Y increasing downward."""
    theta = math.radians((360.0 - heading) % 360.0)
    c = math.cos(theta)
    s = math.sin(theta)
    return (x * c + y * s, -x * s + y * c)


def _draw_compass(draw, ox: float, oy: float, heading: float, span: float) -> None:
    """Windows ``drawCompassLines0``: dark-red cross and a red forward ray."""
    dark = (139, 0, 0, 255)
    red = (220, 32, 32, 255)

    def pt(x: float, y: float) -> tuple[float, float]:
        dx, dy = _compass_offset(x, y, heading)
        return ox + dx, oy + dy

    draw.line((*pt(-span, 0), *pt(span, 0)), fill=dark, width=max(1, SCALE // 2))
    draw.line((*pt(0, 0), *pt(0, span)), fill=dark, width=max(1, SCALE // 2))
    draw.line((*pt(0, -span), *pt(0, 0)), fill=red, width=max(1, SCALE // 2))


def _draw_obelisk_group_names(
    draw,
    site_type: str | None,
    pub,
    site_heading: float,
    ox: float,
    oy: float,
    scale_m: float,
    map_box: tuple[float, float, float, float],
) -> None:
    allowed = set(pub.obelisk_groups) if pub is not None and pub.obelisk_groups else None
    font = _font(14, bold=True)
    for key, angle, dist in obelisk_group_name_locations(site_type):
        if allowed is not None and (not key or key[0] not in allowed):
            continue
        mx, my = rotate_line(180.0 - site_heading - angle, dist)
        sx = ox + mx * scale_m
        sy = oy - my * scale_m
        if sx < map_box[0] or sx > map_box[2] or sy < map_box[1] or sy > map_box[3]:
            continue
        tw = _tw(draw, key, font)
        draw.text((sx - tw / 2, sy - _s(8)), key, font=font, fill=cyan())


def _draw_relic_heading(draw, sx: float, sy: float, tower_heading: int) -> None:
    """Short axis through a relic, rotated by ``heading - 180``."""
    length = float(_s(18))
    theta = math.radians(float(tower_heading) - 180.0)
    dx = math.sin(theta) * length
    dy = math.cos(theta) * length
    draw.line((sx - dx, sy + dy, sx + dx, sy - dy), fill=cyan(), width=max(1, SCALE // 2))


def nearest_relic_name(
    pois: list[SitePoi],
    site_heading: float,
    commander_xy: tuple[float, float],
) -> str | None:
    """Closest relic in site-map metres. Windows uses the painted nearest POI."""
    best_name: str | None = None
    best_d = float("inf")
    cx, cy = commander_xy
    for poi in pois:
        if _norm_poi_type(poi.poi_type) != "relic":
            continue
        mx, my = poi_xy(poi, site_heading)
        dist = math.hypot(mx - cx, my - cy)
        if dist < best_d:
            best_d = dist
            best_name = poi.name
    return best_name


def commander_map_offset_m(status, pub, site_heading: float) -> tuple[float, float] | None:
    if (
        status is None
        or pub is None
        or status.latitude is None
        or status.longitude is None
        or pub.latitude is None
        or pub.longitude is None
        or not status.planet_radius
        or status.planet_radius <= 0
    ):
        return None
    dist = surface_distance_m(
        pub.latitude,
        pub.longitude,
        status.latitude,
        status.longitude,
        status.planet_radius,
    )
    brg = bearing_deg(
        pub.latitude,
        pub.longitude,
        status.latitude,
        status.longitude,
    )
    rel = (brg - site_heading + 360.0) % 360.0
    deg = 180.0 - rel
    return (
        math.sin(math.radians(deg)) * dist,
        math.cos(math.radians(deg)) * dist,
    )


def render_guardians_bitmap(
    survey: SurveyState,
    *,
    game: GameSettings | None = None,
    status: StatusSnapshot | None = None,
    force_show: bool = False,
    max_width: int | None = None,
    max_height: int | None = None,
    zoom: float | None = None,
    pub_dir=None,
    commander: str | None = None,
    cmdr=None,
    guardian_state=None,
) -> tuple[bytes, int, int] | None:
    """Render PlotGuardians. None when not allowed."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    if not force_show and not guardians_allowed(gs, survey, status):
        return None

    if guardian_state is None:
        _, guardian_state, _ = load_guardian_survey(
            survey, commander=commander, cmdr=cmdr
        )

    site, pub, site_type, heading = site_context(
        survey, pub_dir=pub_dir, guardian_state=guardian_state
    )
    if site is None and not force_show:
        return None

    mode = resolve_survey_mode(
        site_type=site_type,
        heading=heading,
        guardian_state=guardian_state,
        game=gs,
    )

    col = orange(gs)
    dim = orange_dim(gs)
    cy = cyan(gs)

    sizes = ((300, 400), (500, 500), (600, 700), (800, 1000), (1200, 1200))
    idx = max(0, min(4, int(getattr(gs, "idxGuardianPlotter", 0) or 0)))
    def_w, def_h = sizes[idx]
    width_logical = max(200, min(1200, int(max_width or def_w)))
    height_logical = max(200, min(1200, int(max_height or def_h)))

    font_title = _font(TITLE_PX)
    font_body = _font(BODY_PX)
    lines = guardians_lines(
        survey,
        status,
        pub_dir=pub_dir,
        guardian_state=guardian_state,
        mode=mode,
        game=gs,
    )

    header_h = _s(10) + len(lines) * _s(14) + _s(6)
    map_h = max(_s(160), _s(height_logical) - header_h - _s(8))
    width = _s(width_logical)
    height = header_h + map_h

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height, col)

    y = _s(10)
    for text, colour in lines:
        max_w = width - _s(PAD * 2)
        label = text
        while (
            _tw(draw, label, font_title if y < _s(28) else font_body) > max_w
            and len(label) > 4
        ):
            label = label[:-2] + "…"
        draw.text((_s(PAD), y), label, font=font_body, fill=colour)
        y += _s(14)

    map_top = header_h
    map_box = (_s(4), map_top, width - _s(4), height - _s(6))
    draw.rectangle(map_box, fill=(8, 8, 8, 255), outline=dim)

    if mode == "site":
        _draw_site_mode(draw, width, height, site, col, cy, dim)
        return _finish(img)

    if mode == "heading":
        _draw_heading_mode(draw, width, height, status, heading, site_type, col, cy, dim)
        return _finish(img)

    if mode == "aerial":
        _draw_aerial_mode(
            draw, width, height, status, site_type, heading, pub, gs, col, cy, dim
        )
        return _finish(img)

    # —— map mode ——
    template = filter_pois_for_site(template_pois(site_type), pub)
    overlays = overlay_pois_from_state(guardian_state)
    pois = [*template, *overlays]
    use_heading = heading if heading >= 0 else 0
    if zoom is not None:
        z = float(zoom)
    elif guardian_state is not None and guardian_state.zoom:
        z = float(guardian_state.zoom)
    else:
        z = float(getattr(gs, "guardianZoom", 1.0) or 1.0)
    map_px = min(map_box[2] - map_box[0], map_box[3] - map_box[1])
    scale_m = map_scale_for_pois(pois, map_px=map_px, zoom=z)

    ox = (map_box[0] + map_box[2]) / 2.0
    oy = (map_box[1] + map_box[3]) / 2.0

    if status is not None and status.heading is not None:
        _draw_compass(draw, ox, oy, float(status.heading), map_px * 0.45)

    _draw_obelisk_group_names(
        draw,
        site_type,
        pub,
        use_heading,
        ox,
        oy,
        scale_m,
        map_box,
    )

    draw.line((ox - _s(8), oy, ox + _s(8), oy), fill=col, width=max(1, SCALE // 2))
    draw.line((ox, oy - _s(8), ox, oy + _s(8)), fill=col, width=max(1, SCALE // 2))

    if heading >= 0:
        hx, hy = rotate_line(180.0 - heading, map_px * 0.35 / max(scale_m, 1e-6))
        draw.line(
            (ox, oy, ox + hx * scale_m, oy - hy * scale_m),
            fill=YELLOW,
            width=max(1, SCALE // 2),
        )

    target = (
        guardian_state.target_obelisk.upper()
        if guardian_state is not None and guardian_state.target_obelisk
        else None
    )
    overlay_names = {p.name for p in overlays}
    font_label = _font(8)
    drawn = 0
    if pois and site_type:
        for poi in pois:
            mx, my = poi_xy(poi, use_heading)
            sx = ox + mx * scale_m
            sy = oy - my * scale_m
            if sx < map_box[0] or sx > map_box[2] or sy < map_box[1] or sy > map_box[3]:
                continue
            st = effective_poi_status(pub, poi.name, guardian_state)
            hi = bool(target and poi.name.upper() == target)
            is_overlay = poi.name in overlay_names
            label = (
                poi.name
                if should_label_poi(
                    poi, status=st, highlight=hi, is_overlay=is_overlay
                )
                else None
            )
            _draw_poi_dot(
                draw,
                sx,
                sy,
                poi.poi_type,
                st,
                highlight=hi,
                label=label,
                font=font_label,
            )
            tower = relic_heading_for(
                poi.name,
                local=getattr(guardian_state, "relic_headings", None),
                pub=pub,
                raw_rot=int(poi.rot) if is_overlay else None,
            )
            if tower is not None and _norm_poi_type(poi.poi_type) == "relic":
                _draw_relic_heading(draw, sx, sy, tower)
            drawn += 1
        legend = f"{site_type} map · {drawn} POI · zoom {z:.1f}"
        draw.text((_s(PAD), height - _s(18)), legend, font=font_title, fill=dim)
    else:
        msg = "Awaiting site type / template"
        if site_type and template_for(site_type) is None:
            msg = f"No template: {site_type}"
        draw.text(
            (ox - _tw(draw, msg, font_body) / 2, oy - _s(6)),
            msg,
            font=font_body,
            fill=cy,
        )

    if (
        status is not None
        and status.latitude is not None
        and status.longitude is not None
        and pub is not None
        and pub.latitude is not None
        and pub.longitude is not None
        and status.planet_radius
        and status.planet_radius > 0
        and heading >= 0
    ):
        dist = surface_distance_m(
            pub.latitude,
            pub.longitude,
            status.latitude,
            status.longitude,
            status.planet_radius,
        )
        brg = bearing_deg(
            pub.latitude,
            pub.longitude,
            status.latitude,
            status.longitude,
        )
        rel = (brg - heading + 360.0) % 360.0
        deg = 180.0 - rel
        cx_m = math.sin(math.radians(deg)) * dist
        cy_m = math.cos(math.radians(deg)) * dist
        sx = ox + cx_m * scale_m
        sy = oy - cy_m * scale_m
        if map_box[0] <= sx <= map_box[2] and map_box[1] <= sy <= map_box[3]:
            r = _s(5)
            draw.ellipse((sx - r, sy - r, sx + r, sy + r), fill=LIME, outline=col)
            if status.heading is not None:
                hrad = math.radians(status.heading - heading)
                nx = sx + math.sin(hrad) * _s(10)
                ny = sy - math.cos(hrad) * _s(10)
                draw.line((sx, sy, nx, ny), fill=LIME, width=max(1, SCALE // 2))

    return _finish(img)


def assign_tower_command(
    guardian_state,
    survey: SurveyState,
    status: StatusSnapshot | None,
    degrees: int | None,
    *,
    fallback_heading: float | None = None,
) -> str:
    """Windows ``.tower``.

    Bare ``.tower`` on ruins stores the ship heading as the site relic
    heading. ``.tower <int>`` stores that angle on the nearest relic.
    """
    site, pub, site_type, heading = site_context(survey, guardian_state=guardian_state)
    is_ruins = bool(site is not None and site.is_ruins)
    if degrees is None:
        if not is_ruins:
            return "Usage: .tower [heading]"
        chosen = status.heading if status is not None else None
        if chosen is None:
            chosen = fallback_heading
        if chosen is None:
            return "Need heading for .tower"
        guardian_state.relic_tower_heading = float(chosen) % 360.0
        return f"Relic tower heading {guardian_state.relic_tower_heading:.1f}°"
    angle = int(degrees) % 360
    use_heading = heading if heading >= 0 else 0.0
    pois = filter_pois_for_site(template_pois(site_type), pub)
    offset = commander_map_offset_m(status, pub, use_heading)
    name = nearest_relic_name(pois, use_heading, offset) if offset is not None else None
    if name is None:
        return "Need a nearby relic tower for .tower"
    guardian_state.relic_headings[name] = angle
    return f"Relic tower {name} heading {angle}°"


def adjust_guardian_zoom(
    cmdr,
    site_key: str | None = None,
    *,
    zoom_in: bool | None = None,
    absolute: float | None = None,
    persist: bool = True,
) -> float:
    """Chord / chat zoom helper. Returns new zoom."""
    g = _guardian_state_for(cmdr, site_key)
    if g is None:
        return 1.0
    if absolute is not None:
        g.zoom = max(0.25, min(8.0, float(absolute)))
    elif zoom_in is True:
        g.zoom = max(0.25, min(8.0, float(g.zoom) + 0.25))
    elif zoom_in is False:
        g.zoom = max(0.25, min(8.0, float(g.zoom) - 0.25))
    else:
        g.zoom = 1.0
    if persist and hasattr(cmdr, "save"):
        cmdr.save()
    return float(g.zoom)
