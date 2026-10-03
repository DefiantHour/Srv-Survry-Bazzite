#!/usr/bin/env python3
"""Theme colours — Linux mirror of GameColors.Defaults + Settings colour fields.

Persisted as ``gs.defaultOrange=#RRGGBB`` (optional ``#AARRGGBB``). Plotters
call ``orange(game)`` etc.; missing/invalid hex falls back to Windows defaults.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game_settings import GameSettings

# Windows GameColors.Defaults (RGB) + Color.Yellow for the banner.
DEFAULT_ORANGE = (255, 111, 0, 255)
DEFAULT_ORANGE_DIM = (95, 48, 3, 255)
DEFAULT_CYAN = (84, 223, 237, 255)
DEFAULT_DARK_CYAN = (0, 139, 139, 255)
DEFAULT_BANNER = (255, 255, 0, 255)

DEFAULT_ORANGE_HEX = "#FF6F00"
DEFAULT_ORANGE_DIM_HEX = "#5F3003"
DEFAULT_CYAN_HEX = "#54DFED"
DEFAULT_DARK_CYAN_HEX = "#008B8B"
DEFAULT_BANNER_HEX = "#FFFF00"

Rgba = tuple[int, int, int, int]

_cache: dict[tuple[str | None, str], Rgba] = {}


def parse_hex(value: str | None, fallback: Rgba = DEFAULT_ORANGE) -> Rgba:
    """Parse ``#RGB``, ``#RRGGBB``, or ``#AARRGGBB`` into an RGBA tuple."""
    if value is None:
        return fallback
    text = str(value).strip()
    if not text:
        return fallback
    if text.startswith("#"):
        text = text[1:]
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    try:
        if len(text) == 6:
            r = int(text[0:2], 16)
            g = int(text[2:4], 16)
            b = int(text[4:6], 16)
            return (r, g, b, 255)
        if len(text) == 8:
            a = int(text[0:2], 16)
            r = int(text[2:4], 16)
            g = int(text[4:6], 16)
            b = int(text[6:8], 16)
            return (r, g, b, a)
    except ValueError:
        return fallback
    return fallback


def to_hex(rgba: Rgba, *, include_alpha: bool = False) -> str:
    """Format an RGBA tuple as ``#RRGGBB`` or ``#AARRGGBB``."""
    r, g, b, a = rgba
    if include_alpha and a != 255:
        return f"#{a:02X}{r:02X}{g:02X}{b:02X}"
    return f"#{r:02X}{g:02X}{b:02X}"


def _field_hex(game: GameSettings | None, name: str) -> str | None:
    if game is None:
        return None
    raw = getattr(game, name, None)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _cached(game: GameSettings | None, name: str, fallback: Rgba) -> Rgba:
    key = (_field_hex(game, name), name)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    parsed = parse_hex(key[0], fallback)
    if len(_cache) > 64:
        _cache.clear()
    _cache[key] = parsed
    return parsed


def orange(game: GameSettings | None = None) -> Rgba:
    return _cached(game, "defaultOrange", DEFAULT_ORANGE)


def orange_dim(game: GameSettings | None = None) -> Rgba:
    return _cached(game, "defaultOrangeDim", DEFAULT_ORANGE_DIM)


def cyan(game: GameSettings | None = None) -> Rgba:
    return _cached(game, "defaultCyan", DEFAULT_CYAN)


def dark_cyan(game: GameSettings | None = None) -> Rgba:
    return _cached(game, "defaultDarkCyan", DEFAULT_DARK_CYAN)


def banner(game: GameSettings | None = None) -> Rgba:
    return _cached(game, "screenshotBannerColor", DEFAULT_BANNER)


def clear_cache() -> None:
    """Drop the light parse cache (tests / after settings save)."""
    _cache.clear()
