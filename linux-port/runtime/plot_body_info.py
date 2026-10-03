#!/usr/bin/env python3
"""Pillow renderer — 1-1 Linux port of PlotBodyInfo.

Faithful to PlotBodyInfo.cs + .resx English strings + GameColors.
Uses journal Scan / Status data via SurveyState.fss_bodies.
Bio signal rewards / volume bars reuse ``codex_ref.py`` (same as PlotBioSystem).
Orange theme + gothic stand-in fonts (same as plot_fss_info).
"""

from __future__ import annotations

from hud_scale import AA, SCALE
import math
from pathlib import Path

from body_value import format_credits
from companion import (
    FLAG_IN_MAIN_SHIP,
    StatusSnapshot,
)
from game_settings import GameSettings
from journal import CommanderLocation, FssBodyEntry, SurveyState

# GameColors defaults
ORANGE = (255, 111, 0, 255)
ORANGE_DIM = (95, 48, 3, 255)
CYAN = (84, 223, 237, 255)
RED = (255, 48, 0, 255)
STRIPE = (12, 12, 12, 255)

SOL = (0.0, 0.0, 0.0)

TITLE_PX = 11  # fontMiddleBold stand-in
BODY_PX = 9  # fontSmall2
PAD = 8
ROW = 14
DEFAULT_WIDTH = 320

# PlotBodyInfo.resx English
_SCAN_REQUIRED = "Scan required"
_TERRAFORMABLE = "Terraformable"
_UNDISCOVERED = "Undiscovered"
_FIRST_MAPPED = "First mapped"
_UNMAPPED = "Unmapped"
_SCAN_VALUE = "Scan value"
_WITH_DSS = "(with DSS: {0})"
_TEMP = "Temp: {0}K"
_GRAVITY = "Gravity: {0}g"
_STAR_CLASS = "Class: {0}"
_PRESSURE = "Pressure: {0}"
_PRESSURE_VALUE = "{0}(atm)"
_NONE = "None"
_BIO_SIGNALS = "Bio signals: {0} ( value: {1} cr )"
_GEO_SIGNALS = "Geo signals: {0}"
_VOLCANISM = "Volcanism:"
_ATMOSPHERE = "Atmosphere:"
_EARTH_LIKE = "Earth Like"
_MATERIALS = "Materials:"
_RINGS = "Rings:"
_REWARD_FOOTER = "Reward: {0}"
_VOL_ROW = 28

