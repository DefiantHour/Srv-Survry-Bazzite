#!/usr/bin/env python3
"""Quests runtime — journal missions plus the Windows PlayState host.

PlotQuestMini still uses MissionAccepted rows. Scripted quests follow
PlayState / PlayQuest / PlayChapter. Chapter source runs under lupa.
os, io, debug, and package are removed after the Lua state is created so a
chapter cannot shell out. A chapter error is logged and does not leave this
module. Raven Colonial writes go through the local queue and are not posted
while offline or dry-run.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


@dataclass
class ActiveQuest:
    """One active mission shown on PlotQuestMini."""

    mission_id: int
    title: str
    objective: str = ""
    faction: str = ""
    destination: str = ""
    localised_name: str = ""

    def as_row(self) -> dict[str, str]:
        title = self.localised_name or self.title or f"Mission {self.mission_id}"
        objective = self.objective or self.destination or self.faction
        return {"title": title, "objective": objective}


@dataclass
class QuestList:
    """Persisted active quests."""

    quests: list[ActiveQuest] = field(default_factory=list)

    def active_rows(self) -> list[dict[str, str]]:
        return [q.as_row() for q in self.quests]

    def find(self, mission_id: int) -> ActiveQuest | None:
        for quest in self.quests:
            if quest.mission_id == mission_id:
                return quest
        return None


def default_quests_path(
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    env = os.environ if environ is None else environ
    root = Path.home() if home is None else home
    xdg = env.get("XDG_DATA_HOME") or str(root / ".local" / "share")
    return Path(xdg) / "srvsurvey" / "quests.json"


def load_quests(
    path: Path | None = None,
    *,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> QuestList:
    target = path if path is not None else default_quests_path(environ=environ, home=home)
    if not target.is_file():
        return QuestList()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return QuestList()
    rows: list[object]
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict):
        nested = raw.get("quests")
        rows = list(nested) if isinstance(nested, list) else []
    else:
        return QuestList()
    out: list[ActiveQuest] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        mid = row.get("mission_id") or row.get("MissionID") or row.get("id")
        if not isinstance(mid, (int, float)):
            # Manual JSON rows without ids still show in the mini plotter.
            title = str(
                row.get("title") or row.get("name") or row.get("quest") or ""
            ).strip()
            objective = str(
                row.get("objective") or row.get("detail") or row.get("status") or ""
            ).strip()
            if title or objective:
                out.append(
                    ActiveQuest(
                        mission_id=-(len(out) + 1),
                        title=title or "Quest",
                        objective=objective,
                    )
                )
            continue
        out.append(
            ActiveQuest(
                mission_id=int(mid),
                title=str(row.get("title") or row.get("Name") or "").strip()
                or f"Mission {int(mid)}",
                objective=str(row.get("objective") or "").strip(),
                faction=str(row.get("faction") or row.get("Faction") or "").strip(),
                destination=str(
                    row.get("destination") or row.get("DestinationSystem") or ""
                ).strip(),
                localised_name=str(
                    row.get("localised_name") or row.get("LocalisedName") or ""
                ).strip(),
            )
        )
    return QuestList(quests=out)


def save_quests(
    quest_list: QuestList,
    path: Path | None = None,
    *,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    target = path if path is not None else default_quests_path(environ=environ, home=home)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "quests": [asdict(q) for q in quest_list.quests if q.mission_id >= 0],
    }
    # Preserve negative-id manual stub rows in a friendly shape.
    manual = [q.as_row() for q in quest_list.quests if q.mission_id < 0]
    if manual and not payload["quests"]:
        payload = {"quests": manual}
    elif manual:
        payload["quests"] = list(payload["quests"]) + [
            {**asdict(q), "title": q.title, "objective": q.objective}
            for q in quest_list.quests
            if q.mission_id < 0
        ]
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def _mission_title(entry: dict[str, Any]) -> str:
    for key in ("LocalisedName", "Name", "title"):
        raw = entry.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    mid = entry.get("MissionID")
    return f"Mission {int(mid)}" if isinstance(mid, (int, float)) else "Mission"


def _mission_objective(entry: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("DestinationSystem", "DestinationStation", "TargetType_Localised", "Target"):
        raw = entry.get(key)
        if isinstance(raw, str) and raw.strip():
            parts.append(raw.strip())
    count = entry.get("Count") or entry.get("KillCount")
    if isinstance(count, (int, float)) and count:
        parts.append(f"x{int(count)}")
    return " · ".join(parts)


def apply_journal_event(quest_list: QuestList, entry: dict[str, Any]) -> bool:
    """Update quest list from one journal event. Returns True if changed."""
    event = entry.get("event")
    if not isinstance(event, str):
        return False

    if event == "MissionAccepted":
        mid = entry.get("MissionID")
        if not isinstance(mid, (int, float)):
            return False
        mission_id = int(mid)
        existing = quest_list.find(mission_id)
        title = _mission_title(entry)
        objective = _mission_objective(entry)
        faction = entry.get("Faction")
        dest = entry.get("DestinationSystem")
        localised = entry.get("LocalisedName")
        quest = ActiveQuest(
            mission_id=mission_id,
            title=title,
            objective=objective,
            faction=faction if isinstance(faction, str) else "",
            destination=dest if isinstance(dest, str) else "",
            localised_name=localised if isinstance(localised, str) else "",
        )
        if existing is None:
            quest_list.quests.append(quest)
        else:
            idx = quest_list.quests.index(existing)
            quest_list.quests[idx] = quest
        return True

    if event in ("MissionCompleted", "MissionFailed", "MissionAbandoned"):
        mid = entry.get("MissionID")
        if not isinstance(mid, (int, float)):
            return False
        mission_id = int(mid)
        before = len(quest_list.quests)
        quest_list.quests = [q for q in quest_list.quests if q.mission_id != mission_id]
        return len(quest_list.quests) != before

    if event == "Missions":
        active_ids: set[int] = set()
        for key in ("Active", "Complete"):
            rows = entry.get(key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                mid = row.get("MissionID")
                if isinstance(mid, (int, float)):
                    active_ids.add(int(mid))
        if not active_ids:
            return False
        before = len(quest_list.quests)
        quest_list.quests = [
            q for q in quest_list.quests if q.mission_id < 0 or q.mission_id in active_ids
        ]
        return len(quest_list.quests) != before

    return False


def apply_journal_events(
    quest_list: QuestList,
    events: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> bool:
    changed = False
    for entry in events:
        if apply_journal_event(quest_list, entry):
            changed = True
    return changed


_ON_FUNC = re.compile(r"function\s+on_([A-Za-z0-9_]+)\s*\(")
_ON_START = re.compile(r"function\s+onStart\s*\(")
_ON_EMOTE = re.compile(r"function\s+onEmote\s*\(")
_EMOTE_PART = re.compile(r"=(.+)$")
_ACTION_PART = re.compile(r"_(.+?)_")
_CHIME_PATHS = (
    "/usr/share/sounds/freedesktop/stereo/message.oga",
    "/usr/share/sounds/freedesktop/stereo/complete.oga",
    "/usr/share/sounds/oxygen/stereo/message-new-instant.ogg",
)
_DISK_EVENTS = (
    "Backpack",
    "ModulesInfo",
    "Outfitting",
    "ShipLocker",
    "Shipyard",
    "FCMaterials",
)
_OBJECTIVE_STATES = ("hidden", "visible", "complete", "failed")
_LIVE: dict[int, "PlayQuest"] = {}
_CURRENT: "PlayState | None" = None
_QUEUE_LOCK = threading.Lock()
_WAKE = threading.Event()
_DRAIN_STARTED = False
_UI_LISTENERS: list[Callable[..., None]] = []


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stamp_id() -> str:
    # .NET DateTimeOffset.ToString("yyyyMMddhhmmss") is a 12-hour clock.
    return datetime.now(timezone.utc).strftime("%Y%m%d%I%M%S")


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def rcc_offline() -> bool:
    return (
        _flag("SRVSURVEY_RCC_OFFLINE")
        or _flag("SRVSURVEY_NET_OFFLINE")
        or _flag("SRVSURVEY_GGG_OFFLINE")
    )


def rcc_dry_run() -> bool:
    return _flag("SRVSURVEY_DRY_RUN") or _flag("SRVSURVEY_RCC_DRY_RUN")


def _xdg_data(environ: dict[str, str] | None = None, home: Path | None = None) -> Path:
    env = os.environ if environ is None else environ
    root = Path.home() if home is None else home
    xdg = env.get("XDG_DATA_HOME") or str(root / ".local" / "share")
    return Path(xdg) / "srvsurvey"


def play_state_path(
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    return _xdg_data(environ, home) / "play-state.json"


def rcc_queue_path(
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    return _xdg_data(environ, home) / "rcc-quest-queue.json"


def journal_handlers(source: str) -> list[str]:
    """Event names a chapter would bind (``function on_FSDJump``)."""
    if not source:
        return []
    names = _ON_FUNC.findall(source)
    if _ON_START.search(source):
        names = ["Start", *names]
    return names


def parse_message_markdown(text: str, msg_id: str) -> dict[str, Any]:
    """Windows PlayState.parseMsgMd — header lines then a body."""
    msg: dict[str, Any] = {
        "id": msg_id,
        "from": "",
        "subject": "",
        "body": "",
        "actions": {},
        "tags": [],
    }
    body: list[str] = []
    first_blank = True
    for line in text.splitlines():
        low = line.lower()
        if low.startswith("from:"):
            msg["from"] = line.split(":", 1)[1].strip()
        elif low.startswith("subject:"):
            msg["subject"] = line.split(":", 1)[1].strip()
        elif low.startswith("action:"):
            parts = [p.strip() for p in line.split(":", 2)]
            if len(parts) >= 3 and parts[1]:
                msg["actions"][parts[1]] = parts[2]
        elif low.startswith("tags:"):
            raw = line.split(":", 1)[1].strip()
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = [p.strip() for p in raw.split(",") if p.strip()]
            if isinstance(parsed, list):
                msg["tags"] = [str(item) for item in parsed]
        else:
            if line == "" and first_blank:
                first_blank = False
            else:
                body.append(line)
    msg["body"] = "\n".join(body).strip() + ("\n" if body else "")
    if not msg["actions"]:
        msg["actions"] = {}
    return msg


def _user_agent() -> str:
    try:
        from client_identity import user_agent
    except ImportError as exc:
        _log(f"quest identity: {exc}")
        return "SrvSurvey-2.0.95.0"
    return user_agent()


def _rcc_key(explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    try:
        from secrets_store import RCC_API_KEY, get_secret
    except ImportError as exc:
        _log(f"quest secrets: {exc}")
        return ""
    try:
        return (get_secret(RCC_API_KEY) or "").strip()
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        _log(f"quest secrets read: {exc}")
        return ""


def _svc(override: str | None = None) -> str:
    try:
        from raven_colonial import resolve_svc_uri
    except ImportError as exc:
        _log(f"quest rcc uri: {exc}")
        return "https://ravencolonial100-awcbdvabgze4c5cq.canadacentral-01.azurewebsites.net"
    return resolve_svc_uri(override)


def _quote(part: str) -> str:
    return urllib.parse.quote(str(part), safe="")


def _read_queue(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        _log(f"quest queue read: {exc}")
        return []
    rows = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _write_queue(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"items": items}, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _ensure_drain_thread() -> None:
    global _DRAIN_STARTED
    with _QUEUE_LOCK:
        if _DRAIN_STARTED:
            return
        _DRAIN_STARTED = True

    def loop() -> None:
        while True:
            _WAKE.wait(30)
            _WAKE.clear()
            try:
                drain_rcc_queue()
            except (OSError, json.JSONDecodeError, UnicodeError, ValueError) as exc:
                _log(f"quest queue drain: {exc}")

    threading.Thread(target=loop, name="srvsurvey-rcc-quest-queue", daemon=True).start()


def enqueue_rcc(item: dict[str, Any]) -> dict[str, Any]:
    """Append one Raven Colonial payload. Dry-run and offline items are not posted."""
    path = rcc_queue_path()
    stored = dict(item)
    stored["id"] = str(time.monotonic_ns())
    stored["queued_at"] = _utc_now()
    with _QUEUE_LOCK:
        rows = _read_queue(path)
        rows.append(stored)
        _write_queue(path, rows)
    _ensure_drain_thread()
    if stored.get("reason") == "send":
        _WAKE.set()
    return stored


def _http_rcc(method: str, url: str, body: str | None, key: str) -> tuple[int, str]:
    headers = {
        "User-Agent": _user_agent(),
        "Accept": "application/json",
        "rcc-key": key,
    }
    data = None if body is None else body.encode("utf-8")
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return int(getattr(resp, "status", 200) or 200), resp.read().decode(
                "utf-8", errors="replace"
            )
    except urllib.error.HTTPError as exc:
        try:
            text = exc.read().decode("utf-8", errors="replace")
        except OSError:
            text = str(exc.reason)
        return int(exc.code), text
    except urllib.error.URLError as exc:
        return 0, str(exc.reason)
    except TimeoutError as exc:
        return 0, str(exc)
    except OSError as exc:
        return 0, str(exc)


def drain_rcc_queue() -> int:
    """Post queued Raven Colonial payloads once the link is up and dry-run is off."""
    if rcc_offline() or rcc_dry_run():
        return 0
    key = _rcc_key(None)
    if not key:
        return 0
    path = rcc_queue_path()
    sent = 0
    finished: set[str] = set()
    with _QUEUE_LOCK:
        rows = _read_queue(path)
    for item in rows:
        reason = str(item.get("reason") or "")
        item_id = str(item.get("id") or "")
        if reason == "dry_run" or reason not in {"send", "offline"}:
            continue
        method = str(item.get("method") or "POST")
        url = str(item.get("url") or "")
        body = item.get("body")
        status, text = _http_rcc(method, url, body if isinstance(body, str) else None, key)
        if status == 0 or status >= 500:
            _log(f"quest queue hold {method} {url}: {status} {text}")
            break
        finished.add(item_id)
        if 200 <= status < 300:
            sent += 1
            _finish_queued(item, status, text)
            continue
        _log(f"quest queue drop {method} {url}: {status} {text}")
    with _QUEUE_LOCK:
        current = _read_queue(path)
        _write_queue(path, [row for row in current if str(row.get("id") or "") not in finished])
    return sent


def _finish_queued(item: dict[str, Any], status: int, text: str) -> None:
    op = str(item.get("op") or "")
    if op != "activate":
        return
    try:
        definition = json.loads(text) if text else None
    except json.JSONDecodeError as exc:
        _log(f"quest activate body: {exc}")
        return
    if not isinstance(definition, dict):
        _log("quest activate body was not an object")
        return
    state = _CURRENT
    if state is None:
        return
    try:
        state.install_activated(definition)
    except (ValueError, KeyError, OSError) as exc:
        _log(f"quest activate install: {exc}")


def _queue_or_send(
    *,
    op: str,
    method: str,
    url: str,
    body: str | None,
    fid: str,
    publisher: str = "",
    quest_id: str = "",
    wait: bool = False,
) -> dict[str, Any]:
    reason = "dry_run" if rcc_dry_run() else "offline" if rcc_offline() else "send"
    item = enqueue_rcc(
        {
            "op": op,
            "method": method,
            "url": url,
            "body": body,
            "reason": reason,
            "fid": fid,
            "publisher": publisher,
            "quest_id": quest_id,
        }
    )
    result: dict[str, Any] = {
        "ok": False,
        "skipped": reason != "send",
        "dry_run": reason == "dry_run",
        "queued": True,
        "status_code": None,
        "body": body or "",
    }
    if reason != "send":
        if reason == "dry_run":
            result["ok"] = True
        return result
    if not wait:
        return result
    status_count = drain_rcc_queue()
    result["ok"] = status_count > 0
    result["skipped"] = False
    return result


def publish_quest_stub(
    fid: str,
    quest: dict[str, Any],
    *,
    api_key: str | None = None,
    svc_uri: str | None = None,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    """POST /api/quest/publish through the local queue.

    Offline and dry-run append the payload and do not POST.
    """
    result: dict[str, Any] = {
        "ok": False,
        "skipped": False,
        "dry_run": False,
        "queued": False,
        "status_code": None,
        "body": "",
    }
    key = _rcc_key(api_key)
    if not key:
        result["skipped"] = True
        result["body"] = "no rcc api key"
        return result
    if not (fid or "").strip():
        result["skipped"] = True
        result["body"] = "missing fid"
        return result
    explicit_dry = dry_run is True or (dry_run is None and rcc_dry_run())
    if dry_run is False:
        explicit_dry = False
    url = f"{_svc(svc_uri)}/api/quest/publish"
    payload = json.dumps(quest)
    if explicit_dry or rcc_offline():
        reason = "dry_run" if explicit_dry else "offline"
        enqueue_rcc(
            {
                "op": "publish",
                "method": "POST",
                "url": url,
                "body": payload,
                "reason": reason,
                "fid": fid,
            }
        )
        result["queued"] = True
        result["dry_run"] = reason == "dry_run"
        result["skipped"] = reason != "send"
        result["ok"] = reason == "dry_run"
        result["body"] = json.dumps({"fid": fid, "quest": quest})
        return result
    queued = _queue_or_send(
        op="publish",
        method="POST",
        url=url,
        body=payload,
        fid=fid,
        wait=True,
    )
    queued["body"] = payload
    return queued


def play_chime() -> None:
    """Play a message chime when a freedesktop sound and a player exist."""
    found: str | None = None
    for candidate in _CHIME_PATHS:
        if os.path.isfile(candidate):
            found = candidate
            break
    if found is None:
        pass
        return
    player: str | None = None
    for candidate in ("/usr/bin/pw-play", "/usr/bin/paplay"):
        if os.path.isfile(candidate):
            player = candidate
            break
    if player is None:
        pass
        return
    try:
        subprocess.Popen(
            [player, found],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        _log(f"quest chime: {exc}")


def gtk_dialog(message: str, title: str, *, yes_no: bool) -> str:
    """WinForms MessageBox replacement. Returns yes, no, or ok."""
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        _log(f"quest dialog ({title}): {message}")
        return "no" if yes_no else "ok"
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
    except (ImportError, ValueError) as exc:
        _log(f"quest dialog ({title}): {message} ({exc})")
        return "no" if yes_no else "ok"
    try:
        ok, _argv = Gtk.init_check()
    except (RuntimeError, TypeError) as exc:
        _log(f"quest dialog ({title}): {message} ({exc})")
        return "no" if yes_no else "ok"
    if not ok:
        _log(f"quest dialog ({title}): {message}")
        return "no" if yes_no else "ok"
    buttons = Gtk.ButtonsType.YES_NO if yes_no else Gtk.ButtonsType.OK
    dialog = Gtk.MessageDialog(
        None,
        Gtk.DialogFlags.MODAL,
        Gtk.MessageType.WARNING if yes_no else Gtk.MessageType.INFO,
        buttons,
        message,
    )
    dialog.set_title(title)
    try:
        response = dialog.run()
    except RuntimeError as exc:
        _log(f"quest dialog run: {exc}")
        return "no" if yes_no else "ok"
    finally:
        dialog.destroy()
    if yes_no:
        return "yes" if response == Gtk.ResponseType.YES else "no"
    return "ok"


def update_ui(quest: "PlayQuest | None") -> None:
    for listener in list(_UI_LISTENERS):
        try:
            listener(quest)
        except (RuntimeError, ValueError, OSError) as exc:
            _log(f"quest ui: {exc}")


def on_quest_ui(listener: Callable[..., None]) -> None:
    _UI_LISTENERS.append(listener)


def _lua_error_types() -> tuple[type[BaseException], ...]:
    try:
        from lupa import LuaError
    except ImportError:
        return ()
    return (LuaError,)


def _is_lua_table(value: object) -> bool:
    if value is None or isinstance(value, (str, bytes, bool, int, float, dict, list)):
        return False
    module = getattr(type(value), "__module__", "")
    return module.startswith("lupa") and hasattr(value, "items")


def _lua_strings(value: object) -> list[str]:
    if _is_lua_table(value):
        out: list[str] = []
        for _key, item in value.items():
            out.append("" if item is None else str(item))
        return out
    return ["" if value is None else str(value)]


def _drop_colon(args: tuple[Any, ...], owner: object) -> tuple[Any, ...]:
    if args and args[0] is owner:
        return args[1:]
    return args


def _py_to_lua(lua: Any, value: object) -> Any:
    """JToken/JObject conversion. ``to_tbl_discarded`` is the empty-table path."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, datetime):
        table = lua.table()
        table["year"] = value.year
        table["month"] = value.month
        table["day"] = value.day
        table["hour"] = value.hour
        table["min"] = value.minute
        table["sec"] = value.second
        # Lua Sunday = 1. Python weekday Monday = 0.
        table["wday"] = (value.weekday() + 1) % 7 + 1
        table["yday"] = value.timetuple().tm_yday
        if value.tzinfo is not None:
            table["isdst"] = bool(value.astimezone().dst())
        else:
            table["isdst"] = bool(time.localtime(time.mktime(value.timetuple())).tm_isdst)
        return table
    if isinstance(value, dict):
        table = lua.table()
        for key, item in value.items():
            if key is None or item is None:
                continue
            table[str(key)] = _py_to_lua(lua, item)
        return table
    if isinstance(value, (list, tuple)):
        table = lua.table()
        for index, item in enumerate(value, start=1):
            table[index] = _py_to_lua(lua, item)
        return table
    raise TypeError(f"Unexpected value: ({type(value).__name__}) {value}")


