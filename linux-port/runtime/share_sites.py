#!/usr/bin/env python3
"""Windows FormShareData — zip guardian sites that have local discoveries.

The zip name is surveys-{fid}-{md5 of site names}.json entries, matching
FormShareData_Load. Discord links are the same channel the Windows form opens.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from paths import srvsurvey_data_dir

DISCORD_CHANNEL = "discord://-/channels/1055035389791969352/1200547428303122522"
DISCORD_INVITE = "https://discord.gg/9PhBwwDAbV"


def build_share_package(
    *,
    data_dir: Path | None = None,
    fid: str | None = None,
) -> dict[str, Any]:
    root = data_dir if data_dir is not None else srvsurvey_data_dir()
    cmdr = root / "cmdr"
    sites, seen_fid = _discover_sites(cmdr)
    commander = (fid or seen_fid or "unknown").strip() or "unknown"
    share = root / "share"
    folder = share / commander
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    for site in sites:
        name = str(site.get("displayName") or site.get("site_key") or "site")
        names.append(name)
        safe = "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in name) or "site"
        (folder / f"{safe}.json").write_text(json.dumps(site, indent=2) + "\n", encoding="utf-8")
    digest = hashlib.md5(",".join(names).encode("utf-8")).hexdigest()
    zip_path = share / f"surveys-{commander}-{digest}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.glob("*.json")):
            archive.write(path, path.name)
    return {
        "ok": True,
        "count": len(names),
        "sites": names,
        "zip": str(zip_path),
        "folder": str(share),
        "discord_channel": DISCORD_CHANNEL,
        "discord_invite": DISCORD_INVITE,
    }


def site_has_discovery(raw: dict[str, Any]) -> bool:
    """FormShareData only includes GuardianSiteData.hasDiscoveredData()."""
    extra = raw.get("extra_poi") or raw.get("rawPoi") or []
    if isinstance(extra, list) and extra:
        return True
    if str(raw.get("notes") or "").strip():
        return True
    scanned = raw.get("scanned_obelisks") or []
    if isinstance(scanned, list) and scanned:
        return True
    empty = raw.get("empty_puddles") or []
    if isinstance(empty, list) and empty:
        return True
    poi = raw.get("poiStatus") or {}
    if isinstance(poi, dict) and poi:
        return True
    relics = raw.get("relicHeadings") or {}
    if isinstance(relics, dict) and relics:
        return True
    heading = raw.get("heading", raw.get("siteHeading", -1))
    tower = raw.get("relic_tower_heading", raw.get("relicTowerHeading", -1))
    try:
        if float(heading) != -1:
            return True
        if float(tower) != -1:
            return True
    except (TypeError, ValueError):
        return False
    return False


def _discover_sites(cmdr: Path) -> tuple[list[dict[str, Any]], str]:
    if not cmdr.is_dir():
        return [], ""
    found: list[dict[str, Any]] = []
    seen_fid = ""
    for path in sorted(cmdr.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(raw, dict):
            continue
        if isinstance(raw.get("fid"), str) and raw["fid"].strip():
            seen_fid = raw["fid"].strip()
        sites = raw.get("guardian_sites") or raw.get("guardianSites")
        if isinstance(sites, dict):
            for key, site in sites.items():
                if isinstance(site, dict) and site_has_discovery(site):
                    item = dict(site)
                    item.setdefault("site_key", key)
                    item.setdefault("displayName", key)
                    found.append(item)
            continue
        if site_has_discovery(raw):
            item = dict(raw)
            item.setdefault("displayName", path.stem)
            found.append(item)
    return found, seen_fid


if __name__ == "__main__":
    print(json.dumps(build_share_package()))
