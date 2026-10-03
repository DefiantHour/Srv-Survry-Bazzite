#!/usr/bin/env python3
"""Ram Tah decode table — Linux port of ActiveObelisk.prepLogItems / mapMsgItems.

Maps log message ids (``B1``, ``C4``, ``#12``, …) to required obelisk items.
Also resolves display names matching Properties.Guardian.
"""

from __future__ import annotations

from functools import lru_cache

# Item code → English display (Properties.Guardian)
ITEM_NAMES: dict[str, str] = {
    "ca": "Casket",
    "or": "Orb",
    "re": "Relic",
    "ta": "Tablet",
    "to": "Totem",
    "ur": "Urn",
    "se": "Sensor",
    "pr": "Probe",
    "li": "Link",
    "cy": "Cyclops",
    "ba": "Basilisk",
    "me": "Medusa",
}

LOG_CATEGORY: dict[str, str] = {
    "B": "Biology",
    "C": "Culture",
    "H": "History",
    "L": "Language",
    "T": "Technology",
    "#": "",
}

# Exact source list from GuardianSiteData.ActiveObelisk.prepLogItems
_LOG_SOURCE: tuple[str, ...] = (
    "B1-ur-re",
    "B2-ur-ur",
    "B3-ur-ca",
    "B4-ur-ta",
    "B5-ur-or",
    "B6-ur-to",
    "B7-ur-re",
    "B8-ur-ur",
    "B9-ur-ca",
    "B10-ur-ta",
    "B11-ur-or",
    "B12-ur-to",
    "B13-ur",
    "B14-ur-ur",
    "B15-ur-ca",
    "B16-ur-ta",
    "B17-ur-or",
    "B18-ur-to",
    "B19-ur-re",
    "C1-to-re",
    "C2-to-to",
    "C3-to-ca",
    "C4-to-ur",
    "C5-to-ta",
    "C6-to-or",
    "C7-to",
    "C8-to-to",
    "C9-to-ca",
    "C10-to-ur",
    "C11-to-ta",
    "C12-to-or",
    "C13-to-re",
    "C14-to",
    "C15-to-to",
    "C16-to-ca",
    "C17-to-ur",
    "C18-to-ta",
    "C19-to-or",
    "C20-to-re",
    "H1-ca",
    "H2-ca-ca",
    "H3-ca-ur",
    "H4-ca-ta",
    "H5-ca-or",
    "H6-ca-to",
    "H7-ca-re",
    "H8-ca",
    "H9-ca-ca",
    "H10-ca-re",
    "H11-ca-ta",
    "H12-ca-or",
    "H13-ca-to",
    "H14-ca-re",
    "H15-ca-to",
    "H16-ca-re",
    "H17-ca-to",
    "H18-ca-ca",
    "H19-ca-ur",
    "H20-ca-ta",
    "H21-ca-or",
    "L1-ta",
    "L2-ta-ta",
    "L3-ta-ca",
    "L4-ta-ur",
    "L5-ta-or",
    "L6-ta-ta",
    "L7-ta-re",
    "L8-ta",
    "L9-ta-ta",
    "L10-ta-ca",
    "L11-ta-ur",
    "L12-ta-or",
    "L13-ta-to",
    "L14-ta-re",
    "L15-ta",
    "L16-ta-ta",
    "L17-ta-ca",
    "L18-ta-ur",
    "L19-ta-or",
    "L20-ta-to",
    "L21-ta-re",
    "T1-or",
    "T2-or-or",
    "T3-or-ca",
    "T4-or-ur",
    "T5-or-ta",
    "T6-or-to",
    "T7-or",
    "T8-or-or",
    "T9-or-ca",
    "T10-or-ur",
    "T11-or-ta",
    "T12-or-re",
    "T13-or-re",
    "T14-or",
    "T15-or-or",
    "T16-or-ca",
    "T17-or-ur",
    "T18-or-ta",
    "T19-or-to",
    "T20-or-re",
    "#1-se-cy",
    "#2-se-ba",
    "#3-se-li",
    "#4-se-pr",
    "#5-se-me",
    "#6-ca-or",
    "#7-ca-ta",
    "#8-ca-to",
    "#9-ca-re",
    "#10-ca-ur",
    "#11-or-re",
    "#12-or-or",
    "#13-or-ca",
    "#14-re-to",
    "#15-re-ca",
    "#16-re-ur",
    "#17-re-ta",
    "#18-or-to",
    "#19-or-ca",
    "#20-re-or",
    "#21-or-ur",
    "#22-or-ta",
    "#23-or-re",
    "#24-ta-to",
    "#25-ur-or",
    "#26-ur-to",
    "#27-ur-ta",
    "#28-ur-ca",
)

RUINS_LOG_TOTAL = 101  # FormRamTah progress divisor
LOGS_LOG_TOTAL = 28


def _build_map() -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for txt in _LOG_SOURCE:
        parts = [p for p in txt.split("-") if p]
        if len(parts) < 2:
            continue
        msg = parts[0]
        items = tuple(parts[1:])
        out[msg] = items
    return out


_MSG_ITEMS = _build_map()


def items_for_msg(msg: str | None) -> tuple[str, ...]:
    """Return item codes required for a log message id."""
    if not msg:
        return ()
    return _MSG_ITEMS.get(msg.strip(), ())


def item_display(code: str | None) -> str:
    if not code:
        return "?"
    return ITEM_NAMES.get(code, code)


def log_display_name(msg: str | None) -> str:
    """Match ActiveObelisk.msgDisplay / Util.getLogNameFromChar."""
    if not msg:
        return "?"
    text = msg.strip()
    if not text:
        return "?"
    cat = LOG_CATEGORY.get(text[0], "")
    rest = text[1:]
    if cat:
        return f"{cat} #{rest}".strip()
    return f"#{rest}" if rest else text


@lru_cache(maxsize=1)
def all_ruins_msgs() -> frozenset[str]:
    return frozenset(m for m in _MSG_ITEMS if not m.startswith("#"))


@lru_cache(maxsize=1)
def all_structure_msgs() -> frozenset[str]:
    return frozenset(m for m in _MSG_ITEMS if m.startswith("#"))


def group_obelisks_by_msg(
    obelisks: list | tuple,
    *,
    decoded: frozenset[str] | None = None,
) -> list[tuple[str, list[str], tuple[str, ...]]]:
    """Build PlotRamTah rows: (msg, [obelisk names], item codes).

    Skips msgs listed in ``decoded`` (commander progress). When decoded is
    None, all site logs are shown as still needed.
    """
    by_msg: dict[str, list[str]] = {}
    for ob in obelisks:
        msg = getattr(ob, "msg", None)
        name = getattr(ob, "name", None)
        if not isinstance(msg, str) or not msg or not isinstance(name, str):
            continue
        if decoded is not None and msg in decoded:
            continue
        by_msg.setdefault(msg, []).append(name)

    def _sort_key(m: str) -> tuple:
        if m.startswith("#"):
            try:
                return (1, int(m[1:]))
            except ValueError:
                return (1, 0, m)
        return (0, m[0], int(m[1:]) if m[1:].isdigit() else 0, m)

    rows: list[tuple[str, list[str], tuple[str, ...]]] = []
    for msg in sorted(by_msg.keys(), key=_sort_key):
        names = sorted(set(by_msg[msg]))
        rows.append((msg, names, items_for_msg(msg)))
    return rows
