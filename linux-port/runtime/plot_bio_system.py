"""Pillow renderer — 1-1 Linux port of PlotBioSystem.

Faithful to PlotBioSystem.cs + PlotBioSystem.resx + GameColors / theme.json
bio colours. Volume bars match VolumeBar.cs; credit ranges omitted until a
Codex reward table lands (same gap as PlotBodyInfo). Renders at 2× then
LANCZOS-downscales.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from body_value import format_credits
from companion import (
    GUI_FOCUS_EXTERNAL_PANEL,
    GUI_FOCUS_FSS,
    GUI_FOCUS_ORRERY,
    GUI_FOCUS_ROLE_PANEL,
    GUI_FOCUS_SAA,
    GUI_FOCUS_SYSTEM_MAP,
    StatusSnapshot,
)
from game_settings import GameSettings
from journal import (
    CommanderLocation,
    SurveyState,
)

# theme.json / GameColors
ORANGE = (255, 111, 0, 255)
ORANGE_DIM = (95, 48, 3, 255)
ORANGE_DARK = (160, 70, 0, 255)
CYAN = (84, 223, 237, 255)
CYAN_DARK = (0, 139, 139, 255)
STRIPE = (12, 12, 12, 255)
BLACK = (0, 0, 0, 255)
GOLD = (255, 215, 0, 255)
GOLD_DARK = (120, 95, 0, 255)
BIO_WHITE = (255, 255, 255, 255)
BIO_PREDICTION = (47, 79, 79, 255)
HATCH = (64, 64, 64, 242)
DIM_GRAY = (105, 105, 105, 255)

# GuiFocus extras used by PlotBioSystem.allowed
_GUI_COMMS = 3
_GUI_CODEX = 11

TITLE_PX = 8  # fontSmall
BODY_PX = 10  # fontMiddle stand-in
SMALLER_PX = 9
PAD = 8
DEFAULT_WIDTH = 220

# PlotBioSystem.resx (English)
_BODY_HEADER = "Body {0} bio signals: {1}"
_SYS_HEADER = "Bio signals: {0}"
_DSS_REQUIRED = "DSS required"
_FSS_REQUIRED = "System FSS required"
_REWARD_FOOTER = "Rewards: {0}"
_FF_BONUS = "(FF bonus: {0})"
_GEO_SIGNALS = "Geo signals: {0}"
_HAS_CANONN = "Has Canonn signals"
_NOT_PREDICTED = "Not predicted!"


class VolColor(str, Enum):
    ORANGE = "orange"
    BLUE = "blue"
    GOLD = "gold"
    WHITE = "white"
    DARK_ORANGE = "dark_orange"
    DARK_GOLD = "dark_gold"


# (edge, min_fill, min_pen, max_fill, max_pen)
_VOL_PALETTE: dict[VolColor, tuple] = {
    VolColor.ORANGE: (
        (*ORANGE[:3], 96),
        ORANGE,
        ORANGE_DIM,
        (*ORANGE_DIM[:3], 140),
        (*ORANGE[:3], 124),
    ),
    VolColor.BLUE: (
        (*CYAN_DARK[:3], 96),
        CYAN,
        CYAN_DARK,
        (*CYAN_DARK[:3], 180),
        CYAN_DARK,
    ),
    VolColor.GOLD: (
        (*GOLD[:3], 96),
        (184, 134, 11, 255),  # DarkGoldenrod fill
        GOLD,
        (184, 134, 11, 144),
        (214, 164, 11, 144),
    ),
    VolColor.WHITE: (
        (255, 255, 255, 96),
        (244, 244, 244, 255),
        (128, 128, 128, 255),
        (184, 184, 184, 140),
        (255, 255, 255, 144),
    ),
    VolColor.DARK_ORANGE: (
        (128, 55, 0, 96),
        (180, 70, 0, 255),
        (70, 30, 0, 255),
        (70, 30, 0, 140),
        (128, 55, 0, 124),
    ),
    VolColor.DARK_GOLD: (
        (120, 95, 0, 96),
        (100, 75, 0, 255),
        (184, 134, 11, 255),
        (184, 134, 11, 140),
        (100, 75, 0, 124),
    ),
}


@dataclass(frozen=True)
class BioBodyRow:
    """Merged body bio row from BodySignals + FssBodyEntry."""

    body_name: str
    short_name: str
    bio_count: int
    geo_count: int
    genuses: tuple[str, ...]
    analyzed_count: int
    dss_complete: bool
    first_footfall: bool
    body_id: int | None = None


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
        (
            "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Regular.ttf"
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
    draw.rectangle((0, 0, w - 1, h - 1), fill=BLACK)
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


def get_min_max_credits(min_v: int, max_v: int) -> str:
    """Match Util.getMinMaxCredits."""
    if min_v <= 0 and max_v <= 0:
        return ""
    if min_v == max_v:
        return format_credits(min_v, hide_units=True)
    return (
        f"{format_credits(min_v, hide_units=True)}"
        f" ~ {format_credits(max_v, hide_units=True)}"
    )


def _short_body(name: str, system: str | None) -> str:
    if system and name.startswith(system):
        short = name[len(system) :].strip()
        return short or name
    return name


def _bio_bodies(survey: SurveyState) -> list[BioBodyRow]:
    """Bodies with bio signals, ordered by FSS body id when known."""
    by_name: dict[str, BioBodyRow] = {}
    system = survey.system

    for sig in survey.body_signals:
        if sig.bio_count <= 0 and not sig.genuses:
            continue
        bio_n = sig.bio_count or len(sig.genuses)
        if bio_n <= 0:
            continue
        by_name[sig.body_name] = BioBodyRow(
            body_name=sig.body_name,
            short_name=_short_body(sig.body_name, system),
            bio_count=bio_n,
            geo_count=sig.geo_count,
            genuses=sig.genuses,
            analyzed_count=0,
            dss_complete=False,
            first_footfall=False,
        )

    for fss in survey.fss_bodies:
        if fss.bio_signal_count <= 0 and fss.body_name not in by_name:
            continue
        prev = by_name.get(fss.body_name)
        if prev is None and fss.bio_signal_count <= 0:
            continue
        bio_n = fss.bio_signal_count or (prev.bio_count if prev else 0)
        if bio_n <= 0:
            continue
        by_name[fss.body_name] = BioBodyRow(
            body_name=fss.body_name,
            short_name=fss.short_name or _short_body(fss.body_name, system),
            bio_count=bio_n,
            geo_count=fss.geo_signal_count or (prev.geo_count if prev else 0),
            genuses=prev.genuses if prev else (),
            analyzed_count=fss.analyzed_bio_count,
            dss_complete=fss.dss_complete,
            first_footfall=fss.first_footfall,
            body_id=fss.body_id,
        )

    return sorted(
        by_name.values(),
        key=lambda b: (b.body_id if b.body_id is not None else 9999, b.short_name),
    )


def _total_bio(survey: SurveyState) -> int:
    bodies = _bio_bodies(survey)
    if bodies:
        return sum(b.bio_count for b in bodies)
    return int(survey.total_bio_signals or 0)


def _analyzed_genuses(survey: SurveyState, body_name: str | None) -> set[str]:
    out: set[str] = set()
    for p in survey.organic_progress:
        if p.scan_type != "Analyse":
            continue
        if body_name and p.body_name and p.body_name != body_name:
            continue
        out.add(p.genus)
    return out


def _active_genus(survey: SurveyState, body_name: str | None) -> str | None:
    for p in reversed(survey.organic_progress):
        if p.scan_type not in ("Log", "Sample"):
            continue
        if body_name and p.body_name and p.body_name != body_name:
            continue
        return p.genus
    return None


def _destination_short(status: StatusSnapshot | None, system: str | None) -> str | None:
    if status is None:
        return None
    if status.destination_body is not None and status.destination_body > 0:
        # Caller matches by body_id; short name still useful for highlight text.
        pass
    if status.destination:
        name = status.destination
        if system and name.startswith(system):
            return _short_body(name, system)
        # Station names etc. — still try as body short if it looks like one.
        return name.replace(system or "", "").replace(" ", "") or name
    return None


def resolve_target_body(
    survey: SurveyState,
    location: CommanderLocation,
    status: StatusSnapshot | None,
    game: GameSettings,
) -> BioBodyRow | None:
    """Match PlotBioSystem.targetBody as journal/status allow."""
    bodies = _bio_bodies(survey)
    if not bodies:
        return None

    # System-map style panels leave body view.
    if status is not None and status.gui_focus in (
        GUI_FOCUS_EXTERNAL_PANEL,
        GUI_FOCUS_SYSTEM_MAP,
        GUI_FOCUS_ORRERY,
    ):
        return None

    local_name = location.body or (status.body_name if status is not None else None)
    dest_id = status.destination_body if status is not None else None
    dest_name = status.destination if status is not None else None

    target: BioBodyRow | None = None
    if dest_id is not None and dest_id > 0:
        target = next((b for b in bodies if b.body_id == dest_id), None)
    if target is None and dest_name:
        for b in bodies:
            if b.body_name == dest_name or b.short_name == dest_name:
                target = b
                break
            if system := survey.system:
                if dest_name == f"{system} {b.short_name}":
                    target = b
                    break

    local = next((b for b in bodies if b.body_name == local_name), None)

    # Supercruise / no surface fix → system overview (Windows clears systemBody).
    if (
        status is not None
        and status.supercruise
        and not status.has_lat_long
        and (target is None or (local is not None and target.body_name == local.body_name))
    ):
        return None

    if not game.drawBodyBiosOnlyWhenNear:
        body = target or local
    elif target is None or (local is not None and target.body_name == local.body_name):
        body = local
    else:
        body = None

    if body is not None and body.bio_count <= 0:
        return None
    return body


def _system_mode(status: StatusSnapshot | None) -> bool:
    if status is None:
        return True
    if status.supercruise:
        return True
    gui = status.gui_focus
    if gui in (
        GUI_FOCUS_SAA,
        GUI_FOCUS_FSS,
        GUI_FOCUS_EXTERNAL_PANEL,
        GUI_FOCUS_ORRERY,
        GUI_FOCUS_SYSTEM_MAP,
    ):
        return True
    return False


def _body_mode(status: StatusSnapshot | None) -> bool:
    if status is None:
        return True
    if status.glide_mode or status.landed or status.on_foot or status.in_srv:
        return True
    if status.is_flying_or_supercruise() and not status.supercruise:
        return True
    gui = status.gui_focus
    if gui in (GUI_FOCUS_ROLE_PANEL, _GUI_COMMS, _GUI_CODEX):
        return True
    return False


def bio_system_allowed(
    game: GameSettings,
    survey: SurveyState,
    location: CommanderLocation,
    status: StatusSnapshot | None,
    *,
    force_show: bool = False,
) -> bool:
    """Match PlotBioSystem.allowed (minus Guardian plot collision)."""
    if not force_show and not game.autoShowPlotBioSystem:
        return False
    if game.buildProjectsSuppressOtherOverlays:
        return False
    if status is not None and status.in_taxi:
        return False
    if _total_bio(survey) <= 0:
        return False
    if force_show:
        return True
    if _system_mode(status):
        return True
    body = resolve_target_body(survey, location, status, game)
    if body is None or body.bio_count <= 0:
        return False
    if survey.system_station is not None and game.autoShowHumanSitesTest:
        return False
    return _body_mode(status)


def bio_system_lines(
    survey: SurveyState,
    location: CommanderLocation,
    *,
    game: GameSettings | None = None,
    status: StatusSnapshot | None = None,
) -> list[tuple[str, tuple[int, int, int, int], bool]]:
    """Pure layout rows: (text, colour, strike). Unit-testable."""
    gs = game if game is not None else GameSettings()
    rows: list[tuple[str, tuple[int, int, int, int], bool]] = []
    bodies = _bio_bodies(survey)
    if not bodies:
        return rows

    body = resolve_target_body(survey, location, status, gs)
    # FSS: prefer last scanned bio body when present
    if status is not None and status.gui_focus == GUI_FOCUS_FSS and survey.fss_bodies:
        last = survey.fss_bodies[0]
        if last.bio_signal_count > 0:
            match = next((b for b in bodies if b.body_name == last.body_name), None)
            if match is not None:
                body = match
        else:
            body = None

    if body is not None:
        rows.append(
            (_BODY_HEADER.format(body.short_name, body.bio_count), ORANGE, False)
        )
        analyzed = _analyzed_genuses(survey, body.body_name)
        active = _active_genus(survey, body.body_name)
        if not body.genuses:
            if not body.dss_complete:
                rows.append((f"► {_DSS_REQUIRED}", CYAN, False))
        else:
            for genus in body.genuses:
                done = genus in analyzed
                highlight = (not done) and (active is None or active == genus)
                col = CYAN if highlight else (ORANGE_DARK if done else ORANGE)
                rows.append((genus, col, done))
        if body.geo_count > 0 and not gs.hideGeoCountInBioSystem:
            rows.append((_GEO_SIGNALS.format(body.geo_count), ORANGE, False))
        rows.append((_REWARD_FOOTER.format("—"), ORANGE, False))
        if body.first_footfall:
            rows.append((_FF_BONUS.format("—"), CYAN, False))
        return rows

    total = sum(b.bio_count for b in bodies)
    rows.append((_SYS_HEADER.format(total), ORANGE, False))
    dest = _destination_short(status, survey.system)
    fss_needed = False
    any_ff = False
    for b in bodies:
        any_ff |= b.first_footfall
        scans_done = b.analyzed_count >= b.bio_count and b.bio_count > 0
        highlight = (dest is not None and b.short_name == dest) or (
            0 < b.analyzed_count < b.bio_count
        )
        col = ORANGE_DARK if scans_done else (CYAN if highlight else ORANGE)
        rows.append((f"{b.short_name}  ×{b.bio_count}", col, scans_done))
        if (
            not b.dss_complete
            and len(b.genuses) < b.bio_count
        ):
            fss_needed = True
    if fss_needed:
        tip = _DSS_REQUIRED if survey.fss_complete else _FSS_REQUIRED
        rows.append((f"► {tip}", CYAN, False))
    rows.append((_REWARD_FOOTER.format("—"), ORANGE, False))
    if any_ff:
        rows.append((_FF_BONUS.format("—"), CYAN, False))
    return rows


def render_volume_bar(
    draw,
    x: int,
    y: int,
    col: VolColor,
    reward: int,
    max_reward: int = -1,
    *,
    prediction: bool = False,
    buckets: tuple[float, float, float] = (3.0, 7.0, 12.0),
) -> None:
    """VolumeBar.render — stacked value rings in a dotted box."""
    ww = _s(8)
    yy = y
    edge, min_fill, min_pen, max_fill, max_pen = _VOL_PALETTE[col]
    # Outer box
    draw.rectangle((x, y - _s(12), x + ww, y), fill=BLACK)
    _dotted_rect(draw, x, y - _s(12), ww, _s(15), edge)

    if reward <= 0:
        font = _font(TITLE_PX, bold=True)
        draw.text((x - _s(1), y - _s(11)), "?", font=font, fill=BIO_PREDICTION)
        return

    bucket_vals = (
        0,
        int(buckets[0] * 1_000_000),
        int(buckets[1] * 1_000_000),
        int(buckets[2] * 1_000_000),
    )
    cy = y
    for bucket in bucket_vals:
        if reward > bucket:
            draw.rectangle((x, cy, x + ww, cy + _s(3)), fill=min_fill, outline=min_pen)
        elif max_reward > bucket:
            draw.rectangle((x, cy, x + ww, cy + _s(3)), fill=max_fill, outline=max_pen)
        cy -= _s(4)

    if prediction:
        # Diagonal hatch approximation
        hx0, hy0 = x + _s(1), cy + _s(5)
        hx1, hy1 = x + ww - _s(1), y + _s(2)
        step = max(2, _s(2))
        for i in range(hx0 - (hy1 - hy0), hx1 + 1, step):
            draw.line((i, hy0, i + (hy1 - hy0), hy1), fill=HATCH, width=1)

    if col == VolColor.WHITE:
        _dotted_rect(draw, x, yy - _s(12), ww, _s(15), edge)
        _dotted_rect(draw, x, yy - _s(12), ww, _s(15), edge)


def _dotted_rect(draw, x: int, y: int, w: int, h: int, colour) -> None:
    # Approximate DashStyle.Dot
    step = max(2, _s(2))
    # top / bottom
    for px in range(x, x + w, step * 2):
        draw.line((px, y, min(px + step, x + w), y), fill=colour, width=max(1, SCALE // 2))
        draw.line(
            (px, y + h, min(px + step, x + w), y + h),
            fill=colour,
            width=max(1, SCALE // 2),
        )
    for py in range(y, y + h, step * 2):
        draw.line((x, py, x, min(py + step, y + h)), fill=colour, width=max(1, SCALE // 2))
        draw.line(
            (x + w, py, x + w, min(py + step, y + h)),
            fill=colour,
            width=max(1, SCALE // 2),
        )


def render_bio_system_bitmap(
    survey: SurveyState,
    location: CommanderLocation,
    *,
    game: GameSettings | None = None,
    status: StatusSnapshot | None = None,
    force_show: bool = False,
    max_width: int = DEFAULT_WIDTH,
) -> tuple[bytes, int, int] | None:
    """Render PlotBioSystem. Returns None when not allowed / nothing to show."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    if not bio_system_allowed(
        gs, survey, location, status, force_show=force_show
    ):
        return None

    bodies = _bio_bodies(survey)
    if not bodies:
        return None

    body = resolve_target_body(survey, location, status, gs)
    if status is not None and status.gui_focus == GUI_FOCUS_FSS and survey.fss_bodies:
        last = survey.fss_bodies[0]
        if last.bio_signal_count > 0:
            match = next((b for b in bodies if b.body_name == last.body_name), None)
            body = match
        else:
            body = None

    font_small = _font(TITLE_PX)
    font_mid = _font(BODY_PX)
    font_smaller = _font(SMALLER_PX)
    buckets = (
        gs.bioRingBucketOne,
        gs.bioRingBucketTwo,
        gs.bioRingBucketThree,
    )

    if body is not None:
        return _render_body_view(
            body,
            survey,
            gs,
            font_small,
            font_mid,
            font_smaller,
            buckets,
            max_width,
        )
    return _render_system_view(
        bodies,
        survey,
        status,
        gs,
        font_small,
        font_mid,
        font_smaller,
        buckets,
        max_width,
    )


