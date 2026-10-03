#!/usr/bin/env python3
"""PlotVerticalStripe — center alignment grid for Guardian ruins.

Windows draws this as its own topmost window, centered on the game, when
heading mode or aerial mode is active. The red WinForms color key is fully
transparent here. Opacity follows the Windows altitude fade.
"""

from __future__ import annotations

from typing import Any

_AERIAL_ALTITUDE = {
    "alpha": "aerial",
    "beta": "aerial",
    "gamma": "aerial",
    "bear": 650.0,
    "bowl": 650.0,
    "crossroads": 650.0,
    "fistbump": 450.0,
    "hammerbot": 650.0,
    "lacrosse": 650.0,
    "robolobster": 1000.0,
    "squid": 650.0,
    "stickyhand": 650.0,
    "turtle": 650.0,
}


def stripe_opacity(*, landed: bool, mode: str, altitude: float | None, target: float) -> float:
    """Windows PlotVerticalStripe.getOpacity."""
    if landed:
        return 0.0
    if mode == "relictower":
        return 0.8
    alt = max(0.0, float(altitude or 0.0))
    delta = abs(alt - float(target))
    if delta > 220:
        return 0.0
    if delta < 20:
        return 0.8
    return (220.0 - delta) / 200.0


def select_stripe(
    *,
    mode: str,
    site_type: str | None,
    disable_ruins_grid: bool,
    disable_aerial_grid: bool,
    in_srv: bool,
    on_foot: bool,
    landed: bool,
    aerial_alpha: float,
    aerial_beta: float,
    aerial_gamma: float,
) -> tuple[str, float] | None:
    """Which grid to show, or None when Windows would close the plotter."""
    if landed:
        return None
    survey = (mode or "").strip().lower()
    if survey == "heading":
        if disable_ruins_grid:
            return None
        return ("buttress", 20.0)
    if survey != "aerial" or disable_aerial_grid or in_srv:
        return None
    if on_foot:
        return ("relictower", 0.0)
    key = (site_type or "").strip().lower()
    if key == "alpha":
        return ("alpha", float(aerial_alpha))
    if key == "beta":
        return ("beta", float(aerial_beta))
    if key == "gamma":
        return ("gamma", float(aerial_gamma))
    fixed = _AERIAL_ALTITUDE.get(key)
    if isinstance(fixed, float):
        return (key, fixed)
    return None


def _ink(opacity: float) -> tuple[int, int, int, int]:
    return (255, 214, 0, max(1, min(255, int(round(255 * opacity)))))


def _dash(opacity: float) -> tuple[int, int, int, int]:
    return (0, 0, 0, max(1, min(255, int(round(180 * opacity)))))


def _line(draw: Any, color: tuple[int, int, int, int], dash: tuple[int, int, int, int], box: tuple[float, float, float, float]) -> None:
    x1, y1, x2, y2 = box
    draw.line((x1, y1, x2, y2), fill=color, width=4)
    draw.line((x1, y1, x2, y2), fill=dash, width=2)


def _circle(draw: Any, color: tuple[int, int, int, int], dash: tuple[int, int, int, int], x: float, y: float, radius: float) -> None:
    rect = (x - radius, y - radius, x + radius, y + radius)
    draw.ellipse(rect, outline=color, width=4)
    draw.ellipse(rect, outline=dash, width=2)


