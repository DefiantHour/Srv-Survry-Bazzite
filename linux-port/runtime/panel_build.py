#!/usr/bin/env python3
"""Pillow renderer — 1-1 Linux port of PlotBuildCommodities.

Faithful to PlotBuildCommodities.cs + GameGraphics + theme.json.
Renders at 2× then LANCZOS-downscales so AA approximates GDI ClearType.
"""

from __future__ import annotations

from hud_scale import AA, SCALE
import math
from pathlib import Path

from colony import BuildListModel, MAP_CARGO_TYPE, cargo_qty, display_name
from companion import (
    GUI_FOCUS_EXTERNAL_PANEL,
    GUI_FOCUS_FSS,
    GUI_FOCUS_GALAXY_MAP,
    GUI_FOCUS_INTERNAL_PANEL,
    GUI_FOCUS_ORRERY,
    GUI_FOCUS_SAA,
    GUI_FOCUS_STATION_SERVICES,
    GUI_FOCUS_SYSTEM_MAP,
    StatusSnapshot,
)
from game_settings import GameSettings
from journal import SurveyState
from theme import cyan as theme_cyan
from theme import orange as theme_orange
from theme import orange_dim as theme_orange_dim

ORANGE = theme_orange()
ORANGE_DARK = theme_orange_dim()
SURPLUS = (0, 255, 0, 255)
SURPLUS_DARK = (0, 139, 0, 255)
DEFICIT = (255, 0, 0, 255)
DEFICIT_DARK = (139, 0, 0, 255)
CYAN = theme_cyan()
ITEM = ORANGE
STRIPE = (12, 12, 12, 255)
PIN_ME = (255, 200, 40, 255)
PIN_OTHER = (160, 160, 160, 255)

# Logical px ≈ gothic sizes that fit the Windows ~245px panel
TITLE_PX = 13
CAT_PX = 11
BODY_PX = 10
PAD = 8
ROW = 14


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


def _measure(font, text: str) -> int:
    from PIL import Image, ImageDraw

    return _tw(ImageDraw.Draw(Image.new("RGBA", (4, 4))), text, font)


def _check(draw, x: int, y: int, color) -> None:
    """Geometric ✓ — URW Gothic has no checkmark glyph."""
    w = max(3, _s(2))
    draw.line(
        [(x + _s(1), y + _s(6)), (x + _s(5), y + _s(10)), (x + _s(13), y + _s(1))],
        fill=color,
        width=w,
    )


def commodity_gathered(
    need: int,
    ship: int,
    fc: int = 0,
    *,
    use_fc: bool = False,
) -> tuple[bool, bool, bool]:
    """Windows shipHasEnough / fcHasEnough / (ship + FC) haveEnough."""
    n = int(need)
    hold = int(ship)
    stock = int(fc) if use_fc else 0
    ship_enough = n > 0 and hold >= n
    fc_enough = use_fc and n > 0 and stock >= n
    have_enough = ship_enough or fc_enough or (n > 0 and hold + stock >= n)
    return ship_enough, fc_enough, have_enough


