#!/usr/bin/env python3
"""Pillow renderer — 1-1 Linux port of PlotRamTah.

Uses guardian pub ``ao`` + ``ram_tah_decode`` item table (Windows
ActiveObelisk.prepLogItems). Commander decode-progress sets come from
``cmdr_state`` when wired by the host.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
from pathlib import Path

from companion import StatusSnapshot
from game_settings import GameSettings
from guardian_templates import find_pub_for_site
from journal import SurveyState
from plot_guardians import resolve_guardian_site
from ram_tah_decode import (
    group_obelisks_by_msg,
    item_display,
    log_display_name,
)
from theme import cyan, orange, orange_dim

STRIPE = (12, 12, 12, 255)
RED = (255, 60, 40, 255)

TITLE_PX = 9
BODY_PX = 11
PAD = 8
ROW = 14
DEFAULT_WIDTH = 220

_HEADER = "Unscanned Ram Tah logs: {0}"
_NO_NEW = "No new logs available"
_FOOTER = "Set target obelisk with '.to <A01>'"


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
    draw.rectangle((0, 0, w - 1, h - 1), fill=(0, 0, 0, 255))
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


def ram_tah_rows(
    survey: SurveyState,
    *,
    decoded: frozenset[str] | None = None,
    pub_dir=None,
    max_rows: int = 12,
) -> list[tuple[str, list[str], tuple[str, ...]]]:
    """Return (msg, obelisk_names, item_codes) for the current site."""
    site = resolve_guardian_site(survey)
    if site is None:
        return []
    pub = find_pub_for_site(
        site.body_name,
        site.index or (1 if not site.is_ruins else None),
        site.is_ruins,
        pub_dir=pub_dir,
    )
    if pub is None or not pub.active_obelisks:
        # Fall back to journal extra hints only
        return []
    rows = group_obelisks_by_msg(pub.active_obelisks, decoded=decoded)
    return rows[:max_rows]


def ram_tah_log_hints(survey: SurveyState) -> list[str]:
    """Legacy journal extra lines (Ram Tah: …) when pub data missing."""
    hints: list[str] = []
    for site in survey.guardian_sites:
        if site.extra and site.extra.startswith("Ram Tah:"):
            hints.append(f"{site.display_text}: {site.extra}")
    return hints


def ram_tah_allowed(
    game: GameSettings,
    survey: SurveyState,
    status: StatusSnapshot | None,
    cmdr=None,
) -> bool:
    """Match PlotRamTah.allowed as far as Linux state allows.

    Windows requires cmdr.ramTahActive and ruins↔ruins-mission /
    structure↔logs-mission pairing. Without CommanderState we keep the
    prior Linux fallback (enable + site + lat/long).
    """
    if not game.autoShowRamTah:
        return False
    if game.buildProjectsSuppressOtherOverlays:
        return False
    if not game.enableGuardianSites:
        return False
    if status is None or not status.has_lat_long:
        return False
    if survey.current_guardian_site is None and not survey.guardian_sites:
        return False
    if cmdr is not None:
        if not getattr(cmdr, "ram_tah_active", False):
            return False
        site = resolve_guardian_site(survey)
        if site is not None:
            from cmdr_state import TahMissionStatus

            ruins_active = (
                cmdr.decode_the_ruins_mission_active == TahMissionStatus.Active
            )
            logs_active = (
                cmdr.decode_the_logs_mission_active == TahMissionStatus.Active
            )
            if site.is_ruins and not ruins_active:
                return False
            if not site.is_ruins and not logs_active:
                return False
    if status.docked or status.supercruise:
        return False
    if status.on_foot or status.in_srv or status.in_fighter or status.landed:
        return True
    return status.in_main_ship


def _draw_item_dot(draw, x: float, y: float, code: str, col) -> float:
    """Return width consumed. Relic = triangle; others = circle."""
    if code == "re":
        pts = [
            (x + _s(8), y - _s(2)),
            (x + _s(16), y - _s(2)),
            (x + _s(12), y + _s(8)),
        ]
        draw.polygon(pts, fill=col, outline=col)
        return float(_s(24))
    r = _s(5)
    cx = x + r
    cy = y + r // 2
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col, outline=col)
    return float(_s(16))


def render_ram_tah_bitmap(
    survey: SurveyState,
    *,
    game: GameSettings | None = None,
    status: StatusSnapshot | None = None,
    force_show: bool = False,
    max_width: int = DEFAULT_WIDTH,
    decoded: frozenset[str] | None = None,
    pub_dir=None,
    cmdr=None,
) -> tuple[bytes, int, int] | None:
    """Render PlotRamTah. Returns None when not allowed."""
    from PIL import Image, ImageDraw

    gs = game if game is not None else GameSettings()
    if not force_show and not ram_tah_allowed(gs, survey, status, cmdr=cmdr):
        return None

    col = orange(gs)
    dim = orange_dim(gs)
    cy = cyan(gs)

    font_small = _font(TITLE_PX)
    font_body = _font(BODY_PX)

    use_decoded = decoded
    if use_decoded is None and cmdr is not None:
        site = resolve_guardian_site(survey)
        is_ruins = True if site is None else bool(site.is_ruins)
        use_decoded = cmdr.decoded_set(is_ruins=is_ruins)

    rows = ram_tah_rows(survey, decoded=use_decoded, pub_dir=pub_dir)
    hints = ram_tah_log_hints(survey) if not rows else []

    target = None
    if cmdr is not None:
        try:
            from cmdr_state import guardian_site_key

            key = guardian_site_key(resolve_guardian_site(survey))
            if hasattr(cmdr, "guardian_for"):
                g = cmdr.guardian_for(key)
            elif hasattr(cmdr, "guardian"):
                g = cmdr.guardian
            else:
                g = None
            if g is not None:
                target = g.target_obelisk
        except Exception:
            target = None

    # Layout lines as (text, colour, font, optional item codes for dots)
    layout: list[tuple] = [
        (_HEADER.format(len(rows) if rows else len(hints)), col, font_small, None)
    ]
    if rows:
        for msg, names, items in rows:
            item_labels = [item_display(c) for c in items]
            layout.append(
                (log_display_name(msg) + ":", col, font_body, list(zip(items, item_labels)))
            )
            name_line = f"  {', '.join(names)}"
            if target and target in names:
                name_line = f"  ► {', '.join(names)}"
            layout.append((name_line, cy, font_small, None))
        layout.append((_FOOTER, dim, font_small, None))
    elif hints:
        for hint in hints:
            layout.append((hint, col, font_body, None))
        layout.append((_FOOTER, dim, font_small, None))
    else:
        layout.append((_NO_NEW, col, font_body, None))
        site = resolve_guardian_site(survey)
        if site is not None:
            layout.append(
                (f"Site: {site.display_text}", dim, font_small, None)
            )
            layout.append(
                ("(no pub ao / decode rows)", dim, font_small, None)
            )

    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    content_w = max(_tw(probe, t, f) for t, _, f, _ in layout) + _s(36)
    width = max(_s(DEFAULT_WIDTH), min(_s(max(max_width, DEFAULT_WIDTH)), content_w))
    height = _s(12) + len(layout) * _s(ROW) + _s(20)

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height, col)

    y = _s(10)
    for text, colour, font, items in layout:
        x = float(_s(PAD))
        if items:
            # items is list of (code, label)
            draw.text((x, y), text, font=font, fill=colour)
            x += _tw(draw, text, font) + _s(6)
            for i, pair in enumerate(items):
                code, label = pair
                x += _draw_item_dot(draw, x, y, code, colour)
                draw.text((x, y + _s(2)), label, font=font_small, fill=colour)
                x += _tw(draw, label, font_small)
                if i < len(items) - 1:
                    draw.text((x, y + _s(2)), " +", font=font_small, fill=colour)
                    x += _tw(draw, " +", font_small) + _s(2)
        else:
            draw.text((x, y), text, font=font, fill=colour)
        y += _s(ROW)

    used = min(height, y + _s(12))
    if used < height:
        img = img.crop((0, 0, width, used))
        height = used
        draw = ImageDraw.Draw(img)
        for yy, c in (
            (height - _s(5), dim),
            (height - _s(4), col),
            (height - _s(3), dim),
        ):
            draw.line((_s(2), yy, width - _s(4), yy), fill=c)
        draw.rectangle(
            (0, 0, width - 1, height - 1), outline=col, width=max(1, SCALE // 2)
        )

    return _finish(img)
