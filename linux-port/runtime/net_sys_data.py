#!/usr/bin/env python3
"""Spansh / EDSM NetSysData client — Linux port of SrvSurvey/net/NetSysData.cs.

Fetches EDSM bodies + traffic and Spansh system dumps with a TTL cache.
Offline when ``SRVSURVEY_NET_OFFLINE=1`` (all) or ``SRVSURVEY_SPANSH_OFFLINE=1``
(Spansh only). Failures return a partial NetSysData so plotters stay safe.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from journal import LandingPads, StationInfo

from client_identity import user_agent

EDSM_SYSTEMS_URL = "https://www.edsm.net/api-v1/systems"
EDSM_BODIES_URL = "https://www.edsm.net/api-system-v1/bodies"
EDSM_TRAFFIC_URL = "https://www.edsm.net/api-system-v1/traffic"
EDSM_STATIONS_URL = "https://www.edsm.net/api-system-v1/stations"
SPANSH_DUMP_URL = "https://spansh.co.uk/api/dump/{address}/"
USER_AGENT = user_agent()
CACHE_TTL_SECONDS = 120.0
HTTP_TIMEOUT_SECONDS = 4.0

# EdsmSystemStations.Starports (large pads, excl. FC / mega-ship)
_STARPORTS = frozenset(
    {
        "Coriolis Starport",
        "Orbis Starport",
        "Ocellus Starport",
        "Asteroid base",
        "Planetary Port",
        "Planetary Outpost",
    }
)

_POI_KEYS = (
    "Bodies",
    "Genus",
    "StarPorts",
    "Outposts",
    "Settlements",
    "FC",
    "Wars",
)

_POI_LABELS = {
    "Bodies": "Bodies",
    "Genus": "Genus",
    "StarPorts": "Star ports",
    "Outposts": "Outposts",
    "Settlements": "Settlements",
    "FC": "FC",
    "Wars": "Wars",
}

_UNDISCOVERED = "Undiscovered system"
_UNSCANNED = "Unscanned system"
_DISCOVERED_ALL = "Discovered, {0} bodies"
_DISCOVERED_PARTIAL = "Discovered ({0} of {1})"

_cache: dict[str, tuple[float, Any]] = {}
_instances: dict[str, Any] = {}


@dataclass
class EdsmTrafficCounts:
    """EDSM traffic day / week / total."""

    day: int = 0
    week: int = 0
    total: int = 0


@dataclass
class NetSysData:
    """Mirror of SrvSurvey.net.NetSysData (fields used by jump / galmap / station)."""

    system_name: str
    system_address: int = 0
    star_class: str | None = None
    star_pos: tuple[float, float, float] | None = None
    discovered: bool | None = None
    discovered_by: str | None = None
    discovered_date: str | None = None
    total_body_count: int = 0
    scan_body_count: int = 0
    genus_count: int = 0
    last_updated: str | None = None
    count_poi: dict[str, int] = field(
        default_factory=lambda: {k: 0 for k in _POI_KEYS}
    )
    special: dict[str, list[str]] = field(default_factory=dict)
    traffic: EdsmTrafficCounts | None = None
    stations: list[StationInfo] = field(default_factory=list)
    spansh_dump: dict[str, Any] | None = None

    @property
    def discovery_status(self) -> str | None:
        """Match NetSysData.discoveryStatus (Misc.resx English)."""
        if self.discovered is None:
            return None
        if self.discovered is False or (
            self.last_updated is None and self.total_body_count == 0
        ):
            return _UNDISCOVERED
        if self.total_body_count == 0:
            return _UNSCANNED
        if self.total_body_count == self.scan_body_count:
            return _DISCOVERED_ALL.format(self.total_body_count)
        return _DISCOVERED_PARTIAL.format(self.scan_body_count, self.total_body_count)

    def poi_summary_parts(self) -> list[str]:
        """Bodies: N, Genus: N, … for PlotJumpInfo POI line."""
        parts: list[str] = []
        for key in _POI_KEYS:
            value = self.count_poi.get(key, 0)
            if value > 0:
                parts.append(f"{_POI_LABELS.get(key, key)}: {value}")
        return parts


def clear_cache() -> None:
    """Drop HTTP cache and in-memory NetSysData instances (tests / refresh)."""
    _cache.clear()
    _instances.clear()


def _env_truthy(key: str) -> bool:
    return os.environ.get(key, "").strip().lower() in {"1", "true", "yes", "on"}


def net_offline() -> bool:
    return _env_truthy("SRVSURVEY_NET_OFFLINE")


def spansh_offline() -> bool:
    return net_offline() or _env_truthy("SRVSURVEY_SPANSH_OFFLINE")


def edsm_offline() -> bool:
    return net_offline()


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


def _as_int(raw: object) -> int | None:
    if isinstance(raw, (int, float)):
        return int(raw)
    return None


def _as_float(raw: object) -> float | None:
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def _short_date(raw: object) -> str | None:
    """ISO / EDSM date → short display (YYYY-MM-DD)."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if "T" in text:
        return text.split("T", 1)[0]
    if " " in text:
        return text.split(" ", 1)[0]
    return text[:10] if len(text) >= 10 else text


