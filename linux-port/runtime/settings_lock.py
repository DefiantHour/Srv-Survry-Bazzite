#!/usr/bin/env python3
"""Single Settings window lock — the main app cannot quit while it is held."""

from __future__ import annotations

import os
from pathlib import Path

from paths import srvsurvey_config_dir, srvsurvey_data_dir


LOCK_NAME = "settings.lock"
LOCK_TOKEN = "srvsurvey-settings"


def settings_lock_paths(
    *,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> list[Path]:
    """Config dir first (matches Avalonia), then the data dir copy."""
    return [
        srvsurvey_config_dir(environ=environ, home=home) / LOCK_NAME,
        srvsurvey_data_dir(environ=environ, home=home) / LOCK_NAME,
    ]


def settings_lock_path(
    *,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    return settings_lock_paths(environ=environ, home=home)[0]


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    return Path(f"/proc/{pid}").is_dir()


def _cmdline_text(pid: int) -> str:
    cmdline = Path(f"/proc/{pid}/cmdline")
    if not cmdline.is_file():
        return ""
    try:
        return cmdline.read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace")
    except OSError:
        return ""


def _pid_is_settings(pid: int) -> bool:
    if not _pid_is_alive(pid):
        return False
    text = _cmdline_text(pid)
    if "--settings" in text or "settings_ui" in text:
        return True
    return False


def _lock_pid_from_file(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        pid = int(raw.split()[0])
    except (OSError, ValueError, IndexError):
        return None
    if not _pid_is_settings(pid):
        return None
    return pid


def settings_lock_pid(
    *,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> int | None:
    for path in settings_lock_paths(environ=environ, home=home):
        pid = _lock_pid_from_file(path)
        if pid is not None:
            return pid
    return None


def iter_settings_pids(*, exclude: int | None = None) -> list[int]:
    """Live processes whose cmdline is SrvSurvey Settings."""
    found: list[int] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return found
    try:
        entries = proc.iterdir()
    except OSError:
        return found
    for entry in entries:
        name = entry.name
        if not name.isdigit():
            continue
        pid = int(name)
        if exclude is not None and pid == exclude:
            continue
        if _pid_is_settings(pid):
            found.append(pid)
    return found


def settings_is_open(
    *,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> bool:
    if settings_lock_pid(environ=environ, home=home) is not None:
        return True
    if environ is not None:
        return False
    return bool(iter_settings_pids(exclude=os.getpid()))


def acquire_settings_lock(
    *,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
    pid: int | None = None,
) -> bool:
    """Write this process pid. False if another Settings window is already live."""
    other = settings_lock_pid(environ=environ, home=home)
    me = int(pid if pid is not None else os.getpid())
    if other is not None and other != me:
        return False
    payload = f"{me}\n{LOCK_TOKEN}\n"
    for path in settings_lock_paths(environ=environ, home=home):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    return True


def release_settings_lock(
    *,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
    pid: int | None = None,
) -> None:
    me = int(pid if pid is not None else os.getpid())
    for path in settings_lock_paths(environ=environ, home=home):
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8").strip()
            locked = int(raw.split()[0])
        except (OSError, ValueError, IndexError):
            locked = me
        if locked != me:
            continue
        try:
            path.unlink()
        except OSError:
            pass
