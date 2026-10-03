#!/usr/bin/env python3
"""Windows KeyChords / keyActions_TEST parity for Linux.

Defaults mirror ``SrvSurvey/KeyChords.cs`` ``defaultKeys``. Chord strings use
the Windows FormSettings shape (``ALT F``, ``CTRL SHIFT N``). Linux X11
grabbing normalizes them via ``hotkey.parse_chord`` (``Alt+F``).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

# KeyAction names — keep identical to the Windows enum.
TOGGLE_ALL_VISIBILITY = "toggleAllVisibility"
MAP_ZOOM_IN = "mapZoomIn"
MAP_ZOOM_OUT = "mapZoomOut"
MAP_ZOOM_AUTO = "mapZoomAuto"
MAP_BE_HUGE = "mapBeHuge"
SHOW_JUMP_INFO = "showJumpInfo"
PASTE_GAL_MAP = "pasteGalMap"
COPY_NEXT_BOXEL = "copyNextBoxel"
SHOW_FSS_INFO = "showFssInfo"
SHOW_BODY_INFO = "showBodyInfo"
SHOW_STATION_INFO = "showStationInfo"
SHOW_COLONY_SHOPPING = "showColonyShopping"
REFRESH_COLONY_DATA = "refreshColonyData"
COLLAPSE_COLONY_DATA = "collapseColonyData"
SHOW_SYSTEM_NOTES = "showSystemNotes"
TRACK_1 = "track1"
TRACK_2 = "track2"
TRACK_3 = "track3"
TRACK_4 = "track4"
TRACK_5 = "track5"
TRACK_6 = "track6"
TRACK_7 = "track7"
TRACK_8 = "track8"
NEXT_WINDOW = "nextWindow"
STREAM_ONE = "streamOne"
ADJUST_VR = "adjustVR"
RESET_VR = "resetVR"
TOGGLE_FF = "toggleFF"
QUEST_SHOW = "questShow"
TOGGLE_IMAGE_EMBED = "toggleImageEmbed"

# Windows KeyChords.defaultKeys
DEFAULT_KEYS: dict[str, str] = {
    TOGGLE_ALL_VISIBILITY: "ALT F2",
    MAP_ZOOM_IN: "CTRL +",
    MAP_ZOOM_OUT: "CTRL -",
    MAP_ZOOM_AUTO: "CTRL SHIFT Backspace",
    MAP_BE_HUGE: "CTRL Backspace",
    SHOW_JUMP_INFO: "ALT D",
    PASTE_GAL_MAP: "",
    COPY_NEXT_BOXEL: "CTRL C",
    SHOW_FSS_INFO: "ALT F",
    SHOW_BODY_INFO: "ALT B",
    SHOW_STATION_INFO: "ALT I",
    SHOW_COLONY_SHOPPING: "ALT S",
    REFRESH_COLONY_DATA: "ALT CTRL S",
    COLLAPSE_COLONY_DATA: "ALT SHIFT S",
    SHOW_SYSTEM_NOTES: "CTRL SHIFT N",
    TRACK_1: "ALT CTRL F1",
    TRACK_2: "ALT CTRL F2",
    TRACK_3: "ALT CTRL F3",
    TRACK_4: "ALT CTRL F4",
    TRACK_5: "ALT CTRL F5",
    TRACK_6: "ALT CTRL F6",
    TRACK_7: "ALT CTRL F7",
    TRACK_8: "ALT CTRL F8",
    NEXT_WINDOW: "ALT CTRL W",
    STREAM_ONE: "ALT CTRL O",
    ADJUST_VR: "ALT V",
    TOGGLE_FF: "",
    QUEST_SHOW: "ALT Q",
    TOGGLE_IMAGE_EMBED: "ALT CTRL I",
}

ACTION_DESCRIPTIONS: dict[str, str] = {
    TOGGLE_ALL_VISIBILITY: "Toggles visibility of all overlay windows.",
    MAP_ZOOM_IN: "Zoom in on maps at Human and Guardian sites.",
    MAP_ZOOM_OUT: "Zoom out on maps at Human and Guardian sites.",
    MAP_ZOOM_AUTO: "Reset the zoom to default, at Human and Guardian sites.",
    MAP_BE_HUGE: "Toggles making the map fill half the screen, at Human settlements only.",
    SHOW_JUMP_INFO: "Force toggle the FSD jump overlay without starting to jump.",
    COPY_NEXT_BOXEL: "In gal-map, copy the next boxel search system to clipboard.",
    PASTE_GAL_MAP: "Paste clipboard text when in Gal-Map.",
    SHOW_FSS_INFO: "Force show the FSS info overlay.",
    SHOW_BODY_INFO: "Force show the Body info overlay.",
    SHOW_STATION_INFO: "Force show the Station Info overlay.",
    SHOW_SYSTEM_NOTES: "Make the system notes window visible.",
    SHOW_COLONY_SHOPPING: "Force show the Colonisation shopping list overlay.",
    REFRESH_COLONY_DATA: "Immediately refresh Colonisation data.",
    COLLAPSE_COLONY_DATA: "Toggle collapsing cargo groups when enough on FCs.",
    NEXT_WINDOW: "Set focus on a different game window.",
    STREAM_ONE: "Toggle stream-one overlay mode.",
    ADJUST_VR: "For VR players. Opens an overlay to adjust positions.",
    RESET_VR: "Reset VR headset orientation.",
    TOGGLE_FF: "Toggles the First Footfall status for the current body.",
    QUEST_SHOW: "Show the quests window.",
    TOGGLE_IMAGE_EMBED: "Toggle adding data embeds to screenshots.",
    TRACK_1: "Add or remove tracker #1",
    TRACK_2: "Add or remove tracker #2",
    TRACK_3: "Add or remove tracker #3",
    TRACK_4: "Add or remove tracker #4",
    TRACK_5: "Add or remove tracker #5",
    TRACK_6: "Add or remove tracker #6",
    TRACK_7: "Add or remove tracker #7",
    TRACK_8: "Add or remove tracker #8",
}

# Actions that Linux X11/GTK can meaningfully honor today.
LINUX_SUPPORTED_ACTIONS: frozenset[str] = frozenset(
    {
        TOGGLE_ALL_VISIBILITY,
        SHOW_FSS_INFO,
        SHOW_BODY_INFO,
        SHOW_STATION_INFO,
        SHOW_JUMP_INFO,
        SHOW_COLONY_SHOPPING,
        REFRESH_COLONY_DATA,
        COLLAPSE_COLONY_DATA,
        TOGGLE_IMAGE_EMBED,
        COPY_NEXT_BOXEL,
        ADJUST_VR,
        MAP_ZOOM_IN,
        MAP_ZOOM_OUT,
        MAP_ZOOM_AUTO,
    }
)

# Panel id ↔ force-show flag used by host / plotters.
PANEL_FORCE_MAP: dict[str, str] = {
    "colonisation": SHOW_COLONY_SHOPPING,
    "fss": SHOW_FSS_INFO,
    "bodyinfo": SHOW_BODY_INFO,
    "station": SHOW_STATION_INFO,
    "jumpinfo": SHOW_JUMP_INFO,
    "adjustvr": ADJUST_VR,
}


def merge_key_actions(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Return defaults with user overrides; ensure every default key exists."""
    merged = dict(DEFAULT_KEYS)
    if overrides:
        for key, value in overrides.items():
            if key in merged or key in ACTION_DESCRIPTIONS:
                if value is None:
                    merged[key] = ""
                else:
                    text = str(value).strip()
                    merged[key] = normalize_windows_chord(text) if text else ""
    return merged


