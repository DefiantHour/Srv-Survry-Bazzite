#!/usr/bin/env python3
"""Retry queue for a mutating POST that was attempted and failed in transport.

Offline and dry-run never enqueue and never drain. 2xx finishes the row.
4xx drops it so a bad body cannot block the file. 5xx and a missing HTTP
status hold the row and stop the drain. The stored body is the exact bytes
that were posted. API keys are not written here.
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

_LOCK = threading.Lock()
Post = Callable[[str, str], tuple[int, str]]


def queue_path(kind: str, data_dir: Path) -> Path:
    safe = "eddn" if kind == "eddn" else "canonn"
    return data_dir / f"{safe}-retry.json"


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return []
    if not isinstance(data, list):
        return []
    rows: list[dict[str, Any]] = []
    for row in data:
        if isinstance(row, dict) and row.get("id") and row.get("url") and isinstance(row.get("body"), str):
            rows.append({"id": str(row["id"]), "url": str(row["url"]), "body": row["body"]})
    return rows


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def enqueue(kind: str, url: str, body: str, *, data_dir: Path) -> bool:
    """Append one failed POST. Returns False when that body is already queued."""
    target = (url or "").strip()
    if not target or not isinstance(body, str):
        return False
    path = queue_path(kind, data_dir)
    with _LOCK:
        rows = _read(path)
        for row in rows:
            if row["url"] == target and row["body"] == body:
                return False
        if len(rows) >= 50:
            rows = rows[-49:]
        rows.append({"id": uuid.uuid4().hex, "url": target, "body": body})
        _write(path, rows)
    return True


def drain(kind: str, post: Post, *, data_dir: Path, blocked: bool = False) -> int:
    """POST queued bodies. Returns how many rows were finished."""
    if blocked:
        return 0
    path = queue_path(kind, data_dir)
    with _LOCK:
        rows = _read(path)
    if not rows:
        return 0
    finished: set[str] = set()
    for row in rows:
        try:
            status, _text = post(row["url"], row["body"])
        except (OSError, TimeoutError):
            break
        code = int(status)
        if 200 <= code < 300 or 400 <= code < 500:
            finished.add(row["id"])
            continue
        break
    if not finished:
        return 0
    with _LOCK:
        current = _read(path)
        _write(path, [row for row in current if row["id"] not in finished])
    return len(finished)