def _discarded_object_table(lua: Any) -> Any:
    """Windows LuaUtils.toTbl(object) builds a JObject and returns a new empty table."""
    return lua.table()


def _lua_to_py(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if not _is_lua_table(value):
        return str(value)
    array_items: list[tuple[int, object]] = []
    map_items: list[tuple[str, object]] = []
    for key, item in value.items():
        if isinstance(key, int) or (isinstance(key, float) and key == int(key)):
            array_items.append((int(key), _lua_to_py(item)))
        elif isinstance(key, str):
            map_items.append((key, _lua_to_py(item)))
        else:
            raise ValueError(
                f"Not supported: Table keys must be strings. Found ({type(key).__name__}) '{key}'"
            )
    if array_items and map_items:
        raise ValueError("Not supported: tables must be either an array or a map, not both")
    if map_items:
        return {key: item for key, item in map_items}
    array_items.sort(key=lambda pair: pair[0])
    return [item for _key, item in array_items]


def _new_lua(chapter_id: str, quest: "PlayQuest", chapter: "PlayChapter") -> Any:
    try:
        from lupa import LuaRuntime
    except ImportError as exc:
        _log(f"quest lua runtime missing: {exc}")
        return None
    lua = LuaRuntime(unpack_returned_tuples=True, register_eval=False, register_builtins=False)
    lua.execute("os = nil; io = nil; debug = nil; package = nil; loadfile = nil; dofile = nil; require = nil")
    lua.globals().chapterId = chapter_id

    def lua_print(*args: object) -> None:
        text = ", ".join("" if arg is None else str(arg) for arg in args)
        _log(f"-- {quest.quest_id}/{chapter_id} -- {text}")

    lua.globals().print = lua_print
    lua.execute(
        "function arrlen(tt)\n"
        "  local count = 0\n"
        "  for _ in pairs(tt) do\n"
        "    count = count + 1\n"
        "  end\n"
        "  return count\n"
        "end\n"
    )
    lua.globals().quest = _bind_api(lua, QuestApi(quest))
    lua.globals().objective = _bind_api(lua, ObjectiveApi(quest))
    lua.globals().chapter = _bind_api(lua, ChapterApi(chapter))
    lua.globals().cmdr = _bind_api(lua, CmdrApi(chapter))
    return lua


def _bind_api(lua: Any, api: object) -> Any:
    """Expose methods and the current property values. Colon calls drop the Lua self table."""
    table = lua.table()
    for name in dir(api):
        if name.startswith("_"):
            continue
        descriptor = getattr(type(api), name, None)
        if isinstance(descriptor, property) and descriptor.fget is not None:
            if name in {"lastDocked", "lastFSDJump"}:
                table[name] = None
            else:
                table[name] = descriptor.fget(api)
            continue
        method = getattr(api, name)
        if not callable(method):
            continue

        def caller(*args: object, _method: Callable[..., object] = method, _owner: object = table) -> object:
            return _method(*_drop_colon(args, _owner))

        table[name] = caller
    return table


def _refresh_cmdr(chapter: "PlayChapter") -> None:
    if chapter.lua is None:
        return
    api = CmdrApi(chapter)
    table = chapter.lua.globals().cmdr
    table["name"] = api.name
    table["status"] = api.status
    kept = chapter.quest.kept
    if "Docked" in kept and kept.get("Docked") is not None:
        try:
            table["lastDocked"] = _py_to_lua(chapter.lua, kept["Docked"])
        except TypeError as exc:
            _log(f"quest last Docked: {exc}")
            table["lastDocked"] = None
    else:
        table["lastDocked"] = None
    if "FSDJump" in kept and kept.get("FSDJump") is not None:
        try:
            table["lastFSDJump"] = _py_to_lua(chapter.lua, kept["FSDJump"])
        except TypeError as exc:
            _log(f"quest last FSDJump: {exc}")
            table["lastFSDJump"] = None
    else:
        table["lastFSDJump"] = None


def _scan_globals(lua: Any) -> list[tuple[str, str]]:
    lua.execute(
        "function __srv_scan()\n"
        "  local rows = {}\n"
        "  for k, v in pairs(_G) do\n"
        "    if type(k) == 'string' then\n"
        "      rows[#rows + 1] = k .. '\\0' .. type(v)\n"
        "    end\n"
        "  end\n"
        "  return rows\n"
        "end\n"
    )
    rows = lua.globals()["__srv_scan"]()
    found: list[tuple[str, str]] = []
    if rows is None:
        return found
    for row in rows.values():
        text = "" if row is None else str(row)
        if "\0" not in text:
            continue
        name, kind = text.split("\0", 1)
        if name.startswith("__srv"):
            continue
        found.append((name, kind))
    return found


def _should_save(result: object) -> bool:
    if isinstance(result, tuple):
        if not result:
            return False
        first: object = result[0]
    else:
        first = result
    if first is None or first is False:
        return False
    if str(first) == "false":
        return False
    return True


class CmdrContext:
    def __init__(self) -> None:
        self.commander = ""
        self.latitude: float | None = None
        self.longitude: float | None = None
        self.heading: float | None = None
        self.planet_radius = 0.0
        self.has_lat_long = False
        self.status_present = False
        self.factions: list[dict[str, Any]] = []

    def apply_status(self, status: object) -> None:
        if status is None:
            return
        self.status_present = True
        if isinstance(status, dict):
            lat = status.get("latitude", status.get("Latitude"))
            lon = status.get("longitude", status.get("Longitude"))
            heading = status.get("heading", status.get("Heading"))
            radius = status.get("planet_radius", status.get("PlanetRadius"))
            self.commander = str(status.get("commander") or self.commander)
        else:
            lat = getattr(status, "latitude", None)
            lon = getattr(status, "longitude", None)
            heading = getattr(status, "heading", None)
            radius = getattr(status, "planet_radius", None)
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            self.latitude = float(lat)
            self.longitude = float(lon)
            self.has_lat_long = True
        if isinstance(heading, (int, float)):
            self.heading = float(heading)
        if isinstance(radius, (int, float)):
            self.planet_radius = float(radius)


class PlayChapter:
    def __init__(self, chapter_id: str, quest: "PlayQuest", source: str = "") -> None:
        self.id = chapter_id
        self.quest = quest
        self.source = source
        self.start_time: str | None = None
        self.end_time: str | None = None
        self.vars: dict[str, Any] = {}
        self.handlers: list[str] = journal_handlers(source)
        self.var_names: set[str] = set()
        self.pending: list[Callable[[], None]] = []
        self.lua: Any = None
        self.in_lua = False
        self.invoking_func: str | None = None

    @property
    def active(self) -> bool:
        return self.end_time is None and self.start_time is not None

    def has_func(self, name: str) -> bool:
        if self.lua is not None:
            value = self.lua.globals()[name]
            if callable(value):
                return True
        if name == "onStart":
            return "Start" in self.handlers
        if name == "onEmote":
            return _ON_EMOTE.search(self.source or "") is not None
        if name.startswith("on_"):
            return name[3:] in self.handlers
        return False

    def load(self) -> None:
        if not self.active:
            return
        _log(f"PlayChapter.load: {self.id} (dev:{self.quest.dev})")
        if not (self.source or "").strip():
            if self.quest.dev:
                self.source = self.quest.chapter_sources.get(self.id, "")
            else:
                self.source = _fetch_chapter_source(self) or ""
        if not (self.source or "").strip():
            _log(f"No code for: '{self.id}'")
            raise ValueError(f"No code for: '{self.id}' ?")
        self.handlers = journal_handlers(self.source)
        lua = _new_lua(self.id, self.quest, self)
        if lua is None:
            return
        prior = {name for name, _kind in _scan_globals(lua)}
        try:
            lua.execute(self.source)
        except _lua_error_types() as exc:
            self._report_lua(exc)
            return
        self.lua = lua
        _refresh_cmdr(self)
        func_names: list[str] = []
        for name, kind in _scan_globals(lua):
            if kind == "function" and name.startswith("on_"):
                func_names.append(name[3:])
            elif kind != "function" and name not in prior and name not in {"chapterId", "quest", "objective", "chapter", "cmdr", "arrlen", "print"}:
                self.var_names.add(name)
        for name in func_names:
            if name not in self.handlers:
                self.handlers.append(name)
        if self.has_func("onStart") and "Start" not in self.handlers:
            self.handlers.insert(0, "Start")
        self.push_vars()
        self.pull_vars()
        self.quest.lua_executed = True

    def push_vars(self) -> None:
        if self.lua is None:
            return
        for key, value in self.vars.items():
            self.lua.globals()[key] = _py_to_lua(self.lua, value)

    def pull_vars(self) -> None:
        if not self.active or self.lua is None:
            return
        env = self.lua.globals()
        for name in self.var_names:
            try:
                self.vars[name] = _lua_to_py(env[name])
            except ValueError as exc:
                _log(f"quest var {name}: {exc}")

    def start(self) -> None:
        if self.active:
            return
        self.start_time = _utc_now()
        self.end_time = None
        if self.lua is None:
            self.load()
        has_on_start = self.has_func("onStart")
        _log(f"Starting chapter: {self.id}, run onStart: {has_on_start}")
        if has_on_start and self.lua is not None:
            self.invoke("onStart", [])
            self.quest.dirty = True
        elif has_on_start:
            self.quest.dirty = True

    def stop(self) -> None:
        if not self.active:
            return
        if self.in_lua:
            self.pending.append(self.stop)
            return
        _log(f"Stopping chapter: {self.id}")
        self.end_time = _utc_now()
        self.lua = None
        self.quest.dirty = True

    def do_pendings(self) -> None:
        if not self.pending:
            return
        queued = list(self.pending)
        self.pending.clear()
        for action in queued:
            action()

    def run_debug(self, code: str) -> str:
        if not self.active or self.lua is None:
            return "Chapter not active"
        try:
            result = self.lua.execute(code)
        except _lua_error_types() as exc:
            self._report_lua(exc)
            return json.dumps(str(exc))
        self.do_pendings()
        try:
            payload = _lua_to_py(result)
        except ValueError as exc:
            _log(f"quest debug: {exc}")
            payload = str(result)
        return json.dumps(payload)

    def process_entry(self, entry: dict[str, Any]) -> tuple[bool, list[str]]:
        event = entry.get("event")
        if not isinstance(event, str) or not self.active:
            return False, []
        should = False
        fired: list[str] = []
        func_name = f"on_{event}"
        if self.has_func(func_name):
            fired.append(f"{self.id}.{func_name}")
            if self.lua is not None:
                try:
                    lua_entry = _py_to_lua(self.lua, entry)
                except TypeError as exc:
                    _log(f"quest journal value: {exc}")
                    lua_entry = self.lua.table()
                should = self.invoke(func_name, [lua_entry]) or should
        if event == "ReceiveText" and self.has_func("onEmote"):
            message = entry.get("Message")
            text = message if isinstance(message, str) else ""
            if text.startswith("$HumanoidEmote_"):
                fired.append(f"{self.id}.onEmote")
                should = self._emote(text) or should
        return should, fired

    def invoke(self, func_name: str, args: list[object]) -> bool:
        if self.lua is None or not callable(self.lua.globals()[func_name]):
            _log(f"Missing function '{func_name}'")
            return False
        if self.quest.invoking is not None:
            _log(f"nested quest invoke while {self.quest.invoking.id} is running")
        _log(f"[{self.quest.quest_id}/{self.id}] Invoking: {func_name}")
        self.quest.invoking = self
        self.invoking_func = func_name
        self.in_lua = True
        _refresh_cmdr(self)
        try:
            try:
                result = self.lua.globals()[func_name](*args)
            except _lua_error_types() as exc:
                self._report_lua(exc)
                return False
            return _should_save(result)
        finally:
            self.in_lua = False
            self.invoking_func = None
            self.quest.invoking = None

    def _report_lua(self, exc: BaseException) -> None:
        match = re.search(r":(\d+):", str(exc))
        line = match.group(1) if match else "?"
        message = f"Script error on line {line} of {self.id}.lua: {exc}"
        _log(message)
        if gtk_dialog(message + "\n\nDebug?", "LUA Error", yes_no=True) == "yes":
            _log(f"quest debug break: {exc}")

    def _emote(self, message: str) -> bool:
        parts = [part for part in re.split(r"[:;]", message) if part]
        try:
            actor_match = _EMOTE_PART.search(parts[2])
            action_match = _EMOTE_PART.search(parts[3])
            if actor_match is None or action_match is None:
                raise IndexError(message)
            actor = actor_match.group(1)
            action_inner = _ACTION_PART.search(action_match.group(1))
            if action_inner is None:
                raise IndexError(message)
            action = action_inner.group(1)
            if len(parts) < 5:
                target = ""
            else:
                target_match = _EMOTE_PART.search(parts[-1])
                target = "" if target_match is None else target_match.group(1)
        except IndexError as exc:
            _log(f"quest emote: {exc}")
            return False
        return self.invoke("onEmote", [actor, action, target])

    def on_message_read(self, msg_id: str) -> None:
        if not self.active:
            raise ValueError(f"Cannot invoke message read action: {msg_id}, chapter not active: {self.id}")
        if self.quest.message(msg_id) is None:
            raise ValueError(f"Message not found, id: {msg_id}")
        if self.has_func("onMsgRead"):
            self.invoke("onMsgRead", [msg_id])
        update_ui(self.quest)

    def on_message_action(self, msg_id: str, action_id: str) -> None:
        if not self.active:
            raise ValueError(
                f"Cannot invoke message: {msg_id}, response action: {action_id}, chapter not active: {self.id}"
            )
        message = self.quest.message(msg_id)
        if message is None:
            raise ValueError(f"Message not found, id: {msg_id}")
        self.invoke("onMsgAction", [action_id, msg_id])
        message["replied"] = action_id
        self.quest.dirty = True
        update_ui(self.quest)

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "handlers": list(self.handlers),
            "start_time": self.start_time,
            "end_time": self.end_time,
            "vars": self.vars,
            "active": self.active,
        }


