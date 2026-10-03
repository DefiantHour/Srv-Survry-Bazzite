"""Pillow renderer — 1-1 Linux port of PlotFSSInfo.

Faithful to PlotFSSInfo.cs + GameColors (orange / cyan / gothic stand-in).
Renders at 2× then LANCZOS-downscales so AA approximates GDI ClearType.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
from pathlib import Path

from body_value import format_credits
from companion import StatusSnapshot
from game_settings import GameSettings
from journal import FssBodyEntry, SurveyState

# GameColors defaults
ORANGE = (255, 111, 0, 255)
ORANGE_DIM = (95, 48, 3, 255)
CYAN = (84, 223, 237, 255)
STRIPE = (12, 12, 12, 255)

# Status GuiFocus values matching GameMode
_GUI_FSS = 9
_GUI_SYSTEM_MAP = 7
_GUI_EXTERNAL_PANEL = 2

TITLE_PX = 12  # gothic_12B
BODY_PX = 9  # fontSmall2
PAD = 8
ROW = 14
DEFAULT_WIDTH = 300

# Linux-safe footer (Windows uses emoji)
_FOOTER1 = "Scan value | DSS value"
_FOOTER2 = "(T) Terraformable\n(L) Landable * Undiscovered"
_SCAN_TO_POPULATE = "(scan to populate)"


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


def fss_info_allowed(
    game: GameSettings,
    status: StatusSnapshot | None,
    *,
    force_show: bool = False,
) -> bool:
    """Match PlotFSSInfo.allowed (minus Guardian-system collision)."""
    if not game.autoShowPlotFSSInfo:
        return False
    if force_show:
        return True
    gui = status.gui_focus if status is not None else None
    if gui == _GUI_FSS:
        return True
    if gui == _GUI_SYSTEM_MAP and game.autoShowPlotFSSInfoInSystemMap:
        return True
    if gui == _GUI_EXTERNAL_PANEL and game.autoShowPlotFSSInfoInNavPanel:
        return True
    return False


def _is_interesting(body: FssBodyEntry) -> bool:
    if body.terraformable:
        return True
    pc = body.planet_class or ""
    return (
        pc.startswith("Water ")
        or pc.startswith("Ammonia ")
        or pc.startswith("Earthlike ")
    )


def _should_show_body(body: FssBodyEntry, game: GameSettings) -> bool:
    if body.body_type == "Asteroid":
        return False
    if "Belt Cluster" in body.body_name:
        return False
    if _is_interesting(body):
        return True
    if body.bio_signal_count > 0:
        return True
    if body.geo_signal_count > 0 and not game.hideGeoCountInFssInfo:
        return True
    threshold = game.hideFssLowValueAmount
    return max(body.reward, body.dss_reward) >= threshold


def _dss_worthy(body: FssBodyEntry, game: GameSettings) -> bool:
    if body.body_type == "Star":
        return False
    if not game.skipLowValueDSS:
        return False
    if body.dss_reward <= game.skipLowValueAmount:
        return False
    if (
        game.skipHighDistanceDSS
        and body.distance_from_arrival_ls > game.skipHighDistanceDSSValue
    ):
        return False
    if game.skipGasGiantDSS and body.body_type == "Giant":
        return False
    return True


def _body_title_line(body: FssBodyEntry) -> str:
    prefix = "" if body.was_discovered else "* "
    if body.body_type == "Star":
        star = body.star_type or "?"
        return f"{prefix}{body.short_name} - {star} Star"
    planet = (body.planet_class or "?").replace("Sudarsky c", "C")
    txt = f"{prefix}{body.short_name} - {planet}"
    suffixes: list[str] = []
    if body.terraformable or (body.planet_class or "").startswith("Earth"):
        suffixes.append("(T)")
    if body.body_type == "LandableBody":
        suffixes.append("(L)")
    if body.first_footfall:
        suffixes.append("(ff)")
    if suffixes:
        txt += " " + " ".join(suffixes)
    return txt


def visible_fss_bodies(
    survey: SurveyState,
    game: GameSettings | None = None,
) -> list[FssBodyEntry]:
    """Bodies that pass PlotFSSInfo filter, newest first."""
    gs = game if game is not None else GameSettings()
    return [b for b in survey.fss_bodies if _should_show_body(b, gs)]


def fss_info_lines(
    survey: SurveyState,
    game: GameSettings | None = None,
) -> list[tuple[str, tuple[int, int, int, int], bool]]:
    """Pure layout rows: (text, colour, strike). Unit-testable."""
    gs = game if game is not None else GameSettings()
    rows: list[tuple[str, tuple[int, int, int, int], bool]] = []

    system = survey.system or "Unknown system"
    main = next((b for b in survey.fss_bodies if b.is_main_star), None)
    undiscovered = main is not None and not main.was_discovered
    title = f"* {system}" if undiscovered else system
    if survey.fss_complete:
        title += " ✓"
    rows.append((title, CYAN if undiscovered else ORANGE, False))

    body_count = sum(
        1 for b in survey.fss_bodies if b.body_type != "Asteroid" and b.scanned
    )
    if body_count == 0:
        body_count = survey.scanned_count
    total = sum(b.reward for b in survey.fss_bodies)
    credits = format_credits(total)
    if survey.fss_complete:
        rows.append((f"Scanned all {body_count} bodies: {credits}", ORANGE, False))
    else:
        rows.append((f"Scanned {body_count} bodies: {credits}", ORANGE, False))

    hide = format_credits(gs.hideFssLowValueAmount)
    rows.append((f"( Hiding bodies < {hide} )", ORANGE_DIM, False))

    shown = visible_fss_bodies(survey, gs)
    if not shown:
        rows.append((_SCAN_TO_POPULATE, ORANGE, False))

    for body in shown:
        dss_ok = _dss_worthy(body, gs)
        highlight = dss_ok or body.bio_signal_count > 0
        rows.append((_body_title_line(body), CYAN if highlight else ORANGE, False))

        reward_txt = ("✓ " if body.dss_complete else "") + format_credits(
            body.reward, hide_units=True
        )
        parts: list[tuple[str, tuple[int, int, int, int], bool]] = [
            (reward_txt, CYAN if dss_ok else ORANGE, False)
        ]
        if body.body_type != "Star" and not body.dss_complete:
            parts.append((" | ", ORANGE_DIM, False))
            parts.append((f"{body.dss_reward:,}", CYAN if dss_ok else ORANGE, False))
        if body.bio_signal_count > 0:
            parts.append((" | ", ORANGE_DIM, False))
            analyzed = body.analyzed_bio_count >= body.bio_signal_count
            parts.append(
                (
                    f"{body.bio_signal_count} Genus",
                    ORANGE if analyzed else CYAN,
                    analyzed,
                )
            )
        if not gs.hideGeoCountInFssInfo and body.geo_signal_count > 0:
            parts.append((" | ", ORANGE_DIM, False))
            analyzed_geo = body.geo_analyzed
            parts.append(
                (
                    f"{body.geo_signal_count} Geo",
                    ORANGE if analyzed_geo else CYAN,
                    analyzed_geo,
                )
            )
        # Flatten value line as a single joined row for the line-list API;
        # bitmap renderer draws segments for strikethrough fidelity.
        joined = "".join(p[0] for p in parts)
        strike = any(p[2] for p in parts)
        colour = CYAN if dss_ok or body.bio_signal_count > 0 else ORANGE
        rows.append((joined, colour, strike))
        # Keep segment metadata on a private attribute via trailing special rows — skip;
        # bitmap uses bodies directly.

    rows.append((_FOOTER1, ORANGE_DIM, False))
    for line in _FOOTER2.splitlines():
        rows.append((line, ORANGE_DIM, False))
    return rows


def render_fss_info_bitmap(
    survey: SurveyState,
    *,
    game: GameSettings | None = None,
    status: StatusSnapshot | None = None,
    force_show: bool = False,
    max_width: int = DEFAULT_WIDTH,
) -> tuple[bytes, int, int] | None:
    """Render PlotFSSInfo. Returns None when not allowed / nothing to show."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    if not fss_info_allowed(gs, status, force_show=force_show):
        return None
    if not survey.system:
        return None

    font_title = _font(TITLE_PX, bold=True)
    font_body = _font(BODY_PX)

    shown = visible_fss_bodies(survey, gs)

    # Measure width from content
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    samples = [
        survey.system or "",
        _FOOTER1,
        "( Hiding bodies < 10 K CR )",
        _SCAN_TO_POPULATE,
    ]
    for body in shown[:12]:
        samples.append(_body_title_line(body))
        samples.append(f"✓ {format_credits(body.reward, hide_units=True)} | {body.dss_reward:,} | {body.bio_signal_count} Genus")
    content_w = max(_tw(probe, t, font_body) for t in samples if t)
    content_w = max(content_w, _tw(probe, survey.system or "?", font_title))
    width = max(_s(DEFAULT_WIDTH), min(_s(max_width), content_w + _s(18)))
    if width > _s(max_width):
        width = _s(max_width)

    # Build draw list
    draw_ops: list[tuple] = []
    system = survey.system or "Unknown system"
    main = next((b for b in survey.fss_bodies if b.is_main_star), None)
    undiscovered = main is not None and not main.was_discovered
    title = f"* {system}" if undiscovered else system
    if survey.fss_complete:
        title += " ✓"
    draw_ops.append(("title", title, CYAN if undiscovered else ORANGE))
    draw_ops.append(("gap", _s(8)))

    body_count = sum(
        1 for b in survey.fss_bodies if b.body_type != "Asteroid" and b.scanned
    )
    if body_count == 0:
        body_count = survey.scanned_count
    total = sum(b.reward for b in survey.fss_bodies)
    credits = format_credits(total)
    if survey.fss_complete:
        summary = f"Scanned all {body_count} bodies: {credits}"
    else:
        summary = f"Scanned {body_count} bodies: {credits}"
    draw_ops.append(("text", _s(8), summary, ORANGE, font_body, False))
    hide = format_credits(gs.hideFssLowValueAmount)
    draw_ops.append(
        ("text", _s(8), f"( Hiding bodies < {hide} )", ORANGE_DIM, font_body, False)
    )
    draw_ops.append(("gap", _s(8)))

    if not shown:
        draw_ops.append(("text", _s(8), _SCAN_TO_POPULATE, ORANGE, font_body, False))

    for body in shown:
        dss_ok = _dss_worthy(body, gs)
        highlight = dss_ok or body.bio_signal_count > 0
        draw_ops.append(
            (
                "text",
                _s(16),
                _body_title_line(body),
                CYAN if highlight else ORANGE,
                font_body,
                False,
            )
        )
        segs: list[tuple[str, tuple[int, int, int, int], bool]] = []
        reward_txt = ("✓ " if body.dss_complete else "") + format_credits(
            body.reward, hide_units=True
        )
        segs.append((reward_txt, CYAN if dss_ok else ORANGE, False))
        if body.body_type != "Star" and not body.dss_complete:
            segs.append((" | ", ORANGE_DIM, False))
            segs.append((f"{body.dss_reward:,}", CYAN if dss_ok else ORANGE, False))
        if body.bio_signal_count > 0:
            segs.append((" | ", ORANGE_DIM, False))
            analyzed = body.analyzed_bio_count >= body.bio_signal_count
            segs.append(
                (f"{body.bio_signal_count} Genus", ORANGE if analyzed else CYAN, analyzed)
            )
        if not gs.hideGeoCountInFssInfo and body.geo_signal_count > 0:
            segs.append((" | ", ORANGE_DIM, False))
            segs.append(
                (
                    f"{body.geo_signal_count} Geo",
                    ORANGE if body.geo_analyzed else CYAN,
                    body.geo_analyzed,
                )
            )
        draw_ops.append(("segs", _s(30), segs, font_body))
        draw_ops.append(("gap", _s(4)))

    draw_ops.append(("text", _s(8), _FOOTER1, ORANGE_DIM, font_body, False))
    for line in _FOOTER2.splitlines():
        draw_ops.append(("text", _s(8), line, ORANGE_DIM, font_body, False))

    # Estimate height
    height = _s(12)
    for op in draw_ops:
        kind = op[0]
        if kind == "gap":
            height += int(op[1])
        elif kind == "title":
            height += _s(TITLE_PX + 4)
        else:
            height += _s(ROW)
    height += _s(10)

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height)

    y = _s(10)
    for op in draw_ops:
        kind = op[0]
        if kind == "gap":
            y += int(op[1])
            continue
        if kind == "title":
            draw.text((_s(PAD), y), op[1], font=font_title, fill=op[2])
            y += _s(TITLE_PX + 4)
            continue
        if kind == "text":
            _, x, text, colour, font, strike = op
            draw.text((x, y), text, font=font, fill=colour)
            if strike:
                tw = _tw(draw, text, font)
                mid = y + _th(draw, text, font) // 2
                draw.line((x, mid, x + tw, mid), fill=colour, width=max(1, SCALE // 2))
            y += _s(ROW)
            continue
        if kind == "segs":
            _, x, segs, font = op
            cx = x
            for text, colour, strike in segs:
                draw.text((cx, y), text, font=font, fill=colour)
                tw = _tw(draw, text, font)
                if strike:
                    mid = y + _th(draw, text, font) // 2
                    draw.line(
                        (cx, mid, cx + tw, mid), fill=colour, width=max(1, SCALE // 2)
                    )
                cx += tw
            y += _s(ROW)
            continue

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
            (0, 0, width - 1, height - 1), outline=ORANGE, width=max(1, SCALE // 2)
        )

    return _finish(img)
