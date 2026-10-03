#!/usr/bin/env python3
"""Journal post-process — Windows FormPostProcess statistics pass.

Walks Journal.*.log files after a start time and counts the same headline
stats the Windows form shows. Does not rewrite system JSON or codex files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


GAME_RELEASE = datetime(2014, 12, 15, tzinfo=timezone.utc)
TRAILBLAZERS_RELEASE = datetime(2025, 2, 26, tzinfo=timezone.utc)


@dataclass
class PostProcessStats:
    jumps: int = 0
    distance_ly: float = 0.0
    bodies_approached: int = 0
    organisms_analysed: int = 0
    cargo_bought: int = 0
    cargo_sold: int = 0
    cargo_transferred: int = 0
    cargo_collected: int = 0
    cargo_contributed: int = 0
    docked: int = 0
    touchdowns: int = 0
    died: int = 0
    files: int = 0
    systems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "jumps": self.jumps,
            "distance_ly": round(self.distance_ly, 2),
            "bodies_approached": self.bodies_approached,
            "organisms_analysed": self.organisms_analysed,
            "cargo_bought": self.cargo_bought,
            "cargo_sold": self.cargo_sold,
            "cargo_transferred": self.cargo_transferred,
            "cargo_collected": self.cargo_collected,
            "cargo_contributed": self.cargo_contributed,
            "docked": self.docked,
            "touchdowns": self.touchdowns,
            "died": self.died,
            "files": self.files,
            "systems": self.systems,
        }


def journal_file_time(path: Path) -> datetime | None:
    """Parse Journal.YYYY-MM-DDTHHMMSS.log or Journal.yyMMddHHmmss.log."""
    parts = path.name.split(".")
    if len(parts) < 3:
        return None
    stamp = parts[1]
    try:
        if "-" in stamp:
            parsed = datetime.strptime(stamp, "%Y-%m-%dT%H%M%S")
        else:
            parsed = datetime.strptime(stamp, "%y%m%d%H%M%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def _count_delta(entry: dict, key: str = "Count") -> int:
    raw = entry.get(key)
    if isinstance(raw, (int, float)):
        return int(raw)
    return 0


def post_process_journals(
    folder: Path | str,
    *,
    start: datetime | None = None,
    fid: str | None = None,
) -> PostProcessStats:
    """Count exploration and cargo events at or after ``start``."""
    root = Path(folder)
    stats = PostProcessStats()
    if not root.is_dir():
        return stats
    cutoff = start or datetime.now(timezone.utc)
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    files = []
    for path in root.glob("Journal.*.log"):
        stamp = journal_file_time(path)
        if stamp is None or stamp < cutoff:
            continue
        files.append((stamp, path))
    files.sort(key=lambda item: item[0])
    seen_systems: list[str] = []
    for _stamp, path in files:
        stats.files += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            if fid:
                entry_fid = entry.get("FID")
                if isinstance(entry_fid, str) and entry_fid and entry_fid != fid:
                    # File may still belong to this commander; FID is only on some events.
                    pass
            event = entry.get("event")
            if event == "FSDJump":
                stats.jumps += 1
                dist = entry.get("JumpDist")
                if isinstance(dist, (int, float)):
                    stats.distance_ly += float(dist)
                star = entry.get("StarSystem")
                if isinstance(star, str) and star and star not in seen_systems:
                    seen_systems.append(star)
            elif event == "ApproachBody":
                stats.bodies_approached += 1
            elif event == "ScanOrganic" and entry.get("ScanType") == "Analyse":
                stats.organisms_analysed += 1
            elif event == "MarketBuy":
                stats.cargo_bought += _count_delta(entry)
            elif event == "MarketSell":
                stats.cargo_sold += _count_delta(entry)
            elif event in ("CargoTransfer", "CargoDepot"):
                if event == "CargoDepot":
                    stats.cargo_contributed += _count_delta(entry)
                else:
                    stats.cargo_transferred += _count_delta(entry)
            elif event == "CollectCargo":
                stats.cargo_collected += 1
            elif event == "Docked":
                stats.docked += 1
            elif event == "Touchdown":
                stats.touchdowns += 1
            elif event == "Died":
                stats.died += 1
    stats.systems = seen_systems
    return stats