def _fetch_chapter_source(chapter: PlayChapter) -> str | None:
    quest = chapter.quest
    if rcc_offline() or rcc_dry_run():
        _log(f"quest chapter fetch skipped: {chapter.id}")
        return None
    key = _rcc_key(None)
    if not key:
        _log("quest chapter fetch skipped: no rcc api key")
        return None
    parent = quest.parent
    fid = "" if parent is None else parent.fid
    url = (
        f"{_svc(None)}/api/quest/{_quote(quest.publisher)}/{_quote(quest.quest_id)}/"
        f"{quest.ver}/chapter/{_quote(chapter.id)}"
    )
    status, text = _http_rcc("GET", url, None, key)
    if status in {401, 404} or not (200 <= status < 300):
        _log(f"RCC.getQuestChapter: HTTP:{status} {text}")
        return None
    return text


class PlayQuest:
    def __init__(self) -> None:
        self.parent: PlayState | None = None
        self.publisher = ""
        self.quest_id = ""
        self.ver = 0.0
        self.title = ""
        self.first_chapter = ""
        self.dev = False
        self.watch_folder = ""
        self.dirty = False
        self.invoking: PlayChapter | None = None
        self.chapters_to_start: list[str] = []
        self.chapters_to_stop: list[str] = []
        self.start_time: str | None = None
        self.end_time: str | None = None
        self.paused = False
        self.tags: set[str] = set()
        self.body_locations: dict[str, dict[str, float]] = {}
        self.chapters: list[PlayChapter] = []
        self.messages: list[dict[str, Any]] = []
        self.templates: list[dict[str, Any]] = []
        self.objective_text: dict[str, str] = {}
        self.objectives: dict[str, dict[str, Any]] = {}
        self.vars: dict[str, Any] = {}
        self.kept: dict[str, Any] = {}
        self.routes: list[dict[str, Any]] = []
        self.strings: dict[str, str] = {}
        self.chapter_sources: dict[str, str] = {}
        self.lua_executed = False
        self.sub_title = ""
        self.desc = ""
        self.cmdr = CmdrContext()

    def _log(self, message: str) -> None:
        chapter = self.invoking.id if self.invoking is not None else ""
        func = self.invoking.invoking_func if self.invoking is not None else ""
        _log(f"[{self.quest_id}/{chapter}/{func}] {message}")

    def chapter(self, chapter_id: str) -> PlayChapter | None:
        for row in self.chapters:
            if row.id == chapter_id:
                return row
        return None

    def message(self, msg_id: str) -> dict[str, Any] | None:
        for row in self.messages:
            if row.get("id") == msg_id:
                return row
        return None

    def template(self, msg_id: str) -> dict[str, Any] | None:
        for row in self.templates:
            if row.get("id") == msg_id:
                return row
        return None

    def process_entry(self, entry: dict[str, Any]) -> bool:
        self.dirty = False
        triggered = False
        fired: list[str] = []
        active = [chapter for chapter in self.chapters if chapter.active]
        for chapter in active:
            try:
                should, names = chapter.process_entry(entry)
            except ValueError as exc:
                _log(f"quest chapter {chapter.id}: {exc}")
                continue
            triggered = triggered or should
            fired.extend(names)
        event = entry.get("event")
        if isinstance(event, str) and (event in self.kept or event in {"Docked", "FSDJump"}):
            self.kept[event] = entry
            self.dirty = True
        for chapter in active:
            chapter.do_pendings()
        self._fired = fired
        self.save(force=triggered)
        return triggered

    def save(self, force: bool = False) -> bool:
        if not self.dirty and not force:
            return False
        if self.chapters_to_stop:
            self.stop_chapters()
        if self.chapters_to_start:
            self.start_chapters()
        for chapter in self.chapters:
            if chapter.active:
                chapter.pull_vars()
        if self.dev:
            if self.parent is not None:
                self.parent.save_local()
            self.dirty = False
        else:
            payload = self.to_rcc_body()
            fid = "" if self.parent is None else self.parent.fid

            def fire(body: str = payload, commander: str = fid, publisher: str = self.publisher, quest_id: str = self.quest_id, ver: float = self.ver) -> None:
                if self.dev or not publisher or not quest_id.strip() or ver == 0:
                    return
                url = f"{_svc(None)}/api/quest/cmdr/save/{_quote(publisher)}/{_quote(quest_id)}"
                _queue_or_send(
                    op="save",
                    method="POST",
                    url=url,
                    body=body,
                    fid=commander,
                    publisher=publisher,
                    quest_id=quest_id,
                    wait=False,
                )
                self.dirty = False

            threading.Timer(5.0, fire).start()
        update_ui(self)
        self.dirty = False
        return True

    def complete(self) -> None:
        self._log("PQ.complete")
        self.end_time = _utc_now()
        if self.parent is None:
            return
        if self.dev:
            self.parent.remove_quest(self, "complete")
            self.save(force=True)
        else:
            self.save(force=True)
            self.parent.remove_quest(self, "complete")
        update_ui(None)

    def fail(self) -> None:
        self._log("PQ.fail")
        self.end_time = _utc_now()
        if self.parent is None:
            return
        if self.dev:
            self.parent.remove_quest(self, "failed")
            self.save(force=True)
        else:
            self.save(force=True)
            self.parent.remove_quest(self, "failed")
        update_ui(None)

    def queue_start(self, chapter_id: str) -> None:
        self.chapters_to_start.append(chapter_id)
        self.dirty = True

    def queue_stop(self, chapter_id: str) -> None:
        self.chapters_to_stop.append(chapter_id)
        self.dirty = True

    def start_chapters(self) -> None:
        while self.chapters_to_start:
            chapter_id = self.chapters_to_start[0]
            self._log(f"PQ.startChapter: {chapter_id}")
            chapter = self.chapter(chapter_id)
            if chapter is None:
                raise ValueError(f"Bad chapter id: {chapter_id}")
            if not chapter.active:
                chapter.start()
            self.chapters_to_start.pop(0)

    def stop_chapters(self) -> None:
        while self.chapters_to_stop:
            chapter_id = self.chapters_to_stop[0]
            self._log(f"PQ.stopChapter: {chapter_id}")
            chapter = self.chapter(chapter_id)
            if chapter is None:
                raise ValueError(f"Bad chapter id: {chapter_id}")
            if chapter.active:
                chapter.stop()
            self.chapters_to_stop.pop(0)

    def set_var(self, name: str, value: object) -> None:
        self._log(f"PQ.setVar: {name}")
        if value is None:
            if name in self.vars:
                del self.vars[name]
                self.dirty = True
            return
        if name not in self.vars or self.vars[name] != value:
            self.vars[name] = _lua_to_py(value) if _is_lua_table(value) else value
            self.dirty = True

    def get_var(self, name: str) -> object:
        if name not in self.vars:
            self._log(f"PQ.getVar: NOT STORED: '{name}'")
            return None
        return self.vars[name]

    def send_msg(
        self,
        msg_id: str | None = None,
        sender: str | None = None,
        subject: str | None = None,
        body: str | None = None,
    ) -> None:
        template = None if msg_id is None else self.template(msg_id)
        if msg_id is not None and template is None and sender is None:
            raise ValueError(f"Bad message: {msg_id}")
        chapter_id = None if self.invoking is None else self.invoking.id
        actions = None if template is None else template.get("actions")
        if isinstance(actions, dict) and actions and chapter_id is None:
            raise ValueError(
                f"Chapter must be set when using messages with actions. Id: {template.get('id') if template else msg_id}"
            )
        play: dict[str, Any] = {
            "id": (None if template is None else template.get("id")) or _stamp_id(),
            "from": sender if sender is not None else (None if template is None else template.get("from")),
            "subject": subject if subject is not None else (None if template is None else template.get("subject")),
            "body": body if body is not None else (None if template is None else template.get("body")),
            "received": _utc_now(),
            "chapter": chapter_id,
            "actions": list(actions.keys()) if isinstance(actions, dict) else None,
            "read": False,
            "replied": None,
        }
        if template is not None:
            if play["from"] == template.get("from"):
                play["from"] = None
            if play["subject"] == template.get("subject"):
                play["subject"] = None
            if play["body"] == template.get("body"):
                play["body"] = None
            tags = template.get("tags")
            if isinstance(tags, list) and tags:
                for tag in tags:
                    if str(tag).strip():
                        self.tags.add(str(tag))
                self.dirty = True
        self._log(f"PQ.sendMsg: {play['id']}")
        self.messages = [row for row in self.messages if row.get("id") != play["id"]]
        self.messages.append(play)
        self.dirty = True
        play_chime()

    def delete_msg(self, msg_id: str) -> bool:
        self._log(f"PQ.deleteMsg: {msg_id}")
        before = len(self.messages)
        self.messages = [row for row in self.messages if row.get("id") != msg_id]
        removed = len(self.messages) != before
        if removed:
            self.dirty = True
        update_ui(self)
        return removed

    def on_message_read(self, msg_id: str) -> None:
        self._log(f"PQ.onMessageRead: {msg_id}")
        message = self.message(msg_id)
        if message is None:
            raise ValueError(f"Message not found, id: {msg_id}")
        chapter_id = message.get("chapter")
        chapter = None if not isinstance(chapter_id, str) else self.chapter(chapter_id)
        if chapter is None:
            _log(f"Bad chapter id: {self.quest_id}")
            return
        chapter.on_message_read(msg_id)

    def invoke_message_action(self, msg_id: str, action_id: str) -> None:
        self._log(f"PQ.invokeMessageAction: {msg_id}")
        message = self.message(msg_id)
        if message is None:
            raise ValueError(f"Message not found, id: {msg_id}")
        chapter_id = message.get("chapter")
        chapter = None if not isinstance(chapter_id, str) else self.chapter(chapter_id)
        if chapter is None:
            raise ValueError(f"Bad chapter id: {self.quest_id}")
        chapter.on_message_action(msg_id, action_id)

    def keep_last(self, names: set[str]) -> None:
        names.add("Docked")
        names.add("FSDJump")
        self._log(f"PQ.keepLast: {','.join(sorted(names))}")
        if len(names) == len(self.kept) and all(name in names for name in self.kept):
            return
        rebuilt: dict[str, Any] = {}
        for name in names:
            if name.strip():
                rebuilt[name] = self.kept.get(name)
        self.kept = rebuilt
        self.dirty = True

    def get_last(self, event_name: str) -> object:
        if event_name not in self.kept:
            self._log(f"PQ.getLast: NOT TRACKING: '{event_name}'")
        last = self.kept.get(event_name)
        if last is None or self.invoking is None or self.invoking.lua is None:
            return None
        try:
            return _py_to_lua(self.invoking.lua, last)
        except TypeError as exc:
            _log(f"quest last {event_name}: {exc}")
            return None

    def to_rcc_body(self) -> str:
        return json.dumps(self.to_public())

    def to_public(self) -> dict[str, Any]:
        runtime_id = id(self)
        _LIVE[runtime_id] = self
        return {
            "__runtime_id": runtime_id,
            "publisher": self.publisher,
            "id": self.quest_id,
            "ver": self.ver,
            "title": self.title,
            "subTitle": self.sub_title,
            "desc": self.desc,
            "firstChapter": self.first_chapter,
            "dev": self.dev,
            "watchFolder": self.watch_folder,
            "startTime": self.start_time,
            "endTime": self.end_time,
            "paused": self.paused,
            "strings": self.strings,
            "objectives": {
                key: {
                    "id": key,
                    "text": self.objective_text.get(key, key),
                    "state": row.get("state", "hidden"),
                    "current": row.get("current", 0),
                    "total": row.get("total", 0),
                }
                for key, row in {**{k: {"state": "hidden", "current": 0, "total": 0} for k in self.objective_text}, **self.objectives}.items()
            },
            "messages": self.messages,
            "templates": self.templates,
            "chapters": [chapter.to_public() for chapter in self.chapters],
            "tags": sorted(self.tags),
            "locations": self.body_locations,
            "keptLasts": self.kept,
            "routes": self.routes,
            "vars": self.vars,
            "luaExecuted": self.lua_executed,
            "pendingHandlers": list(getattr(self, "_fired", [])),
        }