def _render_body_view(
    body: BioBodyRow,
    survey: SurveyState,
    gs: GameSettings,
    font_small,
    font_mid,
    font_smaller,
    buckets: tuple[float, float, float],
    max_width: int,
) -> tuple[bytes, int, int]:
    from PIL import Image, ImageDraw

    analyzed = _analyzed_genuses(survey, body.body_name)
    active = _active_genus(survey, body.body_name)
    genuses = list(body.genuses)

    # Estimate size
    width = _s(min(max_width, DEFAULT_WIDTH + 40))
    rows = max(1, len(genuses)) if genuses else 1
    height = _s(18) + rows * _s(28) + _s(40)
    if body.geo_count > 0 and not gs.hideGeoCountInBioSystem:
        height += _s(16) + body.geo_count * _s(12)
    if body.first_footfall:
        height += _s(14)

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height)

    y = _s(10)
    header = _BODY_HEADER.format(body.short_name, body.bio_count)
    draw.text((_s(8), y), header, font=font_small, fill=ORANGE)
    y += _s(16)

    if not genuses:
        if not body.dss_complete:
            draw.text((_s(10), y), f"► {_DSS_REQUIRED}", font=font_small, fill=CYAN)
            y += _s(14)
        predicted_names: list[str] = []
        if not gs.disableBioPredictions:
            try:
                from bio_predict import predict_for_survey

                fss = next(
                    (b for b in survey.fss_bodies if b.body_name == body.body_name),
                    None,
                )
                if fss is not None:
                    for row in predict_for_survey(
                        survey, body_name=body.body_name, limit=body.bio_count or 8
                    ):
                        label = row.genus or row.name
                        if label and label not in predicted_names:
                            predicted_names.append(label)
            except Exception:
                predicted_names = []
        if predicted_names:
            for i, genus in enumerate(predicted_names[: max(1, body.bio_count)]):
                if i:
                    draw.line(
                        (_s(8), y - _s(5), width - _s(8), y - _s(5)),
                        fill=ORANGE_DIM,
                        width=1,
                    )
                try:
                    from codex_ref import format_credits as format_credits_fn
                    from codex_ref import max_reward_for_genus

                    max_r = max_reward_for_genus(genus)
                except Exception:
                    format_credits_fn = None
                    max_r = 0
                render_volume_bar(
                    draw,
                    _s(12),
                    y + _s(16),
                    VolColor.BLUE,
                    max_r if max_r > 0 else -1,
                    max_reward=max_r,
                    prediction=True,
                    buckets=buckets,
                )
                draw.text((_s(28), y), f"? {genus}", font=font_small, fill=CYAN)
                if format_credits_fn and max_r:
                    cred = f"≤{format_credits_fn(max_r)}"
                    twc = _tw(draw, cred, font_small)
                    draw.text(
                        (width - _s(8) - twc, y + _s(12)),
                        cred,
                        font=font_small,
                        fill=ORANGE_DIM,
                    )
                y += _s(26)
        else:
            # Unknown signal placeholders
            for i in range(body.bio_count):
                if i:
                    draw.line(
                        (_s(8), y - _s(5), width - _s(8), y - _s(5)),
                        fill=ORANGE_DIM,
                        width=1,
                    )
                render_volume_bar(
                    draw, _s(12), y + _s(16), VolColor.BLUE, -1, buckets=buckets
                )
                draw.text((_s(28), y), _NOT_PREDICTED, font=font_small, fill=CYAN)
                y += _s(26)
    else:
        for i, genus in enumerate(genuses):
            if i:
                draw.line(
                    (_s(8), y - _s(5), width - _s(8), y - _s(5)),
                    fill=ORANGE_DIM,
                    width=1,
                )
            done = genus in analyzed
            highlight = (not done) and (active is None or active == genus)
            vol = VolColor.ORANGE
            if gs.dimIfAnalyzed and done:
                vol = VolColor.DARK_ORANGE
            species = None
            for p in survey.organic_progress:
                if p.genus == genus and p.species:
                    species = p.species
                    break
            known_r, max_r = 0, 0
            format_credits_fn = None
            try:
                from codex_ref import format_credits as format_credits_fn
                from codex_ref import reward_for_progress

                known_r, max_r = reward_for_progress(genus, species)
            except Exception:
                known_r, max_r = 0, 0
            bar_reward = known_r if known_r > 0 else (max_r if max_r > 0 else -1)
            render_volume_bar(
                draw,
                _s(12),
                y + _s(16),
                vol,
                bar_reward,
                max_reward=max_r if known_r <= 0 else known_r,
                prediction=known_r <= 0 and max_r > 0,
                buckets=buckets,
            )
            col = CYAN if highlight else ORANGE
            if vol == VolColor.GOLD:
                col = GOLD
            draw.text((_s(28), y), genus, font=font_small, fill=col)
            if done:
                tw = _tw(draw, genus, font_small)
                mid = y + _th(draw, genus, font_small) // 2
                draw.line(
                    (_s(28), mid, _s(28) + tw, mid),
                    fill=col,
                    width=max(1, SCALE // 2),
                )
            # Second line: species or genus, credits right
            y2 = y + _s(12)
            left = species if species else genus
            draw.text((_s(28), y2), left, font=font_small, fill=col)
            if format_credits_fn and (known_r or max_r):
                if known_r > 0:
                    cred = format_credits_fn(known_r)
                else:
                    cred = f"≤{format_credits_fn(max_r)}"
            else:
                cred = "—"
            twc = _tw(draw, cred, font_small)
            draw.text((width - _s(8) - twc, y2), cred, font=font_small, fill=ORANGE_DIM)
            if active == genus:
                draw.line(
                    (_s(4), y - _s(1), _s(4), y2 + _s(10)),
                    fill=CYAN,
                    width=_s(2),
                )
                draw.line(
                    (width - _s(4), y - _s(1), width - _s(4), y2 + _s(10)),
                    fill=CYAN,
                    width=_s(2),
                )
            y = y2 + _s(14)

    y += _s(4)
    # Sum max rewards for listed genuses
    total_reward = 0
    try:
        from codex_ref import format_credits, max_reward_for_genus, reward_for_species

        for genus in genuses:
            species = None
            for p in survey.organic_progress:
                if p.genus == genus and p.species:
                    species = p.species
                    break
            if species:
                total_reward += reward_for_species(species) or max_reward_for_genus(genus)
            else:
                total_reward += max_reward_for_genus(genus)
        footer = _REWARD_FOOTER.format(format_credits(total_reward))
    except Exception:
        footer = _REWARD_FOOTER.format("—")
    draw.text((_s(8), y), footer, font=font_small, fill=ORANGE)
    y += _s(12)
    if body.first_footfall:
        ff = _FF_BONUS.format("—")
        tw = _tw(draw, ff, font_small)
        draw.text((width - _s(8) - tw, y), ff, font=font_small, fill=CYAN)
        y += _s(12)

    if body.geo_count > 0 and not gs.hideGeoCountInBioSystem:
        y += _s(6)
        draw.line(
            (_s(8), y - _s(5), width - _s(8), y - _s(5)),
            fill=ORANGE_DIM,
            width=1,
        )
        y += _s(2)
        draw.text(
            (_s(8), y),
            _GEO_SIGNALS.format(body.geo_count),
            font=font_small,
            fill=ORANGE,
        )
        y += _s(12)
        for n in range(body.geo_count):
            draw.text((_s(12), y), f"► ?", font=font_small, fill=ORANGE_DARK)
            y += _s(12)

    used = min(height, y + _s(10))
    if used < height:
        img = img.crop((0, 0, width, used))
        height = used
        draw = ImageDraw.Draw(img)
        for yy, col in (
            (height - _s(5), ORANGE_DIM),
            (height - _s(4), ORANGE),
            (height - _s(3), ORANGE_DIM),
        ):
            draw.line((_s(2), yy, width - _s(4), yy), fill=col)
        draw.rectangle(
            (0, 0, width - 1, height - 1),
            outline=ORANGE,
            width=max(1, SCALE // 2),
        )

    return _finish(img)


def _render_system_view(
    bodies: list[BioBodyRow],
    survey: SurveyState,
    status: StatusSnapshot | None,
    gs: GameSettings,
    font_small,
    font_mid,
    font_smaller,
    buckets: tuple[float, float, float],
    max_width: int,
) -> tuple[bytes, int, int]:
    from PIL import Image, ImageDraw

    total = sum(b.bio_count for b in bodies)
    dest = _destination_short(status, survey.system)
    dest_id = status.destination_body if status is not None else None

    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    max_name_w = max(_tw(probe, b.short_name, font_mid) for b in bodies)
    max_bio = max(b.bio_count for b in bodies)
    content_w = _s(12) + max_name_w + (max_bio * _s(12)) + _s(80)
    width = max(_s(DEFAULT_WIDTH), min(_s(max_width + 80), content_w))
    if width > _s(max_width + 80):
        width = _s(max_width + 80)

    height = _s(16) + len(bodies) * _s(22) + _s(40)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height)

    y = _s(8)
    draw.text((_s(6), y), _SYS_HEADER.format(total), font=font_small, fill=ORANGE)
    y += _s(14)

    box_left = _s(12) + max_name_w
    any_ff = False
    fss_needed = False

    for body in bodies:
        any_ff |= body.first_footfall
        highlight = False
        if dest_id is not None and body.body_id == dest_id:
            highlight = True
        elif dest is not None and body.short_name == dest:
            highlight = True
        elif 0 < body.analyzed_count < body.bio_count:
            highlight = True

        scans_complete = body.analyzed_count >= body.bio_count and body.bio_count > 0
        col = ORANGE_DARK if scans_complete else (CYAN if highlight else ORANGE)

        draw.text((_s(8), y), body.short_name, font=font_mid, fill=col)
        if scans_complete:
            tw = _tw(draw, body.short_name, font_mid)
            mid = y + _th(draw, body.short_name, font_mid) // 2
            draw.line(
                (_s(8), mid, _s(8) + tw, mid),
                fill=col,
                width=max(1, SCALE // 2),
            )

        bar_x = box_left
        bar_x += _draw_body_bars(
            draw, body, bar_x, y, highlight, gs, buckets
        )

        # Credits unknown without Codex table
        draw.text(
            (width - _s(10) - _tw(draw, " ", font_smaller), y + _s(2)),
            " ",
            font=font_smaller,
            fill=col,
        )
        y += _s(20)

        if (
            not body.dss_complete
            and len(body.genuses) < body.bio_count
        ):
            fss_needed = True

    if fss_needed:
        y += _s(6)
        tip = _DSS_REQUIRED if survey.fss_complete else _FSS_REQUIRED
        draw.text((_s(6), y), f"► {tip}", font=font_small, fill=CYAN)
        y += _s(12)

    y += _s(4)
    footer = _REWARD_FOOTER.format("—")
    draw.text((_s(6), y), footer, font=font_small, fill=ORANGE)
    y += _s(12)
    if any_ff:
        ff = _FF_BONUS.format("—")
        tw = _tw(draw, ff, font_small)
        draw.text((width - _s(8) - tw, y), ff, font=font_small, fill=CYAN)
        y += _s(10)

    used = min(height, y + _s(8))
    if used < height:
        img = img.crop((0, 0, width, used))
        height = used
        draw = ImageDraw.Draw(img)
        for yy, col in (
            (height - _s(5), ORANGE_DIM),
            (height - _s(4), ORANGE),
            (height - _s(3), ORANGE_DIM),
        ):
            draw.line((_s(2), yy, width - _s(4), yy), fill=col)
        draw.rectangle(
            (0, 0, width - 1, height - 1),
            outline=ORANGE,
            width=max(1, SCALE // 2),
        )

    return _finish(img)


def _draw_body_bars(
    draw,
    body: BioBodyRow,
    x: int,
    y: int,
    highlight: bool,
    gs: GameSettings,
    buckets: tuple[float, float, float],
) -> int:
    """PlotBioSystem.drawBodyBars — dotted outer box + per-signal volume bars."""
    if body.bio_count <= 0:
        return 0
    ix = x
    signal_count = body.bio_count
    by = y + _s(15)
    w = body.bio_count * _s(12) + _s(2)
    edge = CYAN if highlight else ORANGE
    _dotted_rect(draw, x - _s(3), by - _s(15), w, _s(21), (*edge[:3], 180))

    cx = x
    # Known genuses (DSS / SAA Genuses list). Dim the first analyzed_count bars.
    remaining_analyzed = body.analyzed_count if gs.dimIfAnalyzed else 0
    for _genus in body.genuses:
        vol = VolColor.ORANGE
        if remaining_analyzed > 0:
            vol = VolColor.DARK_ORANGE
            remaining_analyzed -= 1
        render_volume_bar(draw, cx, by, vol, -1, buckets=buckets)
        cx += _s(12)
        signal_count -= 1
        if signal_count <= 0:
            break

    # Remaining unknown slots — blue ? bars (predictions / unscanned)
    while signal_count > 0:
        render_volume_bar(draw, cx, by, VolColor.BLUE, -1, buckets=buckets)
        cx += _s(12)
        signal_count -= 1

    return cx - ix
