#!/usr/bin/env python3
"""Canonn getSystemPoi client — Linux port of SrvSurvey/net/Canonn.cs (POI subset).

Offline by default when ``SRVSURVEY_CANONN_OFFLINE=1`` (or RCC offline).
Returns an empty SystemPoi when unreachable so PlotPriorScans stays safe.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from client_identity import user_agent

CANONN_POI_URL = (
    "https://us-central1-canonn-api-236217.cloudfunctions.net/query/getSystemPoi"
)
USER_AGENT = user_agent()
CACHE_TTL_SECONDS = 120.0
HTTP_TIMEOUT_SECONDS = 4.0

_cache: dict[str, tuple[float, Any]] = {}
# Windows keeps Game.canonnPoi until the system changes. The HTTP cache TTL
# is only for refetch; PlotSysStatus.allowed must not forget the object.
_sticky_poi: dict[str, Any] = {}


@dataclass(frozen=True)
class CodexPoi:
    """One Canonn SystemPoi.codex row with optional lat/long."""

    body: str | None = None
    english_name: str | None = None
    entry_id: int | None = None
    hud_category: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    scanned: bool = False


@dataclass
class SystemPoi:
    """Mirror of SrvSurvey.canonn.SystemPoi (codex + system name)."""

    system: str | None = None
    cmdr_name: str | None = None
    codex: list[CodexPoi] = field(default_factory=list)


def clear_cache() -> None:
    _cache.clear()
    _sticky_poi.clear()


def _offline() -> bool:
    for key in (
        "SRVSURVEY_CANONN_OFFLINE",
        "SRVSURVEY_RCC_OFFLINE",
        "SRVSURVEY_NET_OFFLINE",
        "SRVSURVEY_DRY_RUN",
    ):
        if os.environ.get(key, "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def _cache_get(key: str) -> Any | None:
    hit = _cache.get(key)
    if hit is None:
        return None
    expires, value = hit
    if time.monotonic() >= expires:
        _cache.pop(key, None)
        return None
    return value


def _remember_poi(value: Any) -> None:
    if isinstance(value, SystemPoi):
        system = (value.system or "").strip()
        if system:
            _sticky_poi[system.lower()] = value


def _sticky_for(system_name: str) -> Any | None:
    system = (system_name or "").strip()
    if not system:
        return None
    return _sticky_poi.get(system.lower())


def _cache_set(key: str, value: Any, ttl: float = CACHE_TTL_SECONDS) -> None:
    _cache[key] = (time.monotonic() + ttl, value)
    _remember_poi(value)


def _http_get_json(url: str) -> Any | None:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return None
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _as_float(raw: object) -> float | None:
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def _as_int(raw: object) -> int | None:
    if isinstance(raw, (int, float)):
        return int(raw)
    return None


def _parse_codex_row(row: object) -> CodexPoi | None:
    if not isinstance(row, dict):
        return None
    scanned_raw = row.get("scanned")
    scanned = False
    if isinstance(scanned_raw, bool):
        scanned = scanned_raw
    elif isinstance(scanned_raw, str):
        scanned = scanned_raw.strip().lower() in {"1", "true", "yes", "y"}
    return CodexPoi(
        body=row.get("body") if isinstance(row.get("body"), str) else None,
        english_name=(
            row.get("english_name")
            if isinstance(row.get("english_name"), str)
            else None
        ),
        entry_id=_as_int(row.get("entryid")),
        hud_category=(
            row.get("hud_category")
            if isinstance(row.get("hud_category"), str)
            else None
        ),
        latitude=_as_float(row.get("latitude")),
        longitude=_as_float(row.get("longitude")),
        scanned=scanned,
    )


def parse_system_poi(data: object) -> SystemPoi:
    if not isinstance(data, dict):
        return SystemPoi()
    codex: list[CodexPoi] = []
    raw_codex = data.get("codex")
    if isinstance(raw_codex, list):
        for row in raw_codex:
            poi = _parse_codex_row(row)
            if poi is not None:
                codex.append(poi)
    return SystemPoi(
        system=data.get("system") if isinstance(data.get("system"), str) else None,
        cmdr_name=(
            data.get("cmdrName") if isinstance(data.get("cmdrName"), str) else None
        ),
        codex=codex,
    )


def empty_system_poi(system: str | None = None, cmdr: str | None = None) -> SystemPoi:
    """Offline / failure stub — no signals."""
    return SystemPoi(system=system, cmdr_name=cmdr, codex=[])


def get_system_poi(
    system_name: str,
    cmdr_name: str = "",
    *,
    force_offline: bool = False,
) -> SystemPoi:
    """Fetch Canonn SystemPoi (cached). Empty stub when offline or on error."""
    system = (system_name or "").strip()
    cmdr = (cmdr_name or "").strip() or "Unknown"
    if not system:
        return empty_system_poi(None, cmdr)
    if force_offline or _offline():
        return empty_system_poi(system, cmdr)

    cache_key = f"poi:{system.lower()}/{cmdr.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    sticky = _sticky_for(system)
    if sticky is not None:
        _cache_set(cache_key, sticky)
        return sticky

    query = urllib.parse.urlencode(
        {"system": system, "odyssey": "Y", "cmdr": cmdr}
    )
    data = _http_get_json(f"{CANONN_POI_URL}?{query}")
    poi = parse_system_poi(data) if data is not None else empty_system_poi(system, cmdr)
    if poi.system is None:
        poi.system = system
    if poi.cmdr_name is None:
        poi.cmdr_name = cmdr
    _cache_set(cache_key, poi)
    return poi


def peek_cached_poi(system_name: str, cmdr_name: str = "") -> SystemPoi | None:
    """Return a cached SystemPoi without a network fetch. None if uncached.

    When ``cmdr_name`` is empty, any cached row for the system matches.
    Prefetch stores ``poi:<system>/<cmdr>``; PlotSysStatus only has the system.
    """
    system = (system_name or "").strip()
    if not system:
        return None
    cmdr = (cmdr_name or "").strip()
    if cmdr:
        hit = _cache_get(f"poi:{system.lower()}/{cmdr.lower()}")
        if hit is not None:
            return hit
        return _sticky_for(system)
    prefix = f"poi:{system.lower()}/"
    now = time.monotonic()
    for key, hit in _cache.items():
        if not key.startswith(prefix):
            continue
        expires, value = hit
        if now < expires:
            return value
    return _sticky_for(system)


def has_local_bio_signals(
    poi: SystemPoi | None,
    body_short: str | None,
    *,
    hide_own: bool = True,
) -> bool:
    """Match Game.canonnPoiHasLocalBioSignals (no organism analyzed check)."""
    if poi is None or not poi.codex or not body_short:
        return False
    short = body_short.replace(" ", "")
    for row in poi.codex:
        if row.hud_category != "Biology":
            continue
        if row.latitude is None or row.longitude is None:
            continue
        body = (row.body or "").replace(" ", "")
        if body != short:
            continue
        if hide_own and row.scanned:
            continue
        return True
    return False


CANONN_BIO_URL = (
    "https://us-central1-canonn-api-236217.cloudfunctions.net/query/codex/bodies/{address}"
)
CANONN_STATIONS_URL = (
    "https://us-central1-canonn-api-236217.cloudfunctions.net/query/srvsurvey/system/{address}"
)
CANONN_STATION_POST = (
    "https://us-central1-canonn-api-236217.cloudfunctions.net/postEvent/srvsurvey/stations"
)
CANONN_GRAPHQL = "https://api.canonn.tech/graphql"
CANONN_NEAREST_URL = (
    "https://us-central1-canonn-api-236217.cloudfunctions.net/query/nearest/codex"
)


def _skipped(reason: str = "offline") -> dict[str, Any]:
    return {"ok": False, "skipped": True, "reason": reason, "result": None}


def _http_send(url: str, payload: dict[str, Any] | str | None, method: str) -> Any | None:
    data = None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if payload is not None:
        if isinstance(payload, str):
            data = payload.encode("utf-8")
        else:
            data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return None
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def system_bio_stats(system_address: int) -> dict[str, Any]:
    """GET Canonn codex/bodies/{systemAddress}. Never called when offline."""
    addr = int(system_address or 0)
    if addr <= 0:
        return _skipped("missing address")
    if _offline():
        return _skipped("offline")
    cache_key = f"bio:{addr}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return {"ok": True, "skipped": False, "reason": "", "result": cached}
    data = _http_get_json(CANONN_BIO_URL.format(address=addr))
    rows = data if isinstance(data, list) else []
    _cache_set(cache_key, rows)
    return {"ok": data is not None, "skipped": False, "reason": "", "result": rows}


def get_stations(system_address: int) -> dict[str, Any]:
    """GET srvsurvey/system/{address} and unwrap raw_json station rows."""
    addr = int(system_address or 0)
    if addr <= 0:
        return _skipped("missing address")
    if _offline():
        return _skipped("offline")
    data = _http_get_json(CANONN_STATIONS_URL.format(address=addr))
    stations: list[Any] = []
    if isinstance(data, list):
        for row in data:
            if not isinstance(row, dict):
                continue
            raw = row.get("raw_json")
            if isinstance(raw, str) and raw.strip():
                try:
                    stations.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
            elif isinstance(raw, dict):
                stations.append(raw)
    return {"ok": data is not None, "skipped": False, "reason": "", "result": stations}


def _http_status(url: str, payload: dict[str, Any] | str | None, method: str) -> tuple[int, Any | None]:
    data = None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if payload is not None:
        if isinstance(payload, str):
            data = payload.encode("utf-8")
        else:
            data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = int(getattr(resp, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        return int(exc.code), None
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, None
    if not raw.strip():
        return status, None
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def submit_station(station: dict[str, Any]) -> dict[str, Any]:
    """POST a station survey. Offline / dry-run never POST.

    A transport failure or HTTP 5xx is queued and retried later. 4xx is not.
    """
    if _offline():
        return _skipped("offline")
    from mutation_queue import drain, enqueue
    from paths import srvsurvey_data_dir

    data_dir = srvsurvey_data_dir()

    def _post(url: str, body: str) -> tuple[int, str]:
        status, _parsed = _http_status(url, body, "POST")
        return status, ""

    drain("canonn", _post, data_dir=data_dir)
    status, body = _http_status(CANONN_STATION_POST, station, "POST")
    if status == 0 or status >= 500:
        enqueue("canonn", CANONN_STATION_POST, json.dumps(station), data_dir=data_dir)
        return {
            "ok": False,
            "skipped": False,
            "queued": True,
            "reason": "queued",
            "result": None,
        }
    if status < 200 or status >= 300:
        return {
            "ok": False,
            "skipped": False,
            "queued": False,
            "reason": f"HTTP {status}",
            "result": body,
        }
    return {"ok": True, "skipped": False, "queued": False, "reason": "", "result": body}


def _graphql(query: str) -> Any | None:
    payload = {"operationName": None, "variables": {}, "query": query}
    return _http_send(CANONN_GRAPHQL, payload, "POST")


def get_ruins_reports(
    body_name: str,
    idx: int,
    *,
    descending: bool = True,
) -> dict[str, Any]:
    """POST Canonn GraphQL grreports for one ruin. Offline never POSTs."""
    if _offline():
        return _skipped("offline")
    order = "DESC" if descending else "ASC"
    safe_body = body_name.replace('"', "")
    query = (
        "{ grreports(limit:32, sort: \"updated_at:"
        + order
        + "\", where: { bodyName: \""
        + safe_body
        + "\", frontierID: "
        + str(int(idx))
        + " }) { updated_at type latitude longitude } }"
    )
    data = _graphql(query)
    reports: list[Any] = []
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, dict) and isinstance(inner.get("grreports"), list):
            reports = inner["grreports"]
    return {"ok": data is not None, "skipped": False, "reason": "", "result": reports}


def get_ruins_reports_by_cmdr(cmdr_name: str) -> dict[str, Any]:
    if _offline():
        return _skipped("offline")
    safe = cmdr_name.replace('"', "")
    query = (
        "{ grreports(limit:1000, where: { cmdrName: \""
        + safe
        + "\" }) { updated_at type latitude longitude bodyName frontierID } }"
    )
    data = _graphql(query)
    reports: list[Any] = []
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, dict) and isinstance(inner.get("grreports"), list):
            reports = inner["grreports"]
    return {"ok": data is not None, "skipped": False, "reason": "", "result": reports}


def get_raw_ruins() -> dict[str, Any]:
    """POST Canonn GraphQL grsites. Offline never POSTs."""
    if _offline():
        return _skipped("offline")
    query = (
        "{ grsites(limit: 1000) { id siteID updated_at system { systemName id64 } "
        "body { bodyName bodyID } type { type } latitude longitude frontierID } }"
    )
    data = _graphql(query)
    sites: list[Any] = []
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, dict) and isinstance(inner.get("grsites"), list):
            sites = inner["grsites"]
    return {"ok": data is not None, "skipped": False, "reason": "", "result": sites}


def find_nearest_system_with_bio(
    x: float,
    y: float,
    z: float,
    bio_name: str,
    limit: int = 5,
) -> dict[str, Any]:
    """GET /query/nearest/codex. Offline never GETs."""
    name = (bio_name or "").strip()
    if not name:
        return _skipped("missing bio name")
    if _offline():
        return _skipped("offline")
    query = urllib.parse.urlencode(
        {
            "x": f"{x:.5f}",
            "y": f"{y:.5f}",
            "z": f"{z:.5f}",
            "name": name,
            "limit": str(int(limit)),
        }
    )
    data = _http_get_json(f"{CANONN_NEAREST_URL}?{query}")
    return {"ok": isinstance(data, dict), "skipped": False, "reason": "", "result": data}


def import_canonn_challenge(
    commander: str,
    *,
    codex_rows: list[dict[str, Any]],
    known_ids: set[int] | list[int] | None = None,
    fetch: Any = None,
) -> dict[str, Any]:
    """Windows Canonn.importCanonnChallenge.

    GET challenge/status for the commander. Match types_found to local codex
    rows by english_name and hud_category. Return new entry ids. Does not POST.
    ``fetch`` replaces the HTTP call in tests. Offline and dry-run skip.
    """
    name = (commander or "").strip()
    if not name:
        return {"ok": False, "skipped": True, "reason": "missing commander", "added": []}
    if _offline():
        return {"ok": False, "skipped": True, "reason": "offline", "added": []}
    url = (
        "https://us-central1-canonn-api-236217.cloudfunctions.net"
        f"/query/challenge/status?cmdr={urllib.parse.quote(name)}"
    )
    getter = fetch if fetch is not None else _http_get_json
    data = getter(url)
    if not isinstance(data, dict):
        return {"ok": False, "skipped": False, "reason": "no response", "added": []}
    known = {int(item) for item in (known_ids or [])}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in codex_rows:
        if not isinstance(row, dict):
            continue
        english = str(row.get("english_name") or "")
        if english:
            by_name.setdefault(english, []).append(row)
    added: list[int] = []
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        found = entry.get("types_found")
        if not isinstance(found, list):
            continue
        category = str(entry.get("hud_category") or "")
        for found_type in found:
            matches = by_name.get(str(found_type), [])
            match = next(
                (row for row in matches if str(row.get("hud_category") or "") == category),
                None,
            )
            if match is None:
                continue
            try:
                entry_id = int(match.get("entryid"))
            except (TypeError, ValueError):
                continue
            if entry_id in known or entry_id in added:
                continue
            added.append(entry_id)
    return {"ok": True, "skipped": False, "reason": "", "added": added}


def load_static_catalogs(repo_root: Path | None = None) -> dict[str, int]:
    """Canonn.init — local allRuins / allBeacons / allStructures counts. No network."""
    root = repo_root or Path(__file__).resolve().parents[2]
    counts = {"ruins": 0, "beacons": 0, "structures": 0}
    mapping = {
        "ruins": root / "SrvSurvey" / "allRuins.json",
        "beacons": root / "SrvSurvey" / "allBeacons.json",
        "structures": root / "SrvSurvey" / "allStructures.json",
    }
    for key, path in mapping.items():
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
        if isinstance(data, list):
            counts[key] = len(data)
    return counts