class QuestApi:
    def __init__(self, quest: PlayQuest) -> None:
        self._quest = quest

    def complete(self) -> None:
        self._quest.complete()

    def fail(self) -> None:
        self._quest.fail()

    def startChapter(self, chapter_id: str) -> None:
        self._quest.queue_start(str(chapter_id))

    def nextChapter(self, chapter_id: str) -> None:
        invoking = self._quest.invoking
        self._quest.queue_start(str(chapter_id))
        if invoking is not None:
            self._quest.queue_stop(invoking.id)

    def stopChapter(self, chapter_id: str) -> None:
        self._quest.queue_stop(str(chapter_id))

    def set(self, name: str, value: object = None) -> None:
        self._quest.set_var(str(name), value)

    def get(self, name: str) -> object:
        value = self._quest.get_var(str(name))
        chapter = self._quest.invoking
        if chapter is None or chapter.lua is None or not isinstance(value, (dict, list)):
            return value
        return _py_to_lua(chapter.lua, value)

    def sendMsg(self, msg_id: object = None, sender: object = None, subject: object = None, body: object = None) -> None:
        self._quest.send_msg(
            None if msg_id is None else str(msg_id),
            None if sender is None else str(sender),
            None if subject is None else str(subject),
            None if body is None else str(body),
        )

    def deleteMsg(self, msg_id: str) -> bool:
        return self._quest.delete_msg(str(msg_id))

    def tag(self, value: object) -> None:
        for tag in _lua_strings(value):
            if tag.strip():
                if tag not in self._quest.tags:
                    self._quest.dirty = True
                self._quest.tags.add(tag)

    def untag(self, value: object) -> None:
        for tag in _lua_strings(value):
            if tag.strip() and tag in self._quest.tags:
                self._quest.tags.remove(tag)
                self._quest.dirty = True

    def setTags(self, value: object) -> None:
        self.clearTags()
        self.tag(value)

    def clearTags(self) -> None:
        if self._quest.tags:
            self._quest.dirty = True
        self._quest.tags.clear()

    def trackLocation(self, name: str, lat: float, longitude: float, size: float) -> None:
        self._quest.body_locations[str(name)] = {
            "lat": float(lat),
            "long": float(longitude),
            "size": float(size),
        }
        self._quest.dirty = True

    def clearLocation(self, name: str) -> None:
        if str(name) in self._quest.body_locations:
            del self._quest.body_locations[str(name)]
            self._quest.dirty = True

    def clearAllLocations(self) -> None:
        if self._quest.body_locations:
            self._quest.dirty = True
        self._quest.body_locations.clear()

    def keepLast(self, value: object) -> None:
        self._quest.keep_last({item for item in _lua_strings(value) if item.strip()})

    def setRoute(self, route_id: str, width: float, lat_longs: object) -> None:
        if not _is_lua_table(lat_longs):
            raise ValueError("setRoute waypoints must be a table")
        waypoints: list[list[float]] = []
        for _key, item in lat_longs.items():
            parts = str(item).split(",")
            waypoints.append([float(part.strip()) for part in parts])
        self._quest.routes = [row for row in self._quest.routes if row.get("id") != route_id]
        self._quest.routes.append({"id": str(route_id), "w": float(width), "wp": waypoints})
        self._quest.dirty = True

    def clearRoute(self, route_id: str) -> None:
        self._quest.routes = [row for row in self._quest.routes if row.get("id") != route_id]
        self._quest.dirty = True