def normalize_windows_chord(text: str) -> str:
    """Normalize ``ALT  f`` / ``alt+f`` toward Windows FormSettings form."""
    raw = (text or "").strip()
    if not raw:
        return ""
    # Accept Linux ``Alt+F`` and Windows ``ALT F``.
    tokens = [t for t in raw.replace("+", " ").replace("-", " ").split() if t]
    if not tokens:
        return ""
    mods: list[str] = []
    key_parts: list[str] = []
    for tok in tokens:
        low = tok.lower()
        if low in {"alt", "mod1"}:
            if "ALT" not in mods:
                mods.append("ALT")
        elif low in {"ctrl", "control"}:
            if "CTRL" not in mods:
                mods.append("CTRL")
        elif low in {"shift"}:
            if "SHIFT" not in mods:
                mods.append("SHIFT")
        elif low in {"super", "meta", "win", "mod4"}:
            if "SUPER" not in mods:
                mods.append("SUPER")
        else:
            key_parts.append(tok)
    if not key_parts:
        return " ".join(mods)
    key = " ".join(key_parts)
    low_key = key.lower().replace(" ", "")
    special = {
        "backspace": "Backspace",
        "pause": "Pause",
        "break": "Pause",
        "plus": "+",
        "minus": "-",
        "equal": "=",
        "scrolllock": "ScrollLock",
        "scroll_lock": "ScrollLock",
    }
    if low_key in special:
        key_out = special[low_key]
    elif low_key.startswith("f") and low_key[1:].isdigit():
        key_out = low_key.upper()
    elif len(key) == 1:
        key_out = key.upper() if key.isalpha() else key
    else:
        key_out = key[:1].upper() + key[1:]
    return " ".join([*mods, key_out])


