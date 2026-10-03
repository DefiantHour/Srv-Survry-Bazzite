"""Tail Elite journals and poll companion files for live updates."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from companion import (
    CargoSnapshot,
    NavRouteSnapshot,
    ShipLockerSnapshot,
    StatusSnapshot,
    companion_paths,
    extended_companion_paths,
    read_cargo_file,
    read_nav_route_file,
    read_ship_locker_file,
    read_status_file,
)
from journal import (
    CommanderLocation,
    SessionSnapshot,
    SurveyState,
    latest_journal_file,
    read_session,
)


@dataclass(frozen=True)
class WatchSnapshot:
    """Everything the HUD can refresh from disk in one poll."""

    journal_path: Path | None
    session: SessionSnapshot
    status: StatusSnapshot | None
    cargo: CargoSnapshot | None
    locker: ShipLockerSnapshot | None = None
    nav_route: NavRouteSnapshot | None = None
    new_events: tuple[dict, ...] = ()
    last_journal_write_monotonic: float | None = None


class JournalWatcher:
    """Follow the newest Journal.*.log and re-read companion sidecars.

    Journal lines are tailed when the file grows. Status.json / Cargo.json /
    ShipLocker.json / NavRoute.json are re-read when their mtime changes.

    Survey state is rebuilt from the full journal text on each append. That is
    correct across system jumps and stays cheap for typical journal sizes.
    """

    def __init__(self, journal_folder: Path | None) -> None:
        self.journal_folder = journal_folder
        self._path: Path | None = None
        self._offset = 0
        self._partial = ""
        self._full_text = ""
        self._session = SessionSnapshot(
            location=CommanderLocation(None, None, None),
            survey=SurveyState(),
        )
        self._status: StatusSnapshot | None = None
        self._cargo: CargoSnapshot | None = None
        self._locker: ShipLockerSnapshot | None = None
        self._nav_route: NavRouteSnapshot | None = None
        self._mtimes: dict[str, float] = {}
        self._journal_mtime: float | None = None
        self.last_journal_write_monotonic: float | None = None
        if journal_folder is not None and journal_folder.is_dir():
            self.poll(force_full=True)

    def _note_journal_write(self, path: Path) -> None:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        if self._journal_mtime is None or mtime != self._journal_mtime:
            self._journal_mtime = mtime
            self.last_journal_write_monotonic = time.monotonic()

    def poll(self, *, force_full: bool = False) -> WatchSnapshot:
        new_events: list[dict] = []
        if self.journal_folder is None or not self.journal_folder.is_dir():
            return WatchSnapshot(
                None,
                self._session,
                self._status,
                self._cargo,
                self._locker,
                self._nav_route,
                (),
                self.last_journal_write_monotonic,
            )

        latest = latest_journal_file(self.journal_folder)
        if latest is None:
            return WatchSnapshot(
                None,
                self._session,
                self._status,
                self._cargo,
                self._locker,
                self._nav_route,
                (),
                self.last_journal_write_monotonic,
            )

        if force_full or latest != self._path:
            self._path = latest
            text = latest.read_text(encoding="utf-8", errors="replace")
            self._full_text = text
            self._offset = latest.stat().st_size
            self._partial = ""
            self._session = read_session(text)
            self._note_journal_write(latest)
        else:
            size = latest.stat().st_size
            if size < self._offset:
                text = latest.read_text(encoding="utf-8", errors="replace")
                self._full_text = text
                self._offset = size
                self._partial = ""
                self._session = read_session(text)
                self._note_journal_write(latest)
            elif size > self._offset:
                with latest.open("rb") as handle:
                    handle.seek(self._offset)
                    chunk = handle.read()
                    self._offset = handle.tell()
                decoded = self._partial + chunk.decode("utf-8", errors="replace")
                lines = decoded.splitlines(keepends=True)
                if lines and not decoded.endswith(("\n", "\r")):
                    self._partial = lines.pop()
                else:
                    self._partial = ""
                appended = "".join(lines)
                if appended:
                    self._full_text += appended
                    self._session = read_session(self._full_text)
                    self._note_journal_write(latest)
                    for line in appended.splitlines():
                        stripped = line.strip()
                        if not stripped:
                            continue
                        try:
                            entry = json.loads(stripped)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(entry, dict):
                            new_events.append(entry)

        self._refresh_companions()
        return WatchSnapshot(
            journal_path=self._path,
            session=self._session,
            status=self._status,
            cargo=self._cargo,
            locker=self._locker,
            nav_route=self._nav_route,
            new_events=tuple(new_events),
            last_journal_write_monotonic=self.last_journal_write_monotonic,
        )

    def _refresh_companions(self) -> None:
        assert self.journal_folder is not None
        paths = extended_companion_paths(self.journal_folder)
        # Prefer ShipLocker.json; fall back to Backpack.json totals if locker missing.
        status_path, cargo_path = companion_paths(self.journal_folder)
        self._maybe_read("status", status_path, lambda p: setattr(self, "_status", read_status_file(p)))
        self._maybe_read("cargo", cargo_path, lambda p: setattr(self, "_cargo", read_cargo_file(p)))
        locker_path = paths["locker"]
        if locker_path.is_file():
            self._maybe_read(
                "locker",
                locker_path,
                lambda p: setattr(self, "_locker", read_ship_locker_file(p)),
            )
        else:
            backpack = paths["backpack"]
            if backpack.is_file():
                self._maybe_read(
                    "backpack",
                    backpack,
                    lambda p: setattr(self, "_locker", read_ship_locker_file(p)),
                )
        self._maybe_read(
            "navroute",
            paths["navroute"],
            lambda p: setattr(self, "_nav_route", read_nav_route_file(p)),
        )

    def _maybe_read(self, key: str, path: Path, apply) -> None:
        if not path.is_file():
            return
        mtime = path.stat().st_mtime
        if self._mtimes.get(key) == mtime:
            return
        apply(path)
        self._mtimes[key] = mtime


def sleep_poll(seconds: float) -> None:
    """Interruptible sleep helper for hold loops."""
    if seconds <= 0:
        return
    time.sleep(seconds)
