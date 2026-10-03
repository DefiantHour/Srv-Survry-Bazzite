#!/usr/bin/env python3
"""EDDN upload client — Linux port of SrvSurvey/net/EDDN.cs.

Builds ``$schemaRef`` / ``header`` / ``message`` payloads and POSTs when
``gs.eddnUpload`` is on and the process is not offline. Windows still has a
dead ``DateTime.Now.Year > 3000`` guard around the real POST; Linux POSTs for
real when enabled, with ``SRVSURVEY_EDDN_DRYRUN=1`` to log without sending.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from client_identity import release_version, user_agent

USER_AGENT = user_agent()
SOFTWARE_NAME = "SrvSurvey"
SOFTWARE_VERSION = release_version()
HTTP_TIMEOUT_SECONDS = 5.0
DEFAULT_ENV = "dev"

URLS: dict[str, str] = {
    "dev": "https://dev.eddn.edcd.io:4432/upload/",
    "beta": "https://beta.eddn.edcd.io:4431/upload/",
    "live": "https://eddn.edcd.io:4430/upload/",
}

JOURNAL_SCHEMA = "https://eddn.edcd.io/schemas/journal/1"
SCHEMA_BY_EVENT: dict[str, str] = {
    "CodexEntry": "https://eddn.edcd.io/schemas/codexentry/1",
    "ApproachSettlement": "https://eddn.edcd.io/schemas/approachsettlement/1",
    "DockingGranted": "https://eddn.edcd.io/schemas/dockinggranted/1",
    "DockingDenied": "https://eddn.edcd.io/schemas/dockingdenied/1",
    "FSSAllBodiesFound": "https://eddn.edcd.io/schemas/fssallbodiesfound/1",
    "FSSBodySignals": "https://eddn.edcd.io/schemas/fssbodysignals/1",
    "FSSDiscoveryScan": "https://eddn.edcd.io/schemas/fssdiscoveryscan/1",
    "NavBeaconScan": "https://eddn.edcd.io/schemas/navbeaconscan/1",
    "NavRoute": "https://eddn.edcd.io/schemas/navroute/1",
    "ScanBaryCentre": "https://eddn.edcd.io/schemas/scanbarycentre/1",
    # journal/1 schema group
    "Docked": JOURNAL_SCHEMA,
    "FSDJump": JOURNAL_SCHEMA,
    "CarrierJump": JOURNAL_SCHEMA,
    "Scan": JOURNAL_SCHEMA,
    "Location": JOURNAL_SCHEMA,
    "SAASignalsFound": JOURNAL_SCHEMA,
}

# Events that need SystemAddress to match the current system.
_ADDRESS_MATCH_EVENTS = frozenset(
    {
        "CodexEntry",
        "ApproachSettlement",
        "FSSAllBodiesFound",
        "FSSBodySignals",
        "FSSDiscoveryScan",
        "NavBeaconScan",
        "ScanBaryCentre",
        "Docked",
        "FSDJump",
        "CarrierJump",
        "Scan",
        "Location",
        "SAASignalsFound",
    }
)

_log = logging.getLogger("srvsurvey.eddn")

# Module header — set from LoadGame + Fileheader (Windows EDDN.header).
_header: dict[str, str] | None = None
_game_version: str = ""
_game_build: str = ""
_is_odyssey: bool = False
_is_horizons: bool = False

# Injected by tests to assert no live HTTP.
_post_hook: Callable[[str, str], tuple[int, str]] | None = None


@dataclass
class EddnContext:
    """Current system / body context for schema augmentation."""

    system_name: str | None = None
    system_address: int | None = None
    star_pos: tuple[float, float, float] | None = None
    body_name: str | None = None
    body_id: int | None = None
    is_odyssey: bool | None = None
    is_horizons: bool | None = None


@dataclass
class UploadResult:
    """Outcome of one attempted EDDN upload (or skip)."""

    event: str
    skipped: bool = False
    reason: str | None = None
    dry_run: bool = False
    status_code: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)


def clear_state() -> None:
    """Reset header / game flags (tests)."""
    global _header, _game_version, _game_build, _is_odyssey, _is_horizons
    _header = None
    _game_version = ""
    _game_build = ""
    _is_odyssey = False
    _is_horizons = False


def get_header() -> dict[str, str] | None:
    return None if _header is None else dict(_header)


def set_post_hook(hook: Callable[[str, str], tuple[int, str]] | None) -> None:
    """Replace urllib POST (tests). Hook receives (url, payload_json)."""
    global _post_hook
    _post_hook = hook


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def offline() -> bool:
    """True when EDDN must not POST."""
    return _env_flag("SRVSURVEY_NET_OFFLINE") or _env_flag("SRVSURVEY_EDDN_OFFLINE")


def dry_run() -> bool:
    return _env_flag("SRVSURVEY_EDDN_DRYRUN")


def resolve_url(environment: str | None = None) -> tuple[str, str]:
    """Return (url, env_key). Default env is ``dev`` like Windows ``useEnv``."""
    key = (environment or DEFAULT_ENV).strip().lower() or DEFAULT_ENV
    if key not in URLS:
        key = DEFAULT_ENV
    return URLS[key], key


def _trim(obj: Any, names: list[str]) -> None:
    """In-place trim mirroring Windows EDDN.trim (including ``*_Localised``)."""
    if not isinstance(obj, dict):
        return
    to_remove: list[str] = []
    for key in list(obj.keys()):
        for name in names:
            if name.startswith("*"):
                suffix = name[1:]
                if key.endswith(suffix):
                    to_remove.append(key)
                    break
            elif key == name:
                to_remove.append(key)
                break
    for key in to_remove:
        obj.pop(key, None)
    for val in obj.values():
        if isinstance(val, dict):
            _trim(val, names)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    _trim(item, names)


def _augment_flags(message: dict[str, Any], ctx: EddnContext) -> None:
    odyssey = _is_odyssey if ctx.is_odyssey is None else ctx.is_odyssey
    horizons = _is_horizons if ctx.is_horizons is None else ctx.is_horizons
    if odyssey:
        message["odyssey"] = True
    if horizons:
        message["horizons"] = True


def _star_pos_list(ctx: EddnContext) -> list[float] | None:
    if ctx.star_pos is None or len(ctx.star_pos) != 3:
        return None
    return [float(ctx.star_pos[0]), float(ctx.star_pos[1]), float(ctx.star_pos[2])]


def note_fileheader(entry: dict[str, Any]) -> None:
    """Capture gameversion / build / Odyssey from journal Fileheader."""
    global _game_version, _game_build, _is_odyssey, _is_horizons
    gv = entry.get("gameversion")
    if isinstance(gv, str) and gv.strip():
        _game_version = gv.strip()
    build = entry.get("build")
    if isinstance(build, str) and build.strip():
        _game_build = build.strip()
    if entry.get("Odyssey") is True:
        _is_odyssey = True
        _is_horizons = False
    elif "Odyssey" in entry:
        _is_odyssey = False
        _is_horizons = True


def set_header_from_load_game(commander: str, game_version: str | None = None, game_build: str | None = None) -> dict[str, str]:
    """Mirror Windows ``EDDN.header = new UploadPayloadHeader(...)`` on LoadGame."""
    global _header, _game_version, _game_build
    if game_version and str(game_version).strip():
        _game_version = str(game_version).strip()
    if game_build and str(game_build).strip():
        _game_build = str(game_build).strip()
    _header = {
        "uploaderID": commander,
        "softwareName": SOFTWARE_NAME,
        "softwareVersion": SOFTWARE_VERSION,
        "gameVersion": _game_version or "unknown",
        "gamebuild": _game_build or "unknown",
    }
    return dict(_header)


def build_payload(message: dict[str, Any], schema_ref: str, *, environment: str | None = None) -> dict[str, Any]:
    """Assemble ``$schemaRef`` / ``header`` / ``message``. Appends ``/test`` off live."""
    if _header is None:
        raise RuntimeError("EDDN header not set")
    _, env_key = resolve_url(environment)
    ref = schema_ref
    if env_key != "live":
        ref = f"{schema_ref}/test"
    return {
        "$schemaRef": ref,
        "header": dict(_header),
        "message": message,
    }


def _http_post(url: str, payload_json: str) -> tuple[int, str]:
    if _post_hook is not None:
        return _post_hook(url, payload_json)
    req = urllib.request.Request(
        url,
        data=payload_json.encode("utf-8"),
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return int(getattr(resp, "status", 200) or 200), body
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(exc)
        return int(exc.code), body
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, str(exc)


def upload(
    message: dict[str, Any],
    schema_ref: str,
    *,
    eddn_upload: bool,
    environment: str | None = None,
) -> UploadResult:
    """POST (or dry-run / skip) one EDDN schema payload. Fail-soft."""
    event = str(message.get("event") or "?")
    if not eddn_upload:
        return UploadResult(event=event, skipped=True, reason="eddnUpload=false")
    if _header is None:
        return UploadResult(event=event, skipped=True, reason="no-header")
    if offline():
        return UploadResult(event=event, skipped=True, reason="offline")

    try:
        payload = build_payload(message, schema_ref, environment=environment)
    except Exception as exc:
        _log.warning("EDDN build_payload failed: %s", exc)
        return UploadResult(event=event, skipped=True, reason=str(exc))

    payload_json = json.dumps(payload, separators=(",", ":"))
    url, _env = resolve_url(environment)

    if dry_run():
        _log.info("EDDN dry-run %s → %s\n%s", event, url, json.dumps(payload, indent=2))
        return UploadResult(event=event, dry_run=True, payload=payload)

    from mutation_queue import drain, enqueue
    from paths import srvsurvey_data_dir

    data_dir = srvsurvey_data_dir()
    drain("eddn", _http_post, data_dir=data_dir)
    try:
        status, body = _http_post(url, payload_json)
    except Exception as exc:
        _log.warning("EDDN POST failed: %s", exc)
        enqueue("eddn", url, payload_json, data_dir=data_dir)
        return UploadResult(event=event, skipped=True, reason=str(exc), payload=payload)

    if status == 0 or status >= 500:
        enqueue("eddn", url, payload_json, data_dir=data_dir)
        _log.warning("EDDN upload held HTTP %s: %s", status, body[:500])
    elif status < 200 or status >= 300:
        _log.warning("EDDN upload failed HTTP %s: %s", status, body[:500])
    else:
        _log.debug("EDDN upload ok HTTP %s for %s", status, event)
    return UploadResult(event=event, status_code=status, payload=payload)


def _prepare_message(entry: dict[str, Any], ctx: EddnContext) -> dict[str, Any] | None:
    """Clone, trim, and augment a journal entry for its EDDN schema. None = skip."""
    event = entry.get("event")
    if not isinstance(event, str) or event not in SCHEMA_BY_EVENT:
        return None

    if event in _ADDRESS_MATCH_EVENTS:
        raw_addr = entry.get("SystemAddress")
        if ctx.system_address is not None and isinstance(raw_addr, (int, float)):
            if int(raw_addr) != int(ctx.system_address):
                return None

    message = copy.deepcopy(entry)

    if event == "CodexEntry":
        _trim(message, ["*_Localised", "BodyID", "IsNewEntry", "NewTraitsDiscovered"])
        system = entry.get("System")
        if isinstance(system, str) and system:
            message["StarSystem"] = system
        pos = _star_pos_list(ctx)
        if pos is not None:
            message["StarPos"] = pos
        _augment_flags(message, ctx)
        if (
            ctx.body_name
            and isinstance(ctx.body_name, str)
            and ctx.body_id is not None
            and isinstance(entry.get("BodyID"), (int, float))
            and int(entry["BodyID"]) == int(ctx.body_id)
        ):
            message["BodyName"] = ctx.body_name
            message["BodyID"] = int(ctx.body_id)
        return message

    if event == "ApproachSettlement":
        _trim(message, ["*_Localised"])
        if ctx.system_name:
            message["StarSystem"] = ctx.system_name
        pos = _star_pos_list(ctx)
        if pos is not None:
            message["StarPos"] = pos
        _augment_flags(message, ctx)
        return message

    if event in ("DockingGranted", "DockingDenied"):
        _augment_flags(message, ctx)
        return message

    if event == "FSSAllBodiesFound":
        pos = _star_pos_list(ctx)
        if pos is not None:
            message["StarPos"] = pos
        _augment_flags(message, ctx)
        return message

    if event == "FSSBodySignals":
        _trim(message, ["*_Localised"])
        if ctx.system_name:
            message["StarSystem"] = ctx.system_name
        pos = _star_pos_list(ctx)
        if pos is not None:
            message["StarPos"] = pos
        _augment_flags(message, ctx)
        return message

    if event == "FSSDiscoveryScan":
        _trim(message, ["*_Localised", "Progress"])
        pos = _star_pos_list(ctx)
        if pos is not None:
            message["StarPos"] = pos
        _augment_flags(message, ctx)
        return message

    if event == "NavBeaconScan":
        if ctx.system_name:
            message["StarSystem"] = ctx.system_name
        pos = _star_pos_list(ctx)
        if pos is not None:
            message["StarPos"] = pos
        _augment_flags(message, ctx)
        return message

    if event == "NavRoute":
        _augment_flags(message, ctx)
        return message

    if event == "ScanBaryCentre":
        pos = _star_pos_list(ctx)
        if pos is not None:
            message["StarPos"] = pos
        _augment_flags(message, ctx)
        return message

    if event == "Docked":
        _trim(message, ["*_Localised", "Wanted", "ActiveFine", "CockpitBreach"])
        pos = _star_pos_list(ctx)
        if pos is not None:
            message["StarPos"] = pos
        _augment_flags(message, ctx)
        return message

    if event in ("FSDJump", "CarrierJump"):
        _trim(
            message,
            [
                "*_Localised",
                "Wanted",
                "BoostUsed",
                "FuelLevel",
                "FuelUsed",
                "JumpDist",
                "HappiestSystem",
                "HomeSystem",
                "MyReputation",
                "SquadronFaction",
            ],
        )
        _augment_flags(message, ctx)
        return message

    if event == "Scan":
        _trim(message, ["*_Localised"])
        pos = _star_pos_list(ctx)
        if pos is not None:
            message["StarPos"] = pos
        _augment_flags(message, ctx)
        return message

    if event == "Location":
        _trim(
            message,
            [
                "*_Localised",
                "Wanted",
                "Latitude",
                "Longitude",
                "HappiestSystem",
                "HomeSystem",
                "MyReputation",
                "SquadronFaction",
            ],
        )
        _augment_flags(message, ctx)
        return message

    if event == "SAASignalsFound":
        _trim(message, ["*_Localised"])
        if ctx.system_name:
            message["StarSystem"] = ctx.system_name
        pos = _star_pos_list(ctx)
        if pos is not None:
            message["StarPos"] = pos
        _augment_flags(message, ctx)
        return message

    return None


def handle_journal_entry(
    entry: dict[str, Any],
    *,
    eddn_upload: bool,
    environment: str | None = None,
    ctx: EddnContext | None = None,
) -> UploadResult | None:
    """Update header state and maybe upload one journal event. Fail-soft."""
    if not isinstance(entry, dict):
        return None
    event = entry.get("event")
    if not isinstance(event, str):
        return None

    try:
        if event == "Fileheader":
            note_fileheader(entry)
            return None
        if event == "LoadGame":
            cmdr = entry.get("Commander")
            if isinstance(cmdr, str) and cmdr.strip():
                set_header_from_load_game(cmdr.strip())
            return None
        if not eddn_upload:
            return None
        context = ctx or EddnContext()
        message = _prepare_message(entry, context)
        if message is None:
            return None
        schema = SCHEMA_BY_EVENT.get(event)
        if schema is None:
            return None
        return upload(
            message,
            schema,
            eddn_upload=eddn_upload,
            environment=environment,
        )
    except Exception as exc:
        _log.warning("EDDN handle_journal_entry failed for %s: %s", event, exc)
        return UploadResult(event=event, skipped=True, reason=str(exc))


def process_journal_events(
    events: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    eddn_upload: bool,
    environment: str | None = None,
    ctx: EddnContext | None = None,
) -> list[UploadResult]:
    """Process a batch of new journal events (header updates + uploads)."""
    results: list[UploadResult] = []
    for entry in events:
        result = handle_journal_entry(
            entry,
            eddn_upload=eddn_upload,
            environment=environment,
            ctx=ctx,
        )
        if result is not None:
            results.append(result)
    return results