_MAT_LEVEL_3 = frozenset(
    {"cadmium", "mercury", "molybdenum", "niobium", "tin", "tungsten"}
)
_MAT_LEVEL_4 = frozenset(
    {"antimony", "polonium", "ruthenium", "technetium", "tellurium", "yttrium"}
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


def _background(draw, w: int, h: int) -> None:
    draw.rectangle((0, 0, w - 1, h - 1), fill=(0, 0, 0, 255))
    step = _s(3)
    for y in range(0, h, step):
        draw.line((0, y, w - 1, y), fill=STRIPE)
    for y, col in ((_s(3), ORANGE_DIM), (_s(4), ORANGE), (_s(5), ORANGE_DIM)):
        draw.line((_s(2), y, w - _s(4), y), fill=col)
    for y, col in (
        (h - _s(5), ORANGE_DIM),
        (h - _s(4), ORANGE),
        (h - _s(3), ORANGE_DIM),
    ):
        draw.line((_s(2), y, w - _s(4), y), fill=col)
    draw.rectangle((0, 0, w - 1, h - 1), outline=ORANGE, width=max(1, SCALE // 2))


def _finish(img):
    from PIL import Image

    if SCALE != 1:
        w, h = img.size
        img = img.resize((w // AA, h // AA), Image.Resampling.LANCZOS)
    w, h = img.size
    return img.tobytes("raw", "RGBA"), w, h


def _pascal(txt: str | None) -> str:
    if not txt:
        return ""
    return txt[0].upper() + txt[1:]


def _system_distance(
    here: tuple[float, float, float] | None,
    there: tuple[float, float, float],
) -> float:
    if here is None:
        return -1.0
    return math.sqrt(
        (here[0] - there[0]) ** 2
        + (here[1] - there[1]) ** 2
        + (here[2] - there[2]) ** 2
    )


def _decode_ring(ring_class: str) -> str:
    key = ring_class.strip()
    mapping = {
        "Rocky": "Rocky",
        "eRingClass_Rocky": "Rocky",
        "Metallic": "Matallic",
        "Metalic": "Matallic",
        "eRingClass_Metalic": "Matallic",
        "Metal Rich": "Metal Rich",
        "Metal rich": "Metal Rich",
        "eRingClass_MetalRich": "Metal Rich",
        "Icy": "Icy",
        "eRingClass_Icy": "Icy",
    }
    return mapping.get(key, key)


def _find_body(
    survey: SurveyState,
    *,
    body_id: int | None = None,
    name: str | None = None,
) -> FssBodyEntry | None:
    if body_id is not None:
        for body in survey.fss_bodies:
            if body.body_id == body_id:
                return body
    if name:
        for body in survey.fss_bodies:
            if body.body_name == name:
                return body
        # Destination names sometimes omit the system prefix
        for body in survey.fss_bodies:
            if body.body_name.endswith(name) or body.short_name == name.replace(" ", ""):
                return body
    return None


def _unknown_stub(name: str) -> FssBodyEntry:
    return FssBodyEntry(
        body_id=-1,
        body_name=name,
        short_name=name,
        body_type="Unknown",
        scanned=False,
        was_discovered=False,
        was_mapped=False,
    )


def resolve_body(
    survey: SurveyState,
    location: CommanderLocation,
    status: StatusSnapshot | None,
    *,
    force_show: bool = False,
) -> FssBodyEntry | None:
    """Match Windows targetBody vs systemBody selection."""
    use_target = force_show or (status is not None and status.in_system_map)
    if use_target:
        if status is not None:
            if status.destination_body is not None and status.destination_body > 0:
                found = _find_body(survey, body_id=status.destination_body)
                if found is not None:
                    return found
            if status.destination:
                found = _find_body(survey, name=status.destination)
                if found is not None:
                    return found
                return _unknown_stub(status.destination)
        if location.body:
            found = _find_body(survey, name=location.body)
            return found or _unknown_stub(location.body)
        return None

    # systemBody — current body from status BodyName or journal location
    name = None
    if status is not None and status.body_name:
        name = status.body_name
    elif location.body:
        name = location.body
    if not name:
        return None
    return _find_body(survey, name=name) or _unknown_stub(name)


def body_info_allowed(
    survey: SurveyState,
    location: CommanderLocation,
    status: StatusSnapshot | None,
    game: GameSettings,
    *,
    force_show: bool = False,
) -> bool:
    """Match PlotBodyInfo.allowed, including the guardian-system collision hide."""
    if not game.autoShowPlotBodyInfo:
        return False
    if game.buildProjectsSuppressOtherOverlays:
        return False
    if survey.system is None and location.system is None:
        return False

    guardian_disabled = (not game.enableGuardianSites) and (not game.autoShowGuardianSummary)
    if not guardian_disabled:
        from plot_guardian_system import guardian_system_allowed

        if guardian_system_allowed(game, survey, status):
            return False

    body = resolve_body(survey, location, status, force_show=force_show)
    if body is None:
        return False

    # Bubble hide — if star_pos unknown, do not hide (can't evaluate)
    if game.autoHidePlotBodyInfoInBubble and survey.star_pos is not None:
        dist = _system_distance(survey.star_pos, SOL)
        if dist >= 0 and dist <= float(game.bodyInfoBubbleSize):
            return False

    if force_show:
        jumping = bool(survey.fsd_jumping) or (
            status is not None and status.fsd_jumping
        )
        return not jumping

    if status is None:
        return False

    # SAA + system body
    if status.in_saa and (
        (status.body_name or location.body) is not None
    ):
        return True

    # SystemMap / Orrery
    if (
        status.in_system_map
        and game.autoShowPlotBodyInfoInMap
        and not game.autoShowPlotFSSInfoInSystemMap
    ):
        return True

    # Supercruise / glide near body
    if (
        (status.supercruise or status.glide_mode)
        and status.has_lat_long
        and game.autoShowPlotBodyInfoInOrbit
    ):
        return True

    # Surface (flying / landed / SRV) + analysis mode
    flying = (
        bool(status.flags & FLAG_IN_MAIN_SHIP)
        and not status.docked
        and not status.landed
        and not status.supercruise
        and not status.in_srv
        and not status.in_fighter
        and not status.on_foot
    )
    if (
        (flying or status.landed or status.in_srv)
        and status.has_lat_long
        and game.autoShowPlotBodyInfoAtSurface
        and status.hud_in_analysis_mode
    ):
        return True

    return False


def _within_bubble(survey: SurveyState, game: GameSettings) -> bool:
    if survey.star_pos is None:
        return False
    dist = _system_distance(survey.star_pos, SOL)
    return dist >= 0 and dist < float(game.bodyInfoBubbleSize)


def _format_n0(value: float) -> str:
    return f"{int(round(value)):,}"


def _format_n3(value: float) -> str:
    return f"{value:,.3f}"


def _format_n2(value: float) -> str:
    return f"{value:,.2f}"


def _format_n4(value: float) -> str:
    return f"{value:,.4f}"


def _body_name_match(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    return a.endswith(b) or b.endswith(a)


def genuses_for_body(survey: SurveyState, body: FssBodyEntry) -> list[str]:
    """Body genuses from FSSBodySignals / organic progress (PlotBioSystem pattern)."""
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(name: str | None) -> None:
        if not name or name in seen:
            return
        seen.add(name)
        ordered.append(name)

    for sig in survey.body_signals:
        if not _body_name_match(sig.body_name, body.body_name):
            continue
        for genus in sig.genuses:
            _add(genus)
    for prog in survey.organic_progress:
        if prog.body_name and not _body_name_match(prog.body_name, body.body_name):
            continue
        _add(prog.genus)
    return ordered


def bio_reward_range(
    survey: SurveyState, genuses: list[str]
) -> tuple[int, int]:
    """Sum (min, max) Codex rewards for body genuses — fail soft to (0, 0)."""
    if not genuses:
        return 0, 0
    try:
        from codex_ref import (
            max_reward_for_genus,
            min_reward_for_genus,
            reward_for_species,
        )
    except Exception:
        return 0, 0

    min_total = 0
    max_total = 0
    for genus in genuses:
        species = None
        for prog in survey.organic_progress:
            if prog.genus == genus and prog.species:
                species = prog.species
                break
        if species:
            known = reward_for_species(species) or max_reward_for_genus(genus)
            min_total += known
            max_total += known
        else:
            lo = min_reward_for_genus(genus)
            hi = max_reward_for_genus(genus)
            if hi <= 0 and lo <= 0:
                continue
            min_total += lo if lo > 0 else hi
            max_total += hi if hi > 0 else lo
    return min_total, max_total


def format_bio_reward_credits(min_v: int, max_v: int) -> str:
    """Match Util.getMinMaxCredits for the BioSignals value slot."""
    if min_v <= 0 and max_v <= 0:
        return ""
    try:
        from plot_bio_system import get_min_max_credits

        return get_min_max_credits(min_v, max_v)
    except Exception:
        if min_v == max_v:
            return format_credits(min_v, hide_units=True)
        return (
            f"{format_credits(min_v, hide_units=True)}"
            f" ~ {format_credits(max_v, hide_units=True)}"
        )


def _species_for_genus(survey: SurveyState, genus: str) -> str | None:
    for prog in survey.organic_progress:
        if prog.genus == genus and prog.species:
            return prog.species
    return None


def _build_lines(
    body: FssBodyEntry,
    game: GameSettings,
    survey: SurveyState,
    *,
    within_bubble: bool,
) -> list[tuple]:
    """Return draw ops: ('row', cells) | ('vol', genus) | ('footer', text).

    x_mode: 'left' | 'indent1' | 'indent2' | 'right' | 'mat_name' | 'mat_pct' | 'ring'
    font_key: 'title' | 'body' | 'bold'
    """
    lines: list[tuple] = []

    # Body name
    name = body.body_name if body.was_discovered else f"* {body.body_name}"
    lines.append(("row", [("left", name, "title", ORANGE)]))

    planetish = body.body_type not in ("Star", "Asteroid", "PlanetaryRing")

    if body.body_type == "Unknown":
        lines.append(("row", [("left8", _SCAN_REQUIRED, "body", CYAN)]))
        return lines

    # Sub-status tags (right-aligned cyan)
    tags: list[str] = []
    if body.terraformable or (body.planet_class or "").startswith("Earth"):
        tags.append(_TERRAFORMABLE)
    if not body.was_discovered and not body.was_mapped:
        tags.append(_UNDISCOVERED)
    elif not body.was_mapped and body.dss_complete:
        tags.append(_FIRST_MAPPED)
    elif body.scanned and not body.was_mapped and not within_bubble:
        tags.append(_UNMAPPED)
    if tags:
        lines.append(("row", [("right", f"( {', '.join(tags)} )", "body", CYAN)]))

    # Scan value
    check = "✓ " if body.dss_complete else ""
    scan_txt = f"{_SCAN_VALUE}: {check}{format_credits(body.reward)}"
    highlight = game.skipLowValueDSS and body.reward > game.skipLowValueAmount
    if not body.dss_complete and planetish:
        dss = body.dss_reward or body.reward
        scan_txt += " " + _WITH_DSS.format(format_credits(dss))
        highlight = game.skipLowValueDSS and dss > game.skipLowValueAmount
    lines.append(
        ("row", [("left8", scan_txt, "body", CYAN if highlight else ORANGE)])
    )

    temp_text = _TEMP.format(_format_n0(body.surface_temperature))
    grav_g = body.surface_gravity / 10.0
    grav_text = _GRAVITY.format(_format_n3(grav_g))

    if body.body_type != "Asteroid":
        class_txt = (
            _STAR_CLASS.format(body.star_type or "?")
            if body.body_type == "Star"
            else (body.planet_class or "")
        )
        lines.append(
            (
                "row",
                [
                    ("left8", temp_text, "body", ORANGE),
                    ("indent1", class_txt, "body", ORANGE),
                ],
            )
        )

    if planetish:
        is_high = body.surface_gravity >= game.highGravityWarningLevel * 10
        pressure_raw = body.surface_pressure / 100_000.0
        pressure_val = _PRESSURE_VALUE.format(_format_n4(pressure_raw))
        if pressure_raw == 0.0:
            pressure_val = _NONE
        cells: list[tuple] = [
            ("left8", grav_text, "body", RED if is_high else ORANGE),
        ]
        if pressure_val != _NONE or body.body_type == "LandableBody":
            cells.append(
                ("indent1", _PRESSURE.format(pressure_val), "body", ORANGE)
            )
        lines.append(("row", cells))

    if body.bio_signal_count > 0:
        genuses = genuses_for_body(survey, body)
        lo, hi = bio_reward_range(survey, genuses)
        reward_txt = format_bio_reward_credits(lo, hi) or "—"
        bio_txt = _BIO_SIGNALS.format(body.bio_signal_count, reward_txt)
        lines.append(("row", [("left8", bio_txt, "body", CYAN)]))
        for genus in genuses:
            lines.append(("vol", genus))
        if genuses:
            try:
                from codex_ref import format_credits as codex_credits
                from codex_ref import max_reward_for_genus, reward_for_species

                total = 0
                for genus in genuses:
                    species = _species_for_genus(survey, genus)
                    if species:
                        total += reward_for_species(species) or max_reward_for_genus(
                            genus
                        )
                    else:
                        total += max_reward_for_genus(genus)
                footer = _REWARD_FOOTER.format(codex_credits(total))
            except Exception:
                footer = _REWARD_FOOTER.format("—")
            lines.append(("footer", footer))

    if body.geo_signal_count > 0:
        geo_txt = _GEO_SIGNALS.format(body.geo_signal_count)
        lines.append(("row", [("left8", geo_txt, "body", CYAN)]))

    if planetish and body.body_type != "Giant":
        volc = body.volcanism
        if not volc or volc == "No volcanism":
            volc_disp = _NONE
        else:
            volc_disp = _pascal(volc.replace("volcanism", "").strip())
        lines.append(
            (
                "row",
                [
                    ("left8", _VOLCANISM, "body", ORANGE),
                    ("indent2", volc_disp, "body", ORANGE),
                ],
            )
        )

    if planetish:
        atmos = body.atmosphere
        if not atmos or atmos == "No atmosphere":
            atmos_disp = _NONE
        else:
            atmos_disp = _pascal(atmos.replace(" atmosphere", ""))
        if body.atmosphere_type == "EarthLike":
            atmos_disp = _EARTH_LIKE
        if atmos_disp == "None" and body.body_type != "LandableBody":
            atmos_disp = " "
        lines.append(
            (
                "row",
                [
                    ("left8", _ATMOSPHERE, "body", ORANGE),
                    ("indent2", atmos_disp, "body", ORANGE),
                ],
            )
        )
        for name, pct in body.atmosphere_composition:
            pretty = name[0].upper() + name[1:] if name else name
            lines.append(
                (
                    "row",
                    [
                        ("left44", f"{pretty}:", "body", ORANGE),
                        ("mat_pct", f"{_format_n2(pct).rjust(5)} %", "body", ORANGE),
                    ],
                )
            )

        if body.materials and not game.bodyInfoHideMats:
            first = True
            for mat_name, pct in sorted(
                body.materials, key=lambda item: item[1], reverse=True
            ):
                pretty = _pascal(mat_name)
                bold = mat_name.lower() in _MAT_LEVEL_3 or mat_name.lower() in _MAT_LEVEL_4
                font_key = "bold" if bold else "body"
                cells = []
                if first:
                    cells.append(("left8", _MATERIALS, "body", ORANGE))
                    first = False
                cells.append(("indent2", f"{pretty}:", font_key, ORANGE))
                cells.append(
                    ("mat_pct", f"{_format_n2(pct).rjust(5)} %", font_key, ORANGE)
                )
                lines.append(("row", cells))

    if body.rings:
        first = True
        for ring_name, ring_class in body.rings:
            letter = "?"
            if body.body_name and ring_name.startswith(body.body_name):
                rest = ring_name[len(body.body_name) :].strip()
                if rest:
                    letter = rest[0]
            ring_txt = f"{letter} - {_decode_ring(ring_class)}"
            cells = []
            if first:
                cells.append(("left8", _RINGS, "body", ORANGE))
                first = False
            cells.append(("ring", ring_txt, "body", ORANGE))
            lines.append(("row", cells))

    return lines


def render_body_info_bitmap(
    survey: SurveyState,
    location: CommanderLocation,
    *,
    status: StatusSnapshot | None = None,
    game: GameSettings | None = None,
    force_show: bool = False,
) -> tuple[bytes, int, int] | None:
    """Draw PlotBodyInfo. Returns None when allowed() would hide the plotter."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    if not body_info_allowed(
        survey, location, status, gs, force_show=force_show
    ):
        return None

    body = resolve_body(survey, location, status, force_show=force_show)
    if body is None:
        return None

    font_title = _font(TITLE_PX, bold=True)
    font_body = _font(BODY_PX)
    font_bold = _font(BODY_PX, bold=True)
    fonts = {"title": font_title, "body": font_body, "bold": font_bold}

    lines = _build_lines(
        body, gs, survey, within_bubble=_within_bubble(survey, gs)
    )

    # Measure column anchors
    temp_text = _TEMP.format(_format_n0(body.surface_temperature))
    grav_text = _GRAVITY.format(_format_n3(body.surface_gravity / 10.0))
    indent1 = _s(20) + max(
        _tw(ImageDraw.Draw(Image.new("RGBA", (4, 4))), temp_text, font_body),
        _tw(ImageDraw.Draw(Image.new("RGBA", (4, 4))), grav_text, font_body),
    )
    label_w = max(
        _tw(ImageDraw.Draw(Image.new("RGBA", (4, 4))), _VOLCANISM, font_body),
        _tw(ImageDraw.Draw(Image.new("RGBA", (4, 4))), _ATMOSPHERE, font_body),
        _tw(ImageDraw.Draw(Image.new("RGBA", (4, 4))), _MATERIALS, font_body),
    )
    indent2 = _s(10) + label_w
    mat_pct_x = indent2 + _s(140)

    # Width pass
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    width = _s(DEFAULT_WIDTH)
    for item in lines:
        kind = item[0]
        if kind == "row":
            cells = item[1]
            for mode, text, font_key, _color in cells:
                font = fonts[font_key]
                tw = _tw(probe, text, font)
                if mode == "left":
                    width = max(width, _s(PAD) + tw + _s(PAD))
                elif mode == "left8":
                    width = max(width, _s(8) + tw + _s(PAD))
                elif mode == "right":
                    width = max(width, tw + _s(20))
                elif mode == "indent1":
                    width = max(width, indent1 + tw + _s(PAD))
                elif mode == "indent2":
                    width = max(width, indent2 + tw + _s(PAD))
                elif mode == "mat_pct":
                    width = max(width, mat_pct_x + tw + _s(PAD))
                elif mode == "ring":
                    width = max(width, _s(80) + tw + _s(PAD))
                elif mode == "left44":
                    width = max(width, _s(44) + tw + _s(PAD))
        elif kind == "vol":
            genus = item[1]
            width = max(width, _s(28) + _tw(probe, genus, font_body) + _s(80))
        elif kind == "footer":
            width = max(width, _s(8) + _tw(probe, item[1], font_body) + _s(PAD))

    height = _s(PAD) + _s(14)
    for item in lines:
        kind = item[0]
        if kind == "vol":
            height += _s(_VOL_ROW)
        else:
            height += _s(ROW)

    img = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height)

    buckets = (
        float(gs.bioRingBucketOne),
        float(gs.bioRingBucketTwo),
        float(gs.bioRingBucketThree),
    )
    render_volume_bar = None
    VolColor = None
    reward_for_progress = None
    try:
        from plot_bio_system import VolColor, render_volume_bar
        from codex_ref import reward_for_progress
    except Exception:
        pass

    y = _s(PAD)
    for item in lines:
        kind = item[0]
        if kind == "row":
            cells = item[1]
            for mode, text, font_key, color in cells:
                font = fonts[font_key]
                if mode == "left":
                    x = _s(PAD)
                elif mode == "left8":
                    x = _s(8)
                elif mode == "left44":
                    x = _s(44)
                elif mode == "indent1":
                    x = indent1
                elif mode == "indent2":
                    x = indent2
                elif mode == "mat_pct":
                    x = mat_pct_x - _tw(draw, text, font)
                elif mode == "ring":
                    x = _s(80)
                elif mode == "right":
                    x = width - _s(10) - _tw(draw, text, font)
                else:
                    x = _s(PAD)
                draw.text((x, y), text, font=font, fill=color)
            y += _s(ROW)
        elif kind == "vol":
            genus = item[1]
            species = _species_for_genus(survey, genus)
            known_r, max_r = 0, 0
            if reward_for_progress is not None:
                try:
                    known_r, max_r = reward_for_progress(genus, species)
                except Exception:
                    known_r, max_r = 0, 0
            if render_volume_bar is not None and VolColor is not None:
                bar_reward = known_r if known_r > 0 else (max_r if max_r > 0 else -1)
                try:
                    render_volume_bar(
                        draw,
                        _s(12),
                        y + _s(16),
                        VolColor.ORANGE,
                        bar_reward,
                        max_reward=max_r if known_r <= 0 else known_r,
                        prediction=known_r <= 0 and max_r > 0,
                        buckets=buckets,
                    )
                except Exception:
                    pass
            draw.text((_s(28), y), genus, font=font_body, fill=CYAN)
            y2 = y + _s(12)
            left = species if species else genus
            draw.text((_s(28), y2), left, font=font_body, fill=CYAN)
            try:
                from codex_ref import format_credits as codex_credits

                if known_r > 0:
                    cred = codex_credits(known_r)
                elif max_r > 0:
                    cred = f"≤{codex_credits(max_r)}"
                else:
                    cred = "—"
            except Exception:
                cred = "—"
            twc = _tw(draw, cred, font_body)
            draw.text(
                (width - _s(8) - twc, y2), cred, font=font_body, fill=ORANGE_DIM
            )
            y += _s(_VOL_ROW)
        elif kind == "footer":
            draw.text((_s(8), y), item[1], font=font_body, fill=ORANGE)
            y += _s(ROW)

    return _finish(img)