def _set_discovered(data: NetSysData, address: int) -> None:
    if address > 0:
        data.discovered = True
    elif data.discovered is None:
        data.discovered = False


def _spectral_letter(spectral: object) -> str | None:
    if not isinstance(spectral, str) or not spectral:
        return None
    return spectral[0]


def fetch_edsm_bodies(system_name: str) -> dict[str, Any] | None:
    """GET EDSM api-system-v1/bodies (cached)."""
    name = (system_name or "").strip()
    if not name or edsm_offline():
        return None
    cache_key = f"edsm-bodies:{name.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached if cached is not False else None
    query = urllib.parse.urlencode({"systemName": name})
    data = _http_get_json(f"{EDSM_BODIES_URL}?{query}")
    _cache_set(cache_key, data if data is not None else False)
    return data if isinstance(data, dict) else None


def fetch_edsm_traffic(system_name: str) -> dict[str, Any] | None:
    """GET EDSM api-system-v1/traffic (cached)."""
    name = (system_name or "").strip()
    if not name or edsm_offline():
        return None
    cache_key = f"edsm-traffic:{name.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached if cached is not False else None
    query = urllib.parse.urlencode({"systemName": name})
    data = _http_get_json(f"{EDSM_TRAFFIC_URL}?{query}")
    _cache_set(cache_key, data if data is not None else False)
    return data if isinstance(data, dict) else None


def fetch_edsm_systems(system_name: str) -> list[dict[str, Any]] | None:
    """GET EDSM api-v1/systems — Windows EDSM.getSystems."""
    name = (system_name or "").strip()
    if not name or edsm_offline():
        return None
    cache_key = f"edsm-systems:{name.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached if cached is not False else None
    query = urllib.parse.urlencode(
        {"showCoordinates": "1", "showId": "1", "systemName": name}
    )
    data = _http_get_json(f"{EDSM_SYSTEMS_URL}?{query}")
    rows = data if isinstance(data, list) else None
    _cache_set(cache_key, rows if rows is not None else False)
    return rows


def fetch_edsm_stations(system_name: str) -> dict[str, Any] | None:
    """GET EDSM api-system-v1/stations — Windows EDSM.getSystemStations."""
    name = (system_name or "").strip()
    if not name or edsm_offline():
        return None
    cache_key = f"edsm-stations:{name.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached if cached is not False else None
    query = urllib.parse.urlencode({"systemName": name})
    data = _http_get_json(f"{EDSM_STATIONS_URL}?{query}")
    _cache_set(cache_key, data if data is not None else False)
    return data if isinstance(data, dict) else None


def fetch_spansh_dump(system_address: int) -> dict[str, Any] | None:
    """GET Spansh api/dump/{id64}/ → system object (cached)."""
    addr = int(system_address or 0)
    if addr <= 0 or spansh_offline():
        return None
    cache_key = f"spansh-dump:{addr}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached if cached is not False else None
    url = SPANSH_DUMP_URL.format(address=addr)
    data = _http_get_json(url)
    system = None
    if isinstance(data, dict):
        inner = data.get("system")
        system = inner if isinstance(inner, dict) else data
    _cache_set(cache_key, system if system is not None else False)
    return system


def _parse_landing_pads(raw: object) -> LandingPads | None:
    if not isinstance(raw, dict):
        return None
    return LandingPads(
        small=int(raw.get("Small") or raw.get("small") or 0),
        medium=int(raw.get("Medium") or raw.get("medium") or 0),
        large=int(raw.get("Large") or raw.get("large") or 0),
    )