def _play(draw, x: int, y: int, color) -> int:
    h = _s(8)
    draw.polygon([(x, y + _s(1)), (x + _s(5), y + h // 2), (x, y + h)], fill=color)
    return _s(9)


def _background(draw, w: int, h: int) -> None:
    draw.rectangle((0, 0, w - 1, h - 1), fill=(0, 0, 0, 255))
    step = _s(3)
    for y in range(0, h, step):
        draw.line((0, y, w - 1, y), fill=STRIPE)
    for y, col in ((_s(3), ORANGE_DARK), (_s(4), ORANGE), (_s(5), ORANGE_DARK)):
        draw.line((_s(2), y, w - _s(4), y), fill=col)
    for y, col in (
        (h - _s(5), ORANGE_DARK),
        (h - _s(4), ORANGE),
        (h - _s(3), ORANGE_DARK),
    ):
        draw.line((_s(2), y, w - _s(4), y), fill=col)
    draw.rectangle((0, 0, w - 1, h - 1), outline=ORANGE, width=max(1, SCALE // 2))


def build_commodities_allowed(
    game: GameSettings,
    status: StatusSnapshot | None,
    survey: SurveyState,
    *,
    force_show: bool = False,
    has_projects: bool = False,
) -> bool:
    """PlotBuildCommodities.allowed.

    Shown in station services, docked at a construction site, or the right-hand
    panel when projects exist. Not on every Status.json fuel or lat write.
    """
    if force_show:
        jumping = bool(survey.fsd_jumping) or (
            status is not None and status.fsd_jumping
        )
        external = (
            status is not None and status.gui_focus == GUI_FOCUS_EXTERNAL_PANEL
        )
        return not jumping and not external
    if not game.autoShowPlotBuildCommodities or not game.buildProjects_TEST:
        return False
    jumping = bool(survey.fsd_jumping) or (
        status is not None and status.fsd_jumping
    )
    if jumping:
        return False
    gui = status.gui_focus if status is not None else None
    if gui in (
        GUI_FOCUS_GALAXY_MAP,
        GUI_FOCUS_SYSTEM_MAP,
        GUI_FOCUS_ORRERY,
        GUI_FOCUS_FSS,
        GUI_FOCUS_SAA,
    ):
        return False
    docked = bool(survey.docked) or (status is not None and status.docked)
    supercruise = bool(survey.in_supercruise) or (
        status is not None and status.supercruise
    )
    station_services = gui == GUI_FOCUS_STATION_SERVICES
    from plot_station_info import is_construction_site

    station = survey.docked_station or survey.last_docked_station
    construction = is_construction_site(station)
    dest_construction = is_construction_site(
        status.destination if status is not None else None
    )
    docking_construction = bool(survey.docking_in_progress) and is_construction_site(
        survey.last_docking_station
    )
    last_construction = is_construction_site(survey.last_construction_station)
    if station_services and has_projects:
        return True
    if construction and (docked or station_services):
        return True
    # Locked onto / landing at a construction site — the haul loop lives here.
    if dest_construction or docking_construction:
        return True
    # Active depot after visiting the site: keep the list up at the FC and in SC.
    if has_projects and last_construction and (docked or supercruise):
        return True
    if (
        game.buildProjectsOnRightScreen
        and gui == GUI_FOCUS_INTERNAL_PANEL
        and has_projects
    ):
        return True
    return False


def ship_column_value(ship: int) -> int | None:
    """Windows draws the ship count only when cargoCount > 0 (absolute, not a delta)."""
    if ship <= 0:
        return None
    return int(ship)


def category_should_collapse(
    cat_needs: list[tuple[str, int]],
    fc_cargo: dict[str, int],
    ship_cargo: dict[str, int],
    *,
    collapse_enabled: bool,
    use_fc: bool,
    docked_at_linked_fc: bool = False,
) -> bool:
    """Windows collapseGroup, but keep a lone remaining commodity visible.

    PlotBuildCommodities hides every line in a group when linked FCs cover
    it and the hold is empty. That leaves ``Technology ✓`` with no name when
    the last Need is a single item (Computer Components 8).
    """
    if not collapse_enabled or not use_fc or docked_at_linked_fc:
        return False
    if len(cat_needs) < 2:
        return False
    return all(
        cargo_qty(fc_cargo, k) >= n and cargo_qty(ship_cargo, k) == 0
        for k, n in cat_needs
    )


def fc_column_value(need: int, fc_amount: int, *, show_delta: bool) -> tuple[str, int]:
    """Windows FC column: absolute linked-FC tons, or FC − need when delta is on."""
    if show_delta:
        return ("delta", int(fc_amount) - int(need))
    return ("abs", int(fc_amount))


def trips_needed(sum_need: int, cargo_capacity: int) -> int:
    """Windows: ceil(remaining / this ship's cargoCapacity). Hold cargo is not subtracted."""
    if cargo_capacity <= 0 or sum_need <= 0:
        return 0
    return int(math.ceil(float(sum_need) / float(cargo_capacity)))


def render_build_commodities_bitmap(
    model: BuildListModel,
    *,
    max_width: int = 250,
    show_fc: bool = True,
    show_fc_delta: bool = True,
    collapse_when_fc_enough: bool = True,
    inline_fc: bool = False,
    highlight_almost_fc: bool = False,
    game: GameSettings | None = None,
) -> tuple[bytes, int, int]:
    global ORANGE, ORANGE_DARK, CYAN, ITEM
    saved = (ORANGE, ORANGE_DARK, CYAN, ITEM)
    ORANGE = theme_orange(game)
    ORANGE_DARK = theme_orange_dim(game)
    CYAN = theme_cyan(game)
    ITEM = ORANGE
    try:
        return _render_build_commodities_bitmap(
            model,
            max_width=max_width,
            show_fc=show_fc,
            show_fc_delta=show_fc_delta,
            collapse_when_fc_enough=collapse_when_fc_enough,
            inline_fc=inline_fc,
            highlight_almost_fc=highlight_almost_fc,
        )
    finally:
        ORANGE, ORANGE_DARK, CYAN, ITEM = saved


def _render_build_commodities_bitmap(
    model: BuildListModel,
    *,
    max_width: int = 250,
    show_fc: bool = True,
    show_fc_delta: bool = True,
    collapse_when_fc_enough: bool = True,
    inline_fc: bool = False,
    highlight_almost_fc: bool = False,
) -> tuple[bytes, int, int]:
    from PIL import Image, ImageDraw

    font_title = _font(TITLE_PX, bold=True)
    font_cat = _font(CAT_PX)
    font_body = _font(BODY_PX)

    depot = model.depot
    if depot is None:
        lines = [("Colonisation", ORANGE), ("No construction depot yet", ORANGE_DARK)]
        if model.warning:
            lines.append((f"◬ {model.warning}", CYAN))
        return _finish(_simple(lines, font_title, font_body))
    if depot.complete:
        return _finish(
            _simple(
                [(depot.title, ORANGE), ("✓ Construction complete ✓", SURPLUS)],
                font_title,
                font_body,
            )
        )

    need_map = depot.need_map()
    use_fc = show_fc and model.has_fc_column
    # Inline FC folds ship+FC into the Have column (Windows buildProjectsInlineSumFC).
    if inline_fc and use_fc:
        show_fc_delta = True
    have_any_cargo = any(int(v) > 0 for v in model.ship_cargo.values())
    if inline_fc and use_fc:
        have_any_cargo = have_any_cargo or bool(model.fc_cargo)
    show_fc_col = use_fc and not inline_fc
    show_ship_col = have_any_cargo
    if inline_fc and use_fc:
        show_fc_col = False
        show_ship_col = True
    big_w = max(_measure(font_body, "123,456"), _measure(font_body, "Need"))
    fc_label = ""
    if show_fc_col:
        fc_label = f"{model.fc_count} FCs" if model.fc_count else "FC"
    ship_label = ""
    if show_ship_col:
        ship_label = "Have" if inline_fc and use_fc else "Ship"
    col_w = max(big_w, _measure(font_body, fc_label or "Ship"), _measure(font_body, "+9,999"))
    extra_cols = int(show_fc_col) + int(show_ship_col)

    name_w = _measure(font_body, "Commodity")
    for n in depot.needs:
        if n.need > 0:
            name_w = max(name_w, _measure(font_body, n.label))
    for cat in MAP_CARGO_TYPE:
        name_w = max(name_w, _measure(font_cat, cat))

    foot = (
        _play_w()
        + _measure(font_body, "9,641 remaining")
        + _s(8)
        + _play_w()
        + _measure(font_body, "8 trips in this ship")
    )
    content = max(
        _measure(font_title, model.header),
        foot,
        _s(20) + name_w + _s(8) + big_w + extra_cols * col_w,
    )
    fit_width = max(max_width, 250 + extra_cols * 36)
    width = max(_s(245), min(_s(fit_width), content + _s(18)))
    width = max(width, _s(245))
    if width > _s(fit_width):
        width = _s(fit_width)

    x_ship = width - _s(8)
    x_fc = x_ship - col_w if show_ship_col else x_ship
    x_need = (x_fc if show_fc_col else x_ship) - col_w if (show_fc_col or show_ship_col) else x_ship
    x_name = _s(20)
    pad = _s(PAD)
    row_h = _s(ROW)

    rows: list[tuple] = []
    rows.append(("title", model.header))
    rows.append(("gap", _s(4)))
    if model.warning:
        rows.append(("warn", model.warning))
        rows.append(("gap", _s(2)))
    rows.append(("head", "Commodity", "Need", fc_label, ship_label))

    sum_need = 0
    fc_covered = 0
    stock = model.fc_cargo if use_fc else model.ship_cargo

    def emit_item(k: str, n: int) -> None:
        nonlocal sum_need, fc_covered
        sum_need += n
        label = next((d.label for d in depot.needs if d.key == k), display_name(k))
        ship = cargo_qty(model.ship_cargo, k)
        fc_amt = cargo_qty(model.fc_cargo, k) if use_fc else 0
        fc_covered += min(n, fc_amt if use_fc else ship)
        if k in model.assigned_me:
            label = f"● {label}"
        elif k in model.assigned_others:
            label = f"○ {label}"

        ship_enough, fc_enough, have_enough = commodity_gathered(
            n, ship, fc_amt, use_fc=use_fc
        )
        col = SURPLUS if have_enough else ITEM
        if ship > n:
            label = f"{label} ◬"
        if (
            highlight_almost_fc
            and use_fc
            and not fc_enough
            and fc_amt > 0
            and fc_amt >= int(n * 0.85)
        ):
            col = CYAN

        fc_mode: str | None = None
        fc_val = 0
        ship_val: int | None = None
        fc_col = DEFICIT_DARK
        if inline_fc and use_fc:
            have = ship + fc_amt
            fc_mode, fc_val = "delta", have - n
            ship_val = None
            fc_col = SURPLUS if have >= n else DEFICIT
        else:
            if show_fc_col:
                fc_mode, fc_val = fc_column_value(n, fc_amt, show_delta=show_fc_delta)
                if show_fc_delta:
                    fc_col = SURPLUS if fc_val >= 0 else DEFICIT
                elif fc_enough:
                    fc_col = SURPLUS
                elif fc_amt == 0:
                    fc_col = DEFICIT_DARK
                else:
                    fc_col = DEFICIT
            if show_ship_col:
                ship_val = ship_column_value(ship)
        rows.append(
            (
                "item",
                label,
                n,
                fc_mode,
                fc_val,
                ship_val,
                col,
                have_enough,
                ship_enough,
                fc_col,
            )
        )

    if model.sort_alpha:
        for k, n in sorted(
            ((k, need_map[k]) for k in need_map if need_map[k] > 0),
            key=lambda p: display_name(p[0]).lower(),
        ):
            emit_item(k, n)
    else:
        for cat, keys in MAP_CARGO_TYPE.items():
            cat_needs = [(k, need_map[k]) for k in keys if need_map.get(k, 0) > 0]
            if not cat_needs:
                continue
            collapse = category_should_collapse(
                cat_needs,
                model.fc_cargo if use_fc else {},
                model.ship_cargo,
                collapse_enabled=collapse_when_fc_enough,
                use_fc=use_fc,
            )
            if collapse:
                rows.append(
                    ("cat_done", cat, sum(n for _, n in cat_needs))
                )
                for k, n in cat_needs:
                    sum_need += n
                    fc_covered += min(n, cargo_qty(stock, k))
                continue
            rows.append(("cat", cat))
            for k, n in cat_needs:
                emit_item(k, n)

    trips = trips_needed(sum_need, int(model.cargo_capacity or 0))
    fc_deficit = max(0, sum_need - fc_covered)
    fc_trips = trips_needed(fc_deficit, int(model.cargo_capacity or 0))

    rows.append(("gap", _s(8)))
    rows.append(("footer", sum_need, trips))
    if use_fc:
        rows.append(("gap", _s(3)))
        rows.append(("fcfooter", model.fc_count, fc_deficit, fc_trips))
    if model.pending_updates > 0:
        rows.append(("gap", _s(6)))
        rows.append(("pending",))
    if model.build_id:
        rows.append(("gap", _s(3)))
        rows.append(("id", model.build_id))
    if model.assigned_me or model.assigned_others:
        rows.append(("gap", _s(8)))
        rows.append(("assigned",))

    height = _s(10) + sum(
        row_h
        if r[0] not in ("gap", "title", "warn")
        else (
            r[1]
            if r[0] == "gap"
            else (_s(TITLE_PX + 3) if r[0] == "title" else row_h)
        )
        for r in rows
    ) + _s(12)

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height)

    y = _s(10)
    flip = False
    for row in rows:
        kind = row[0]
        if kind == "gap":
            y += int(row[1])
            continue
        if kind == "title":
            draw.text((pad, y), row[1], font=font_title, fill=ORANGE)
            y += _s(TITLE_PX + 3)
            continue
        if kind == "warn":
            draw.text((pad, y), f"◬ {row[1]}", font=font_body, fill=CYAN)
            y += row_h
            continue
        if kind == "head":
            draw.text((x_name, y), row[1], font=font_body, fill=ORANGE_DARK)
            tw = _tw(draw, row[2], font_body)
            draw.text((x_need - tw, y), row[2], font=font_body, fill=ORANGE_DARK)
            if row[3]:
                tw = _tw(draw, row[3], font_body)
                draw.text((x_fc - tw, y), row[3], font=font_body, fill=ORANGE_DARK)
            if row[4]:
                tw = _tw(draw, row[4], font_body)
                draw.text((x_ship - tw, y), row[4], font=font_body, fill=ORANGE_DARK)
            y += row_h
            continue
        if kind == "cat":
            draw.text((pad, y), row[1], font=font_cat, fill=ORANGE_DARK)
            tw = _tw(draw, row[1], font_cat)
            ly = y + _th(draw, row[1], font_cat) // 2
            draw.line((tw + pad + _s(6), ly, width - _s(4), ly), fill=ORANGE_DARK, width=_s(2))
            y += row_h
            flip = True
            continue
        if kind == "cat_done":
            draw.text((pad, y), row[1], font=font_cat, fill=SURPLUS_DARK)
            tw = _tw(draw, row[1], font_cat)
            _check(draw, tw + pad + _s(4), y + _s(1), SURPLUS_DARK)
            if len(row) > 2 and int(row[2]) > 0:
                need_txt = f"{int(row[2]):,}"
                ntw = _tw(draw, need_txt, font_body)
                draw.text((x_need - ntw, y), need_txt, font=font_body, fill=SURPLUS_DARK)
            ly = y + _th(draw, row[1], font_cat) // 2
            line_left = tw + pad + _s(20)
            line_right = (x_need - _s(8)) if (show_fc_col or show_ship_col) else width - _s(4)
            if line_right > line_left:
                draw.line((line_left, ly, line_right, ly), fill=ORANGE_DARK, width=_s(2))
            y += row_h
            continue
        if kind == "item":
            (
                _,
                label,
                need,
                fc_mode,
                fc_val,
                ship_val,
                col,
                have_enough,
                ship_enough,
                fc_col,
            ) = row
            if flip:
                draw.rectangle(
                    (_s(4), y - _s(1), width - _s(5), y + row_h - _s(1)),
                    fill=STRIPE,
                )
            flip = not flip
            if have_enough:
                _check(draw, _s(4), y + _s(1), SURPLUS if ship_enough else SURPLUS_DARK)
            draw.text((x_name, y), label, font=font_body, fill=col)
            need_txt = f"{need:,}"
            tw = _tw(draw, need_txt, font_body)
            draw.text((x_need - tw, y), need_txt, font=font_body, fill=col)

            def _draw_num(x: int, mode: str, val: int, ink) -> None:
                if mode == "delta":
                    if val > 0:
                        dtxt = f"+{val:,}"
                    elif val < 0:
                        dtxt = f"{val:,}"
                    else:
                        dtxt = "0"
                else:
                    dtxt = f"{val:,}"
                tw = _tw(draw, dtxt, font_body)
                draw.text((x - tw, y), dtxt, font=font_body, fill=ink)

            if fc_mode:
                _draw_num(
                    x_ship if inline_fc and use_fc else x_fc,
                    fc_mode,
                    int(fc_val),
                    fc_col,
                )
            if ship_val is not None:
                _draw_num(x_ship, "abs", int(ship_val), col)
            y += row_h
            continue
        if kind == "footer":
            _, sum_n, trip_n = row
            x = pad
            x += _play(draw, x, y + _s(1), ORANGE)
            t1 = f"{sum_n:,} remaining"
            draw.text((x, y), t1, font=font_body, fill=ORANGE)
            if trip_n:
                x += _tw(draw, t1, font_body) + _s(8)
                x += _play(draw, x, y + _s(1), ORANGE)
                draw.text((x, y), f"{trip_n:,} trips in this ship", font=font_body, fill=ORANGE)
            y += row_h
            continue
        if kind == "fcfooter":
            _, fc_n, deficit, trip_n = row
            x = pad
            x += _play(draw, x, y + _s(1), ORANGE)
            t1 = f"{fc_n} FCs: {deficit:,} deficit"
            draw.text((x, y), t1, font=font_body, fill=ORANGE)
            if trip_n:
                x += _tw(draw, t1, font_body) + _s(8)
                x += _play(draw, x, y + _s(1), ORANGE)
                draw.text((x, y), f"{trip_n:,} trips", font=font_body, fill=ORANGE)
            y += row_h
            continue
        if kind == "pending":
            x = pad
            x += _play(draw, x, y + _s(1), CYAN)
            draw.text((x, y), "Updating...", font=font_title, fill=CYAN)
            y += row_h
            continue
        if kind == "assigned":
            draw.text(
                (pad, y),
                "◬ Assigned commodities",
                font=font_body,
                fill=ORANGE_DARK,
            )
            y += row_h
            continue
        if kind == "id":
            draw.text((pad, y), row[1], font=font_body, fill=ORANGE_DARK)
            y += row_h
            continue

    used = min(height, y + _s(10))
    if used < height:
        img = img.crop((0, 0, width, used))
        height = used
        draw = ImageDraw.Draw(img)
        for yy, col in (
            (height - _s(5), ORANGE_DARK),
            (height - _s(4), ORANGE),
            (height - _s(3), ORANGE_DARK),
        ):
            draw.line((_s(2), yy, width - _s(4), yy), fill=col)
        draw.rectangle((0, 0, width - 1, height - 1), outline=ORANGE, width=max(1, SCALE // 2))

    return _finish(img)


def _play_w() -> int:
    return _s(9)


def _finish(img):
    from PIL import Image

    if SCALE != 1:
        w, h = img.size
        img = img.resize((w // AA, h // AA), Image.Resampling.LANCZOS)
    w, h = img.size
    return img.tobytes("raw", "RGBA"), w, h


def _simple(lines, font_title, font_body):
    from PIL import Image, ImageDraw

    width = _s(245)
    height = _s(16) + len(lines) * _s(ROW + 4) + _s(16)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _background(draw, width, height)
    y = _s(10)
    for i, (text, color) in enumerate(lines):
        draw.text((_s(PAD), y), text, font=font_title if i == 0 else font_body, fill=color)
        y += _s(ROW + 4)
    return img