def windows_chord_to_linux(text: str) -> str:
    """Convert ``ALT CTRL S`` → ``Alt+Ctrl+S`` for ``hotkey.parse_chord``."""
    norm = normalize_windows_chord(text)
    if not norm:
        return ""
    parts = norm.split()
    if len(parts) == 1:
        mods: list[str] = []
        key = parts[0]
    else:
        mods = parts[:-1]
        key = parts[-1]
    mod_map = {"ALT": "Alt", "CTRL": "Ctrl", "SHIFT": "Shift", "SUPER": "Super"}
    linux_mods = [mod_map.get(m, m.capitalize()) for m in mods]
    key_map = {
        "+": "plus",
        "-": "minus",
        "Backspace": "BackSpace",
        "ScrollLock": "Scroll_Lock",
    }
    key_out = key_map.get(key, key)
    return "+".join([*linux_mods, key_out])

def chords_equal(a: str, b: str) -> bool:
    """Compare chords ignoring Windows vs Linux separators."""
    return normalize_windows_chord(a) == normalize_windows_chord(b)


@dataclass
class ForceShowState:
    """Runtime force-show flags (Windows Plot*.forceShow equivalents)."""

    fss_info: bool = False
    body_info: bool = False
    station_info: bool = False
    jump_info: bool = False
    colony: bool = False
    adjust_vr: bool = False
    # XOR with buildProjectsCollapseGroupsWithFCEnough_TEST (Windows toggleCollapse).
    colony_collapse_toggle: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _dirty: threading.Event = field(default_factory=threading.Event, repr=False)

    def mark_dirty(self) -> None:
        self._dirty.set()

    def consume_dirty(self) -> bool:
        if not self._dirty.is_set():
            return False
        self._dirty.clear()
        return True

    def toggle(self, flag: str) -> bool:
        """Flip a named force-show flag; return the new value."""
        with self._lock:
            if flag == SHOW_FSS_INFO:
                self.fss_info = not self.fss_info
                value = self.fss_info
            elif flag == SHOW_BODY_INFO:
                self.body_info = not self.body_info
                value = self.body_info
            elif flag == SHOW_STATION_INFO:
                self.station_info = not self.station_info
                value = self.station_info
            elif flag == SHOW_JUMP_INFO:
                self.jump_info = not self.jump_info
                value = self.jump_info
            elif flag == SHOW_COLONY_SHOPPING:
                self.colony = not self.colony
                value = self.colony
            elif flag == ADJUST_VR:
                self.adjust_vr = not self.adjust_vr
                value = self.adjust_vr
            elif flag == COLLAPSE_COLONY_DATA:
                self.colony_collapse_toggle = not self.colony_collapse_toggle
                value = self.colony_collapse_toggle
            else:
                return False
        self.mark_dirty()
        return value

    def is_forced(self, panel_id: str) -> bool:
        action = PANEL_FORCE_MAP.get(panel_id)
        if action is None:
            return False
        with self._lock:
            if action == SHOW_FSS_INFO:
                return self.fss_info
            if action == SHOW_BODY_INFO:
                return self.body_info
            if action == SHOW_STATION_INFO:
                return self.station_info
            if action == SHOW_JUMP_INFO:
                return self.jump_info
            if action == SHOW_COLONY_SHOPPING:
                return self.colony
            if action == ADJUST_VR:
                return self.adjust_vr
        return False

    def colony_collapse_effective(self, setting: bool) -> bool:
        """Windows: settings.collapse != toggleCollapse."""
        with self._lock:
            return bool(setting) != bool(self.colony_collapse_toggle)

    def adjust_vr_open(self) -> bool:
        with self._lock:
            return bool(self.adjust_vr)