def _economy_pairs(raw: object) -> tuple[tuple[str, float], ...]:
    if not isinstance(raw, dict):
        return ()
    pairs: list[tuple[str, float]] = []
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        pct = float(value) * 100.0 if isinstance(value, (int, float)) else 0.0
        # Spansh often stores share as 0–1; if already >1 treat as percent
        if isinstance(value, (int, float)) and value > 1.0:
            pct = float(value)
        pairs.append((key, pct))
    pairs.sort(key=lambda kv: kv[1], reverse=True)
    return tuple(pairs)


def station_info_from_spansh_station(raw: dict[str, Any]) -> StationInfo | None:
    """Map Spansh dump Station → journal.StationInfo."""
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        return None
    sid = _as_int(raw.get("id")) or 0
    stype = raw.get("type") if isinstance(raw.get("type"), str) else None
    primary = (
        raw.get("primaryEconomy")
        if isinstance(raw.get("primaryEconomy"), str)
        else None
    )
    gov = raw.get("government") if isinstance(raw.get("government"), str) else None
    faction = (
        raw.get("controllingFaction")
        if isinstance(raw.get("controllingFaction"), str)
        else None
    )
    faction_state = (
        raw.get("controllingFactionState")
        if isinstance(raw.get("controllingFactionState"), str)
        else None
    )
    services: list[str] = []
    raw_svc = raw.get("services")
    if isinstance(raw_svc, list):
        for svc in raw_svc:
            if isinstance(svc, str) and svc:
                services.append(svc)
    prohibited: list[str] = []
    market = raw.get("market")
    if isinstance(market, dict):
        for item in market.get("prohibitedCommodities") or []:
            if isinstance(item, str) and item:
                prohibited.append(item)
    update = raw.get("updateTime")
    return StationInfo(
        name=name,
        station_id=sid,
        station_type=stype,
        primary_economy=primary,
        economies=_economy_pairs(raw.get("economies")),
        controlling_faction=faction,
        controlling_faction_state=faction_state,
        government=gov,
        services=tuple(dict.fromkeys(services)),
        landing_pads=_parse_landing_pads(raw.get("landingPads")),
        prohibited_commodities=tuple(prohibited),
        update_time=_short_date(update),
    )


def stations_from_spansh_dump(system: dict[str, Any]) -> list[StationInfo]:
    """Flatten system.stations + body.stations like ApiSystemDump.getAllStations."""
    out: list[StationInfo] = []
    seen: set[str] = set()

    def _add(raw: object) -> None:
        if not isinstance(raw, dict):
            return
        st = station_info_from_spansh_station(raw)
        if st is None or st.name in seen:
            return
        seen.add(st.name)
        out.append(st)

    for row in system.get("stations") or []:
        _add(row)
    for body in system.get("bodies") or []:
        if not isinstance(body, dict):
            continue
        for row in body.get("stations") or []:
            _add(row)
    return out


def find_station_in_dump(
    system_address: int,
    station_name: str,
) -> StationInfo | None:
    """Lookup one station by name from Spansh dump (PlotStationInfo path)."""
    name = (station_name or "").strip()
    if not name or system_address <= 0:
        return None
    dump = fetch_spansh_dump(system_address)
    if dump is None:
        return None
    for st in stations_from_spansh_dump(dump):
        if st.name == name:
            return st
    return None


def _process_edsm_bodies(
    data: NetSysData,
    payload: dict[str, Any],
    *,
    use_spansh_last_updated: bool,
) -> None:
    id64 = _as_int(payload.get("id64")) or 0
    if data.system_address == 0 and id64 > 0:
        data.system_address = id64
    _set_discovered(data, id64)

    bodies = payload.get("bodies")
    if not isinstance(bodies, list):
        return

    if data.star_class is None:
        for body in bodies:
            if not isinstance(body, dict):
                continue
            if body.get("isMainStar"):
                data.star_class = _spectral_letter(body.get("spectralClass"))
                break

    if not use_spansh_last_updated and data.last_updated is None:
        latest: str | None = None
        for body in bodies:
            if not isinstance(body, dict):
                continue
            stamp = _short_date(body.get("updateTime"))
            if stamp and (latest is None or stamp > latest):
                latest = stamp
        data.last_updated = latest

    if data.scan_body_count < len(bodies):
        data.scan_body_count = len(bodies)
    body_count = _as_int(payload.get("bodyCount")) or 0
    if data.total_body_count < body_count:
        data.total_body_count = body_count
    data.count_poi["Bodies"] = data.total_body_count

    if data.discovered_by is None:
        for body in bodies:
            if not isinstance(body, dict):
                continue
            disc = body.get("discovery")
            if not isinstance(disc, dict):
                continue
            cmdr = disc.get("commander")
            if isinstance(cmdr, str) and cmdr:
                data.discovered_by = cmdr
                data.discovered_date = _short_date(disc.get("date"))
                break


