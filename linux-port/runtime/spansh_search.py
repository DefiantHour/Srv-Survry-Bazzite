#!/usr/bin/env python3
"""Spansh bodies/systems search — Windows Spansh.queryBodies / querySystems.

POST https://spansh.co.uk/api/bodies/search and /api/systems/search.
Filter JSON matches CriteriaBuilder.buildQuery (atmosphere value lists,
volcanism_type, landmarks type/subtype, distance min~max, reference_system).
Offline / dry-run never POSTs.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from client_identity import user_agent

BODY_SEARCH_URL = "https://spansh.co.uk/api/bodies/search"
SYSTEM_SEARCH_URL = "https://spansh.co.uk/api/systems/search"
STATION_SEARCH_URL = "https://spansh.co.uk/api/stations/search"
NAME_VALUES_URL = "https://spansh.co.uk/api/systems/field_values/system_names?q="
HTTP_TIMEOUT_SECONDS = 20.0


def spansh_offline() -> bool:
    flags = (
        "SRVSURVEY_NET_OFFLINE",
        "SRVSURVEY_SPANSH_OFFLINE",
        "SRVSURVEY_DRY_RUN",
    )
    return any(os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"} for name in flags)


def build_bodies_query(
    filters: dict[str, str],
    *,
    sort_field: str = "distance",
    sort_dir: str = "asc",
    size: int = 10,
    page: int = 0,
    reference_system: str = "",
    reference_coords: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    """Build the JSON object Windows buildQuery would POST."""
    filt: dict[str, Any] = {}
    for key, raw in filters.items():
        value = (raw or "").strip()
        if not value:
            continue
        if "/" in value and key == "landmarks":
            landmarks = []
            for piece in value.split(","):
                parts = [p.strip() for p in piece.split("/") if p.strip()]
                if len(parts) >= 2:
                    landmarks.append({"type": parts[0], "subtype": [parts[1]]})
            if landmarks:
                filt["landmarks"] = landmarks
            continue
        if "~" in value:
            left, right = value.split("~", 1)
            filt[key] = {"min": _num(left), "max": _num(right)}
            continue
        value_key = "type" if key == "landmarks" else "value"
        filt[key] = {value_key: [part.strip() for part in value.split(",") if part.strip()]}

    if "/" in sort_field:
        group, name = sort_field.split("/", 1)
        sort = [{group: [{"name": name, "direction": sort_dir}]}]
    else:
        sort = [{sort_field: {"direction": sort_dir}}]

    query: dict[str, Any] = {
        "filters": filt,
        "sort": sort,
        "size": int(size),
        "page": int(page),
    }
    if reference_system.strip():
        query["reference_system"] = reference_system.strip()
    if reference_coords is not None and len(reference_coords) == 3:
        query["reference_coords"] = {
            "x": float(reference_coords[0]),
            "y": float(reference_coords[1]),
            "z": float(reference_coords[2]),
        }
    return query


def search_bodies(
    *,
    atmosphere: str = "",
    volcanism: str = "",
    planet_class: str = "",
    landmark: str = "",
    distance_ly: float | None = None,
    reference_system: str = "",
    reference_coords: tuple[float, float, float] | None = None,
    size: int = 10,
) -> dict[str, Any]:
    """Nearest bodies for atmosphere / volcanism / landmark filters."""
    filters: dict[str, str] = {}
    if atmosphere.strip():
        filters["atmosphere"] = atmosphere.strip()
    if volcanism.strip():
        filters["volcanism_type"] = volcanism.strip()
    if planet_class.strip():
        filters["subtype"] = planet_class.strip()
    if landmark.strip():
        filters["landmarks"] = landmark.strip()
    if distance_ly is not None and distance_ly > 0:
        filters["distance"] = f"0~{float(distance_ly)}"
    query = build_bodies_query(
        filters,
        sort_field="distance" if reference_system or reference_coords else "gravity",
        size=size,
        reference_system=reference_system,
        reference_coords=reference_coords,
    )
    return post_search(BODY_SEARCH_URL, query)


def search_systems(
    filters: dict[str, str],
    *,
    reference_system: str = "",
    size: int = 10,
) -> dict[str, Any]:
    query = build_bodies_query(
        filters,
        reference_system=reference_system,
        size=size,
    )
    return post_search(SYSTEM_SEARCH_URL, query)


def _pascal(word: str) -> str:
    text = (word or "").strip()
    if not text:
        return ""
    return text[0].upper() + text[1:]


def _pascal_words(text: str) -> str:
    parts: list[str] = []
    for part in (text or "").split(" "):
        if not part:
            continue
        parts.append(part[0].upper() + part[1:].lower())
    return " ".join(parts)


def build_missing_variants_query(
    x: float,
    y: float,
    z: float,
    genus: str,
    species: str,
    variant_colors: list[str],
) -> dict[str, Any]:
    """Windows CriteriaBuilder.buildMissingVariantsForSpecies."""
    variants = [_pascal(color) for color in variant_colors]
    return {
        "filters": {
            "landmarks": [
                {
                    "type": _pascal(genus),
                    "subtype": [_pascal_words(species)],
                    "variant": variants,
                }
            ]
        },
        "sort": [{"distance": {"direction": "asc"}}],
        "size": 10,
        "page": 0,
        "reference_coords": {"x": x, "y": y, "z": z},
    }


def poll_route(
    route_id: str,
    *,
    max_seconds: int = 60,
    pause_seconds: float = 5.0,
    fetch: Any = None,
    sleep: Any = None,
) -> dict[str, Any]:
    """Windows Spansh.getRoute: GET until state is completed and status is ok.

    ``fetch`` and ``sleep`` exist so tests do not wait on the network.
    Offline and dry-run return before the first GET.
    """
    if spansh_offline():
        return {"ok": False, "skipped": True, "reason": "offline", "result": None}
    getter = fetch if fetch is not None else fetch_route
    waiter = sleep if sleep is not None else time.sleep
    waited = 0.0
    limit = max(0, int(max_seconds)) * 1000
    last: dict[str, Any] = {"ok": False, "skipped": False, "reason": "timeout", "result": None}
    while waited < limit:
        last = getter(route_id)
        result = last.get("result") if isinstance(last, dict) else None
        if isinstance(result, dict) and result.get("state") == "completed" and result.get("status") == "ok":
            return last
        if isinstance(last, dict) and last.get("skipped"):
            return last
        waiter(pause_seconds)
        waited += max(pause_seconds, 0.001) * 1000
    return last


def fetch_route(route_id: str) -> dict[str, Any]:
    """GET /api/results/{id} — Windows Spansh.getRoute."""
    route = (route_id or "").strip().upper()
    if not route:
        return {"ok": False, "skipped": True, "reason": "missing route id", "result": None}
    if spansh_offline():
        return {"ok": False, "skipped": True, "reason": "offline", "result": None}
    url = f"https://spansh.co.uk/api/results/{route}"
    status, text = _http("GET", url, None)
    if status < 200 or status >= 300:
        return {"ok": False, "skipped": False, "reason": text[:200], "result": None}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"ok": False, "skipped": False, "reason": "bad json", "result": None}
    return {"ok": True, "skipped": False, "reason": "", "result": data if isinstance(data, dict) else None}


def post_search(url: str, query: dict[str, Any]) -> dict[str, Any]:
    if spansh_offline():
        return {
            "ok": False,
            "skipped": True,
            "reason": "offline",
            "count": 0,
            "results": [],
            "query": query,
        }
    status, text = _http("POST", url, query)
    if text.strip() == '{"error":"Invalid request"}':
        return {
            "ok": False,
            "skipped": False,
            "reason": "invalid request",
            "count": 0,
            "results": [],
            "query": query,
        }
    if status < 200 or status >= 300:
        return {
            "ok": False,
            "skipped": False,
            "reason": text[:200],
            "count": 0,
            "results": [],
            "query": query,
        }
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = {}
    results = data.get("results") if isinstance(data, dict) else None
    count = data.get("count") if isinstance(data, dict) else 0
    return {
        "ok": True,
        "skipped": False,
        "reason": "",
        "count": int(count or 0),
        "results": results if isinstance(results, list) else [],
        "query": query,
        "search_reference": data.get("search_reference") if isinstance(data, dict) else None,
    }


def _num(text: str) -> float | int:
    raw = text.strip()
    if "." in raw:
        return float(raw)
    return int(raw)


def _http(method: str, url: str, payload: dict[str, Any] | None) -> tuple[int, str]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"User-Agent": user_agent(), "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            return int(getattr(resp, "status", 200) or 200), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(exc)
        return int(exc.code), body
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, str(exc)


def get_system_names(system_name: str) -> dict[str, Any]:
    """GET Spansh field_values/system_names. Offline never GETs."""
    name = (system_name or "").strip()
    if not name:
        return {"ok": False, "skipped": True, "reason": "missing name", "min_max": []}
    if spansh_offline():
        return {"ok": False, "skipped": True, "reason": "offline", "min_max": []}
    status, text = _http("GET", NAME_VALUES_URL + urllib.parse.quote(name), None)
    if status < 200 or status >= 300:
        return {"ok": False, "skipped": False, "reason": text[:200], "min_max": []}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"ok": False, "skipped": False, "reason": "bad json", "min_max": []}
    rows = data.get("min_max") if isinstance(data, dict) else None
    return {
        "ok": True,
        "skipped": False,
        "reason": "",
        "min_max": rows if isinstance(rows, list) else [],
    }


def get_system_address(system_name: str) -> int:
    """Exact name match → id64, else 0. Offline returns 0 without a GET."""
    payload = get_system_names(system_name)
    if not payload.get("ok"):
        return 0
    for row in payload.get("min_max") or []:
        if isinstance(row, dict) and row.get("name") == system_name:
            raw = row.get("id64")
            if isinstance(raw, int):
                return raw
            if isinstance(raw, str) and raw.isdigit():
                return int(raw)
    return 0


def get_system_ref(system_name: str) -> dict[str, Any] | None:
    """First Spansh name hit, including inexact matches. Offline returns None."""
    payload = get_system_names(system_name)
    if not payload.get("ok"):
        return None
    rows = payload.get("min_max") or []
    first = rows[0] if rows else None
    return first if isinstance(first, dict) else None


def query_stations(query: dict[str, Any]) -> dict[str, Any]:
    """POST api/stations/search. Offline / dry-run never POSTs."""
    return post_search(STATION_SEARCH_URL, query)


def build_gas_clause(genus: str, species: str, gas: str) -> dict[str, Any]:
    """Windows Spansh.getClause query body. Does not search until query_bodies."""
    full = f"{genus} {species}".strip()
    return {
        "filters": {
            "atmosphere": {"value": [f"Thin {gas}"]},
            "landmarks": [{"type": genus, "subtype": [full]}],
        },
        "sort": [{"atmosphere_composition": [{"name": gas, "direction": "asc"}]}],
        "size": 1,
        "page": 0,
    }


def atmosphere_clause_from_result(gas: str, result: dict[str, Any]) -> str | None:
    """Turn one bodies-search row into the BioCriteria atmosComp clause string."""
    if not result:
        return None
    rows = result.get("atmosphere_composition")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict) or row.get("name") != gas:
            continue
        share = row.get("share")
        if not isinstance(share, (int, float)):
            continue
        value = f"{float(share):.2f}"
        if value == "100.00":
            value = "100"
        name = "".join(part.capitalize() for part in str(gas).split())
        return f'"atmosComp [{name} >= {value}]"'
    return None