def do_key_action(
    action: str,
    *,
    force_show: ForceShowState,
    on_toggle_overlay: Callable[[], None] | None = None,
    on_toggle_image_embed: Callable[[], None] | None = None,
    on_refresh_colony: Callable[[], None] | None = None,
    on_copy_next_boxel: Callable[[], bool] | None = None,
    on_adjust_vr: Callable[[], None] | None = None,
    on_vr_nudge_opacity: Callable[[float], None] | None = None,
    on_vr_nudge_scale: Callable[[float], None] | None = None,
    on_map_zoom: Callable[[str], None] | None = None,
) -> bool:
    """Dispatch a KeyAction. Returns True when handled (including stubs)."""
    if action == TOGGLE_ALL_VISIBILITY:
        if on_toggle_overlay is not None:
            on_toggle_overlay()
        return True
    if action == ADJUST_VR:
        force_show.toggle(ADJUST_VR)
        if on_adjust_vr is not None:
            on_adjust_vr()
        return True
    if force_show.adjust_vr_open() and action in {
        MAP_ZOOM_IN,
        MAP_ZOOM_OUT,
        MAP_ZOOM_AUTO,
    }:
        if action == MAP_ZOOM_IN and on_vr_nudge_opacity is not None:
            on_vr_nudge_opacity(5.0)
            force_show.mark_dirty()
            return True
        if action == MAP_ZOOM_OUT and on_vr_nudge_opacity is not None:
            on_vr_nudge_opacity(-5.0)
            force_show.mark_dirty()
            return True
        if action == MAP_ZOOM_AUTO and on_vr_nudge_scale is not None:
            on_vr_nudge_scale(1.0)
            force_show.mark_dirty()
            return True
    if action in {MAP_ZOOM_IN, MAP_ZOOM_OUT, MAP_ZOOM_AUTO}:
        if on_map_zoom is not None:
            on_map_zoom(action)
        force_show.mark_dirty()
        return True
    if action in {
        SHOW_FSS_INFO,
        SHOW_BODY_INFO,
        SHOW_STATION_INFO,
        SHOW_JUMP_INFO,
        SHOW_COLONY_SHOPPING,
        COLLAPSE_COLONY_DATA,
    }:
        force_show.toggle(action)
        return True
    if action == REFRESH_COLONY_DATA:
        if on_refresh_colony is not None:
            on_refresh_colony()
        else:
            try:
                from raven_colonial import clear_cache

                clear_cache()
            except Exception:  # noqa: BLE001
                pass
        force_show.mark_dirty()
        return True
    if action == TOGGLE_IMAGE_EMBED:
        if on_toggle_image_embed is not None:
            on_toggle_image_embed()
        return True
    if action == COPY_NEXT_BOXEL:
        if on_copy_next_boxel is not None:
            on_copy_next_boxel()
        return True
    # Known Windows actions we acknowledge but cannot drive yet on Linux.
    if action in DEFAULT_KEYS or action in ACTION_DESCRIPTIONS:
        return True
    return False


def find_action_for_chord(
    chord: str,
    key_actions: dict[str, str],
) -> str | None:
    """Return the first KeyAction whose binding matches ``chord``."""
    if not chord:
        return None
    for action, bound in key_actions.items():
        if not bound:
            continue
        if chords_equal(bound, chord):
            return action
    return None