class ObjectiveApi:
    def __init__(self, quest: PlayQuest) -> None:
        self._quest = quest

    def _ids(self, value: object) -> list[str]:
        return [item for item in _lua_strings(value)]

    def _set(
        self,
        ids: list[str],
        new_state: str | None,
        current: int = -1,
        total: int = -1,
    ) -> None:
        _log(
            f"[{self._quest.quest_id}] SO.setState: ({new_state}, {current}, {total}) => [{', '.join(ids)}]"
        )
        dirty = False
        for objective_id in ids:
            if not objective_id:
                continue
            if objective_id not in self._quest.objective_text:
                raise ValueError(f"Unknown objective ID: {objective_id}")
            row = self._quest.objectives.setdefault(
                objective_id,
                {"state": "hidden", "current": 0, "total": 0},
            )
            if new_state is not None and row.get("state") != new_state:
                row["state"] = new_state
                dirty = True
            if current >= 0 and row.get("current") != current:
                row["current"] = current
                dirty = True
            if total >= 0 and row.get("total") != total:
                row["total"] = total
                dirty = True
        if dirty:
            self._quest.dirty = True

    def complete(self, value: object) -> None:
        self._set(self._ids(value), "complete")

    def failed(self, value: object) -> None:
        self._set(self._ids(value), "failed")

    def hide(self, value: object) -> None:
        self._set(self._ids(value), "hidden")

    def show(self, value: object, current: int = -1, total: int = -1) -> None:
        self._set(self._ids(value), "visible", int(current), int(total))

    def progress(self, value: object, current: int, total: int) -> None:
        self._set(self._ids(value), None, int(current), int(total))

    def remove(self, value: object) -> None:
        ids = self._ids(value)
        _log(f"[{self._quest.quest_id}] SO.remove: [{', '.join(ids)}]")
        for objective_id in ids:
            if objective_id in self._quest.objectives:
                del self._quest.objectives[objective_id]
                self._quest.dirty = True

    def isActive(self, objective_id: str) -> bool:
        _log(f"[{self._quest.quest_id}] SO.isActive: {objective_id}")
        row = self._quest.objectives.get(str(objective_id))
        return bool(row and row.get("state") == "visible")

    def check(self, value: object, state: str) -> bool:
        if state not in _OBJECTIVE_STATES:
            raise ValueError(
                f"Bad objective state: '{state}'. Try: {','.join(_OBJECTIVE_STATES)}"
            )
        ids = self._ids(value)
        _log(f"[{self._quest.quest_id}] SO.check: [{', '.join(ids)}] == {state}")
        for objective_id in ids:
            if objective_id not in self._quest.objective_text:
                raise ValueError(f"Unknown objective ID: {objective_id}")
            row = self._quest.objectives.get(objective_id)
            current = "hidden" if row is None else str(row.get("state") or "hidden")
            if current != state:
                return False
        return True

    def getCurrent(self, objective_id: str) -> int:
        if str(objective_id) not in self._quest.objective_text:
            raise ValueError(f"Unknown objective ID: {objective_id}")
        row = self._quest.objectives.get(str(objective_id))
        return 0 if row is None else int(row.get("current") or 0)

    def getTotal(self, objective_id: str) -> int:
        if str(objective_id) not in self._quest.objective_text:
            raise ValueError(f"Unknown objective ID: {objective_id}")
        row = self._quest.objectives.get(str(objective_id))
        return 0 if row is None else int(row.get("total") or 0)


