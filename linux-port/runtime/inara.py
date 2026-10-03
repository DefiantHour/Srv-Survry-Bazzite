#!/usr/bin/env python3
"""Inara journal upload — Linux port of SrvSurvey/net/Inara*.cs.

Reads the API key from the XDG secrets store (never from main config).
Key presence is the opt-in (matches Windows post-rewrite behaviour).
Offline / dry-run never POSTs: ``SRVSURVEY_NET_OFFLINE``,
``SRVSURVEY_INARA_OFFLINE``, ``SRVSURVEY_INARA_DRYRUN``, ``SRVSURVEY_DRY_RUN``.

Maps the Windows ``InaraEventMapper`` + ``InaraCreditTracker`` event set
(travel, ranks/progress/promotion, reputation, engineer, cargo/materials,
credits/Statistics, shipyard/stored ships/loadout, missions, combat,
suits/locker, community goals, friends). ScanOrganic is not mapped — Windows
does not send it.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping

from client_identity import release_version, user_agent

ENDPOINT = "https://inara.cz/inapi/v1/"
APP_NAME = "SrvSurvey"
APP_VERSION = release_version()
USER_AGENT = user_agent()
HTTP_TIMEOUT_SECONDS = 20.0
# Inara validation phase — matches Windows InaraPayloadBuilder.
IS_BEING_DEVELOPED = True
CREDIT_REPORT_INTERVAL = timedelta(hours=1)
_MATERIAL_CATEGORIES = ("Raw", "Manufactured", "Encoded")
_LOCKER_TYPES = ("Items", "Components", "Data", "Consumables")

_log = logging.getLogger("srvsurvey.inara")

# Injected by tests: (url, payload_json) → (status, body).
_post_hook: Callable[[str, str], tuple[int, str]] | None = None

# Session-scoped mapper state (one commander at a time).
_session_started = False
_session_commander: str | None = None
_in_multicrew = False
_cargo: dict[str, int] = {}
_materials: dict[str, int] = {}
_ranks: dict[str, int] = {}
_has_cargo_snapshot = False
_has_materials_snapshot = False
_credits: int | None = None
_loan: int | None = None
_assets: int | None = None
_credits_last_report: datetime | None = None
_credits_unreported = False


@dataclass
class InaraContext:
    """Travel / ship context for mapped events."""

    commander: str | None = None
    frontier_id: str | None = None
    system_name: str | None = None
    station_name: str | None = None
    body_name: str | None = None
    ship_type: str | None = None
    ship_id: int | None = None
    ship_name: str | None = None
    ship_ident: str | None = None
    is_taxi: bool | None = None


@dataclass
class InaraEvent:
    name: str
    timestamp: str
    data: Any
    replace_key: str | None = None


@dataclass
class UploadResult:
    """Outcome of one Inara batch attempt (or skip)."""

    ok: bool = False
    skipped: bool = False
    reason: str | None = None
    dry_run: bool = False
    status_code: int | None = None
    event_names: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)


def set_post_hook(hook: Callable[[str, str], tuple[int, str]] | None) -> None:
    """Replace urllib POST (tests). Hook receives (url, payload_json)."""
    global _post_hook
    _post_hook = hook


def clear_state() -> None:
    """Reset session mapper flags (tests / commander change)."""
    global _session_started, _session_commander, _in_multicrew
    global _cargo, _materials, _ranks
    global _has_cargo_snapshot, _has_materials_snapshot
    global _credits, _loan, _assets, _credits_last_report, _credits_unreported
    _session_started = False
    _session_commander = None
    _in_multicrew = False
    _cargo = {}
    _materials = {}
    _ranks = {}
    _has_cargo_snapshot = False
    _has_materials_snapshot = False
    _credits = None
    _loan = None
    _assets = None
    _credits_last_report = None
    _credits_unreported = False


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def offline() -> bool:
    """True when Inara must not POST."""
    return _env_flag("SRVSURVEY_NET_OFFLINE") or _env_flag("SRVSURVEY_INARA_OFFLINE")


def dry_run() -> bool:
    return _env_flag("SRVSURVEY_INARA_DRYRUN") or _env_flag("SRVSURVEY_DRY_RUN")


def get_api_key(
    *,
    environ: dict[str, str] | None = None,
    home: Any = None,
) -> str | None:
    """Load Inara API key from XDG secrets (same store as settings_ui)."""
    try:
        from secrets_store import INARA_API_KEY, get_secret

        return get_secret(INARA_API_KEY, environ=environ, home=home)
    except Exception:
        return None


def is_upload_enabled(
    api_key: str | None = None,
    *,
    environ: dict[str, str] | None = None,
    home: Any = None,
) -> bool:
    """Key presence is the per-commander opt-in (Windows parity)."""
    key = (api_key if api_key is not None else get_api_key(environ=environ, home=home)) or ""
    return bool(key.strip())


def _is_beta_version(game_version: str | None) -> bool:
    if not game_version:
        return False
    lower = game_version.lower()
    return "beta" in lower or "alpha" in lower


def _is_live_version(game_version: str | None, odyssey: bool) -> bool:
    if odyssey:
        return True
    if not game_version:
        return False
    numeric = []
    for ch in game_version:
        if ch.isdigit() or ch == ".":
            numeric.append(ch)
        else:
            break
    text = "".join(numeric).rstrip(".")
    if not text:
        return False
    try:
        major = int(text.split(".", 1)[0])
    except ValueError:
        return False
    return major >= 4


def can_prepare_upload(
    api_key: str | None,
    *,
    game_version: str | None = None,
    odyssey: bool = True,
) -> bool:
    if not (api_key or "").strip():
        return False
    if _is_beta_version(game_version):
        return False
    return _is_live_version(game_version, odyssey)


def _update_multicrew(name: str, entry: Mapping[str, Any]) -> None:
    global _in_multicrew
    if name == "QuitACrew":
        _in_multicrew = False
    elif name in {"JoinACrew", "ChangeCrewRole"}:
        _in_multicrew = True
    elif entry.get("Multicrew") is True:
        _in_multicrew = True
    elif name == "LoadGame":
        _in_multicrew = False


def _obj(**kwargs: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in kwargs.items():
        if value is None:
            continue
        out[key] = value
    return out


def _add_required(
    events: list[InaraEvent],
    name: str,
    timestamp: str,
    data: dict[str, Any],
    replace_key: str | None = None,
) -> None:
    if data:
        events.append(InaraEvent(name, timestamp, data, replace_key))


def _add_ship_identity(data: dict[str, Any], ctx: InaraContext, is_taxi: bool | None) -> None:
    if is_taxi is True:
        data["isTaxiShuttle"] = True
        return
    if is_taxi is None:
        return
    if ctx.ship_type:
        data["shipType"] = ctx.ship_type
    if ctx.ship_id is not None and ctx.ship_id >= 0:
        data["shipGameID"] = ctx.ship_id


def _current_ship(ctx: InaraContext) -> dict[str, Any] | None:
    if ctx.ship_id is None or ctx.ship_id < 0 or not ctx.ship_type:
        return None
    return _obj(
        shipType=ctx.ship_type,
        shipGameID=ctx.ship_id,
        shipName=ctx.ship_name,
        shipIdent=ctx.ship_ident,
        isCurrentShip=True,
    )


def _normalize_rank(rank: str) -> str:
    if rank.lower() == "exploration":
        return "explore"
    return rank.lower()


def _item_name(entry: Mapping[str, Any]) -> str | None:
    for key in ("Type", "Name", "Material", "Commodity"):
        val = entry.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return None


def _item_count(entry: Mapping[str, Any], fallback: int = 1) -> int:
    for key in ("Count", "Amount", "Quantity"):
        val = entry.get(key)
        if isinstance(val, (int, float)):
            return int(val)
    return fallback


def _set_count(inventory: dict[str, int], name: str | None, count: int) -> None:
    if not name or not str(name).strip():
        return
    if count <= 0:
        inventory.pop(name, None)
    else:
        inventory[name] = count


def _change_count(inventory: dict[str, int], name: str | None, delta: int) -> bool:
    if not name or delta == 0:
        return False
    old = inventory.get(name, 0)
    new = max(0, old + delta)
    if old == new:
        return False
    _set_count(inventory, name, new)
    return True


def _change_item(inventory: dict[str, int], item: Mapping[str, Any] | None, direction: int) -> bool:
    if not isinstance(item, Mapping):
        return False
    return _change_count(inventory, _item_name(item), direction * _item_count(item, 1))


def _change_many(inventory: dict[str, int], items: Any, direction: int) -> bool:
    if not isinstance(items, list):
        return False
    changed = False
    for item in items:
        if isinstance(item, Mapping):
            changed = _change_item(inventory, item, direction) or changed
    return changed


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _credit_observe(entry: Mapping[str, Any]) -> None:
    """Port of InaraCreditTracker.Observe."""
    global _credits, _loan, _assets, _credits_unreported
    name = entry.get("event")
    if name == "LoadGame":
        _credits = _int_or_none(entry.get("Credits"))
        _loan = _int_or_none(entry.get("Loan"))
        _assets = None
        _credits_unreported = _credits is not None
        return
    if _in_multicrew:
        return
    if name == "Statistics":
        bank = entry.get("Bank_Account")
        if isinstance(bank, Mapping):
            wealth = _int_or_none(bank.get("Current_Wealth"))
            if wealth is not None and wealth != _assets:
                _assets = wealth
                _credits_unreported = True
        return
    if name == "CarrierBankTransfer":
        bal = _int_or_none(entry.get("PlayerBalance"))
        if bal is not None and bal != _credits:
            _credits = bal
            _credits_unreported = True
        return
    if _credits is None:
        return

    def z(key: str) -> int:
        return _int_or_none(entry.get(key)) or 0

    delta = 0
    if name == "ShipyardBuy":
        delta = -z("ShipPrice")
    elif name == "ModuleBuy":
        delta = -z("BuyPrice")
    elif name in {"ModuleRetrieve", "ModuleStore"}:
        delta = -z("Cost")
    elif name in {"ModuleSell", "ModuleSellRemote"}:
        delta = z("SellPrice")
    elif name in {"BuyMicroResources", "BuySuit", "BuyWeapon"}:
        delta = -z("Price")
    elif name in {"SellMicroResources", "SellSuit", "SellWeapon"}:
        delta = z("Price")
    elif name in {"UpgradeSuit", "UpgradeWeapon"}:
        delta = -z("Cost")
    elif name == "SellOrganicData":
        bio = entry.get("BioData")
        if isinstance(bio, list):
            for item in bio:
                if isinstance(item, Mapping):
                    delta += (_int_or_none(item.get("Value")) or 0) + (
                        _int_or_none(item.get("Bonus")) or 0
                    )
    elif name in {"BookDropship", "BookTaxi"}:
        delta = -z("Cost")
    elif name in {"CancelDropship", "CancelTaxi"}:
        delta = z("Refund")
    elif name in {"BuyDrones", "MarketBuy"}:
        delta = -z("TotalCost")
    elif name in {"MarketSell", "SellDrones"}:
        delta = z("TotalSale")
    elif name == "MissionCompleted":
        delta = z("Reward") - z("Donation")
    elif name == "CommunityGoalReward":
        delta = z("Reward")
    elif name in {"MultiSellExplorationData", "SellExplorationData"}:
        delta = z("TotalEarnings")
    elif name in {"BuyExplorationData", "BuyTradeData", "BuyAmmo", "CrewHire"}:
        delta = -z("Cost")
    elif name == "FetchRemoteModule":
        delta = -z("TransferCost")
    elif name in {"PayBounties", "PayFines", "PayLegacyFines"}:
        delta = -z("Amount")
    elif name in {"RedeemVoucher", "PowerplaySalary"}:
        delta = z("Amount")
    elif name in {
        "RefuelAll",
        "RefuelPartial",
        "Repair",
        "RepairAll",
        "RestockVehicle",
    }:
        delta = -z("Cost")
    elif name in {"SellShipOnRebuy", "ShipyardSell"}:
        delta = z("ShipPrice")
    elif name == "ShipyardTransfer":
        delta = -z("TransferPrice")
    elif name == "PowerplayFastTrack":
        delta = -z("Cost")
    elif name == "CarrierBuy":
        delta = -z("Price")
    elif name == "NpcCrewPaidWage":
        delta = -z("Amount")
    elif name == "Resurrect":
        delta = -z("Cost")

    if delta != 0:
        updated = _credits + delta
        if updated < 0:
            _credits = None
            _credits_unreported = False
            return
        _credits = updated
        _credits_unreported = True


def _parse_ts(timestamp: str) -> datetime:
    try:
        text = timestamp.replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except Exception:
        return datetime.now(timezone.utc)


def _credit_report(
    timestamp: str,
    *,
    force: bool,
    include_assets: bool,
) -> InaraEvent | None:
    global _credits_last_report, _credits_unreported
    if _credits is None:
        return None
    report_at = _parse_ts(timestamp)
    if not force:
        if not _credits_unreported:
            return None
        if _credits_last_report is not None and report_at - _credits_last_report < CREDIT_REPORT_INTERVAL:
            return None
    data = _obj(commanderCredits=_credits, commanderLoan=_loan)
    if include_assets and _assets is not None:
        data["commanderAssets"] = _assets
    _credits_last_report = report_at
    _credits_unreported = False
    return InaraEvent("setCommanderCredits", timestamp, data, "credits")


def _update_inventory(name: str, entry: Mapping[str, Any]) -> tuple[bool, bool]:
    global _has_cargo_snapshot, _has_materials_snapshot
    cargo_changed = False
    materials_changed = False

    if name == "Cargo" and entry.get("Vessel") == "Ship" and isinstance(entry.get("Inventory"), list):
        _cargo.clear()
        for item in entry["Inventory"]:
            if isinstance(item, Mapping):
                _set_count(_cargo, item.get("Name") if isinstance(item.get("Name"), str) else None, _item_count(item, 0))
        _has_cargo_snapshot = True
        cargo_changed = True
    elif _has_cargo_snapshot:
        cargo_changed = _update_cargo_delta(name, entry)

    if name == "Materials":
        _materials.clear()
        for category in _MATERIAL_CATEGORIES:
            items = entry.get(category)
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, Mapping):
                    _set_count(
                        _materials,
                        item.get("Name") if isinstance(item.get("Name"), str) else None,
                        _item_count(item, 0),
                    )
        _has_materials_snapshot = True
        materials_changed = True
    elif _has_materials_snapshot:
        materials_changed = _update_material_delta(name, entry)

    return cargo_changed, materials_changed


def _update_cargo_delta(name: str, entry: Mapping[str, Any]) -> bool:
    if name in {"CollectCargo", "MarketBuy", "BuyDrones", "MiningRefined"}:
        return _change_count(_cargo, _item_name(entry), _item_count(entry, 1))
    if name in {"EjectCargo", "MarketSell", "SellDrones"}:
        return _change_count(_cargo, _item_name(entry), -_item_count(entry, 1))
    if name == "CargoTransfer":
        transferred = False
        for item in entry.get("Transfers") or []:
            if not isinstance(item, Mapping):
                continue
            amount = _item_count(item, 0)
            direction = item.get("Direction")
            transferred = (
                _change_count(_cargo, _item_name(item), amount if direction == "toship" else -amount)
                or transferred
            )
        return transferred
    if name == "SearchAndRescue":
        changed = False
        for item in entry.get("Items") or []:
            if isinstance(item, Mapping):
                changed = _change_count(_cargo, _item_name(item), -_item_count(item, 1)) or changed
        return changed
    if name == "MissionCompleted":
        return _change_many(_cargo, entry.get("CommodityReward"), 1)
    if name == "EngineerContribution":
        return _change_count(
            _cargo,
            entry.get("Commodity") if isinstance(entry.get("Commodity"), str) else None,
            -(_int_or_none(entry.get("Quantity")) or 0),
        )
    if name == "TechnologyBroker":
        a = _change_many(_cargo, entry.get("Ingredients"), -1)
        b = _change_many(_cargo, entry.get("Commodities"), -1)
        return a or b
    return False


def _update_material_delta(name: str, entry: Mapping[str, Any]) -> bool:
    if name == "MaterialCollected":
        return _change_count(_materials, _item_name(entry), _item_count(entry, 1))
    if name in {"MaterialDiscarded", "ScientificResearch"}:
        return _change_count(_materials, _item_name(entry), -_item_count(entry, 1))
    if name == "Synthesis":
        return _change_many(_materials, entry.get("Materials"), -1)
    if name in {"EngineerCraft", "EngineerLegacyConvert"}:
        if entry.get("IsPreview") is True:
            return False
        return _change_many(_materials, entry.get("Ingredients"), -1)
    if name == "MaterialTrade":
        a = _change_item(_materials, entry.get("Paid") if isinstance(entry.get("Paid"), Mapping) else None, -1)
        b = _change_item(
            _materials,
            entry.get("Received") if isinstance(entry.get("Received"), Mapping) else None,
            1,
        )
        return a or b
    if name == "TechnologyBroker":
        a = _change_many(_materials, entry.get("Ingredients"), -1)
        b = _change_many(_materials, entry.get("Materials"), -1)
        return a or b
    if name == "MissionCompleted":
        return _change_many(_materials, entry.get("MaterialsReward"), 1)
    if name == "EngineerContribution":
        return _change_count(
            _materials,
            entry.get("Material") if isinstance(entry.get("Material"), str) else None,
            -(_int_or_none(entry.get("Quantity")) or 0),
        )
    return False


def _update_rank_state(name: str, entry: Mapping[str, Any]) -> None:
    if name != "Rank":
        return
    for key, value in entry.items():
        if key in {"timestamp", "event"}:
            continue
        if isinstance(value, int) and not isinstance(value, bool):
            _ranks[key] = value


def _add_inventory_snapshots(
    events: list[InaraEvent],
    timestamp: str,
    cargo_changed: bool,
    materials_changed: bool,
) -> None:
    if cargo_changed and _has_cargo_snapshot:
        data = [
            {"itemName": k, "itemCount": v}
            for k, v in sorted(_cargo.items(), key=lambda kv: kv[0].lower())
        ]
        events.append(InaraEvent("setCommanderInventoryCargo", timestamp, data, "inventory:cargo"))
    if materials_changed and _has_materials_snapshot:
        data = [
            {"itemName": k, "itemCount": v}
            for k, v in sorted(_materials.items(), key=lambda kv: kv[0].lower())
        ]
        events.append(
            InaraEvent("setCommanderInventoryMaterials", timestamp, data, "inventory:materials")
        )


def _map_progress(timestamp: str, entry: Mapping[str, Any], events: list[InaraEvent]) -> None:
    values: list[dict[str, Any]] = []
    for key, value in entry.items():
        if key in {"timestamp", "event"}:
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            continue
        data = _obj(rankName=_normalize_rank(key), rankProgress=value / 100.0)
        if key in _ranks:
            data["rankValue"] = _ranks[key]
        values.append(data)
    if values:
        events.append(InaraEvent("setCommanderRankPilot", timestamp, values, "ranks"))


def _map_promotion(timestamp: str, entry: Mapping[str, Any], events: list[InaraEvent]) -> None:
    for key, value in entry.items():
        if key in {"timestamp", "event"}:
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            continue
        _ranks[key] = value
        events.append(
            InaraEvent(
                "setCommanderRankPilot",
                timestamp,
                _obj(rankName=_normalize_rank(key), rankValue=value, rankProgress=0.0),
                f"rank:{key.lower()}",
            )
        )


def _map_engineer(timestamp: str, entry: Mapping[str, Any], events: list[InaraEvent]) -> None:
    if entry.get("Engineer") is None:
        return
    _add_required(
        events,
        "setCommanderRankEngineer",
        timestamp,
        _obj(
            engineerName=entry.get("Engineer"),
            rankValue=entry.get("Rank"),
            rankStage=entry.get("Progress"),
        ),
        f"engineer:{entry.get('Engineer')}",
    )


def _map_major_reputation(timestamp: str, entry: Mapping[str, Any], events: list[InaraEvent]) -> None:
    data = []
    for key, value in entry.items():
        if key in {"timestamp", "event"}:
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            data.append(
                {
                    "majorfactionName": key.lower(),
                    "majorfactionReputation": float(value) / 100.0,
                }
            )
    if data:
        events.append(
            InaraEvent("setCommanderReputationMajorFaction", timestamp, data, "reputation:major")
        )


def _map_minor_reputation(timestamp: str, entry: Mapping[str, Any], events: list[InaraEvent]) -> None:
    factions = entry.get("Factions")
    if not isinstance(factions, list):
        return
    data = []
    for faction in factions:
        if not isinstance(faction, Mapping):
            continue
        if faction.get("Name") is None or faction.get("MyReputation") is None:
            continue
        rep = faction.get("MyReputation")
        if not isinstance(rep, (int, float)):
            continue
        data.append(
            {
                "minorfactionName": faction["Name"],
                "minorfactionReputation": float(rep) / 100.0,
            }
        )
    if data:
        events.append(
            InaraEvent("setCommanderReputationMinorFaction", timestamp, data, "reputation:minor")
        )


def _map_location(timestamp: str, entry: Mapping[str, Any], events: list[InaraEvent]) -> None:
    data = _obj(
        starsystemName=entry.get("StarSystem"),
        starsystemCoords=entry.get("StarPos"),
    )
    if entry.get("Docked") is True:
        if entry.get("StationName"):
            data["stationName"] = entry["StationName"]
        if entry.get("MarketID") is not None:
            data["marketID"] = entry["MarketID"]
        if entry.get("BodyType") == "Planet" and entry.get("Body"):
            data["starsystemBodyName"] = entry["Body"]
    if entry.get("Latitude") is not None and entry.get("Longitude") is not None:
        if entry.get("Body"):
            data["starsystemBodyName"] = entry["Body"]
        data["starsystemBodyCoords"] = [entry["Latitude"], entry["Longitude"]]
    _add_required(events, "setCommanderTravelLocation", timestamp, data, "location")


def _map_jump(
    event_name: str,
    timestamp: str,
    entry: Mapping[str, Any],
    ctx: InaraContext,
    events: list[InaraEvent],
) -> None:
    data = _obj(
        starsystemName=entry.get("StarSystem"),
        starsystemCoords=entry.get("StarPos"),
        jumpDistance=entry.get("JumpDist"),
        stationName=entry.get("StationName"),
        marketID=entry.get("MarketID"),
    )
    taxi = entry.get("Taxi")
    if not isinstance(taxi, bool):
        taxi = ctx.is_taxi
    _add_ship_identity(data, ctx, taxi if isinstance(taxi, bool) else None)
    _add_required(events, event_name, timestamp, data)


def _map_docked(
    timestamp: str,
    entry: Mapping[str, Any],
    ctx: InaraContext,
    events: list[InaraEvent],
) -> None:
    data = _obj(
        starsystemName=entry.get("StarSystem") or ctx.system_name,
        stationName=entry.get("StationName") or ctx.station_name,
        marketID=entry.get("MarketID"),
    )
    taxi = entry.get("Taxi")
    if not isinstance(taxi, bool):
        taxi = ctx.is_taxi
    _add_ship_identity(data, ctx, taxi if isinstance(taxi, bool) else None)
    _add_required(events, "addCommanderTravelDock", timestamp, data)


def _map_supercruise_exit(timestamp: str, entry: Mapping[str, Any], events: list[InaraEvent]) -> None:
    data = _obj(starsystemName=entry.get("StarSystem"))
    if entry.get("BodyType") == "Planet" and entry.get("Body"):
        data["starsystemBodyName"] = entry["Body"]
    _add_required(events, "setCommanderTravelLocation", timestamp, data, "location")


def _map_settlement(
    timestamp: str,
    entry: Mapping[str, Any],
    ctx: InaraContext,
    events: list[InaraEvent],
) -> None:
    data = _obj(
        starsystemName=entry.get("StarSystem") or ctx.system_name,
        stationName=entry.get("Name"),
        starsystemBodyName=entry.get("BodyName"),
        marketID=entry.get("MarketID"),
    )
    if entry.get("Latitude") is not None and entry.get("Longitude") is not None:
        data["starsystemBodyCoords"] = [entry["Latitude"], entry["Longitude"]]
    _add_required(events, "setCommanderTravelLocation", timestamp, data, "location")


def _map_touchdown(
    timestamp: str,
    entry: Mapping[str, Any],
    ctx: InaraContext,
    events: list[InaraEvent],
) -> None:
    if entry.get("PlayerControlled") is False or entry.get("OnPlanet") is False:
        return
    data = _obj(
        starsystemName=entry.get("StarSystem") or ctx.system_name,
        starsystemBodyName=entry.get("Body") or ctx.body_name,
    )
    if entry.get("Latitude") is not None and entry.get("Longitude") is not None:
        data["starsystemBodyCoords"] = [entry["Latitude"], entry["Longitude"]]
    taxi = entry.get("Taxi")
    if not isinstance(taxi, bool):
        taxi = ctx.is_taxi
    _add_ship_identity(data, ctx, taxi if isinstance(taxi, bool) else None)
    _add_required(events, "addCommanderTravelLand", timestamp, data)


def _map_statistics(timestamp: str, entry: Mapping[str, Any], events: list[InaraEvent]) -> None:
    stats = {k: v for k, v in entry.items() if k not in {"timestamp", "event"}}
    if stats:
        events.append(InaraEvent("setCommanderGameStatistics", timestamp, stats, "statistics"))


def _map_shipyard(
    timestamp: str,
    entry: Mapping[str, Any],
    ctx: InaraContext,
    events: list[InaraEvent],
) -> None:
    if entry.get("StoreShipID") is not None:
        _add_required(
            events,
            "setCommanderShip",
            timestamp,
            _obj(
                shipType=entry.get("StoreOldShip"),
                shipGameID=entry.get("StoreShipID"),
                starsystemName=ctx.system_name,
                stationName=ctx.station_name,
            ),
            f"ship:{entry.get('StoreShipID')}",
        )
    if entry.get("SellShipID") is not None:
        _add_required(
            events,
            "delCommanderShip",
            timestamp,
            _obj(
                shipType=entry.get("SellOldShip") or entry.get("ShipType"),
                shipGameID=entry.get("SellShipID"),
            ),
            f"ship:{entry.get('SellShipID')}",
        )


def _map_stored_ships(timestamp: str, entry: Mapping[str, Any], events: list[InaraEvent]) -> None:
    for ship in entry.get("ShipsHere") or []:
        if not isinstance(ship, Mapping):
            continue
        _add_required(
            events,
            "setCommanderShip",
            timestamp,
            _obj(
                shipType=ship.get("ShipType"),
                shipGameID=ship.get("ShipID"),
                shipName=ship.get("Name"),
                isHot=ship.get("Hot"),
                starsystemName=entry.get("StarSystem"),
                stationName=entry.get("StationName"),
                marketID=entry.get("MarketID"),
            ),
            f"ship:{ship.get('ShipID')}",
        )
    for ship in entry.get("ShipsRemote") or []:
        if not isinstance(ship, Mapping):
            continue
        _add_required(
            events,
            "setCommanderShip",
            timestamp,
            _obj(
                shipType=ship.get("ShipType"),
                shipGameID=ship.get("ShipID"),
                shipName=ship.get("Name"),
                isHot=ship.get("Hot"),
                starsystemName=ship.get("StarSystem"),
                marketID=ship.get("ShipMarketID"),
            ),
            f"ship:{ship.get('ShipID')}",
        )


def _map_module(module: Mapping[str, Any]) -> dict[str, Any]:
    data = _obj(
        slotName=module.get("Slot"),
        itemName=module.get("Item"),
        itemHealth=module.get("Health"),
        isOn=module.get("On"),
        itemPriority=module.get("Priority"),
        itemAmmoClip=module.get("AmmoInClip"),
        itemAmmoHopper=module.get("AmmoInHopper"),
        itemValue=module.get("Value"),
        isHot=module.get("Hot"),
    )
    eng = module.get("Engineering")
    if isinstance(eng, Mapping):
        mapped = _obj(
            blueprintName=eng.get("BlueprintName"),
            blueprintLevel=eng.get("Level"),
            blueprintQuality=eng.get("Quality"),
            experimentalEffect=eng.get("ExperimentalEffect"),
        )
        mods = eng.get("Modifiers")
        if isinstance(mods, list):
            mapped["modifiers"] = [
                _obj(
                    name=m.get("Label"),
                    value=m.get("Value") if m.get("Value") is not None else m.get("ValueStr"),
                    originalValue=m.get("OriginalValue"),
                    lessIsGood=m.get("LessIsGood"),
                )
                for m in mods
                if isinstance(m, Mapping)
            ]
        data["engineering"] = mapped
    return data


def _map_loadout(
    timestamp: str,
    entry: Mapping[str, Any],
    ctx: InaraContext,
    events: list[InaraEvent],
) -> None:
    ship_type = entry.get("Ship") or ctx.ship_type
    ship_id = entry.get("ShipID") if entry.get("ShipID") is not None else ctx.ship_id
    modules = [_map_module(m) for m in (entry.get("Modules") or []) if isinstance(m, Mapping)]
    _add_required(
        events,
        "setCommanderShipLoadout",
        timestamp,
        _obj(shipType=ship_type, shipGameID=ship_id, shipLoadout=modules),
        f"loadout:{ship_id}",
    )
    ship = _obj(
        shipType=ship_type,
        shipGameID=ship_id,
        shipName=entry.get("ShipName") or ctx.ship_name,
        shipIdent=entry.get("ShipIdent") or entry.get("ShipIDent") or ctx.ship_ident,
        isCurrentShip=True,
        shipMaxJumpRange=entry.get("MaxJumpRange"),
        shipCargoCapacity=entry.get("CargoCapacity"),
        shipHullValue=entry.get("HullValue"),
        shipModulesValue=entry.get("ModulesValue"),
        shipRebuyCost=entry.get("Rebuy"),
    )
    _add_required(events, "setCommanderShip", timestamp, ship, f"ship:{ship_id}")


def _map_stored_modules(timestamp: str, entry: Mapping[str, Any], events: list[InaraEvent]) -> None:
    items = entry.get("Items")
    if not isinstance(items, list):
        events.append(InaraEvent("setCommanderStorageModules", timestamp, [], "stored-modules"))
        return
    ordered = sorted(
        [i for i in items if isinstance(i, Mapping)],
        key=lambda i: _int_or_none(i.get("StorageSlot")) or 0,
    )
    modules = []
    for item in ordered:
        module = _obj(
            itemName=item.get("Name"),
            itemValue=item.get("BuyPrice"),
            isHot=item.get("Hot"),
            starsystemName=item.get("StarSystem"),
            marketID=item.get("MarketID"),
        )
        if item.get("EngineerModifications") is not None:
            module["engineering"] = _obj(
                blueprintName=item.get("EngineerModifications"),
                blueprintLevel=item.get("Level"),
                blueprintQuality=item.get("Quality"),
            )
        modules.append(module)
    events.append(InaraEvent("setCommanderStorageModules", timestamp, modules, "stored-modules"))


def _map_mission_accepted(
    timestamp: str,
    entry: Mapping[str, Any],
    ctx: InaraContext,
    events: list[InaraEvent],
) -> None:
    data = _obj(
        missionName=entry.get("Name"),
        missionGameID=entry.get("MissionID"),
        influenceGain=entry.get("Influence"),
        reputationGain=entry.get("Reputation"),
        starsystemNameOrigin=ctx.system_name,
        stationNameOrigin=ctx.station_name,
        minorfactionNameOrigin=entry.get("Faction"),
        missionExpiry=entry.get("Expiry"),
        starsystemNameTarget=entry.get("DestinationSystem"),
        stationNameTarget=entry.get("DestinationStation"),
        minorfactionNameTarget=entry.get("TargetFaction"),
        commodityName=entry.get("Commodity"),
        commodityCount=entry.get("Count"),
        targetName=entry.get("Target"),
        targetType=entry.get("TargetType"),
        killCount=entry.get("KillCount"),
        passengerType=entry.get("PassengerType"),
        passengerCount=entry.get("PassengerCount"),
        passengerIsVIP=entry.get("PassengerVIPs"),
        passengerIsWanted=entry.get("PassengerWanted"),
    )
    _add_required(events, "addCommanderMission", timestamp, data, f"mission:{entry.get('MissionID')}")


def _map_rewards(rewards: Any) -> list[dict[str, Any]]:
    if not isinstance(rewards, list):
        return []
    return [
        _obj(itemName=item.get("Name"), itemCount=item.get("Count"))
        for item in rewards
        if isinstance(item, Mapping)
    ]


def _map_mission_completed(timestamp: str, entry: Mapping[str, Any], events: list[InaraEvent]) -> None:
    data = _obj(
        missionGameID=entry.get("MissionID"),
        donationCredits=entry.get("Donation"),
        rewardCredits=entry.get("Reward"),
    )
    permits = entry.get("PermitsAwarded")
    if isinstance(permits, list):
        data["rewardPermits"] = [{"starsystemName": p} for p in permits]
        for permit in permits:
            events.append(InaraEvent("addCommanderPermit", timestamp, {"starsystemName": permit}))
    commodities = entry.get("CommodityReward")
    if isinstance(commodities, list):
        data["rewardCommodities"] = _map_rewards(commodities)
    materials_reward = entry.get("MaterialsReward")
    if isinstance(materials_reward, list):
        data["rewardMaterials"] = _map_rewards(materials_reward)
    effects_raw = entry.get("FactionEffects")
    if isinstance(effects_raw, list):
        effects = []
        for faction in effects_raw:
            if not isinstance(faction, Mapping):
                continue
            effect = _obj(
                minorfactionName=faction.get("Faction"),
                reputationGain=faction.get("Reputation"),
            )
            influence_list = faction.get("Influence")
            if isinstance(influence_list, list):
                strings = [
                    v.get("Influence")
                    for v in influence_list
                    if isinstance(v, Mapping) and isinstance(v.get("Influence"), str)
                ]
                if strings:
                    effect["influenceGain"] = max(strings, key=len)
            effects.append(effect)
        if effects:
            data["minorfactionEffects"] = effects
    _add_required(
        events,
        "setCommanderMissionCompleted",
        timestamp,
        data,
        f"mission:{entry.get('MissionID')}",
    )


def _opponent(entry: Mapping[str, Any], primary: str) -> Any:
    if entry.get(primary) is not None:
        return entry.get(primary)
    if entry.get("Faction") is not None:
        return entry.get("Faction")
    if entry.get("Power") is not None:
        return entry.get("Power")
    if entry.get("IsThargoid") is True or entry.get("isThargoid") is True:
        return "Thargoid"
    return None


def _map_combat(
    name: str,
    timestamp: str,
    entry: Mapping[str, Any],
    ctx: InaraContext,
    events: list[InaraEvent],
) -> None:
    data = _obj(starsystemName=entry.get("StarSystem") or ctx.system_name)
    if name == "Died":
        event_name = "addCommanderCombatDeath"
        killers = entry.get("Killers")
        if isinstance(killers, list):
            data["wingOpponentNames"] = [
                k.get("Name") for k in killers if isinstance(k, Mapping)
            ]
        else:
            data["opponentName"] = entry.get("KillerName") or entry.get("KillerShip")
    elif name == "Interdicted":
        event_name = "addCommanderCombatInterdicted"
        data["isPlayer"] = entry.get("IsPlayer")
        data["isSubmit"] = entry.get("Submitted")
        data["opponentName"] = _opponent(entry, "Interdictor")
    elif name == "Interdiction":
        event_name = "addCommanderCombatInterdiction"
        data["isPlayer"] = entry.get("IsPlayer")
        data["isSuccess"] = entry.get("Success")
        data["opponentName"] = _opponent(entry, "Interdicted")
    elif name == "EscapeInterdiction":
        event_name = "addCommanderCombatInterdictionEscape"
        data["isPlayer"] = entry.get("IsPlayer")
        data["opponentName"] = _opponent(entry, "Interdictor")
    else:
        event_name = "addCommanderCombatKill"
        data["opponentName"] = entry.get("Victim")

    # Drop Nones added above
    data = {k: v for k, v in data.items() if v is not None}
    has_opponent = bool(data.get("opponentName")) or (
        isinstance(data.get("wingOpponentNames"), list) and bool(data["wingOpponentNames"])
    )
    if has_opponent:
        events.append(InaraEvent(event_name, timestamp, data))


def _map_ship_locker(timestamp: str, entry: Mapping[str, Any], events: list[InaraEvent]) -> None:
    if any(not isinstance(entry.get(t), list) for t in _LOCKER_TYPES):
        return
    events.append(
        InaraEvent(
            "resetCommanderInventory",
            timestamp,
            [{"itemType": t} for t in _LOCKER_TYPES],
            "locker:reset",
        )
    )
    data = []
    for type_name in _LOCKER_TYPES:
        for item in entry[type_name]:
            if isinstance(item, Mapping):
                data.append(
                    _obj(
                        itemName=item.get("Name"),
                        itemCount=item.get("Count"),
                        itemType=type_name,
                        itemLocation="ShipLocker",
                    )
                )
    events.append(InaraEvent("setCommanderInventory", timestamp, data, "locker:items"))


def _map_suit_loadout(
    event_name: str,
    timestamp: str,
    entry: Mapping[str, Any],
    events: list[InaraEvent],
) -> None:
    modules = []
    for module in entry.get("Modules") or []:
        if not isinstance(module, Mapping):
            continue
        mods = module.get("WeaponMods")
        modules.append(
            _obj(
                slotName=module.get("SlotName"),
                itemName=module.get("ModuleName"),
                itemClass=module.get("Class"),
                itemGameID=module.get("SuitModuleID"),
                engineering=[
                    {"blueprintName": m}
                    for m in (mods if isinstance(mods, list) else [])
                ],
            )
        )
    _add_required(
        events,
        event_name,
        timestamp,
        _obj(
            loadoutGameID=entry.get("LoadoutID"),
            loadoutName=entry.get("LoadoutName"),
            suitGameID=entry.get("SuitID"),
            suitType=entry.get("SuitName"),
            suitMods=entry.get("SuitMods"),
            suitLoadout=modules,
        ),
        f"suit:{entry.get('LoadoutID')}",
    )


def _map_suit_module(timestamp: str, entry: Mapping[str, Any], events: list[InaraEvent]) -> None:
    mods = entry.get("WeaponMods")
    module = _obj(
        slotName=entry.get("SlotName"),
        itemName=entry.get("ModuleName"),
        itemClass=entry.get("Class"),
        itemGameID=entry.get("SuitModuleID"),
        engineering=[{"blueprintName": m} for m in (mods if isinstance(mods, list) else [])],
    )
    _add_required(
        events,
        "updateCommanderSuitLoadout",
        timestamp,
        _obj(
            loadoutGameID=entry.get("LoadoutID"),
            loadoutName=entry.get("LoadoutName"),
            suitGameID=entry.get("SuitID"),
            suitType=entry.get("SuitName"),
            suitLoadout=[module],
        ),
        f"suit:{entry.get('LoadoutID')}",
    )


def _map_community_goals(timestamp: str, entry: Mapping[str, Any], events: list[InaraEvent]) -> None:
    for goal in entry.get("CurrentGoals") or []:
        if not isinstance(goal, Mapping):
            continue
        gid = goal.get("CGID")
        events.append(
            InaraEvent(
                "setCommunityGoal",
                timestamp,
                _obj(
                    communitygoalGameID=gid,
                    communitygoalName=goal.get("Title"),
                    starsystemName=goal.get("SystemName"),
                    stationName=goal.get("MarketName"),
                    goalExpiry=goal.get("Expiry"),
                    isCompleted=goal.get("IsComplete"),
                    contributorsNum=goal.get("NumContributors"),
                    contributionsTotal=goal.get("CurrentTotal"),
                    topRankSize=goal.get("TopRankSize"),
                ),
                f"community-goal:{gid}",
            )
        )
        events.append(
            InaraEvent(
                "setCommanderCommunityGoalProgress",
                timestamp,
                _obj(
                    communitygoalGameID=gid,
                    contribution=goal.get("PlayerContribution"),
                    percentileBand=goal.get("PlayerPercentileBand"),
                    percentileBandReward=goal.get("Bonus"),
                    isTopRank=goal.get("PlayerInTopRank"),
                ),
                f"community-progress:{gid}",
            )
        )


def _map_friend(timestamp: str, entry: Mapping[str, Any], events: list[InaraEvent]) -> None:
    status = entry.get("Status")
    if status in {"Added", "Online"}:
        event_name = "addCommanderFriend"
    elif status in {"Declined", "Lost"}:
        event_name = "delCommanderFriend"
    else:
        return
    _add_required(
        events,
        event_name,
        timestamp,
        _obj(commanderName=entry.get("Name"), gamePlatform="pc"),
        f"friend:{entry.get('Name')}",
    )


def _map_event(
    name: str,
    timestamp: str,
    entry: Mapping[str, Any],
    ctx: InaraContext,
    events: list[InaraEvent],
) -> None:
    if name == "Progress":
        _map_progress(timestamp, entry, events)
    elif name == "Promotion":
        _map_promotion(timestamp, entry, events)
    elif name == "EngineerProgress":
        _map_engineer(timestamp, entry, events)
    elif name == "Reputation":
        _map_major_reputation(timestamp, entry, events)
    elif name == "PowerplayJoin":
        _add_required(
            events,
            "setCommanderRankPower",
            timestamp,
            _obj(powerName=entry.get("Power"), rankValue=1),
            "power",
        )
    elif name == "PowerplayLeave":
        _add_required(
            events,
            "setCommanderRankPower",
            timestamp,
            _obj(powerName=entry.get("Power"), rankValue=-1),
            "power",
        )
    elif name == "PowerplayDefect":
        _add_required(
            events,
            "setCommanderRankPower",
            timestamp,
            _obj(powerName=entry.get("ToPower"), rankValue=1),
            "power",
        )
    elif name == "Powerplay":
        _add_required(
            events,
            "setCommanderRankPower",
            timestamp,
            _obj(
                powerName=entry.get("Power"),
                rankValue=entry.get("Rank"),
                meritsValue=entry.get("Merits"),
            ),
            "power",
        )
    elif name == "PowerplayRank":
        _add_required(
            events,
            "setCommanderRankPower",
            timestamp,
            _obj(powerName=entry.get("Power"), rankValue=entry.get("Rank")),
            "power",
        )
    elif name == "Docked":
        _map_docked(timestamp, entry, ctx, events)
    elif name == "FSDJump":
        _map_jump("addCommanderTravelFSDJump", timestamp, entry, ctx, events)
        _map_minor_reputation(timestamp, entry, events)
    elif name == "CarrierJump":
        _map_jump("addCommanderTravelCarrierJump", timestamp, entry, ctx, events)
        _map_minor_reputation(timestamp, entry, events)
    elif name == "Location":
        _map_location(timestamp, entry, events)
        _map_minor_reputation(timestamp, entry, events)
    elif name == "SupercruiseExit":
        _map_supercruise_exit(timestamp, entry, events)
    elif name == "ApproachSettlement":
        _map_settlement(timestamp, entry, ctx, events)
    elif name == "DropshipDeploy":
        _add_required(
            events,
            "addCommanderTravelLand",
            timestamp,
            _obj(
                starsystemName=entry.get("StarSystem"),
                starsystemBodyName=entry.get("Body"),
                isTaxiDropship=True,
            ),
        )
    elif name == "Touchdown":
        _map_touchdown(timestamp, entry, ctx, events)
    elif name == "Statistics":
        _map_statistics(timestamp, entry, events)
    elif name == "ShipyardNew":
        _add_required(
            events,
            "addCommanderShip",
            timestamp,
            _obj(
                shipType=entry.get("ShipType"),
                shipGameID=entry.get("NewShipID")
                if entry.get("NewShipID") is not None
                else entry.get("ShipID"),
            ),
        )
    elif name in {"ShipyardBuy", "ShipyardSell", "SellShipOnRebuy", "ShipyardSwap"}:
        _map_shipyard(timestamp, entry, ctx, events)
    elif name == "SetUserShipName":
        ship = _current_ship(ctx)
        if ship is not None:
            events.append(InaraEvent("setCommanderShip", timestamp, ship, f"ship:{ctx.ship_id}"))
    elif name == "ShipyardTransfer":
        _add_required(
            events,
            "setCommanderShipTransfer",
            timestamp,
            _obj(
                shipType=entry.get("ShipType"),
                shipGameID=entry.get("ShipID"),
                starsystemName=ctx.system_name,
                stationName=ctx.station_name,
                transferTime=entry.get("TransferTime"),
            ),
            f"ship-transfer:{entry.get('ShipID')}",
        )
    elif name == "StoredShips":
        _map_stored_ships(timestamp, entry, events)
    elif name == "Loadout":
        _map_loadout(timestamp, entry, ctx, events)
    elif name == "StoredModules":
        _map_stored_modules(timestamp, entry, events)
    elif name == "MissionAccepted":
        _map_mission_accepted(timestamp, entry, ctx, events)
    elif name == "MissionAbandoned":
        _add_required(
            events,
            "setCommanderMissionAbandoned",
            timestamp,
            _obj(missionGameID=entry.get("MissionID")),
            f"mission:{entry.get('MissionID')}",
        )
    elif name == "MissionCompleted":
        _map_mission_completed(timestamp, entry, events)
    elif name == "MissionFailed":
        _add_required(
            events,
            "setCommanderMissionFailed",
            timestamp,
            _obj(missionGameID=entry.get("MissionID")),
            f"mission:{entry.get('MissionID')}",
        )
    elif name in {"Died", "Interdicted", "Interdiction", "EscapeInterdiction", "PVPKill"}:
        _map_combat(name, timestamp, entry, ctx, events)
    elif name == "ShipLocker":
        _map_ship_locker(timestamp, entry, events)
    elif name in {"CreateSuitLoadout", "SuitLoadout"}:
        _map_suit_loadout("setCommanderSuitLoadout", timestamp, entry, events)
    elif name == "DeleteSuitLoadout":
        _add_required(
            events,
            "delCommanderSuitLoadout",
            timestamp,
            _obj(loadoutGameID=entry.get("LoadoutID")),
            f"suit:{entry.get('LoadoutID')}",
        )
    elif name == "RenameSuitLoadout":
        _add_required(
            events,
            "updateCommanderSuitLoadout",
            timestamp,
            _obj(
                loadoutGameID=entry.get("LoadoutID"),
                loadoutName=entry.get("LoadoutName"),
                suitType=entry.get("SuitName"),
                suitGameID=entry.get("SuitID"),
            ),
            f"suit:{entry.get('LoadoutID')}",
        )
    elif name == "LoadoutEquipModule":
        _map_suit_module(timestamp, entry, events)
    elif name == "CommunityGoal":
        _map_community_goals(timestamp, entry, events)
    elif name == "Friends":
        _map_friend(timestamp, entry, events)


def map_journal_entry(
    entry: Mapping[str, Any],
    ctx: InaraContext,
    *,
    collect: bool = True,
) -> list[InaraEvent]:
    """Map one journal event to Inara events (Windows InaraEventMapper parity)."""
    global _session_started, _session_commander

    name = entry.get("event")
    if not isinstance(name, str) or not name.strip():
        return []

    if name == "LoadGame":
        clear_state()

    _update_multicrew(name, entry)
    _credit_observe(entry)
    cargo_changed, materials_changed = _update_inventory(name, entry)
    _update_rank_state(name, entry)

    if not collect or _in_multicrew:
        _session_started = False
        return []

    timestamp = entry.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    events: list[InaraEvent] = []
    cmdr = (ctx.commander or "").strip()
    session_starting = (not _session_started) or (
        cmdr and _session_commander and cmdr.lower() != _session_commander.lower()
    ) or (cmdr and not _session_commander)
    if session_starting and cmdr:
        _session_started = True
        _session_commander = cmdr
        events.append(InaraEvent("getCommanderProfile", timestamp, {}, "profile"))
        ship = _current_ship(ctx)
        if ship is not None:
            events.append(InaraEvent("setCommanderShip", timestamp, ship, f"ship:{ctx.ship_id}"))
        _add_inventory_snapshots(events, timestamp, True, True)

    _map_event(name, timestamp, entry, ctx, events)
    _add_inventory_snapshots(events, timestamp, cargo_changed, materials_changed)

    force_credit = (
        bool(session_starting and cmdr)
        or (name == "Statistics" and _credits_unreported)
        or (name == "Shutdown" and _credits_unreported)
    )
    credit = _credit_report(timestamp, force=force_credit, include_assets=(name == "Statistics"))
    if credit is not None:
        events.append(credit)
    return events


def _coalesce_replace_keys(events: list[InaraEvent]) -> list[InaraEvent]:
    """Match InaraEventQueue.Enqueue: a later ReplaceKey replaces the earlier one."""
    pending: list[InaraEvent] = []
    for ev in events:
        key = ev.replace_key
        if key:
            pending = [item for item in pending if item.replace_key != key]
        pending.append(ev)
    return pending


def build_payload(
    api_key: str,
    commander: str,
    frontier_id: str | None,
    events: Iterable[InaraEvent],
) -> dict[str, Any]:
    header: dict[str, Any] = {
        "appName": APP_NAME,
        "appVersion": APP_VERSION,
        "isBeingDeveloped": IS_BEING_DEVELOPED,
        "APIkey": api_key,
        "commanderName": commander,
    }
    if frontier_id:
        header["commanderFrontierID"] = frontier_id
    return {
        "header": header,
        "events": [
            {
                "eventName": ev.name,
                "eventTimestamp": ev.timestamp,
                "eventData": ev.data,
            }
            for ev in events
        ],
    }


def _post_json(url: str, payload: Mapping[str, Any]) -> tuple[int, str]:
    body = json.dumps(payload, separators=(",", ":"))
    if _post_hook is not None:
        return _post_hook(url, body)
    data = body.encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            return int(getattr(resp, "status", 200) or 200), resp.read().decode(
                "utf-8", errors="replace"
            )
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:
            raw = str(exc)
        return int(exc.code), raw
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, str(exc)


def send_batch(
    api_key: str,
    commander: str,
    frontier_id: str | None,
    events: list[InaraEvent],
) -> UploadResult:
    """POST one Inara batch. Offline/dry-run log intent and skip network."""
    names = [ev.name for ev in events]
    result = UploadResult(event_names=list(names))
    if not events:
        result.skipped = True
        result.reason = "no events"
        return result
    if offline():
        result.skipped = True
        result.reason = "offline"
        _log.info("Inara offline — would send %s", ", ".join(names))
        return result

    payload = build_payload(api_key, commander, frontier_id, events)
    result.payload = payload

    if dry_run():
        result.ok = True
        result.dry_run = True
        result.reason = "dry-run"
        _log.info("Inara dry-run — %s event(s): %s", len(events), ", ".join(names))
        return result

    try:
        status, text = _post_json(ENDPOINT, payload)
    except Exception as exc:
        result.reason = str(exc)
        _log.warning("Inara POST failed: %s", exc)
        return result
    result.status_code = status
    result.reason = text[:200] if text else None
    if 200 <= status < 300:
        result.ok = True
        _log.info("Inara uploaded %s event(s)", len(events))
    else:
        _log.warning("Inara HTTP %s: %s", status, (text or "")[:160])
    return result


def process_journal_events(
    events: Iterable[Mapping[str, Any]],
    *,
    commander: str | None = None,
    frontier_id: str | None = None,
    system_name: str | None = None,
    station_name: str | None = None,
    body_name: str | None = None,
    ship_type: str | None = None,
    ship_id: int | None = None,
    ship_name: str | None = None,
    ship_ident: str | None = None,
    is_taxi: bool | None = None,
    game_version: str | None = None,
    odyssey: bool = True,
    api_key: str | None = None,
    flush: bool = True,
) -> UploadResult:
    """Map a journal batch and optionally POST. Never raises."""
    result = UploadResult(skipped=True, reason="init")
    try:
        key = (api_key if api_key is not None else get_api_key()) or ""
        key = key.strip()
        if not key:
            result.reason = "no api key"
            return result
        if not can_prepare_upload(key, game_version=game_version, odyssey=odyssey):
            result.reason = "not live / beta"
            return result

        cmdr = (commander or "").strip()
        if not cmdr:
            result.reason = "no commander"
            return result

        ctx = InaraContext(
            commander=cmdr,
            frontier_id=(frontier_id or "").strip() or None,
            system_name=system_name,
            station_name=station_name,
            body_name=body_name,
            ship_type=ship_type,
            ship_id=ship_id,
            ship_name=ship_name,
            ship_ident=ship_ident,
            is_taxi=is_taxi,
        )

        mapped: list[InaraEvent] = []
        for entry in events:
            if not isinstance(entry, Mapping):
                continue
            try:
                mapped.extend(map_journal_entry(entry, ctx, collect=True))
            except Exception as exc:
                ev = entry.get("event") if isinstance(entry, Mapping) else "?"
                _log.warning("Inara ignored %s: %s", ev, exc)

        if not mapped:
            result.reason = "no mapped events"
            return result

        # Windows InaraEventQueue: same ReplaceKey drops the older event, cap 1000.
        mapped = _coalesce_replace_keys(mapped)[-1000:]

        if not flush:
            result.skipped = False
            result.reason = "queued"
            result.event_names = [ev.name for ev in mapped]
            return result

        sent = send_batch(key, cmdr, ctx.frontier_id, mapped)
        if sent.ok or sent.dry_run:
            sent.skipped = False
        return sent
    except Exception as exc:
        result.reason = str(exc)
        _log.warning("Inara process failed: %s", exc)
        return result
