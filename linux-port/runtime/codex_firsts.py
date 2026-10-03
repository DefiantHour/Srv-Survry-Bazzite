#!/usr/bin/env python3
"""Commander codex firsts — Windows {fid}-codex.json.

codexFirsts values use the Windows CodexFirst string: local
``yyyy-MM-ddTHH:mm:ss_{address}_{bodyId}``.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def codex_path(fid: str, data_dir: Path) -> Path:
    return data_dir / f"{fid}-codex.json"


def load_codex(fid: str, data_dir: Path) -> dict[str, Any]:
    path = codex_path(fid, data_dir)
    if not path.is_file():
        return {"fid": fid, "commander": "", "codexFirsts": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {"fid": fid, "commander": "", "codexFirsts": {}}
    if not isinstance(data, dict):
        return {"fid": fid, "commander": "", "codexFirsts": {}}
    firsts = data.get("codexFirsts")
    if not isinstance(firsts, dict):
        data["codexFirsts"] = {}
    data["fid"] = fid
    return data


def known_ids(fid: str, data_dir: Path) -> set[int]:
    found: set[int] = set()
    for key in load_codex(fid, data_dir).get("codexFirsts", {}):
        try:
            found.add(int(key))
        except (TypeError, ValueError):
            continue
    return found


def _stamp(address: int, body_id: int, when: datetime | None = None) -> str:
    moment = when if when is not None else datetime.now().astimezone().replace(tzinfo=None)
    return f"{moment.strftime('%Y-%m-%dT%H:%M:%S')}_{int(address)}_{int(body_id)}"


def store_firsts(
    fid: str,
    commander: str,
    entry_ids: list[int],
    *,
    data_dir: Path,
    address: int = -1,
    body_id: int = -1,
) -> int:
    """Add entry ids that are not already stored. Returns how many were new."""
    clean = (fid or "").strip()
    if not clean:
        return 0
    data = load_codex(clean, data_dir)
    firsts = data.get("codexFirsts")
    if not isinstance(firsts, dict):
        firsts = {}
    added = 0
    for entry_id in entry_ids:
        key = str(int(entry_id))
        if key in firsts:
            continue
        firsts[key] = _stamp(address, body_id)
        added += 1
    if added == 0:
        return 0
    numeric: dict[str, Any] = {}
    for key, value in firsts.items():
        try:
            numeric[str(int(key))] = value
        except (TypeError, ValueError):
            continue
    data["fid"] = clean
    data["commander"] = commander or data.get("commander") or ""
    data["codexFirsts"] = dict(sorted(numeric.items(), key=lambda item: int(item[0])))
    path = codex_path(clean, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    return added


def save_challenge_firsts(
    fid: str,
    commander: str,
    *,
    codex_rows: list[dict[str, Any]],
    data_dir: Path,
    fetch: Any = None,
) -> dict[str, Any]:
    """Run importCanonnChallenge and write new ids into {fid}-codex.json."""
    from canonn import import_canonn_challenge

    imported = import_canonn_challenge(
        commander,
        codex_rows=codex_rows,
        known_ids=known_ids(fid, data_dir),
        fetch=fetch,
    )
    added = imported.get("added") if isinstance(imported, dict) else []
    if not isinstance(added, list):
        added = []
    written = 0
    if imported.get("ok") and added:
        written = store_firsts(fid, commander, [int(item) for item in added], data_dir=data_dir)
    result = dict(imported)
    result["written"] = written
    return result