class ChapterApi:
    def __init__(self, chapter: PlayChapter) -> None:
        self._chapter = chapter

    def stop(self) -> None:
        self._chapter.quest.queue_stop(self._chapter.id)


class CmdrApi:
    def __init__(self, chapter: PlayChapter) -> None:
        self._chapter = chapter

    def _ctx(self) -> CmdrContext:
        return self._chapter.quest.cmdr

    @property
    def name(self) -> str:
        return self._ctx().commander

    def last(self, event_name: str) -> object:
        return self._chapter.quest.get_last(str(event_name))

    @property
    def lastDocked(self) -> object:
        return self._chapter.quest.get_last("Docked")

    @property
    def lastFSDJump(self) -> object:
        return self._chapter.quest.get_last("FSDJump")

    def _faction(self, name: str) -> dict[str, Any] | None:
        for row in self._ctx().factions:
            if row.get("Name") == name:
                return row
        return None

    def getFactionRep(self, faction_name: str) -> float:
        match = self._faction(str(faction_name))
        if match is None or not isinstance(match.get("MyReputation"), (int, float)):
            return float("nan")
        return float(match["MyReputation"])

    def getFactionInf(self, faction_name: str) -> float:
        match = self._faction(str(faction_name))
        if match is None or not isinstance(match.get("Influence"), (int, float)):
            return float("nan")
        return float(match["Influence"])

    def getFactionStates(self, faction_name: str, tense: str = "active") -> object:
        lua = self._chapter.lua
        match = self._faction(str(faction_name))
        if lua is None:
            return []
        if match is None:
            return lua.table()
        if tense == "recovering":
            return _state_table(lua, match.get("RecoveringStates"))
        if tense == "pending":
            return _state_table(lua, match.get("PendingStates"))
        if tense == "active":
            active = match.get("ActiveStates")
            if active is None:
                return _state_table(lua, [match.get("FactionState")])
            return _state_table(lua, active)
        raise ValueError("Bad value for tense, try: active, pending, recovering")

    @property
    def status(self) -> object:
        lua = self._chapter.lua
        if lua is None:
            return {}
        return _discarded_object_table(lua)

    def distanceFrom(self, lat: float, longitude: float) -> float:
        ctx = self._ctx()
        if not ctx.status_present or ctx.latitude is None or ctx.longitude is None:
            return -1.0
        from geo import get_distance

        return float(
            get_distance(
                float(lat),
                float(longitude),
                ctx.latitude,
                ctx.longitude,
                ctx.planet_radius,
            )
        )

    def isWithin(self, lat: float, longitude: float, target_dist: float) -> bool:
        ctx = self._ctx()
        if not ctx.has_lat_long:
            return False
        dist = self.distanceFrom(lat, longitude)
        return dist >= 0 and dist < float(target_dist)

    def headingBetween(self, heading: int, tolerance: int) -> bool:
        ctx = self._ctx()
        if not ctx.status_present or ctx.heading is None:
            return False
        cmdr_heading = ctx.heading
        left = int(heading) - int(tolerance)
        if left < 0:
            left += 360
        right = int(heading) + int(tolerance)
        if right >= 360:
            right -= 360
        if left > right:
            return cmdr_heading >= left or cmdr_heading <= right
        return cmdr_heading >= left and cmdr_heading <= right


def _state_table(lua: Any, rows: object) -> Any:
    table = lua.table()
    if not isinstance(rows, list):
        return table
    index = 1
    for item in rows:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            raw = item.get("State", item.get("state"))
            name = "" if raw is None else str(raw)
        else:
            name = "" if item is None else str(item)
        if name:
            table[index] = name
            index += 1
    return table


class PlayState:
    def __init__(self) -> None:
        self.fid = ""
        self.cmdr = ""
        self.dev_ref: dict[str, Any] | None = None
        self.dev_quest: PlayQuest | None = None
        self.active: list[PlayQuest] = []
        self.path: Path | None = None
        self.journal_folder: Path | None = None
        self.data_dir: Path | None = None

    def save_local(self) -> None:
        target = self.path if self.path is not None else play_state_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fid": self.fid,
            "cmdr": self.cmdr,
            "devRef": self.dev_ref,
            "devQuest": None if self.dev_quest is None else _disk_quest(self.dev_quest),
            "activeQuests": [_disk_quest(quest) for quest in self.active],
        }
        target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        if self.fid:
            folder = target.parent / "quests"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{self.fid}.json").write_text(
                json.dumps({"fid": self.fid, "cmdr": self.cmdr, "devRef": self.dev_ref}, indent=2) + "\n",
                encoding="utf-8",
            )

    def save_remote_refused(self) -> None:
        _log("PlayState.Save without localOnly is not used")

    def activate_quest(self, publisher: str, quest_id: str) -> PlayQuest:
        url = f"{_svc(None)}/api/quest/cmdr/{_quote(publisher)}/{_quote(quest_id)}"
        outcome = _queue_or_send(
            op="activate",
            method="PUT",
            url=url,
            body=None,
            fid=self.fid,
            publisher=publisher,
            quest_id=quest_id,
            wait=True,
        )
        if not outcome.get("ok"):
            raise ValueError(f"Cannot activate quest by: {publisher} / {quest_id}")
        found = self.get(quest_id)
        if found is None:
            raise ValueError(f"Cannot activate quest by: {publisher} / {quest_id}")
        return found

    def install_activated(self, definition: dict[str, Any]) -> PlayQuest:
        quest = _quest_from_definition(definition, dev=False)
        quest.parent = self
        quest.start_time = _utc_now()
        _log(f"Activating NEW quest: {quest.publisher} / {quest.quest_id} / {quest.quest_id}")
        self.init_quest(quest, start_first=True)
        update_ui(quest)
        _queue_or_send(
            op="fetch_cmdr",
            method="GET",
            url=f"{_svc(None)}/api/quest/cmdr",
            body=None,
            fid=self.fid,
            wait=False,
        )
        return quest

    def resume_quest(self, publisher: str, quest_id: str) -> PlayQuest:
        url = (
            f"{_svc(None)}/api/quest/cmdr/{_quote(publisher)}/{_quote(quest_id)}/state/active"
        )
        outcome = _queue_or_send(
            op="set_state",
            method="POST",
            url=url,
            body=None,
            fid=self.fid,
            publisher=publisher,
            quest_id=quest_id,
            wait=True,
        )
        if not outcome.get("ok"):
            raise ValueError(f"Cannot resume quest by: {publisher} / {quest_id}")
        loaded = _load_cmdr_quests(self.fid, "active")
        found = None
        for row in loaded:
            if row.get("publisher") == publisher and row.get("id") == quest_id:
                found = row
                break
        if found is None:
            raise ValueError(f"Cannot find quest by: {publisher} / {quest_id}")
        quest = _quest_from_definition(found, dev=False)
        if isinstance(found.get("chapters"), list):
            _apply_play_fields(quest, found)
        self.init_quest(quest, start_first=False)
        update_ui(quest)
        return quest

    def remove_quest(self, quest: PlayQuest, new_state: str) -> None:
        if not quest.dev:
            if new_state == "unknown":
                url = f"{_svc(None)}/api/quest/cmdr/{_quote(quest.publisher)}/{_quote(quest.quest_id)}"
                outcome = _queue_or_send(
                    op="delete",
                    method="DELETE",
                    url=url,
                    body=None,
                    fid=self.fid,
                    publisher=quest.publisher,
                    quest_id=quest.quest_id,
                    wait=True,
                )
            else:
                url = (
                    f"{_svc(None)}/api/quest/cmdr/{_quote(quest.publisher)}/"
                    f"{_quote(quest.quest_id)}/state/{_quote(new_state)}"
                )
                outcome = _queue_or_send(
                    op="set_state",
                    method="POST",
                    url=url,
                    body=None,
                    fid=self.fid,
                    publisher=quest.publisher,
                    quest_id=quest.quest_id,
                    wait=True,
                )
            if outcome.get("ok"):
                self.active = [row for row in self.active if row is not quest]
            else:
                _log(f"quest remove queued or refused: {quest.publisher}/{quest.quest_id}")
        elif quest.dev or (
            self.dev_quest is not None
            and self.dev_quest.publisher == quest.publisher
            and self.dev_quest.quest_id == quest.quest_id
        ):
            self.dev_ref = None
            self.dev_quest = None
            self.save_local()
            self.active = [row for row in self.active if row is not quest]
        else:
            _log(f"quest remove ignored: {quest.publisher}/{quest.quest_id}")

    def init_quest(self, quest: PlayQuest, start_first: bool) -> None:
        quest.parent = self
        _set_prior_kepts(quest, self.journal_folder)
        for chapter in quest.chapters:
            chapter.quest = quest
            if chapter.active:
                chapter.load()
        if start_first:
            first = quest.chapter(quest.first_chapter)
            if first is not None and first.end_time is None:
                quest.queue_start(quest.first_chapter)
                quest.start_chapters()
        self.active = [
            row
            for row in self.active
            if not (row.publisher == quest.publisher and row.quest_id == quest.quest_id)
        ]
        self.active.append(quest)
        if quest.dev:
            self.dev_quest = quest
            self.dev_ref = {
                "publisher": quest.publisher,
                "id": quest.quest_id,
                "ver": quest.ver,
            }
        if start_first:
            quest.save(force=False)

    def get(self, quest_id: str) -> PlayQuest | None:
        for quest in self.active:
            if quest.quest_id == quest_id:
                return quest
        return None

    def is_tagged(self, tag: str) -> bool:
        for quest in self.active:
            for have in quest.tags:
                if have.lower() == tag.lower():
                    return True
        return False

    def process_raw(self, raw: dict[str, Any]) -> None:
        entry = _substitute_journal(raw, self.journal_folder)
        for quest in list(self.active):
            try:
                quest.process_entry(entry)
            except ValueError as exc:
                _log(f"quest {quest.quest_id}: {exc}")
            except OSError as exc:
                _log(f"quest {quest.quest_id}: {exc}")
            except json.JSONDecodeError as exc:
                _log(f"quest {quest.quest_id}: {exc}")
        for quest in [row for row in self.active if row.dirty]:
            quest.save(force=False)


