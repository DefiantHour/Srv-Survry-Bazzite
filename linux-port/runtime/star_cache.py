#!/usr/bin/env python3
"""VisitedStarsCache swap — Windows FormSwapStarCache file operations.

The cache file is Frontier's VisitedStarsCache.dat. On Bazzite the usual
place is a Proton prefix, not a native Linux Elite folder. This module
backs up and restores that file. Downloading a replacement from edgalaxy.net
is a POST and is skipped when offline or dry-run.
"""

from __future__ import annotations

import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from client_identity import user_agent

CACHE_NAME = "VisitedStarsCache.dat"
BACKUP_NAME = "backup-VisitedStarsCache.dat"
EDGALAXY_URL = "https://edgalaxy.net/visitedstars"


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def offline() -> bool:
    return any(
        _truthy(name)
        for name in (
            "SRVSURVEY_NET_OFFLINE",
            "SRVSURVEY_DRY_RUN",
            "SRVSURVEY_STARCACHE_OFFLINE",
        )
    )


def cache_paths(fid: str, game_data: Path | str | None = None) -> tuple[Path, Path]:
    """Original and backup paths. FID 'F123' uses the numeric folder '123'."""
    number = fid[1:] if fid.upper().startswith("F") else fid
    if game_data is not None:
        root = Path(game_data)
    else:
        env = os.environ.get("SRVSURVEY_ELITE_LOCAL")
        root = Path(env) if env else Path.home() / ".local" / "share" / "srvsurvey" / "star-cache"
    folder = root / number
    return folder / CACHE_NAME, folder / BACKUP_NAME


def backup_cache(original: Path, backup: Path) -> str:
    if backup.is_file():
        return "backup-exists"
    if not original.is_file():
        return "missing-original"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original, backup)
    return "backed-up"


def restore_cache(original: Path, backup: Path) -> str:
    if not backup.is_file():
        return "missing-backup"
    original.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(backup), str(original))
    return "restored"


def download_star_cache(system_name: str, dest: Path) -> dict[str, object]:
    """POST edgalaxy.net/visitedstars. Offline never POSTs."""
    if offline():
        return {"ok": False, "skipped": True, "reason": "offline", "path": None}
    name = (system_name or "").strip()
    if not name:
        return {"ok": False, "skipped": True, "reason": "missing system", "path": None}
    body = urllib.parse.urlencode({"system": name}).encode("ascii")
    req = urllib.request.Request(
        EDGALAXY_URL,
        data=body,
        headers={
            "User-Agent": user_agent(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = resp.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "skipped": False, "reason": str(exc), "path": None}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)
    return {"ok": True, "skipped": False, "reason": "", "path": str(dest)}


def swap_cache(
    fid: str,
    system_name: str,
    *,
    game_data: Path | str | None = None,
    download_dir: Path | str | None = None,
) -> dict[str, object]:
    """Backup the live cache, then copy a downloaded .dat over it."""
    original, backup = cache_paths(fid, game_data)
    status = backup_cache(original, backup)
    if offline():
        return {
            "ok": False,
            "skipped": True,
            "reason": "offline",
            "backup": status,
            "original": str(original),
        }
    folder = Path(download_dir) if download_dir else original.parent / "downloads"
    fetched = download_star_cache(system_name, folder / f"{system_name}.dat")
    if not fetched.get("ok"):
        return {**fetched, "backup": status, "original": str(original)}
    src = Path(str(fetched["path"]))
    original.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, original)
    return {
        "ok": True,
        "skipped": False,
        "reason": "",
        "backup": status,
        "original": str(original),
        "path": str(src),
    }
