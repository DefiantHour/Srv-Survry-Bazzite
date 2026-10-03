#!/usr/bin/env python3
"""Minimal boxel-search helpers for Linux PlotSphericalSearch parity.

Windows keeps full BoxelSearch state on CommanderSettings. Linux persists
prefix / next-system strings on GameSettings and copies via wl-copy (Wayland),
then xclip, then GTK clipboard.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Callable

from game_settings import GameSettings

# GuiFocus.GalaxyMap — match companion / PlotSphericalSearch
_GUI_GAL_MAP = 6


def set_clipboard_text(text: str) -> bool:
    """Copy ``text`` to the system clipboard. Fail soft; prefer Wayland."""
    payload = text if text is not None else ""
    if not payload:
        return False

    # Bazzite / SteamOS: Wayland first.
    if shutil.which("wl-copy"):
        try:
            proc = subprocess.run(
                ["wl-copy", "--", payload],
                capture_output=True,
                timeout=3,
                check=False,
            )
            if proc.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            proc = subprocess.run(
                ["wl-copy"],
                input=payload.encode("utf-8"),
                capture_output=True,
                timeout=3,
                check=False,
            )
            if proc.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass

    if shutil.which("xclip"):
        try:
            proc = subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=payload.encode("utf-8"),
                capture_output=True,
                timeout=3,
                check=False,
            )
            if proc.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass

    if shutil.which("xsel"):
        try:
            proc = subprocess.run(
                ["xsel", "--clipboard", "--input"],
                input=payload.encode("utf-8"),
                capture_output=True,
                timeout=3,
                check=False,
            )
            if proc.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass

    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gdk, Gtk

        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(payload, -1)
        clipboard.store()
        return True
    except Exception:  # noqa: BLE001 — fail soft
        return False


def next_boxel_system(game: GameSettings) -> str:
    """Return the next system name to search, or empty string."""
    return (getattr(game, "boxelSearchNextSystem", None) or "").strip()


def boxel_prefix(game: GameSettings) -> str:
    return (getattr(game, "boxelSearchPrefix", None) or "").strip()


def boxel_current(game: GameSettings) -> str:
    cur = (getattr(game, "boxelSearchCurrent", None) or "").strip()
    return cur or boxel_prefix(game)


def copy_next_boxel_system(
    game: GameSettings,
    *,
    gui_focus: int | None = None,
    set_text: Callable[[str], bool] | None = None,
) -> bool:
    """Copy next boxel system when search is active (Gal-Map if focus known).

    Returns True only when text was handed to a clipboard backend successfully.
    """
    if not game.boxelSearchActive:
        return False
    if gui_focus is not None and gui_focus != _GUI_GAL_MAP:
        return False
    text = next_boxel_system(game)
    if not text:
        return False
    setter = set_text if set_text is not None else set_clipboard_text
    try:
        return bool(setter(text))
    except Exception:  # noqa: BLE001
        return False