def _disk_quest(quest: PlayQuest) -> dict[str, Any]:
    payload = quest.to_public()
    payload.pop("__runtime_id", None)
    return payload


def _set_prior_kepts(quest: PlayQuest, folder: Path | None) -> None:
    if "Docked" not in quest.kept:
        found = _walk_latest(folder, "Docked")
        if found is not None:
            quest.kept["Docked"] = found
    if "FSDJump" not in quest.kept:
        found = _walk_latest(folder, "FSDJump")
        if found is not None:
            quest.kept["FSDJump"] = found


def _walk_latest(folder: Path | None, event_name: str) -> dict[str, Any] | None:
    if folder is None or not folder.is_dir():
        return None
    files = sorted(folder.glob("Journal.*.log"), key=lambda path: path.name, reverse=True)
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            _log(f"quest journal walk: {exc}")
            continue
        found: dict[str, Any] | None = None
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict) and entry.get("event") == event_name:
                found = entry
        if found is not None:
            return found
    return None


def _substitute_journal(raw: dict[str, Any], folder: Path | None) -> dict[str, Any]:
    event = raw.get("event")
    if event in {"Cargo", "Market", "NavRoute"} and folder is not None:
        path = folder / f"{event}.json"
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeError) as exc:
                _log(f"quest companion {event}: {exc}")
                return raw
            if isinstance(loaded, dict):
                return loaded
        return raw
    if event in _DISK_EVENTS:
        if folder is None:
            raise FileNotFoundError(f"{event}.json")
        path = folder / f"{event}.json"
        if not path.is_file():
            raise FileNotFoundError(str(path))
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"Unexpected value: {event}.json")
        return loaded
    return raw


def _load_cmdr_quests(fid: str, state_name: str) -> list[dict[str, Any]]:
    url = f"{_svc(None)}/api/quest/cmdr/load/{_quote(state_name)}"
    if rcc_offline() or rcc_dry_run():
        _queue_or_send(
            op="load",
            method="POST",
            url=url,
            body=None,
            fid=fid,
            wait=False,
        )
        return []
    key = _rcc_key(None)
    if not key:
        return []
    status, text = _http_rcc("POST", url, None, key)
    if status in {401, 404} or not (200 <= status < 300):
        _log(f"RCC.loadCmdrQuests: HTTP:{status} {text}")
        return []
    try:
        data = json.loads(text) if text else []
    except json.JSONDecodeError as exc:
        _log(f"RCC.loadCmdrQuests: {exc}")
        return []
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def _quest_from_definition(raw: dict[str, Any], *, dev: bool) -> PlayQuest:
    quest = PlayQuest()
    quest.dev = dev
    quest.publisher = str(raw.get("publisher") or "")
    quest.quest_id = str(raw.get("id") or "")
    quest.ver = float(raw.get("ver") or 0)
    quest.title = str(raw.get("title") or quest.quest_id or "Quest")
    quest.sub_title = str(raw.get("subTitle") or "")
    quest.desc = str(raw.get("desc") or "")
    quest.first_chapter = str(raw.get("firstChapter") or raw.get("first_chapter") or "")
    strings = raw.get("strings") if isinstance(raw.get("strings"), dict) else {}
    quest.strings = {str(key): str(value) for key, value in strings.items()}
    objectives = raw.get("objectives") if isinstance(raw.get("objectives"), dict) else {}
    for key, value in objectives.items():
        if isinstance(value, str):
            quest.objective_text[str(key)] = value
        elif isinstance(value, dict):
            quest.objective_text[str(key)] = str(value.get("text") or key)
            quest.objectives[str(key)] = {
                "state": str(value.get("state") or "hidden"),
                "current": int(value.get("current") or 0),
                "total": int(value.get("total") or 0),
            }
    chapters = raw.get("chapters") if isinstance(raw.get("chapters"), dict) else {}
    for key, value in chapters.items():
        source = value if isinstance(value, str) else ""
        quest.chapter_sources[str(key)] = source
        quest.chapters.append(PlayChapter(str(key), quest, source))
    for item in raw.get("msgs") or []:
        if isinstance(item, dict) and item.get("id"):
            quest.templates.append(dict(item))
    return quest


def _apply_play_fields(quest: PlayQuest, raw: dict[str, Any]) -> None:
    if isinstance(raw.get("vars"), dict):
        quest.vars = dict(raw["vars"])
    if isinstance(raw.get("keptLasts"), dict):
        quest.kept = dict(raw["keptLasts"])
    if isinstance(raw.get("tags"), list):
        quest.tags = {str(item) for item in raw["tags"]}
    if isinstance(raw.get("locations"), dict):
        quest.body_locations = dict(raw["locations"])
    if isinstance(raw.get("routes"), list):
        quest.routes = [row for row in raw["routes"] if isinstance(row, dict)]
    if isinstance(raw.get("messages"), list):
        quest.messages = [row for row in raw["messages"] if isinstance(row, dict)]
    chapters = raw.get("chapters")
    if isinstance(chapters, list):
        for row in chapters:
            if not isinstance(row, dict):
                continue
            chapter = quest.chapter(str(row.get("id") or ""))
            if chapter is None:
                continue
            chapter.start_time = row.get("start_time")
            chapter.end_time = row.get("end_time")
            if isinstance(row.get("vars"), dict):
                chapter.vars = dict(row["vars"])
            if isinstance(row.get("source"), str) and row["source"]:
                chapter.source = row["source"]


def _preserve_dev(previous: PlayQuest, quest: PlayQuest) -> None:
    quest.objectives.update(previous.objectives)
    quest.vars.update(previous.vars)
    quest.tags.update(previous.tags)
    quest.body_locations.update(previous.body_locations)
    quest.kept.update(previous.kept)
    for route in previous.routes:
        quest.routes.append(route)
    for old in previous.chapters:
        chapter = quest.chapter(old.id)
        if chapter is None:
            continue
        chapter.start_time = old.start_time
        chapter.end_time = old.end_time
        chapter.vars.update(old.vars)
        chapter.push_vars()
    for old in previous.messages:
        replaced = False
        for index, row in enumerate(quest.messages):
            if row.get("id") == old.get("id"):
                quest.messages[index] = old
                replaced = True
                break
        if not replaced:
            quest.messages.append(old)