def _process_edsm_traffic(data: NetSysData, payload: dict[str, Any]) -> None:
    id64 = _as_int(payload.get("id64")) or 0
    if data.system_address == 0 and id64 > 0:
        data.system_address = id64
    _set_discovered(data, id64)

    disc = payload.get("discovery")
    if isinstance(disc, dict):
        cmdr = disc.get("commander")
        if isinstance(cmdr, str) and cmdr:
            data.discovered_by = cmdr
            data.discovered_date = _short_date(disc.get("date"))

    traffic = payload.get("traffic")
    if isinstance(traffic, dict):
        data.traffic = EdsmTrafficCounts(
            day=int(traffic.get("day") or 0),
            week=int(traffic.get("week") or 0),
            total=int(traffic.get("total") or 0),
        )


def _mat_trader_suffix(station: dict[str, Any]) -> str | None:
    primary = (station.get("primaryEconomy") or "").lower()
    economies = station.get("economies")
    secondary = ""
    if isinstance(economies, dict) and economies:
        ordered = sorted(
            ((k, v) for k, v in economies.items() if isinstance(k, str)),
            key=lambda kv: float(kv[1]) if isinstance(kv[1], (int, float)) else 0.0,
        )
        if len(ordered) > 1:
            secondary = ordered[1][0].lower()
    if primary in ("high tech", "military") or secondary in ("high tech", "military"):
        return "(Encoded)"
    if primary in ("extraction", "refinery") or secondary in ("extraction", "refinery"):
        return "(Raw)"
    if primary == "industrial" or secondary == "industrial":
        return "(Manufactured)"
    return None


def _tech_broker_suffix(station: dict[str, Any]) -> str | None:
    sid = _as_int(station.get("id")) or 0
    stype = station.get("type")
    if sid > 4_200_000_000 or stype == "Dodec Starport":
        return "(Human)"
    primary = (station.get("primaryEconomy") or "").lower()
    economies = station.get("economies")
    secondary = None
    if isinstance(economies, dict) and economies:
        ordered = sorted(
            ((k, v) for k, v in economies.items() if isinstance(k, str)),
            key=lambda kv: float(kv[1]) if isinstance(kv[1], (int, float)) else 0.0,
        )
        if len(ordered) > 1:
            secondary = ordered[1][0].lower()
    if primary == "high tech" or secondary == "high tech":
        return "(Guardian)"
    if primary == "industrial" or primary == "rescue":
        return "(Human)"
    if secondary is not None and secondary != "high tech":
        return "(Human)"
    return None


