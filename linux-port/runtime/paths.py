"""Linux locations for SrvSurvey and for Elite Dangerous under Proton.

Journal files stay inside the Proton prefix. Finding that folder is not Wine.
The native app only reads the files the game already writes.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ELITE_APP_ID = "359320"


@dataclass(frozen=True)
class SteamLibrary:
    path: str
    app_ids: frozenset[str]


def srvsurvey_data_dir(environ: dict[str, str] | None = None, home: Path | None = None) -> Path:
    """XDG data directory. Replaces %APPDATA%\\SrvSurvey."""
    env = os.environ if environ is None else environ
    base = env.get("XDG_DATA_HOME")
    if not base:
        root = Path.home() if home is None else home
        base = str(root / ".local" / "share")
    return Path(base) / "srvsurvey"


def srvsurvey_config_dir(environ: dict[str, str] | None = None, home: Path | None = None) -> Path:
    """XDG config directory used by config.py and the Avalonia UI."""
    env = os.environ if environ is None else environ
    base = env.get("XDG_CONFIG_HOME")
    if not base:
        root = Path.home() if home is None else home
        base = str(root / ".config")
    return Path(base) / "srvsurvey"


def ensure_data_dir(data_dir: Path | None = None, home: Path | None = None) -> Path:
    """Create the XDG data directory if needed and return it."""
    path = srvsurvey_data_dir(home=home) if data_dir is None else data_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_runtime_state(
    data_dir: Path,
    *,
    journal_folder: Path | None,
    journal_file: Path | None = None,
    host_pid: int | None = None,
    present_active: bool | None = None,
    commander: str | None = None,
    system: str | None = None,
    body: str | None = None,
    mode: str | None = None,
    vehicle: str | None = None,
    overlay_visible: bool | None = None,
) -> Path:
    """Persist a tiny JSON state file for later AppImage / Avalonia Main wiring.

    Optional Main/status fields are omitted when None so watch-only writes stay
    small. Pass ``host_pid=0`` (or ``present_active=False``) from present
    shutdown to clear the live-presenter marker without removing journal paths.
    """
    ensure_data_dir(data_dir)
    payload: dict[str, object] = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "journal_folder": str(journal_folder) if journal_folder else None,
        "journal_file": str(journal_file) if journal_file else None,
    }
    if host_pid is not None:
        payload["host_pid"] = host_pid if host_pid > 0 else None
    if present_active is not None:
        payload["present_active"] = bool(present_active)
    if commander is not None:
        payload["commander"] = commander
    if system is not None:
        payload["system"] = system
    if body is not None:
        payload["body"] = body
    if mode is not None:
        payload["mode"] = mode
    if vehicle is not None:
        payload["vehicle"] = vehicle
    if overlay_visible is not None:
        payload["overlay_visible"] = bool(overlay_visible)
    path = data_dir / "runtime-state.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def parse_vdf(text: str) -> dict:
    """Parse the subset of Valve VDF used by libraryfolders.vdf.

    The file root is a key followed by an object, not a surrounding brace.
    """
    tokens = list(_tokenize_vdf(text))
    value, index = _parse_vdf_pairs(tokens, 0, until_brace=False)
    if index != len(tokens) or not isinstance(value, dict):
        raise ValueError("libraryfolders.vdf is not a single object")
    return value


def steam_libraries(text: str) -> list[SteamLibrary]:
    data = parse_vdf(text)
    root = data.get("libraryfolders", data)
    if not isinstance(root, dict):
        return []
    libraries: list[SteamLibrary] = []
    for value in root.values():
        if not isinstance(value, dict):
            continue
        path = value.get("path")
        apps = value.get("apps") if isinstance(value.get("apps"), dict) else {}
        if not isinstance(path, str) or not path:
            continue
        libraries.append(SteamLibrary(path=path, app_ids=frozenset(str(k) for k in apps)))
    return libraries


def proton_user_dir(library_path: str, app_id: str = ELITE_APP_ID, steam_user: str = "steamuser") -> Path:
    return (
        Path(library_path)
        / "steamapps"
        / "compatdata"
        / app_id
        / "pfx"
        / "drive_c"
        / "users"
        / steam_user
    )


def journal_dir(library_path: str, app_id: str = ELITE_APP_ID) -> Path:
    """Elite's Saved Games folder inside a Proton prefix. Forward slashes only."""
    return proton_user_dir(library_path, app_id) / "Saved Games" / "Frontier Developments" / "Elite Dangerous"


def journal_dir_for_libraries(libraries: list[SteamLibrary], app_id: str = ELITE_APP_ID) -> Path | None:
    for library in libraries:
        if app_id in library.app_ids:
            return journal_dir(library.path, app_id)
    return None


def default_library_vdf_paths(home: Path | None = None) -> list[Path]:
    root = Path.home() if home is None else home
    return [
        root / ".local/share/Steam/steamapps/libraryfolders.vdf",
        root / ".steam/steam/steamapps/libraryfolders.vdf",
        root / ".steam/root/steamapps/libraryfolders.vdf",
        root / ".var/app/com.valvesoftware.Steam/data/Steam/steamapps/libraryfolders.vdf",
    ]


def _tokenize_vdf(text: str):
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if char in "{}":
            yield char
            index += 1
            continue
        if char != '"':
            raise ValueError(f"unexpected character in vdf at {index}: {char!r}")
        index += 1
        chars: list[str] = []
        while index < length:
            char = text[index]
            if char == "\\" and index + 1 < length:
                chars.append(text[index + 1])
                index += 2
                continue
            if char == '"':
                index += 1
                break
            chars.append(char)
            index += 1
        yield "".join(chars)


def _parse_vdf_value(tokens: list[str], index: int):
    if index >= len(tokens):
        raise ValueError("unexpected end of vdf")
    if tokens[index] == "{":
        return _parse_vdf_pairs(tokens, index + 1, until_brace=True)
    return tokens[index], index + 1


def _parse_vdf_pairs(tokens: list[str], index: int, until_brace: bool):
    obj: dict[str, object] = {}
    while index < len(tokens):
        if until_brace and tokens[index] == "}":
            return obj, index + 1
        key = tokens[index]
        index += 1
        value, index = _parse_vdf_value(tokens, index)
        obj[key] = value
    if until_brace:
        raise ValueError("unclosed vdf object")
    return obj, index