def side_load_quest(
    folder: Path | str,
    *,
    data_dir: Path | None = None,
    journal_folder: Path | None = None,
    fid: str = "",
    commander: str = "",
) -> dict[str, Any]:
    """Import a quest folder the way PlayState.sideLoad does, then start the first chapter."""
    global _CURRENT
    root = Path(folder)
    quest_path = root / "quest.json"
    if not quest_path.is_file():
        raise FileNotFoundError(f"quest.json not found in {root}")
    try:
        raw = json.loads(quest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"quest.json: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("quest.json must be an object")
    publisher = str(raw.get("publisher") or "").strip()
    quest_id = str(raw.get("id") or "").strip()
    if "|" in publisher or "|" in quest_id:
        raise ValueError("Quest publisher or ID cannot contain '|' characters")
    _log(f"Begin: sideLoad quest from: {root}")
    for path in sorted(root.glob("*.md")):
        parsed = parse_message_markdown(path.read_text(encoding="utf-8"), path.stem)
        msgs = raw.get("msgs")
        if not isinstance(msgs, list):
            msgs = []
            raw["msgs"] = msgs
        msgs.append(parsed)
    strings_path = root / "strings.json"
    if strings_path.is_file():
        try:
            loaded = json.loads(strings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"strings.json: {exc}") from exc
        if isinstance(loaded, dict):
            raw["strings"] = {str(key): str(value) for key, value in loaded.items()}
    chapters = raw.get("chapters") if isinstance(raw.get("chapters"), dict) else {}
    raw["chapters"] = chapters
    for path in sorted(root.glob("*.lua")):
        chapters[path.stem] = path.read_text(encoding="utf-8")
    first = str(raw.get("firstChapter") or raw.get("first_chapter") or "").strip()
    if not first or first not in chapters:
        raise ValueError(f"First chapter script not found: {first}.lua")
    quest = _quest_from_definition(raw, dev=True)
    quest.watch_folder = str(root)
    quest.start_time = _utc_now()
    quest.messages = [dict(row) for row in quest.templates]
    for row in quest.messages:
        row["read"] = False
    state = PlayState()
    state.fid = fid
    state.cmdr = commander
    state.journal_folder = journal_folder
    state.data_dir = data_dir
    state.path = (data_dir / "play-state.json") if data_dir is not None else play_state_path()
    if _CURRENT is not None and _CURRENT.dev_quest is not None:
        previous = _CURRENT.dev_quest
        if previous.publisher == quest.publisher and previous.quest_id == quest.quest_id:
            _preserve_dev(previous, quest)
    state.dev_ref = {"publisher": quest.publisher, "id": quest.quest_id, "ver": quest.ver}
    state.dev_quest = quest
    host_dir = data_dir if data_dir is not None else _xdg_data() / "quests"
    host_dir.mkdir(parents=True, exist_ok=True)
    definition = dict(raw)
    (host_dir / f"dev-{quest.quest_id}.json").write_text(
        json.dumps(definition, indent=2) + "\n",
        encoding="utf-8",
    )
    state.init_quest(quest, start_first=True)
    state.save_local()
    _CURRENT = state
    update_ui(quest)
    return quest.to_public()


def _resolve(state: dict[str, Any]) -> PlayQuest:
    runtime_id = state.get("__runtime_id")
    if isinstance(runtime_id, int) and runtime_id in _LIVE:
        return _LIVE[runtime_id]
    raw = dict(state)
    chapter_rows = raw.get("chapters")
    if isinstance(chapter_rows, list):
        sources: dict[str, str] = {}
        for row in chapter_rows:
            if isinstance(row, dict) and row.get("id"):
                sources[str(row["id"])] = str(row.get("source") or "")
        raw["chapters"] = sources
    quest = _quest_from_definition(raw, dev=bool(state.get("dev")))
    _apply_play_fields(quest, state)
    if isinstance(chapter_rows, list):
        for row in chapter_rows:
            if not isinstance(row, dict) or not row.get("active"):
                continue
            chapter = quest.chapter(str(row.get("id") or ""))
            if chapter is None:
                continue
            if not chapter.active:
                chapter.start_time = row.get("start_time") or _utc_now()
                chapter.end_time = None
            if chapter.lua is None and (chapter.source or "").strip():
                try:
                    chapter.load()
                except ValueError as exc:
                    _log(f"quest reload {chapter.id}: {exc}")
    parent = PlayState()
    quest.parent = parent
    parent.active.append(quest)
    _LIVE[id(quest)] = quest
    return quest


def _publish_into(state: dict[str, Any], quest: PlayQuest) -> None:
    public = quest.to_public()
    state.clear()
    state.update(public)


def start_chapter(state: dict[str, Any], chapter_id: str) -> dict[str, Any]:
    quest = _resolve(state)
    if quest.chapter(chapter_id) is None:
        raise KeyError(f"Bad chapter id: {chapter_id}")
    quest.queue_start(chapter_id)
    quest.start_chapters()
    _publish_into(state, quest)
    return state


def stop_chapter(state: dict[str, Any], chapter_id: str) -> dict[str, Any]:
    quest = _resolve(state)
    if quest.chapter(chapter_id) is None:
        raise KeyError(f"Bad chapter id: {chapter_id}")
    quest.queue_stop(chapter_id)
    quest.stop_chapters()
    _publish_into(state, quest)
    return state


def activate_first_chapter(state: dict[str, Any]) -> dict[str, Any]:
    first = str(state.get("firstChapter") or "")
    if first:
        start_chapter(state, first)
    return state


def set_objective(
    state: dict[str, Any],
    objective_id: str,
    *,
    state_name: str,
    current: int | None = None,
    total: int | None = None,
) -> dict[str, Any]:
    quest = _resolve(state)
    if objective_id not in quest.objective_text:
        quest.objective_text[objective_id] = objective_id
    ObjectiveApi(quest)._set(
        [objective_id],
        state_name,
        -1 if current is None else int(current),
        -1 if total is None else int(total),
    )
    _publish_into(state, quest)
    return state


def send_message(
    state: dict[str, Any],
    *,
    msg_id: str | None = None,
    sender: str | None = None,
    subject: str | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    quest = _resolve(state)
    if msg_id and quest.template(msg_id) is None:
        quest.templates.append(
            {
                "id": msg_id,
                "from": sender or "",
                "subject": subject or "",
                "body": body or "",
                "actions": {},
            }
        )
    quest.send_msg(msg_id, sender, subject, body)
    _publish_into(state, quest)
    return state


def journal_handler_fragment(entry: dict[str, Any], fields: list[str] | None = None) -> str:
    """Windows FormPlayJournal.generateCodeFragment.

    Selected fields become an ``if`` on string, bool, and number values.
    Other value types are left out, the same as the WinForms generator.
    """
    event_name = str(entry.get("event") or "Journal")
    lines = [f"function on_{event_name}(entry)"]
    clauses: list[str] = []
    for name in fields or []:
        if name == "event" or name not in entry:
            continue
        value = entry[name]
        if isinstance(value, bool):
            clauses.append(f"entry.{name} == {str(value).lower()}")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            clauses.append(f"entry.{name} == {value}")
        elif isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            clauses.append(f'entry.{name} == "{escaped}"')
    if clauses:
        lines.append(f"  if {' and '.join(clauses)} then")
        lines.append("    -- TODO: your code")
        lines.append("  end")
    else:
        lines.append("  -- TODO: your code")
    lines.append("end")
    return "\n".join(lines) + "\n"


def reply_message(state: dict[str, Any], msg_id: str, action_id: str) -> bool:
    """FormPlayComms reply. Runs onMsgAction when the message's chapter is active."""
    quest = _resolve(state)
    try:
        quest.invoke_message_action(msg_id, action_id)
    except ValueError as exc:
        _log(f"quest reply: {exc}")
        return False
    _publish_into(state, quest)
    return True


def mark_message_read(state: dict[str, Any], msg_id: str) -> bool:
    quest = _resolve(state)
    message = quest.message(msg_id)
    if message is None:
        return False
    message["read"] = True
    quest.dirty = True
    try:
        quest.on_message_read(msg_id)
    except ValueError as exc:
        _log(f"quest read: {exc}")
    _publish_into(state, quest)
    return True


def apply_script_journal(state: dict[str, Any], entry: dict[str, Any]) -> list[str]:
    """Run active chapter hooks for one journal event and keep Docked / FSDJump."""
    quest = _resolve(state)
    try:
        quest.process_entry(entry if isinstance(entry, dict) else {})
    except ValueError as exc:
        _log(f"quest script: {exc}")
    except OSError as exc:
        _log(f"quest script: {exc}")
    except json.JSONDecodeError as exc:
        _log(f"quest script: {exc}")
    fired = list(getattr(quest, "_fired", []))
    _publish_into(state, quest)
    return fired


def save_play_state(
    state: dict[str, Any],
    path: Path | None = None,
    *,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    target = path if path is not None else play_state_path(environ=environ, home=home)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state)
    payload.pop("__runtime_id", None)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def load_play_state(
    path: Path | None = None,
    *,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> dict[str, Any] | None:
    target = path if path is not None else play_state_path(environ=environ, home=home)
    if not target.is_file():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    return raw if isinstance(raw, dict) else None


def load_play_state_for(fid: str, *, path: Path | None = None) -> PlayState:
    """Create ``{data}/quests/{fid}.json`` when missing, then load active quests."""
    global _CURRENT
    state = PlayState()
    state.fid = fid
    state.path = path if path is not None else play_state_path()
    folder = state.path.parent / "quests"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _log(f"quest folder: {exc}")
        raise
    fid_path = folder / f"{fid}.json"
    if not fid_path.is_file():
        state.cmdr = _commander_name(fid)
        state.save_local()
    else:
        try:
            raw = json.loads(fid_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError) as exc:
            _log(f"PlayState.loadAsync: {exc}")
            gtk_dialog(str(exc), "SrvSurvey", yes_no=False)
            raise
        if isinstance(raw, dict):
            state.cmdr = str(raw.get("cmdr") or "")
            if isinstance(raw.get("devRef"), dict):
                state.dev_ref = dict(raw["devRef"])
        if not state.cmdr.strip():
            state.cmdr = _commander_name(fid)
            state.save_local()
    for row in _load_cmdr_quests(fid, "active"):
        if not row.get("id"):
            _log("quest load skipped a row with no definition")
            continue
        quest = _quest_from_definition(row, dev=False)
        _apply_play_fields(quest, row)
        state.init_quest(quest, start_first=False)
    if state.dev_ref is not None:
        dev_path = folder / f"dev-{state.dev_ref.get('id')}.json"
        if not dev_path.is_file():
            raise ValueError(f"Missing! {dev_path}")
        try:
            definition = json.loads(dev_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"dev quest: {exc}") from exc
        if isinstance(definition, dict):
            quest = _quest_from_definition(definition, dev=True)
            state.init_quest(quest, start_first=False)
    _CURRENT = state
    update_ui(None)
    return state


def _commander_name(fid: str) -> str:
    folder = _xdg_data() / "cmdr"
    if not folder.is_dir():
        return ""
    files = sorted(folder.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in files:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
        if not isinstance(raw, dict):
            continue
        if fid and str(raw.get("fid") or "") not in {"", fid}:
            continue
        return str(raw.get("commander") or "")
    return ""


def _latest_commander() -> tuple[str, str]:
    folder = _xdg_data() / "cmdr"
    if not folder.is_dir():
        return "", ""
    files = sorted(folder.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in files:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
        if isinstance(raw, dict):
            return str(raw.get("fid") or ""), str(raw.get("commander") or "")
    return "", ""


def enable_galtea1(quest_id: str) -> None:
    """Activate the Grinning2001 sample quest after the Windows confirmation dialogs."""
    try:
        fid, _commander = _latest_commander()
        if not fid:
            return
        if not _rcc_key(None):
            gtk_dialog(
                "Before you can use quests, you must set your Raven Colonial api-key in settings, tab: External Data",
                "Activate Quest?",
                yes_no=False,
            )
            return
        answer = gtk_dialog(
            f"Would you like to activate the '{quest_id}' sample quest?\n\n(This will reset any prior progress)",
            "Activate Quest?",
            yes_no=True,
        )
        if answer != "yes":
            return
        from config import load_settings, save_settings

        settings = load_settings()
        if not settings.game.enableQuests:
            settings.game.enableQuests = True
            save_settings(settings)
        state = _CURRENT if _CURRENT is not None else load_play_state_for(fid)
        state.activate_quest("Grinning2001", quest_id)
        gtk_dialog(
            "The quest is ready!\n\n- Look in the top/right corner of the game for visual queues\n\n"
            "- It is strongly recommended to set an easy key-chord for 'questShow'\n\n"
            "- To interact with quests: use that key-chord or new button on the main window "
            "(with 2 squares diagonal, below the giant Colonise button)",
            "Quest activated: " + quest_id,
            yes_no=False,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
        _log(f"enableGaltea1: {exc}")
        gtk_dialog(str(exc), "SrvSurvey", yes_no=False)


def process_live_journal_events(
    events: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    journal_folder: Path | None = None,
    status: object = None,
    commander: str = "",
    factions: list[dict[str, Any]] | None = None,
) -> None:
    """Feed journal lines to the loaded play state. One bad line does not leave this function raised."""
    global _CURRENT
    if _CURRENT is None:
        path = play_state_path()
        if not path.is_file():
            return
        loaded = load_play_state(path)
        if not isinstance(loaded, dict) or not loaded.get("fid"):
            return
        try:
            _CURRENT = load_play_state_for(str(loaded.get("fid")), path=path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _log(f"quest load: {exc}")
            return
    state = _CURRENT
    if state is None:
        return
    if journal_folder is not None:
        state.journal_folder = journal_folder
    for quest in state.active:
        if commander:
            quest.cmdr.commander = commander
        if factions is not None:
            quest.cmdr.factions = factions
        quest.cmdr.apply_status(status)
    for entry in events:
        if not isinstance(entry, dict):
            continue
        try:
            state.process_raw(entry)
        except FileNotFoundError as exc:
            _log(f"quest companion: {exc}")
        except ValueError as exc:
            _log(f"quest script: {exc}")
        except OSError as exc:
            _log(f"quest script: {exc}")
        except json.JSONDecodeError as exc:
            _log(f"quest script: {exc}")
        except TypeError as exc:
            _log(f"quest script: {exc}")