def _paint(draw: Any, mode: str, width: int, height: int, game_width: int, game_height: int, opacity: float) -> None:
    color = _ink(opacity)
    dash = _dash(opacity)
    mw = width / 2
    mh = height / 2
    eh = game_height * 0.01
    ex = game_width * 0.01

    def line(x1: float, y1: float, x2: float, y2: float) -> None:
        _line(draw, color, dash, (x1, y1, x2, y2))

    def circle(x: float, y: float, radius: float) -> None:
        _circle(draw, color, dash, x, y, radius)

    if mode == "alpha":
        y = mh - (mh * 0.05)
        circle(mw, y, mh * 0.10)
        circle(mw, y, mh * 0.22)
        circle(mw, y, mh * 0.30)
        depth = mh * 0.20
        y += depth * 0.8
        line(mw + depth, y, width - 5, y)
    elif mode == "beta":
        y = height * 0.33
        circle(mw, y, 50)
        y += eh * 2
        line(10, y, mw - 140, y)
        line(mw + 140, y, width - 10, y)
        y += 20
        line(mw, y, mw, y + 240)
    elif mode == "relictower":
        depth = eh * 1.5
        x = mw - depth
        y = mh - eh * 4
        line(x, y, x - eh, y)
        line(x, y + 100, x, y + 100 + eh * 20)
        x = mw + depth
        line(x, y, x + eh, y)
        line(x, y + 100, x, y + 100 + eh * 20)
    elif mode == "gamma":
        x = mw * 1.4
        y = mh * 0.535
        circle(x, y, 30)
        line(x - 30, y, x - mw * 0.50, y)
        line(x + 22, y - 4, x + 30, y - 4)
        line(x, y + 30, x, y + 50)
        line(x - 19, y + 25, x - 30, y + 42)
        line(x - 26, y + 12, x - 45, y + 25)
    elif mode == "buttress":
        span = mh * 0.8
        line(mw, mh, mw, mh + span)
        line(mw - 40, mh + 40, mw - 40, mh + 220)
        line(mw + 40, mh + 40, mw + 40, mh + 220)
        line(mw - 70, mh + 60, mw - 70, mh + 200)
        line(mw + 70, mh + 60, mw + 70, mh + 200)
        line(mw - 70, mh + 80, mw + 70, mh + 80)
        line(mw - 120, mh + 130, mw + 120, mh + 130)
        line(mw - 70, mh + 180, mw + 70, mh + 180)
    elif mode == "robolobster":
        x = mw
        y = mh - eh * 4
        circle(x, y, 80)
        circle(x, y, 120)
        line(x, 200, x, y + 200)
    elif mode == "hammerbot":
        line(mw - ex, mh - 10, mw + ex, mh - 10)
        line(mw - 6 * ex, mh + 10, mw - 4 * ex, mh + 10)
        line(mw + 6 * ex, mh + 10, mw + 4 * ex, mh + 10)
        line(mw, mh + 100, mw, mh + 400)
        ex2 = game_width * 0.007
        ey = game_height * 0.03
        line(mw - ex - ex2, mh + ey, mw - ex, mh + ey + ey)
        line(mw + ex + ex2, mh + ey, mw + ex, mh + ey + ey)
    elif mode == "bowl":
        ey = game_height * 0.1
        line(100, mh - ey, width - 100, mh - ey)
        line(mw, 200, mw, height - 100)
        ee = height / 7
        circle(mw, mh + ee, ee)
        circle(mw, mh + ee, ee * 1.3)
    elif mode == "fistbump":
        ey = game_height * 0.1
        line(mw - 100, mh - ey - 100, mw + 100, mh - ey + 100)
        line(mw + 100, mh - ey - 100, mw - 100, mh - ey + 100)
        line(mw, mh - 200, mw, mh - 400)
    elif mode == "bear":
        ey = game_height * 0.05
        line(100, mh + ey, width - 100, mh + ey)
        line(mw - 48, mh - 25, mw - 48, mh - 175)
        line(mw + 48, mh - 25, mw + 48, mh - 175)
        line(mw, mh - 250, mw, mh - 400)
    else:
        line(mw, mh - 200, mw, mh - 400)


def render_vertical_stripe(
    *,
    mode: str,
    site_type: str | None,
    game_width: int,
    game_height: int,
    altitude: float | None,
    heading: float | None,
    landed: bool,
    in_srv: bool,
    on_foot: bool,
    disable_ruins_grid: bool,
    disable_aerial_grid: bool,
    aerial_alpha: float,
    aerial_beta: float,
    aerial_gamma: float,
) -> tuple[bytes, int, int] | None:
    chosen = select_stripe(
        mode=mode,
        site_type=site_type,
        disable_ruins_grid=disable_ruins_grid,
        disable_aerial_grid=disable_aerial_grid,
        in_srv=in_srv,
        on_foot=on_foot,
        landed=landed,
        aerial_alpha=aerial_alpha,
        aerial_beta=aerial_beta,
        aerial_gamma=aerial_gamma,
    )
    if chosen is None or game_width < 40 or game_height < 40:
        return None
    stripe_mode, target = chosen
    opacity = stripe_opacity(landed=landed, mode=stripe_mode, altitude=altitude, target=target)
    if opacity <= 0:
        return None
    from PIL import Image, ImageDraw

    from panel import _load_hud_font

    width = min(600, game_width)
    height = max(40, game_height - 10)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    _paint(draw, stripe_mode, width, height, game_width, game_height, opacity)
    label = "" if heading is None else f"{heading:.0f}°"
    if label:
        font = _load_hud_font(18, bold=True)
        box = draw.textbbox((0, 0), label, font=font)
        text_w = box[2] - box[0]
        text_h = box[3] - box[1]
        bar_w = text_w + 36
        bar_h = text_h + 16
        left = (width / 2) - (bar_w / 2)
        top = 8
        draw.rectangle((left, top, left + bar_w, top + bar_h), fill=(0, 0, 0, _ink(opacity)[3]))
        draw.text(((width - text_w) / 2, top + 6), label, font=font, fill=_ink(opacity))
    return image.tobytes(), width, height
