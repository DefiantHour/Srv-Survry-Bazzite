"""Pillow renderer — 1-1 Linux port of PlotGuardianStatus.

Faithful to PlotGuardianStatus.cs + GameColors (orange / cyan / gothic stand-in).
Full PlotGuardians map modes need site templates; this port covers approach,
POI selection cues, and foot relic-tower hints from available journal/status.
Renders at 2× then LANCZOS-downscales so AA approximates GDI ClearType.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
from pathlib import Path

from companion import StatusSnapshot
from game_settings import GameSettings
from journal import GuardianSiteSummary, SurveyState

ORANGE = (255, 111, 0, 255)
ORANGE_DIM = (95, 48, 3, 255)
CYAN = (84, 223, 237, 255)
GRAY = (128, 128, 128, 255)
STRIPE = (12, 12, 12, 255)

TITLE_PX = 10
BODY_PX = 11
SMALL_PX = 9
PAD = 8
DEFAULT_WIDTH = 500
DEFAULT_HEIGHT = 108

# English strings from PlotGuardianStatus.resx / Properties.Guardian.resx
_HEADER_UNKNOWN = "Site type unknown"
_CHOOSE_PRESENT = "Present"
_CHOOSE_ABSENT = "Absent"
_CHOOSE_EMPTY = "Empty"
_ALIGN_BUTTRESS = "Align with buttress"
_NO_NEAR_POI = "Move within ~75m to inspect an item"
_TOGGLE_LIGHTS = "(toggle lights to force update)"
_TOGGLE_ONCE = "(toggle cockpit mode once to set)"
_FOOT_RELIC = (
    "Use Profile Analyser near Relic Towers for aiming assistance.\n"
    "Face the side with a single large left facing triangle."
)
_FOOT_HINT = "(toggle weapon to force location update)"
_APPROACH_RUINS = "Approaching Guardian Ruins ..."
_APPROACH_STRUCTURE = "Approaching Guardian Structure ..."
_APPROACH_FOOTER = "( Don't forget to set 3 fire groups in ships and SRVs )"
_ALPHA, _BETA, _GAMMA = "Alpha", "Beta", "Gamma"


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


def _th(draw, text: str, font) -> int:
    b = draw.textbbox((0, 0), text, font=font)
    return int(b[3] - b[1])


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


def _is_ancient_name(name: str | None) -> bool:
    if not name:
        return False
    return name.startswith("$Ancient") or "guardian ruin" in name.lower()


def glide_site_from_survey(
    survey: SurveyState,
    status: StatusSnapshot | None,
) -> GuardianSiteSummary | None:
    """Approximate PlotGuardianStatus.glideSite while GlideMode + Ancient dest."""
    if status is None or not status.glide_mode:
        return None
    dest = status.destination
    if not _is_ancient_name(dest):
        return None
    for site in survey.guardian_sites:
        if site.name == dest or (
            site.body_id is not None and site.body_id == status.destination_body
        ):
            return site
    # Synthesize from destination when journal has not approached yet.
    raw = dest or "Guardian site"
    is_ruins = raw.startswith("$Ancient:#") or not raw.startswith("$Ancient_")
    return GuardianSiteSummary(
        name=raw,
        display_text=raw,
        body_id=status.destination_body,
        is_ruins=is_ruins,
        site_type=None,
        blue_print=_blueprint_for_structure_name(raw),
    )


def _blueprint_for_structure_name(name: str) -> str | None:
    key = name.split(":#", 1)[0] if ":#" in name else name
    table = {
        "$Ancient_Medium_001": "Fighter",
        "$Ancient_Medium_002": "Fighter",
        "$Ancient_Medium_003": "Fighter",
        "$Ancient_Small_005": "Module",
        "$Ancient_Small_001": "Weapon",
        "$Ancient_Small_002": "Weapon",
        "$Ancient_Small_003": "Weapon",
    }
    return table.get(key)


def guardian_status_allowed(
    game: GameSettings,
    survey: SurveyState,
    status: StatusSnapshot | None,
) -> bool:
    """Match PlotGuardianStatus.allowed (PlotGuardians.allowed | glide approach)."""
    if not game.enableGuardianSites:
        return False
    if game.buildProjectsSuppressOtherOverlays:
        return False
    if status is None:
        return False
    if status.fsd_charging_jump:
        return False
    if glide_site_from_survey(survey, status) is not None:
        return True
    if not status.has_lat_long:
        return False
    if survey.current_guardian_site is None and not survey.guardian_sites:
        return False
    # Modes: InSrv / OnFoot / Landed / Flying / InFighter / panels
    if status.on_foot or status.in_srv or status.in_fighter:
        return True
    if status.landed:
        return True
    if status.docked:
        return False
    if status.supercruise:
        return False
    return status.in_main_ship


def _draw_options(
    draw,
    *,
    width: int,
    selected_index: int,
    highlight_idx: int,
    msg1: str,
    msg2: str,
    msg3: str | None,
    font_small,
    font_body,
) -> None:
    block_width = _s(90)
    block_top = _s(45)
    letter_offset = _s(10)
    mw = width // 2
    pts = [
        (int(mw - (block_width * 1.5)), block_top),
        (int(mw - (block_width * 0.5)), block_top),
        (int(mw + (block_width * 0.5)), block_top),
    ]
    letters = [
        (pts[0][0] - letter_offset, block_top - letter_offset),
        (pts[1][0] - letter_offset, block_top - letter_offset),
        (pts[2][0] - letter_offset, block_top - letter_offset),
    ]
    msgs = [msg1, msg2, msg3]
    for i, msg in enumerate(msgs):
        if msg is None:
            continue
        if highlight_idx == -2:
            c = GRAY
        elif highlight_idx == i:
            c = CYAN
        else:
            c = ORANGE
        draw.text(letters[i], f"{chr(ord('A') + i)}:", font=font_small, fill=c)
        draw.text(pts[i], msg, font=font_body, fill=c)

    sel = max(0, min(selected_index, 2 if msg3 else 1))
    rect = (
        pts[sel][0] - _s(12),
        pts[sel][1] - _s(12),
        pts[sel][0] - _s(12) + block_width,
        pts[sel][1] - _s(12) + _s(44),
    )
    if highlight_idx == -2 or (msg3 is None and highlight_idx == 2):
        outline = GRAY
    elif highlight_idx == sel:
        outline = CYAN
    else:
        outline = ORANGE
    draw.rectangle(rect, outline=outline, width=max(1, SCALE // 2))


def render_guardian_status_bitmap(
    survey: SurveyState,
    *,
    game: GameSettings | None = None,
    status: StatusSnapshot | None = None,
    force_show: bool = False,
    max_width: int = DEFAULT_WIDTH,
    commander: str | None = None,
    cmdr=None,
    guardian_state=None,
) -> tuple[bytes, int, int] | None:
    """Render PlotGuardianStatus. Returns None when not allowed."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    if not force_show and not guardian_status_allowed(gs, survey, status):
        return None

    # Pull survey mode / type overrides from cmdr JSON when available
    try:
        from plot_guardians import (
            aerial_guidance_lines,
            load_guardian_survey,
            resolve_survey_mode,
            site_context,
        )

        if guardian_state is None:
            _, guardian_state, _ = load_guardian_survey(
                survey, commander=commander, cmdr=cmdr
            )
        _site, _pub, site_type, heading = site_context(
            survey, guardian_state=guardian_state
        )
        mode = resolve_survey_mode(
            site_type=site_type,
            heading=heading,
            guardian_state=guardian_state,
            game=gs,
        )
    except Exception:
        site_type = None
        heading = -1
        mode = "map"

    font_title = _font(TITLE_PX, bold=True)
    font_body = _font(BODY_PX)
    font_small = _font(SMALL_PX)

    width = _s(max_width)
    height = _s(DEFAULT_HEIGHT)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height)

    fire = (status.fire_group if status is not None else 0) % 3
    glide = glide_site_from_survey(survey, status)

    if glide is not None:
        if glide.is_ruins:
            header = _APPROACH_RUINS
            mid = f"Ruins #{glide.index or 1} - {glide.site_type or 'Unknown'}"
            draw.text((_s(PAD), _s(10)), header, font=font_title, fill=ORANGE)
            mid_w = _tw(draw, mid, font_body)
            draw.text(
                ((width - mid_w) // 2, _s(34)),
                mid,
                font=font_body,
                fill=CYAN,
            )
        else:
            header = _APPROACH_STRUCTURE
            if glide.blue_print:
                mid = f"{glide.site_type or glide.display_text} - blue print: {glide.blue_print}"
            else:
                mid = f"{glide.site_type or glide.display_text} - no blue print"
            draw.text((_s(PAD), _s(10)), header, font=font_title, fill=ORANGE)
            mid_w = _tw(draw, mid, font_body)
            draw.text(
                ((width - mid_w) // 2, _s(34)),
                mid,
                font=font_body,
                fill=CYAN,
            )
        foot_w = _tw(draw, _APPROACH_FOOTER, font_small)
        draw.text(
            ((width - foot_w) // 2, height - _s(22)),
            _APPROACH_FOOTER,
            font=font_small,
            fill=ORANGE,
        )
        return _finish(img)

    # Aerial vertical-stripe assist (text + bar — Linux substitute)
    if mode == "aerial" and not gs.disableAerialAlignmentGrid:
        rows = aerial_guidance_lines(
            site_type=site_type,
            altitude=status.altitude if status is not None else None,
            game=gs,
        )
        y = _s(8)
        for text, colour in rows:
            draw.text((_s(PAD), y), text, font=font_body, fill=colour)
            y += _s(16)
        return _finish(img)

    if mode == "heading":
        draw.text((_s(PAD), _s(8)), _ALIGN_BUTTRESS, font=font_title, fill=CYAN)
        hdg = status.heading if status is not None else None
        if hdg is not None:
            msg = f"Ship heading {hdg:.0f}°"
            if heading >= 0:
                delta = ((heading - hdg + 540.0) % 360.0) - 180.0
                sign = "+" if delta >= 0 else ""
                msg = f"{msg}  ·  site {heading}°  Δ {sign}{delta:.0f}°"
            mw = _tw(draw, msg, font_body)
            draw.text(((width - mw) // 2, _s(40)), msg, font=font_body, fill=ORANGE)
        foot = "Chat .heading to capture"
        foot_w = _tw(draw, foot, font_small)
        draw.text(
            ((width - foot_w) // 2, height - _s(22)),
            foot,
            font=font_small,
            fill=ORANGE,
        )
        return _finish(img)

    site = survey.current_guardian_site
    effective_type = site_type
    if site is not None and effective_type is None and site.is_ruins:
        # Unknown ruins type — Alpha / Beta / Gamma picker
        draw.text((_s(PAD), _s(8)), _HEADER_UNKNOWN, font=font_title, fill=CYAN)
        _draw_options(
            draw,
            width=width,
            selected_index=fire,
            highlight_idx=fire,
            msg1=_ALPHA,
            msg2=_BETA,
            msg3=_GAMMA,
            font_small=font_small,
            font_body=font_body,
        )
        foot = _TOGGLE_ONCE
        foot_w = _tw(draw, foot, font_small)
        draw.text(
            ((width - foot_w) // 2, height - _s(22)),
            foot,
            font=font_small,
            fill=ORANGE,
        )
        return _finish(img)

    if status is not None and status.on_foot:
        msg = _FOOT_RELIC
        y = _s(28)
        for line in msg.splitlines():
            lw = _tw(draw, line, font_body)
            draw.text(((width - lw) // 2, y), line, font=font_body, fill=ORANGE)
            y += _s(16)
        foot_w = _tw(draw, _FOOT_HINT, font_small)
        draw.text(
            ((width - foot_w) // 2, height - _s(22)),
            _FOOT_HINT,
            font=font_small,
            fill=ORANGE,
        )
        return _finish(img)

    # Default near-site cue: Present / Absent / Empty
    draw.text((_s(PAD), _s(8)), _NO_NEAR_POI, font=font_title, fill=ORANGE)
    _draw_options(
        draw,
        width=width,
        selected_index=fire,
        highlight_idx=-2,
        msg1=_CHOOSE_PRESENT,
        msg2=_CHOOSE_ABSENT,
        msg3=_CHOOSE_EMPTY,
        font_small=font_small,
        font_body=font_body,
    )
    foot_w = _tw(draw, _TOGGLE_LIGHTS, font_small)
    draw.text(
        ((width - foot_w) // 2, height - _s(22)),
        _TOGGLE_LIGHTS,
        font=font_small,
        fill=ORANGE,
    )
    return _finish(img)