def _process_spansh_dump(data: NetSysData, system: dict[str, Any]) -> None:
    data.spansh_dump = system
    id64 = _as_int(system.get("id64")) or 0
    if id64 > 0:
        data.system_address = id64
    _set_discovered(data, id64)

    coords = system.get("coords")
    if data.star_pos is None and isinstance(coords, dict):
        x, y, z = _as_float(coords.get("x")), _as_float(coords.get("y")), _as_float(
            coords.get("z")
        )
        if x is not None and y is not None and z is not None:
            data.star_pos = (x, y, z)

    bodies = system.get("bodies")
    if isinstance(bodies, list):
        if data.star_class is None:
            for body in bodies:
                if not isinstance(body, dict):
                    continue
                if body.get("mainStar") is True:
                    data.star_class = _spectral_letter(body.get("spectralClass"))
                    break
        scan_count = sum(
            1
            for b in bodies
            if isinstance(b, dict) and b.get("type") != "Barycentre"
        )
        if data.scan_body_count < scan_count:
            data.scan_body_count = scan_count
        genus = 0
        for body in bodies:
            if not isinstance(body, dict):
                continue
            signals = body.get("signals")
            if not isinstance(signals, dict):
                continue
            sig_map = signals.get("signals")
            if isinstance(sig_map, dict):
                bio = sig_map.get("$SAA_SignalType_Biological;")
                if isinstance(bio, (int, float)):
                    genus += int(bio)
        data.genus_count = genus
        data.count_poi["Genus"] = genus

    body_count = _as_int(system.get("bodyCount")) or 0
    if data.total_body_count < body_count:
        data.total_body_count = body_count
    data.count_poi["Bodies"] = data.total_body_count

    raw_stations: list[dict[str, Any]] = []
    for row in system.get("stations") or []:
        if isinstance(row, dict):
            raw_stations.append(row)
    if isinstance(bodies, list):
        for body in bodies:
            if not isinstance(body, dict):
                continue
            for row in body.get("stations") or []:
                if isinstance(row, dict):
                    raw_stations.append(row)

    count_fc = count_settlements = count_starports = count_outposts = 0
    for station in raw_stations:
        stype = station.get("type") if isinstance(station.get("type"), str) else ""
        if stype == "Drake-Class Carrier":
            count_fc += 1
        elif stype == "Settlement":
            count_settlements += 1
        elif stype == "Outpost":
            count_outposts += 1
        if stype in _STARPORTS:
            count_starports += 1
        if stype == "Mega ship" and station.get("landingPads") is not None:
            count_starports += 1

        services = station.get("services")
        svc_list = services if isinstance(services, list) else []
        name = station.get("name") if isinstance(station.get("name"), str) else "?"
        if "Material Trader" in svc_list:
            suffix = _mat_trader_suffix(station)
            label = f"Material Trader {suffix}" if suffix else "Material Trader"
            data.special.setdefault(name, []).append(label)
        if "Technology Broker" in svc_list:
            suffix = _tech_broker_suffix(station)
            label = f"Tech Broker {suffix}" if suffix else "Tech Broker"
            data.special.setdefault(name, []).append(label)
        if station.get("government") == "Engineer":
            faction = station.get("controllingFaction") or ""
            data.special.setdefault(name, []).append(f"{faction} (Engineer)".strip())

    if count_fc:
        data.count_poi["FC"] = count_fc
    if count_settlements:
        data.count_poi["Settlements"] = count_settlements
    if count_outposts:
        data.count_poi["Outposts"] = count_outposts
    if count_starports:
        data.count_poi["StarPorts"] = count_starports

    factions = system.get("factions")
    if isinstance(factions, list):
        wars = sum(
            1
            for f in factions
            if isinstance(f, dict) and f.get("state") in ("War", "Civil War")
        )
        if wars > 0:
            data.count_poi["Wars"] = wars // 2

    data.stations = stations_from_spansh_dump(system)

    if data.last_updated is None:
        data.last_updated = _short_date(system.get("date"))


def get_net_sys_data(
    system_name: str,
    system_address: int = 0,
    *,
    force_offline: bool = False,
    use_spansh_last_updated: bool = False,
) -> NetSysData:
    """Load / cache NetSysData for a system (sync; empty when offline)."""
    name = (system_name or "").strip()
    addr = int(system_address or 0)
    if not name and addr <= 0:
        return NetSysData(system_name="")

    cache_name = name or f"id64:{addr}"
    existing = _instances.get(cache_name)
    if existing is not None:
        # Re-issue requests if address arrived later (Windows makeRequests)
        if addr > 0 and existing.system_address == 0:
            existing.system_address = addr
            if not force_offline and not spansh_offline() and existing.spansh_dump is None:
                dump = fetch_spansh_dump(addr)
                if dump is not None:
                    _process_spansh_dump(existing, dump)
        return existing

    data = NetSysData(system_name=name or f"#{addr}", system_address=addr)
    _instances[cache_name] = data

    if force_offline or net_offline():
        if addr <= 0 and not name:
            data.discovered = False
        return data

    if name:
        bodies = fetch_edsm_bodies(name)
        if bodies is not None:
            _process_edsm_bodies(
                data, bodies, use_spansh_last_updated=use_spansh_last_updated
            )
        traffic = fetch_edsm_traffic(name)
        if traffic is not None:
            _process_edsm_traffic(data, traffic)

    lookup_addr = data.system_address or addr
    if lookup_addr > 0 and not spansh_offline():
        dump = fetch_spansh_dump(lookup_addr)
        if dump is not None:
            _process_spansh_dump(data, dump)
            if use_spansh_last_updated and data.last_updated is None:
                data.last_updated = _short_date(dump.get("date"))

    return data
