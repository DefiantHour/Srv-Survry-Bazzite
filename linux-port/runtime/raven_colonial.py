#!/usr/bin/env python3
"""RavenColonial HTTP client — Linux port of SrvSurvey/net/RavenColonial.cs.

Enough surface for PlotBuildCommodities: list a commander's linked fleet
carriers, fetch one FC by marketId, and sum cargo across FCs.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from client_identity import user_agent

# Matches RavenColonial.svcUri default when no override / debugger.
DEFAULT_SVC_URI = (
    "https://ravencolonial100-awcbdvabgze4c5cq.canadacentral-01.azurewebsites.net"
)
USER_AGENT = user_agent()
# Present loop polls ~0.75s; keep HTTP off the hot path after the first hit.
CACHE_TTL_SECONDS = 45.0
HTTP_TIMEOUT_SECONDS = 3.0

_cache: dict[str, tuple[float, Any]] = {}
_pending_updates = 0


def pending_count() -> int:
    """Windows PlotBuildCommodities.pendingUpdates mirror."""
    return max(0, _pending_updates)


def start_pending() -> None:
    global _pending_updates
    _pending_updates += 1


def end_pending() -> None:
    global _pending_updates
    _pending_updates = max(0, _pending_updates - 1)


@dataclass
class FleetCarrier:
    """Mirror of RavenColonial.FleetCarrier."""

    market_id: int
    name: str = ""
    display_name: str = ""
    cargo: dict[str, int] = field(default_factory=dict)


def resolve_svc_uri(override: str | None = None) -> str:
    """Resolve API base URI (Windows buildProjectsUrl_TEST / default Azure)."""
    if override and str(override).strip():
        return str(override).strip().rstrip("/")
    env = (
        os.environ.get("SRVSURVEY_BUILD_PROJECTS_URL")
        or os.environ.get("SRVSURVEY_RCC_URL")
        or ""
    ).strip()
    if env:
        return env.rstrip("/")
    return DEFAULT_SVC_URI


def _cache_get(key: str) -> Any | None:
    hit = _cache.get(key)
    if hit is None:
        return None
    expires, value = hit
    if time.monotonic() >= expires:
        _cache.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: Any, ttl: float = CACHE_TTL_SECONDS) -> None:
    _cache[key] = (time.monotonic() + ttl, value)


def clear_cache() -> None:
    """Drop all cached RCC responses (tests / forced refresh)."""
    _cache.clear()


def _http_request_json(
    url: str,
    *,
    method: str = "GET",
    body: str | None = None,
) -> tuple[int, str] | None:
    """HTTP JSON helper. Returns (status, body) or None on transport failure."""
    start_pending()
    try:
        data = body.encode("utf-8") if body is not None else None
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                return int(resp.status), resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            try:
                payload = exc.read().decode("utf-8", errors="replace")
            except Exception:
                payload = ""
            return int(exc.code), payload
        except (urllib.error.URLError, TimeoutError, OSError):
            return None
    finally:
        end_pending()


def _http_get_json(url: str) -> Any | None:
    result = _http_request_json(url, method="GET")
    if result is None:
        return None
    _status, raw = result
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _commodity_key(name: str) -> str:
    """Normalize cargo keys to match colony.commodity_key / depot needs."""
    key = name.strip()
    if key.startswith("$") and key.endswith(";"):
        key = key[1:-1]
    if key.endswith("_name"):
        key = key[: -len("_name")]
    return key.replace(" ", "").replace("-", "").lower()


def _parse_cargo(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for name, count in raw.items():
        if not isinstance(name, str) or not isinstance(count, (int, float)):
            continue
        key = _commodity_key(name)
        out[key] = out.get(key, 0) + int(count)
    return out


def _parse_fc(raw: object) -> FleetCarrier | None:
    if not isinstance(raw, dict):
        return None
    mid = raw.get("marketId")
    if not isinstance(mid, (int, float)):
        return None
    name = raw.get("name")
    display = raw.get("displayName")
    return FleetCarrier(
        market_id=int(mid),
        name=name if isinstance(name, str) else "",
        display_name=display if isinstance(display, str) else "",
        cargo=_parse_cargo(raw.get("cargo")),
    )


def get_fc(
    market_id: int | str,
    *,
    svc_uri: str | None = None,
) -> FleetCarrier | None:
    """GET /api/fc/{marketId} — RavenColonial.getFC."""
    if os.environ.get("SRVSURVEY_RCC_OFFLINE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return None
    mid = str(int(market_id)) if isinstance(market_id, (int, float)) else str(market_id)
    base = resolve_svc_uri(svc_uri)
    cache_key = f"fc:{base}:{mid}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached if cached is not False else None

    url = f"{base}/api/fc/{urllib.parse.quote(mid, safe='')}"
    data = _http_get_json(url)
    fc = _parse_fc(data) if data is not None else None
    _cache_set(cache_key, fc if fc is not None else False)
    return fc


def get_cmdr_fleet_carriers(
    cmdr: str,
    *,
    svc_uri: str | None = None,
) -> list[FleetCarrier]:
    """GET /api/cmdr/{cmdr}/fc/all — RavenColonial.getAllCmdrFCs."""
    name = (cmdr or "").strip()
    if not name:
        return []
    if os.environ.get("SRVSURVEY_RCC_OFFLINE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return []
    base = resolve_svc_uri(svc_uri)
    cache_key = f"cmdr-fc-all:{base}:{name.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)

    url = f"{base}/api/cmdr/{urllib.parse.quote(name, safe='')}/fc/all"
    data = _http_get_json(url)
    out: list[FleetCarrier] = []
    if isinstance(data, list):
        for row in data:
            fc = _parse_fc(row)
            if fc is not None:
                out.append(fc)
    _cache_set(cache_key, out)
    return list(out)


def sum_cargo(fcs: Iterable[FleetCarrier | Mapping[str, Any]]) -> dict[str, int]:
    """Sum cargo across FCs — ColonyData.getSumCargoFC."""
    total: dict[str, int] = {}
    for fc in fcs:
        if isinstance(fc, FleetCarrier):
            cargo = fc.cargo
        elif isinstance(fc, Mapping):
            raw = fc.get("cargo")
            cargo = raw if isinstance(raw, dict) else {}
            # Accept already-normalized or API-shaped maps.
            if cargo and not all(isinstance(v, int) for v in cargo.values()):
                cargo = _parse_cargo(cargo)
            else:
                cargo = {
                    _commodity_key(str(k)): int(v)
                    for k, v in cargo.items()
                    if isinstance(v, (int, float))
                }
        else:
            continue
        for commodity, amount in cargo.items():
            key = _commodity_key(commodity) if isinstance(commodity, str) else str(commodity)
            total[key] = total.get(key, 0) + int(amount)
    return total


def linked_fc_cargo_for_cmdr(
    cmdr: str,
    *,
    svc_uri: str | None = None,
) -> tuple[dict[str, int], int]:
    """Convenience: (sum_cargo, fc_count) for a commander, fail-soft."""
    try:
        fcs = get_cmdr_fleet_carriers(cmdr, svc_uri=svc_uri)
    except Exception:
        return {}, 0
    if not fcs:
        return {}, 0
    return sum_cargo(fcs), len(fcs)


def _rcc_offline() -> bool:
    for key in ("SRVSURVEY_RCC_OFFLINE", "SRVSURVEY_NET_OFFLINE", "SRVSURVEY_GGG_OFFLINE"):
        if os.environ.get(key, "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def _ggg_dry_run() -> bool:
    return os.environ.get("SRVSURVEY_GGG_DRYRUN", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


# Tests may replace PUT; (url, payload_json) → (status, body).
_put_hook: Any = None


def set_put_hook(hook: Any) -> None:
    """Inject PUT implementation for tests (None restores urllib)."""
    global _put_hook
    _put_hook = hook


def _http_put_json(
    url: str,
    payload: Mapping[str, Any],
    *,
    extra_headers: Mapping[str, str] | None = None,
) -> tuple[int, str]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if _put_hook is not None:
        return _put_hook(url, body.decode("utf-8"))
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if extra_headers:
        headers.update({str(k): str(v) for k, v in extra_headers.items() if v})
    req = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return int(getattr(resp, "status", 200) or 200), raw
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:
            raw = str(exc)
        return int(exc.code), raw
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, str(exc)


def _rcc_api_key() -> str | None:
    return get_rcc_api_key()


def _rcc_dry_run() -> bool:
    return os.environ.get("SRVSURVEY_RCC_DRY_RUN", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    } or os.environ.get("SRVSURVEY_DRY_RUN", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def get_rcc_api_key(api_key: str | None = None) -> str | None:
    """RCC key from argument or XDG secrets (never main config)."""
    key = (api_key or "").strip()
    if key:
        return key
    try:
        from secrets_store import RCC_API_KEY, get_secret

        return get_secret(RCC_API_KEY)
    except Exception:
        return None


def _empty_mut_result() -> dict[str, Any]:
    return {
        "ok": False,
        "skipped": False,
        "dry_run": False,
        "status_code": None,
        "body": "",
    }


def _http_mut_json(
    method: str,
    url: str,
    payload: Mapping[str, Any] | list[Any] | None = None,
    *,
    api_key: str | None = None,
) -> tuple[int, str]:
    """Authenticated mutating HTTP. Sends ``rcc-key`` when a key is provided."""
    body_text = (
        json.dumps(payload, separators=(",", ":")) if payload is not None else None
    )
    if _put_hook is not None and method.upper() in {"PUT", "POST", "PATCH", "DELETE"}:
        return _put_hook(url, body_text or "")
    data = body_text.encode("utf-8") if body_text is not None else None
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["rcc-key"] = api_key
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return int(getattr(resp, "status", 200) or 200), raw
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:
            raw = str(exc)
        return int(exc.code), raw
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, str(exc)


def publish_current_ship(
    fid: str,
    ship: Mapping[str, Any],
    *,
    api_key: str | None = None,
    svc_uri: str | None = None,
) -> dict[str, Any]:
    """POST /api/cmdr/currentShip — RavenColonial.publishCurrentShip."""
    result = _empty_mut_result()
    if _rcc_offline():
        result["skipped"] = True
        result["body"] = "offline"
        return result
    key = get_rcc_api_key(api_key)
    if not key:
        result["skipped"] = True
        result["body"] = "no rcc api key"
        return result
    if not (fid or "").strip():
        result["skipped"] = True
        result["body"] = "missing fid"
        return result
    payload = {
        "cmdr": ship.get("cmdr") or "",
        "name": ship.get("name") or "",
        "type": ship.get("type") or "",
        "maxCargo": int(ship.get("maxCargo") or 0),
        "cargo": dict(ship.get("cargo") or {}),
    }
    base = resolve_svc_uri(svc_uri)
    url = f"{base}/api/cmdr/currentShip"
    if _rcc_dry_run():
        result["ok"] = True
        result["dry_run"] = True
        result["body"] = json.dumps({"url": url, "fid": fid, "ship": payload})
        return result
    try:
        status, text = _http_mut_json("POST", url, payload, api_key=key)
    except Exception as exc:
        result["body"] = str(exc)
        return result
    result["status_code"] = status
    result["body"] = text
    result["ok"] = 200 <= status < 300
    return result


def supply_fc(
    fid: str,
    market_id: int,
    diff: Mapping[str, int],
    *,
    api_key: str | None = None,
    svc_uri: str | None = None,
) -> dict[str, Any]:
    """PATCH /api/fc/{marketId}/cargo — RavenColonial.supplyFC."""
    result = _empty_mut_result()
    if _rcc_offline():
        result["skipped"] = True
        result["body"] = "offline"
        return result
    key = get_rcc_api_key(api_key)
    if not key or int(market_id or 0) <= 0:
        result["skipped"] = True
        result["body"] = "missing key or market id"
        return result
    base = resolve_svc_uri(svc_uri)
    url = f"{base}/api/fc/{urllib.parse.quote(str(int(market_id)), safe='')}/cargo"
    payload = {str(name): int(count) for name, count in diff.items()}
    if _rcc_dry_run():
        result["ok"] = True
        result["dry_run"] = True
        result["body"] = json.dumps({"url": url, "fid": fid, "diff": payload})
        return result
    try:
        status, text = _http_mut_json("PATCH", url, payload, api_key=key)
    except Exception as exc:
        result["body"] = str(exc)
        return result
    result["status_code"] = status
    result["body"] = text
    result["ok"] = 200 <= status < 300
    return result


def get_published_quests(
    fid: str,
    *,
    api_key: str | None = None,
    svc_uri: str | None = None,
) -> list[dict[str, Any]]:
    """GET /api/quest/published — RavenColonial.getPublishedQuests."""
    if _rcc_offline() or not (fid or "").strip():
        return []
    key = get_rcc_api_key(api_key)
    if not key or _rcc_dry_run():
        return []
    base = resolve_svc_uri(svc_uri)
    url = f"{base}/api/quest/published"
    try:
        status, text = _http_mut_json("GET", url, None, api_key=key)
    except Exception:
        return []
    if status in {401, 404} or not (200 <= status < 300):
        return []
    try:
        data = json.loads(text) if text else []
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def publish_fc(
    market_id: int | str,
    fc: Mapping[str, Any] | FleetCarrier | None = None,
    *,
    fid: str | None = None,
    api_key: str | None = None,
    svc_uri: str | None = None,
) -> dict[str, Any]:
    """PUT /api/fc/{marketId} — RavenColonial.publishFC (needs rcc-key).

    Signature matches Avalonia ``RavenColonialClient`` / tests: ``(market_id, fc)``.
    Optional ``fid`` is accepted for Windows parity logging only.
    """
    result = _empty_mut_result()
    mid = str(int(market_id) if isinstance(market_id, (int, float)) else str(market_id).strip())
    if not mid or mid == "0":
        # Allow marketId inside fc when first arg is a placeholder.
        if isinstance(fc, Mapping):
            raw = fc.get("marketId", fc.get("market_id"))
            if raw is not None:
                mid = str(int(raw) if isinstance(raw, (int, float)) else str(raw).strip())
        elif isinstance(fc, FleetCarrier):
            mid = str(fc.market_id)
    if not mid:
        result["skipped"] = True
        result["body"] = "missing marketId"
        return result
    if _rcc_offline():
        result["skipped"] = True
        result["body"] = "offline"
        return result

    if isinstance(fc, FleetCarrier):
        payload: dict[str, Any] = {
            "marketId": fc.market_id,
            "name": fc.name,
            "displayName": fc.display_name,
            "cargo": dict(fc.cargo) if fc.cargo else None,
        }
    elif isinstance(fc, Mapping):
        cargo = fc.get("cargo")
        payload = {
            "marketId": int(mid) if mid.isdigit() else mid,
            "name": fc.get("name") or "",
            "displayName": fc.get("displayName") or fc.get("display_name") or "",
            "cargo": cargo if isinstance(cargo, dict) else None,
        }
    else:
        payload = {
            "marketId": int(mid) if mid.isdigit() else mid,
            "name": "",
            "displayName": "",
            "cargo": None,
        }

    key = get_rcc_api_key(api_key)
    base = resolve_svc_uri(svc_uri)
    url = f"{base}/api/fc/{urllib.parse.quote(mid, safe='')}"
    if _rcc_dry_run() or not key:
        result["ok"] = True
        result["dry_run"] = True
        result["skipped"] = not bool(key)
        result["body"] = json.dumps(
            {"url": url, "fid": fid, "fc": payload, "has_key": bool(key)}
        )
        return result
    try:
        status, text = _http_mut_json("PUT", url, payload, api_key=key)
    except Exception as exc:
        result["body"] = str(exc)
        return result
    result["status_code"] = status
    result["body"] = text
    result["ok"] = 200 <= status < 300
    if result["ok"]:
        clear_cache()
    return result


# Windows method alias
publishFC = publish_fc


def get_cmdr_active_projects(
    cmdr: str,
    *,
    svc_uri: str | None = None,
) -> list[dict[str, Any]]:
    """GET /api/cmdr/{cmdr}/active — list colonisation projects."""
    name = (cmdr or "").strip()
    if not name or _rcc_offline():
        return []
    base = resolve_svc_uri(svc_uri)
    url = f"{base}/api/cmdr/{urllib.parse.quote(name, safe='')}/active"
    data = _http_get_json(url)
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def get_system(
    name_or_num: str,
    *,
    svc_uri: str | None = None,
) -> dict[str, Any] | None:
    """GET /api/v2/system/{nameOrNum} — RavenColonial.getSystem (sites/bodies)."""
    target = (name_or_num or "").strip()
    if not target or _rcc_offline():
        return None
    base = resolve_svc_uri(svc_uri)
    url = f"{base}/api/v2/system/{urllib.parse.quote(target, safe='')}"
    data = _http_get_json(url)
    return data if isinstance(data, dict) else None


getSystem = get_system


def upload_ggg(
    cmdr: str,
    tag: str,
    star_pos: list[float] | tuple[float, ...],
    json_body: str,
    *,
    svc_uri: str | None = None,
) -> dict[str, Any]:
    """PUT /api/ggg/create — RavenColonial.uploadGGG. Offline-safe / dry-run.

    Returns a small status dict. Never raises for network failures.
    """
    result: dict[str, Any] = {
        "ok": False,
        "skipped": False,
        "dry_run": False,
        "status_code": None,
        "body": "",
    }
    name = (cmdr or "").strip()
    if not name or not tag:
        result["skipped"] = True
        result["body"] = "missing cmdr/tag"
        return result
    if _rcc_offline():
        result["skipped"] = True
        result["body"] = "offline"
        return result

    payload = {
        "cmdr": name,
        "tag": tag,
        "starPos": [float(star_pos[0]), float(star_pos[1]), float(star_pos[2])],
        "json": json_body,
    }
    base = resolve_svc_uri(svc_uri)
    url = f"{base}/api/ggg/create"

    if _ggg_dry_run():
        result["ok"] = True
        result["dry_run"] = True
        result["body"] = json.dumps(payload)
        return result

    try:
        status, text = _http_put_json(url, payload)
    except Exception as exc:
        result["body"] = str(exc)
        return result
    result["status_code"] = status
    result["body"] = text
    result["ok"] = 200 <= status < 300
    return result


def update_system(
    fid: str,
    name_or_num: str,
    sites_put: Mapping[str, Any] | None = None,
    *,
    api_key: str | None = None,
    svc_uri: str | None = None,
) -> dict[str, Any]:
    """PUT /api/v2/system/{nameOrNum}/sites — RavenColonial.updateSystem."""
    result = _empty_mut_result()
    if _rcc_offline():
        result["skipped"] = True
        result["body"] = "offline"
        return result
    key = get_rcc_api_key(api_key)
    if not key:
        result["skipped"] = True
        result["body"] = "no rcc api key"
        return result
    target = (name_or_num or "").strip()
    if not target:
        result["skipped"] = True
        result["body"] = "missing system"
        return result
    payload = dict(sites_put) if sites_put else {"update": [], "delete": []}
    base = resolve_svc_uri(svc_uri)
    url = f"{base}/api/v2/system/{urllib.parse.quote(target, safe='')}/sites"
    if _rcc_dry_run():
        result["ok"] = True
        result["dry_run"] = True
        result["body"] = json.dumps({"url": url, "fid": fid, "data": payload})
        return result
    try:
        status, text = _http_mut_json("PUT", url, payload, api_key=key)
    except Exception as exc:
        result["body"] = str(exc)
        return result
    result["status_code"] = status
    result["body"] = text
    result["ok"] = 200 <= status < 300
    return result


updateSystem = update_system


def set_primary(
    cmdr: str,
    build_id: str | None,
    *,
    svc_uri: str | None = None,
) -> dict[str, Any]:
    """PUT/DELETE /api/cmdr/{cmdr}/primary/{buildId} — RavenColonial.setPrimary."""
    result = _empty_mut_result()
    if _rcc_offline():
        result["skipped"] = True
        result["body"] = "offline"
        return result
    name = (cmdr or "").strip()
    if not name:
        result["skipped"] = True
        result["body"] = "missing cmdr"
        return result
    base = resolve_svc_uri(svc_uri)
    if build_id is None or not str(build_id).strip():
        url = f"{base}/api/cmdr/{urllib.parse.quote(name, safe='')}/primary/"
        method = "DELETE"
    else:
        bid = str(build_id).strip()
        url = (
            f"{base}/api/cmdr/{urllib.parse.quote(name, safe='')}"
            f"/primary/{urllib.parse.quote(bid, safe='')}"
        )
        method = "PUT"
    if _rcc_dry_run():
        result["ok"] = True
        result["dry_run"] = True
        result["body"] = json.dumps({"method": method, "url": url, "buildId": build_id})
        return result
    try:
        status, text = _http_mut_json(method, url, None)
    except Exception as exc:
        result["body"] = str(exc)
        return result
    result["status_code"] = status
    result["body"] = text
    result["ok"] = 200 <= status < 300
    return result


setPrimary = set_primary


def update_sys_bodies(
    address: int | str,
    bodies: list[Mapping[str, Any]],
    *,
    svc_uri: str | None = None,
) -> dict[str, Any]:
    """PUT /api/v2/system/{address}/bodies — RavenColonial.updateSysBodies."""
    result = _empty_mut_result()
    if _rcc_offline():
        result["skipped"] = True
        result["body"] = "offline"
        return result
    addr = str(address).strip()
    if not addr:
        result["skipped"] = True
        result["body"] = "missing address"
        return result
    base = resolve_svc_uri(svc_uri)
    url = f"{base}/api/v2/system/{urllib.parse.quote(addr, safe='')}/bodies"
    payload_list: list[Any] = list(bodies)
    if _rcc_dry_run():
        result["ok"] = True
        result["dry_run"] = True
        result["body"] = json.dumps({"url": url, "count": len(payload_list)})
        return result
    try:
        status, text = _http_mut_json("PUT", url, payload_list)
    except Exception as exc:
        result["body"] = str(exc)
        return result
    result["status_code"] = status
    result["body"] = text
    result["ok"] = 200 <= status < 300
    return result


updateSysBodies = update_sys_bodies


def _cli_main(argv: list[str] | None = None) -> int:
    """Small CLI for Avalonia ExternalLauncher / manual RCC writes."""
    import argparse

    parser = argparse.ArgumentParser(description="RavenColonial mutating helpers")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fc = sub.add_parser("publish-fc", aliases=["publishFC"])
    p_fc.add_argument("--fid", default="")
    p_fc.add_argument("--market-id", type=int, required=True)
    p_fc.add_argument("--name", required=True)
    p_fc.add_argument("--display-name", default="")
    p_fc.add_argument("--svc-uri", default=None)

    p_sys = sub.add_parser("update-system", aliases=["updateSystem"])
    p_sys.add_argument("--fid", default="")
    p_sys.add_argument("--system", required=True)
    p_sys.add_argument("--architect", default=None)
    p_sys.add_argument("--svc-uri", default=None)

    p_pri = sub.add_parser("set-primary", aliases=["setPrimary"])
    p_pri.add_argument("--cmdr", required=True)
    p_pri.add_argument("--build-id", default=None)
    p_pri.add_argument("--clear", action="store_true")
    p_pri.add_argument("--svc-uri", default=None)

    p_bod = sub.add_parser("update-sys-bodies", aliases=["updateSysBodies"])
    p_bod.add_argument("--address", required=True)
    p_bod.add_argument("--bodies-json", default="[]")
    p_bod.add_argument("--svc-uri", default=None)

    args = parser.parse_args(argv)
    if args.cmd in {"publish-fc", "publishFC"}:
        out = publish_fc(
            args.market_id,
            {
                "marketId": args.market_id,
                "name": args.name,
                "displayName": args.display_name,
            },
            fid=args.fid or None,
            svc_uri=args.svc_uri,
        )
    elif args.cmd in {"update-system", "updateSystem"}:
        data: dict[str, Any] = {"update": [], "delete": []}
        if args.architect:
            data["architect"] = args.architect
        out = update_system(args.fid or "", args.system, data, svc_uri=args.svc_uri)
    elif args.cmd in {"set-primary", "setPrimary"}:
        bid = None if args.clear else args.build_id
        out = set_primary(args.cmdr, bid, svc_uri=args.svc_uri)
    else:
        bodies = json.loads(args.bodies_json)
        if not isinstance(bodies, list):
            print(json.dumps({"ok": False, "body": "bodies-json must be a list"}))
            return 2
        out = update_sys_bodies(args.address, bodies, svc_uri=args.svc_uri)
    print(json.dumps(out))
    return 0 if out.get("ok") or out.get("skipped") or out.get("dry_run") else 1


if __name__ == "__main__":
    raise SystemExit(_cli_main())
