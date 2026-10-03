#!/usr/bin/env python3
"""Commander persistence — Linux mirror of CommanderSettings key fields.

JSON lives under ``~/.local/share/srvsurvey/cmdr/<fid|name>.json`` (XDG data).
Covers Ram Tah decode progress / mission flags, human-settlement headings by
marketId, and per-site guardian interactive survey state used by chat commands.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any

from journal import GuardianSiteSummary, SurveyState
from paths import ensure_data_dir, srvsurvey_data_dir

RUINS_MISSION_NAMES = frozenset({"Mission_TheDead", "Mission_TheDead_name"})
LOGS_MISSION_NAMES = frozenset(
    {"Mission_TheDead_002", "Mission_TheDead_002_name"}
)

_SAFE_KEY = re.compile(r"[^A-Za-z0-9._-]+")
_CACHE: dict[str, "CmdrState"] = {}


class TahMissionStatus(str, Enum):
    NotStarted = "NotStarted"
    Active = "Active"
    Complete = "Complete"


def _parse_status(raw: object) -> TahMissionStatus:
    if isinstance(raw, TahMissionStatus):
        return raw
    if isinstance(raw, str):
        try:
            return TahMissionStatus(raw)
        except ValueError:
            pass
    return TahMissionStatus.NotStarted


def _str_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


@dataclass
class GuardianSurveyState:
    """Interactive guardian survey for one site (PlotGuardians / MsgCmd)."""

    site_key: str = "default"
    site_type: str | None = None
    heading: float = -1.0
    zoom: float = 1.0
    target_obelisk: str | None = None
    scanned_obelisks: list[str] = field(default_factory=list)
    # site | heading | map | aerial
    mode: str = "map"
    empty_puddles: list[str] = field(default_factory=list)
    extra_poi: list[dict[str, Any]] = field(default_factory=list)
    notes: str = ""
    relic_tower_heading: float = -1.0
    # Per-tower headings. Windows ``GuardianSiteData.relicHeadings``.
    relic_headings: dict[str, int] = field(default_factory=dict)

    # Alias used by some callers / tests (Windows plot_mode naming).
    @property
    def plot_mode(self) -> str:
        return self.mode

    @plot_mode.setter
    def plot_mode(self, value: str) -> None:
        self.mode = value

    def to_dict(self) -> dict[str, Any]:
        return {
            "site_key": self.site_key,
            "site_type": self.site_type,
            "heading": self.heading,
            "zoom": self.zoom,
            "target_obelisk": self.target_obelisk,
            "scanned_obelisks": list(self.scanned_obelisks),
            "mode": self.mode,
            "empty_puddles": list(self.empty_puddles),
            "extra_poi": list(self.extra_poi),
            "notes": self.notes,
            "relic_tower_heading": self.relic_tower_heading,
            "relic_headings": {str(k): int(v) for k, v in self.relic_headings.items()},
        }

    @classmethod
    def from_dict(cls, raw: object, *, default_key: str = "default") -> GuardianSurveyState:
        if not isinstance(raw, dict):
            return cls(site_key=default_key)
        scanned = raw.get("scanned_obelisks") or []
        empty = raw.get("empty_puddles") or []
        extra = raw.get("extra_poi") or []
        heading = raw.get("heading", -1)
        zoom = raw.get("zoom", 1.0)
        tower = raw.get("relic_tower_heading", -1)
        headings_raw = raw.get("relic_headings") or raw.get("relicHeadings") or {}
        headings: dict[str, int] = {}
        if isinstance(headings_raw, dict):
            for key, value in headings_raw.items():
                if not isinstance(key, str):
                    continue
                try:
                    headings[key] = int(value)
                except (TypeError, ValueError):
                    continue
        return cls(
            site_key=str(raw.get("site_key") or default_key),
            site_type=_str_or_none(raw.get("site_type")),
            heading=float(heading) if isinstance(heading, (int, float)) else -1.0,
            zoom=float(zoom) if isinstance(zoom, (int, float)) else 1.0,
            target_obelisk=_str_or_none(raw.get("target_obelisk")),
            scanned_obelisks=[str(x) for x in scanned if x is not None]
            if isinstance(scanned, list)
            else [],
            mode=str(raw.get("mode") or raw.get("plot_mode") or "map"),
            empty_puddles=[str(x) for x in empty if x is not None]
            if isinstance(empty, list)
            else [],
            extra_poi=[dict(x) for x in extra if isinstance(x, dict)]
            if isinstance(extra, list)
            else [],
            notes=str(raw.get("notes") or ""),
            relic_tower_heading=float(tower) if isinstance(tower, (int, float)) else -1.0,
            relic_headings=headings,
        )


@dataclass
class CmdrState:
    """Persisted commander slice — mirrors CommanderSettings Ram Tah + sites."""

    fid: str = ""
    commander: str = ""
    decode_the_ruins: list[str] = field(default_factory=list)
    decode_the_logs: list[str] = field(default_factory=list)
    decode_the_ruins_mission_active: TahMissionStatus = TahMissionStatus.NotStarted
    decode_the_logs_mission_active: TahMissionStatus = TahMissionStatus.NotStarted
    human_site_headings: dict[str, float] = field(default_factory=dict)
    # PlotHumanSite / MsgCmd .edit .start .stop
    human_site_edit: bool = False
    human_site_survey: str = "idle"  # idle | active | stopped
    settlement_threat: int | None = None
    guardian_sites: dict[str, GuardianSurveyState] = field(default_factory=dict)
    active_guardian_site: str | None = None
    active_journey: str | None = None
    bookmarks: dict[str, Any] = field(default_factory=dict)
    # body_name -> {"visited": bool, "first_foot": bool}
    body_flags: dict[str, dict[str, bool]] = field(default_factory=dict)
    filepath: Path | None = field(default=None, repr=False)

    def guardian_for(self, site_key: str | None = None) -> GuardianSurveyState:
        """Return (creating if needed) survey state for a site key."""
        key = (site_key or self.active_guardian_site or "default").strip() or "default"
        hit = self.guardian_sites.get(key)
        if hit is None:
            hit = GuardianSurveyState(site_key=key)
            self.guardian_sites[key] = hit
        if self.active_guardian_site is None:
            self.active_guardian_site = key
        return hit

    @property
    def guardian(self) -> GuardianSurveyState:
        """Active guardian survey site (Windows singular ``CommanderSettings`` style)."""
        return self.guardian_for(self.active_guardian_site)

    # Back-compat alias
    @property
    def guardian_current(self) -> GuardianSurveyState:
        return self.guardian

    def put_guardian(self, state: GuardianSurveyState) -> None:
        key = (state.site_key or self.active_guardian_site or "default").strip() or "default"
        state.site_key = key
        self.guardian_sites[key] = state
        self.active_guardian_site = key

    @property
    def ram_tah_active(self) -> bool:
        return (
            self.decode_the_ruins_mission_active == TahMissionStatus.Active
            or self.decode_the_logs_mission_active == TahMissionStatus.Active
        )

    def decoded_set(self, *, is_ruins: bool) -> frozenset[str]:
        src = self.decode_the_ruins if is_ruins else self.decode_the_logs
        return frozenset(src)

    def toggle_ruin(self, name: str) -> bool:
        """Toggle a ruins decode / obelisk id. Returns True if now present."""
        name = name.strip()
        if not name:
            return False
        if name in self.decode_the_ruins:
            self.decode_the_ruins.remove(name)
            return False
        self.decode_the_ruins.append(name)
        return True

    def toggle_log(self, name: str) -> bool:
        name = name.strip()
        if not name:
            return False
        if name in self.decode_the_logs:
            self.decode_the_logs.remove(name)
            return False
        self.decode_the_logs.append(name)
        return True

    def toggle_decode_msg(self, msg: str, *, is_ruins: bool) -> bool:
        return self.toggle_ruin(msg) if is_ruins else self.toggle_log(msg)

    def toggle_scanned_obelisk(self, name: str, site_key: str | None = None) -> bool:
        """Toggle an obelisk id on the active (or named) guardian site."""
        name = (name or "").strip().upper()
        if not name:
            return False
        g = self.guardian_for(site_key)
        if name in g.scanned_obelisks:
            g.scanned_obelisks = [x for x in g.scanned_obelisks if x != name]
            return False
        g.scanned_obelisks = sorted({*g.scanned_obelisks, name})
        return True

    def set_human_heading(self, market_id: int | str, heading: float) -> None:
        self.human_site_headings[str(int(market_id))] = float(heading) % 360.0

    def get_human_heading(self, market_id: int | str) -> float | None:
        val = self.human_site_headings.get(str(int(market_id)))
        return float(val) if val is not None else None

    def human_heading(self, market_id: int | str) -> float | None:
        return self.get_human_heading(market_id)

    def _body_bookmark_map(self, body_name: str) -> dict[str, list[dict[str, float]]]:
        """Return mutable name → [{lat, lon}, ...] map for a body."""
        body = (body_name or "").strip()
        if not body:
            return {}
        raw = self.bookmarks.get(body)
        if not isinstance(raw, dict):
            raw = {}
            self.bookmarks[body] = raw
        out: dict[str, list[dict[str, float]]] = {}
        for name, positions in raw.items():
            cleaned: list[dict[str, float]] = []
            if isinstance(positions, list):
                for pos in positions:
                    if not isinstance(pos, dict):
                        continue
                    lat = pos.get("lat", pos.get("latitude"))
                    lon = pos.get("lon", pos.get("longitude", pos.get("long")))
                    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                        cleaned.append({"lat": float(lat), "lon": float(lon)})
            out[str(name)] = cleaned
            raw[str(name)] = cleaned
        self.bookmarks[body] = raw
        return out

    def add_bookmark(
        self,
        body_name: str,
        name: str,
        lat: float,
        lon: float,
        *,
        min_distance_m: float = 20.0,
        radius_m: float = 0.0,
    ) -> str:
        """Add a named surface bookmark (Windows Game.addBookmark)."""
        from geo import get_distance

        body = (body_name or "").strip()
        label = (name or "").strip()
        if not body or not label:
            return "Need body + bookmark name"
        mapping = self._body_bookmark_map(body)
        spots = mapping.setdefault(label, [])
        if radius_m > 0 and spots:
            for pos in spots:
                dist = get_distance(lat, lon, pos["lat"], pos["lon"], radius_m)
                if dist < min_distance_m:
                    return f"Too close to prior '{label}' bookmark"
        spots.append({"lat": float(lat), "lon": float(lon)})
        mapping[label] = spots
        self.bookmarks[body] = mapping
        return f"Bookmark +{label}"

    def clear_all_bookmarks(self, body_name: str) -> str:
        body = (body_name or "").strip()
        if not body:
            return "No body for ---"
        if body in self.bookmarks:
            del self.bookmarks[body]
        return "Cleared all bookmarks"

    def remove_bookmark_name(self, body_name: str, name: str) -> str:
        body = (body_name or "").strip()
        label = (name or "").strip()
        if not body or not label:
            return "Usage: --name"
        mapping = self._body_bookmark_map(body)
        if label not in mapping:
            return f"No bookmarks named {label}"
        del mapping[label]
        if mapping:
            self.bookmarks[body] = mapping
        elif body in self.bookmarks:
            del self.bookmarks[body]
        return f"Cleared bookmarks '{label}'"

    def remove_bookmark(
        self,
        body_name: str,
        name: str,
        lat: float,
        lon: float,
        *,
        nearest: bool,
        radius_m: float = 1.0,
    ) -> str:
        """Remove nearest (``-name``) or furthest (``=name``) bookmark of that name."""
        from geo import get_distance

        body = (body_name or "").strip()
        label = (name or "").strip()
        if not body or not label:
            return "Usage: -name or =name"
        mapping = self._body_bookmark_map(body)
        spots = mapping.get(label) or []
        if not spots:
            return f"No bookmarks named {label}"
        radius = radius_m if radius_m > 0 else 1.0
        ranked = sorted(
            spots,
            key=lambda p: get_distance(lat, lon, p["lat"], p["lon"], radius),
        )
        victim = ranked[0] if nearest else ranked[-1]
        mapping[label] = [p for p in spots if p is not victim]
        if not mapping[label]:
            del mapping[label]
        if mapping:
            self.bookmarks[body] = mapping
        elif body in self.bookmarks:
            del self.bookmarks[body]
        kind = "nearest" if nearest else "furthest"
        return f"Removed {kind} '{label}'"

    def tracker_bookmarks_for_body(self, body_name: str | None = None) -> list[Any]:
        """Flatten persisted bookmarks into TrackerBookmark-compatible rows."""
        from journal import TrackerBookmark

        rows: list[TrackerBookmark] = []
        bodies = (
            {body_name: self.bookmarks.get(body_name)}
            if body_name
            else dict(self.bookmarks)
        )
        for body, raw in bodies.items():
            if not isinstance(body, str) or not body or not isinstance(raw, dict):
                continue
            for name, positions in raw.items():
                if not isinstance(positions, list):
                    continue
                for pos in positions:
                    if not isinstance(pos, dict):
                        continue
                    lat = pos.get("lat", pos.get("latitude"))
                    lon = pos.get("lon", pos.get("longitude", pos.get("long")))
                    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                        rows.append(
                            TrackerBookmark(
                                name=str(name),
                                latitude=float(lat),
                                longitude=float(lon),
                                body_name=body,
                            )
                        )
        return rows

    def set_body_flag(self, body_name: str, flag: str, value: bool) -> None:
        body = (body_name or "").strip()
        if not body:
            return
        flags = dict(self.body_flags.get(body) or {})
        flags[flag] = bool(value)
        self.body_flags[body] = flags

    def toggle_body_flag(self, body_name: str, flag: str) -> bool:
        body = (body_name or "").strip()
        if not body:
            return False
        flags = dict(self.body_flags.get(body) or {})
        nxt = not bool(flags.get(flag))
        flags[flag] = nxt
        self.body_flags[body] = flags
        return nxt

    def get_body_flag(self, body_name: str, flag: str) -> bool:
        body = (body_name or "").strip()
        if not body:
            return False
        flags = self.body_flags.get(body) or {}
        return bool(flags.get(flag))

    def save(self, path: Path | None = None) -> Path:
        if path is not None:
            self.filepath = path
        return save_cmdr(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fid": self.fid,
            "commander": self.commander,
            "decodeTheRuins": list(self.decode_the_ruins),
            "decodeTheLogs": list(self.decode_the_logs),
            "decodeTheRuinsMissionActive": self.decode_the_ruins_mission_active.value,
            "decodeTheLogsMissionActive": self.decode_the_logs_mission_active.value,
            "humanSiteHeadings": {
                str(k): float(v) for k, v in self.human_site_headings.items()
            },
            "humanSiteEdit": bool(self.human_site_edit),
            "humanSiteSurvey": str(self.human_site_survey or "idle"),
            "settlementThreat": self.settlement_threat,
            "guardianSites": {
                k: v.to_dict() for k, v in self.guardian_sites.items()
            },
            "activeGuardianSite": self.active_guardian_site,
            "activeJourney": self.active_journey,
            "bookmarks": dict(self.bookmarks) if self.bookmarks else {},
            "bodyFlags": {
                k: dict(v) for k, v in self.body_flags.items() if isinstance(v, dict)
            },
        }

    @classmethod
    def from_dict(
        cls,
        raw: dict[str, Any],
        *,
        filepath: Path | None = None,
    ) -> CmdrState:
        headings_raw = raw.get("humanSiteHeadings") or raw.get("human_site_headings") or {}
        headings: dict[str, float] = {}
        if isinstance(headings_raw, dict):
            for key, val in headings_raw.items():
                if isinstance(val, (int, float)):
                    headings[str(key)] = float(val)

        ruins = raw.get("decodeTheRuins") or raw.get("decode_the_ruins") or []
        logs = raw.get("decodeTheLogs") or raw.get("decode_the_logs") or []
        if not isinstance(ruins, list):
            ruins = list(ruins) if isinstance(ruins, (set, tuple)) else []
        if not isinstance(logs, list):
            logs = list(logs) if isinstance(logs, (set, tuple)) else []

        sites_raw = raw.get("guardianSites") or raw.get("guardian_sites") or {}
        sites: dict[str, GuardianSurveyState] = {}
        if isinstance(sites_raw, dict):
            for key, val in sites_raw.items():
                sites[str(key)] = GuardianSurveyState.from_dict(val, default_key=str(key))

        # Legacy single guardian blob
        if not sites and isinstance(raw.get("guardian"), dict):
            g = GuardianSurveyState.from_dict(raw["guardian"])
            sites[g.site_key or "default"] = g

        flags_raw = raw.get("bodyFlags") or raw.get("body_flags") or {}
        body_flags: dict[str, dict[str, bool]] = {}
        if isinstance(flags_raw, dict):
            for key, val in flags_raw.items():
                if isinstance(val, dict):
                    body_flags[str(key)] = {
                        str(fk): bool(fv) for fk, fv in val.items()
                    }

        return cls(
            fid=str(raw.get("fid") or ""),
            commander=str(raw.get("commander") or ""),
            decode_the_ruins=[str(x) for x in ruins],
            decode_the_logs=[str(x) for x in logs],
            decode_the_ruins_mission_active=_parse_status(
                raw.get("decodeTheRuinsMissionActive")
                or raw.get("decode_the_ruins_mission_active")
            ),
            decode_the_logs_mission_active=_parse_status(
                raw.get("decodeTheLogsMissionActive")
                or raw.get("decode_the_logs_mission_active")
            ),
            human_site_headings=headings,
            human_site_edit=bool(
                raw.get("humanSiteEdit")
                if "humanSiteEdit" in raw
                else raw.get("human_site_edit", False)
            ),
            human_site_survey=str(
                raw.get("humanSiteSurvey")
                or raw.get("human_site_survey")
                or "idle"
            ),
            settlement_threat=_optional_int(
                raw.get("settlementThreat")
                if "settlementThreat" in raw
                else raw.get("settlement_threat")
            ),
            guardian_sites=sites,
            active_guardian_site=_str_or_none(
                raw.get("activeGuardianSite") or raw.get("active_guardian_site")
            ),
            active_journey=_str_or_none(
                raw.get("activeJourney") or raw.get("active_journey")
            ),
            bookmarks=dict(raw["bookmarks"])
            if isinstance(raw.get("bookmarks"), dict)
            else {},
            body_flags=body_flags,
            filepath=filepath,
        )


# Back-compat alias
CommanderState = CmdrState


def cmdr_dir(*, home: Path | None = None, data_dir: Path | None = None) -> Path:
    if data_dir is not None:
        root = ensure_data_dir(data_dir)
    elif home is not None:
        root = ensure_data_dir(srvsurvey_data_dir(home=home))
    else:
        root = ensure_data_dir()
    path = root / "cmdr"
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_cmdr_filename(key: str) -> str:
    cleaned = _SAFE_KEY.sub("_", key.strip()) or "unknown"
    return f"{cleaned}.json"


def cmdr_json_path(
    fid_or_name: str,
    *,
    home: Path | None = None,
    data_dir: Path | None = None,
) -> Path:
    return cmdr_dir(home=home, data_dir=data_dir) / safe_cmdr_filename(fid_or_name)


def save_cmdr(cmdr: CmdrState, *, home: Path | None = None) -> Path:
    target = cmdr.filepath
    if target is None:
        key = cmdr.fid or cmdr.commander or "unknown"
        target = cmdr_json_path(key, home=home)
        cmdr.filepath = target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(cmdr.to_dict(), indent=2) + "\n", encoding="utf-8")
    return target


# Bind instance method after save_cmdr exists (chat_commands uses cmdr.save()).
def _cmdr_save(self: CmdrState, *, home: Path | None = None) -> Path:
    return save_cmdr(self, home=home)


CmdrState.save = _cmdr_save  # type: ignore[attr-defined]


def load_cmdr(
    commander_or_fid: str,
    *,
    home: Path | None = None,
    data_dir: Path | None = None,
    use_cache: bool = True,
    fid: str | None = None,
) -> CmdrState:
    key = (commander_or_fid or "").strip() or "unknown"
    cache_key = key
    if use_cache and cache_key in _CACHE:
        return _CACHE[cache_key]

    path = cmdr_json_path(key, home=home, data_dir=data_dir)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        state = CmdrState.from_dict(raw, filepath=path)
    else:
        state = CmdrState(filepath=path)

    if fid:
        state.fid = fid
    # Prefer treating alphanumeric F* as fid
    if key.startswith("F") and key[1:].isdigit():
        state.fid = state.fid or key
    elif not state.commander:
        state.commander = key

    if use_cache:
        _CACHE[cache_key] = state
        if state.fid:
            _CACHE[state.fid] = state
        if state.commander:
            _CACHE[state.commander] = state
    return state


def get_commander(
    fid: str | None = None,
    commander: str | None = None,
    *,
    home: Path | None = None,
    data_dir: Path | None = None,
    reload: bool = False,
) -> CmdrState:
    key = (fid or "").strip() or (commander or "").strip() or "unknown"
    if reload:
        _CACHE.pop(key, None)
    state = load_cmdr(
        key, home=home, data_dir=data_dir, use_cache=not reload, fid=fid
    )
    if commander and state.commander != commander:
        state.commander = commander
    if fid and state.fid != fid:
        state.fid = fid
    return state


def clear_cmdr_cache() -> None:
    _CACHE.clear()


clear_commander_cache = clear_cmdr_cache


def apply_mission_journal(cmdr: CmdrState, entry: dict) -> bool:
    """Update Ram Tah mission flags from a journal mission event. Returns dirty."""
    event = entry.get("event")
    name = entry.get("Name")

    if event == "Missions":
        return _apply_missions_snapshot(cmdr, entry)

    if not isinstance(name, str):
        return False

    dirty = False
    if event == "MissionAccepted":
        if name in RUINS_MISSION_NAMES:
            cmdr.decode_the_ruins_mission_active = TahMissionStatus.Active
            dirty = True
        elif name in LOGS_MISSION_NAMES:
            cmdr.decode_the_logs_mission_active = TahMissionStatus.Active
            dirty = True
    elif event in ("MissionFailed", "MissionAbandoned"):
        if name in RUINS_MISSION_NAMES:
            cmdr.decode_the_ruins_mission_active = TahMissionStatus.NotStarted
            dirty = True
        elif name in LOGS_MISSION_NAMES:
            cmdr.decode_the_logs_mission_active = TahMissionStatus.NotStarted
            dirty = True
    elif event == "MissionCompleted":
        if name in RUINS_MISSION_NAMES:
            cmdr.decode_the_ruins_mission_active = TahMissionStatus.Complete
            dirty = True
        elif name in LOGS_MISSION_NAMES:
            cmdr.decode_the_logs_mission_active = TahMissionStatus.Complete
            dirty = True
    return dirty


def _mission_names_in_list(rows: object) -> set[str]:
    names: set[str] = set()
    if not isinstance(rows, list):
        return names
    for row in rows:
        if isinstance(row, dict):
            n = row.get("Name")
            if isinstance(n, str) and n:
                names.add(n)
    return names


def _apply_missions_snapshot(cmdr: CmdrState, entry: dict) -> bool:
    active = _mission_names_in_list(entry.get("Active"))
    dirty = False
    if active & RUINS_MISSION_NAMES:
        if cmdr.decode_the_ruins_mission_active != TahMissionStatus.Active:
            cmdr.decode_the_ruins_mission_active = TahMissionStatus.Active
            dirty = True
    if active & LOGS_MISSION_NAMES:
        if cmdr.decode_the_logs_mission_active != TahMissionStatus.Active:
            cmdr.decode_the_logs_mission_active = TahMissionStatus.Active
            dirty = True
    return dirty


# Back-compat aliases
apply_mission_entry = apply_mission_journal


def apply_journal_events(cmdr: CmdrState, events: list | tuple) -> bool:
    dirty = False
    for entry in events:
        if isinstance(entry, dict) and apply_mission_journal(cmdr, entry):
            dirty = True
    if dirty:
        save_cmdr(cmdr)
    return dirty


def guardian_site_key(site: GuardianSiteSummary | None) -> str | None:
    if site is None:
        return None
    body = site.body_name or ""
    kind = "ruins" if site.is_ruins else "structure"
    idx = site.index if site.index is not None else 1
    return f"{body}-{kind}-{idx}"


def apply_cmdr_to_survey(
    survey: SurveyState,
    cmdr: CmdrState | None,
) -> SurveyState:
    """Overlay persisted human headings, guardian site_type, bookmarks, FF flags."""
    if cmdr is None:
        return survey

    station = survey.system_station
    if station is not None:
        stored = cmdr.get_human_heading(station.market_id)
        if stored is not None and stored >= 0:
            station = replace(station, heading=float(stored))

    site = survey.current_guardian_site
    key = guardian_site_key(site)
    if site is not None and key:
        g = cmdr.guardian_sites.get(key)
        if g is not None and g.site_type:
            site = replace(site, site_type=g.site_type)

    # Merge cmdr chat bookmarks with journal Codex auto-track bookmarks.
    journal_marks = list(survey.bookmarks)
    seen = {
        (bm.body_name or "", bm.name, round(bm.latitude, 5), round(bm.longitude, 5))
        for bm in journal_marks
    }
    for bm in cmdr.tracker_bookmarks_for_body():
        key_t = (
            bm.body_name or "",
            bm.name,
            round(bm.latitude, 5),
            round(bm.longitude, 5),
        )
        if key_t in seen:
            continue
        journal_marks.append(bm)
        seen.add(key_t)
    bookmarks = tuple(journal_marks)

    fss_bodies = survey.fss_bodies
    if cmdr.body_flags and fss_bodies:
        updated_bodies = []
        changed = False
        for body in fss_bodies:
            flags = cmdr.body_flags.get(body.body_name) or {}
            if "first_foot" not in flags:
                updated_bodies.append(body)
                continue
            ff = bool(flags.get("first_foot"))
            if ff != bool(body.first_footfall):
                updated_bodies.append(replace(body, first_footfall=ff))
                changed = True
            else:
                updated_bodies.append(body)
        if changed:
            fss_bodies = tuple(updated_bodies)

    if (
        station is survey.system_station
        and site is survey.current_guardian_site
        and bookmarks == survey.bookmarks
        and fss_bodies is survey.fss_bodies
    ):
        return survey
    return replace(
        survey,
        system_station=station,
        current_guardian_site=site,
        bookmarks=bookmarks,
        fss_bodies=fss_bodies,
    )
