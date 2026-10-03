"""Pillow renderer — 1-1 Linux port of PlotBioStatus.

Faithful to PlotBioStatus.cs + PlotBioStatus.resx + GameColors
(orange / cyan / gothic stand-in). Renders at 2× then LANCZOS-downscales.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
from pathlib import Path

from companion import StatusSnapshot
from game_settings import GameSettings
from journal import (
    BodySignals,
    CommanderLocation,
    FssBodyEntry,
    OrganicProgress,
    SurveyState,
)

# GameColors defaults
ORANGE = (255, 111, 0, 255)
ORANGE_DIM = (95, 48, 3, 255)
CYAN = (84, 223, 237, 255)
RED = (255, 48, 0, 255)
STRIPE = (12, 12, 12, 255)

TITLE_PX = 8  # fontSmall
BODY_PX = 9
BIG_PX = 18  # fontBig stand-in (scaled down for wrap)
DEFAULT_WIDTH = 480
DEFAULT_HEIGHT = 80

# PlotBioStatus.resx (English)
_HEADER = "Biological signals: {0} | Analyzed: {1}"
_DSS_REQUIRED = "Bio signals detected - DSS Scan required"
_FOOTER_ALL = "All signals scanned"
_FOOTER_ALL_FF = "All signals scanned with FF bonus applied"
_FOOTER_APPLY_FF = "Applying first footfall bonus"
_FOOTER_COMP = "Use Composition Scanner to set tracker targets"
_GEO_N = "Geo #{0}"
_SUFFIX_FF = "(FF bonus)"
_WARN_STALE = "WARNING: Incomplete {0} scans from {1}"


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


def meters_to_string(meters: float) -> str:
    """Match Util.metersToString for the sample-distance scale label."""
    m = abs(float(meters))
    if m < 1:
        return "0m"
    if m < 1000:
        return f"{int(round(m))}m"
    km = m / 1000.0
    if km < 10:
        txt = f"{km:.2f}".rstrip("0").rstrip(".")
        return f"{txt}km"
    if km < 1000:
        txt = f"{km:.1f}".rstrip("0").rstrip(".")
        return f"{txt}km"
    mm = km / 1000.0
    txt = f"{mm:.2f}".rstrip("0").rstrip(".")
    return f"{txt}Mm"


def _body_signals(survey: SurveyState, body_name: str | None) -> BodySignals | None:
    if not body_name:
        return None
    for row in survey.body_signals:
        if row.body_name == body_name:
            return row
    return None


def _fss_body(survey: SurveyState, body_name: str | None) -> FssBodyEntry | None:
    if not body_name:
        return None
    for row in survey.fss_bodies:
        if row.body_name == body_name:
            return row
    return None


def _active_scan(
    survey: SurveyState,
    body_name: str | None,
) -> OrganicProgress | None:
    """Current incomplete ScanOrganic (Log / Sample), preferring current body."""
    candidates = [
        p
        for p in survey.organic_progress
        if p.scan_type in ("Log", "Sample")
    ]
    if not candidates:
        return None
    if body_name:
        local = [p for p in candidates if p.body_name == body_name]
        if local:
            return local[-1]
    return candidates[-1]


def _analyzed_genuses(survey: SurveyState, body_name: str | None) -> set[str]:
    out: set[str] = set()
    for p in survey.organic_progress:
        if p.scan_type != "Analyse":
            continue
        if body_name and p.body_name and p.body_name != body_name:
            continue
        out.add(p.genus)
    return out


def _analyzed_count(
    survey: SurveyState,
    body_name: str | None,
    signals: BodySignals | None,
) -> int:
    fss = _fss_body(survey, body_name)
    if fss is not None and fss.analyzed_bio_count:
        return int(fss.analyzed_bio_count)
    return len(_analyzed_genuses(survey, body_name))


def _bio_signal_count(
    signals: BodySignals | None,
    fss: FssBodyEntry | None,
) -> int:
    if signals is not None and signals.bio_count:
        return int(signals.bio_count)
    if fss is not None and fss.bio_signal_count:
        return int(fss.bio_signal_count)
    return 0


def _first_footfall(survey: SurveyState, body_name: str | None) -> bool:
    fss = _fss_body(survey, body_name)
    return bool(fss is not None and fss.first_footfall)


def _mode_ok(status: StatusSnapshot | None) -> bool:
    """Subset of PlotBioStatus.allowed GameMode checks via Status flags."""
    if status is None:
        # No Status.json — allow so journal-only previews still render.
        return True
    if status.docked or status.in_taxi or status.fsd_charging_jump:
        return False
    return True


def bio_status_allowed(
    game: GameSettings,
    survey: SurveyState,
    location: CommanderLocation,
    status: StatusSnapshot | None,
    *,
    force_show: bool = False,
) -> bool:
    """Match PlotBioStatus.allowed (minus Guardian / HumanSite collision)."""
    if not force_show and not game.autoShowBioSummary:
        return False
    if not _mode_ok(status):
        return False
    body = location.body or (status.body_name if status is not None else None)
    signals = _body_signals(survey, body)
    fss = _fss_body(survey, body)
    return _bio_signal_count(signals, fss) > 0


def bio_status_lines(
    survey: SurveyState,
    location: CommanderLocation,
    *,
    game: GameSettings | None = None,
    status: StatusSnapshot | None = None,
) -> list[tuple[str, tuple[int, int, int, int], bool]]:
    """Pure layout rows: (text, colour, strike). Unit-testable."""
    gs = game if game is not None else GameSettings()
    body = location.body or (status.body_name if status is not None else None)
    signals = _body_signals(survey, body)
    fss = _fss_body(survey, body)
    bio_n = _bio_signal_count(signals, fss)
    analyzed = _analyzed_count(survey, body, signals)
    rows: list[tuple[str, tuple[int, int, int, int], bool]] = []

    if bio_n <= 0:
        return rows

    organisms = list(signals.genuses) if signals and signals.genuses else []
    rows.append((_HEADER.format(bio_n, analyzed), ORANGE, False))

    if not organisms:
        rows.append((_DSS_REQUIRED, CYAN, False))
        return rows

    active = _active_scan(survey, body)
    analyzed_set = _analyzed_genuses(survey, body)
    show_current = bool(
        active is not None
        and organisms
        and active.genus in organisms
        and (active.body_name is None or active.body_name == body)
    )

    if active is not None and active.body_name and body and active.body_name != body:
        rows.append(
            (_WARN_STALE.format(active.genus, active.body_name), RED, False)
        )
        for genus in organisms:
            done = genus in analyzed_set
            rows.append((genus, ORANGE if done else CYAN, done))
    elif show_current and active is not None:
        name = active.species or active.genus
        rows.append((name, CYAN, False))
        step = "●" if active.scan_type == "Sample" else "○"
        rows.append((f"Scan {active.scan_type} {step}", CYAN, False))
    else:
        for genus in organisms:
            done = genus in analyzed_set
            rows.append((genus, ORANGE if done else CYAN, done))
        if (
            signals is not None
            and signals.geo_count > 0
            and not gs.hideGeoCountInBioSystem
        ):
            for n in range(1, signals.geo_count + 1):
                rows.append((_GEO_N.format(n), ORANGE, False))

    all_scanned = analyzed >= bio_n and bio_n > 0
    ff = _first_footfall(survey, body)
    if all_scanned and ff:
        rows.append((_FOOTER_ALL_FF, ORANGE, False))
    elif all_scanned:
        rows.append((_FOOTER_ALL, ORANGE, False))
    elif ff:
        rows.append((_FOOTER_APPLY_FF, CYAN, False))
    else:
        rows.append((_FOOTER_COMP, ORANGE, False))
    return rows


def render_bio_status_bitmap(
    survey: SurveyState,
    location: CommanderLocation,
    *,
    game: GameSettings | None = None,
    status: StatusSnapshot | None = None,
    force_show: bool = False,
    max_width: int = DEFAULT_WIDTH,
) -> tuple[bytes, int, int] | None:
    """Render PlotBioStatus. Returns None when not allowed / nothing to show."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    if not bio_status_allowed(
        gs, survey, location, status, force_show=force_show
    ):
        return None

    body = location.body or (status.body_name if status is not None else None)
    signals = _body_signals(survey, body)
    fss = _fss_body(survey, body)
    bio_n = _bio_signal_count(signals, fss)
    if bio_n <= 0:
        return None

    organisms = list(signals.genuses) if signals and signals.genuses else []
    analyzed = _analyzed_count(survey, body, signals)
    analyzed_set = _analyzed_genuses(survey, body)
    active = _active_scan(survey, body)
    ff = _first_footfall(survey, body)
    # Windows matches scanOne species against systemBody.organisms; we match genus.
    show_current = bool(
        active is not None
        and organisms
        and active.genus in organisms
        and (active.body_name is None or active.body_name == body)
    )

    font_small = _font(TITLE_PX)
    font_body = _font(BODY_PX)
    font_big = _font(BIG_PX)
    font_mid = _font(14)

    width = _s(min(max_width, DEFAULT_WIDTH))
    # Dynamic height: current-genus view ~80, genus wrap may grow.
    height = _s(DEFAULT_HEIGHT)
    if organisms and not show_current:
        # Rough wrap estimate
        chips = len(organisms)
        if (
            signals is not None
            and signals.geo_count > 0
            and not gs.hideGeoCountInBioSystem
        ):
            chips += signals.geo_count
        rows_est = max(1, (chips + 3) // 4)
        height = max(height, _s(28) + rows_est * _s(14) + _s(28))

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height)

    # Header
    header = _HEADER.format(bio_n, analyzed)
    draw.text((_s(4), _s(8)), header, font=font_small, fill=ORANGE)

    # Value completion bar (top-right)
    _draw_value_completion(draw, width, bio_n, analyzed, active is not None and show_current)

    stale = (
        active is not None
        and active.body_name
        and body
        and active.body_name != body
    )

    if not organisms:
        # DSS required message centered
        tw = _tw(draw, _DSS_REQUIRED, font_mid)
        draw.text(
            ((width - tw) // 2, _s(16)),
            _DSS_REQUIRED,
            font=font_mid,
            fill=CYAN,
        )
    elif show_current and active is not None:
        _draw_current_genus(draw, width, height, active, ff, font_big, font_small)
    else:
        _draw_all_genus(
            draw,
            width,
            organisms,
            analyzed_set,
            signals.geo_count if signals else 0,
            not gs.hideGeoCountInBioSystem,
            font_small,
        )
        if stale and active is not None:
            warn = _WARN_STALE.format(active.genus, active.body_name)
            tw = _tw(draw, warn, font_small)
            y = height - _s(20)
            draw.text(((width - tw) // 2, y), warn, font=font_small, fill=RED)
            # Warning bars either side (brushShipDismissWarning ≈ orange flash)
            bar_w = max(_s(8), (width - tw - _s(16)) // 2)
            draw.rectangle(
                (_s(4), y, _s(4) + bar_w, y + _s(14)), fill=ORANGE
            )
            draw.rectangle(
                (width - _s(4) - bar_w, y, width - _s(4), y + _s(14)),
                fill=ORANGE,
            )

    # Footer when not mid-scan on this body
    if not show_current:
        all_scanned = analyzed >= bio_n
        if all_scanned and ff:
            footer, colour = _FOOTER_ALL_FF, ORANGE
        elif all_scanned:
            footer, colour = _FOOTER_ALL, ORANGE
        elif ff:
            footer, colour = _FOOTER_APPLY_FF, CYAN
        else:
            # Prefer recent organic Codex footer when available
            codex_footer = _last_organic_codex(survey)
            if codex_footer:
                footer, colour = codex_footer, CYAN
            else:
                footer, colour = _FOOTER_COMP, ORANGE
        if not stale:
            tw = _tw(draw, footer, font_small)
            draw.text(
                ((width - tw) // 2, height - _s(18)),
                footer,
                font=font_small,
                fill=colour,
            )

    return _finish(img)


def _last_organic_codex(survey: SurveyState) -> str | None:
    for find in reversed(survey.codex_entries):
        sub = (find.subcategory or "").lower()
        cat = (find.category or "").lower()
        if "organic" in sub or "biological" in cat or "organic" in cat:
            return find.name
    return None


def _draw_value_completion(
    draw,
    width: int,
    bio_n: int,
    analyzed: int,
    scanning: bool,
) -> None:
    percent = (100.0 / float(bio_n) * float(analyzed)) if bio_n else 0.0
    txt = f" {percent:.0f}%"
    font = _font(TITLE_PX)
    colour = CYAN if percent < 100 else ORANGE
    tw = _tw(draw, txt, font)
    right = width - _s(18)
    draw.text((right - tw, _s(8)), txt, font=font, fill=colour)

    length = _s(100)
    x = right - tw - length - _s(8)
    y = _s(8) + _s(5)
    # known un-scanned track
    draw.line((x, y, x + length, y), fill=CYAN, width=max(2, _s(2)))
    # already scanned orange bar
    fill_w = int(round(length * (percent / 100.0)))
    if fill_w > 0:
        draw.rectangle((x, _s(9), x + fill_w, _s(9) + _s(10)), fill=ORANGE)
    # active scan slice
    if scanning and bio_n > 0:
        slice_w = max(1, length // bio_n)
        draw.rectangle(
            (x + fill_w, _s(10), x + fill_w + slice_w, _s(10) + _s(8)),
            fill=CYAN,
        )


def _draw_current_genus(
    draw,
    width: int,
    _height: int,
    active: OrganicProgress,
    first_footfall: bool,
    font_big,
    font_small,
) -> None:
    y = _s(28)
    r = _s(24)
    # left circle — always filled (scan one / Log done to be here)
    _circle(draw, _s(8), y, r, filled=True)
    # middle — filled after Sample
    _circle(draw, _s(40), y, r, filled=active.scan_type == "Sample")
    # right — always empty (Analyse completes and leaves this view)
    _circle(draw, _s(72), y, r, filled=False)

    txt = active.species or active.genus
    x = _s(104)
    max_w = width - x - _s(40)
    # Shrink until it fits roughly in two lines of the big box
    font = font_big
    for size in (BIG_PX, 16, 14, 12):
        font = _font(size)
        if _tw(draw, txt, font) <= max_w * 2:
            break
    draw.text((x, y - _s(8)), txt, font=font, fill=CYAN)

    # Reward / sample-distance scale need Codex bio tables (Windows organism.reward
    # / range). Until those land, show scan step as a cyan caption.
    step = active.scan_type or "Log"
    caption = f"{step}"
    if first_footfall:
        caption = f"{caption}  {_SUFFIX_FF}"
    draw.text((_s(4), _s(62)), caption, font=font_small, fill=CYAN)


def _circle(draw, x: int, y: int, size: int, *, filled: bool) -> None:
    box = (x, y, x + size, y + size)
    if filled:
        draw.ellipse(box, fill=ORANGE_DIM, outline=ORANGE, width=max(1, _s(1)))
    else:
        draw.ellipse(box, outline=ORANGE, width=max(1, _s(1)))


def _draw_all_genus(
    draw,
    width: int,
    organisms: list[str],
    analyzed_set: set[str],
    geo_count: int,
    show_geo: bool,
    font,
) -> None:
    x0 = _s(24)
    y = _s(22)
    x = x0
    max_x = width - _s(16)
    gap = _s(8)
    row_h = _s(14)

    chips: list[tuple[str, bool]] = [
        (name, name in analyzed_set) for name in organisms
    ]
    if show_geo and geo_count > 0:
        for n in range(1, geo_count + 1):
            chips.append((_GEO_N.format(n), False))

    for txt, done in chips:
        colour = ORANGE if done else CYAN
        tw = _tw(draw, txt, font)
        if x + tw > max_x:
            x = x0
            y += row_h
        draw.text((x, y), txt, font=font, fill=colour)
        if done:
            mid = y + _th(draw, txt, font) // 2
            draw.line(
                (x, mid, x + tw, mid),
                fill=colour,
                width=max(1, SCALE // 2),
            )
        x += tw + gap
