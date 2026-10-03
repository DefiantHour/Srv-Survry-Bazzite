#!/usr/bin/env python3
"""Windows Git.refreshPublishedData for Bazzite.

Downloads the same published files as SrvSurvey/net/Git.cs:
data.json, codexRef, bio-criteria.zip, settlements.zip, guardian templates,
allRuins, allStructures, guardian.zip, Boxel.Names.txt, nicknames, ggg.json.

The Windows auto-updater then runs a ClickOnce update.cmd. That installer
does not run here. A newer ghVer is reported and left for the user.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from client_identity import release_version, user_agent
from paths import srvsurvey_data_dir

DATA_INDEX_URL = "https://njthomson.github.io/SrvSurvey/data.json"
RAW_ROOT = "https://raw.githubusercontent.com/njthomson/SrvSurvey/main"
BIO_ENGINE = 4
NICKNAME_URL = (
    "https://ravencolonial100-awcbdvabgze4c5cq.canadacentral-01.azurewebsites.net"
    "/api/misc/nicknames"
)

Fetch = Callable[[str], tuple[int, bytes]]


def pub_offline() -> bool:
    flags = ("SRVSURVEY_NET_OFFLINE", "SRVSURVEY_PUB_OFFLINE", "SRVSURVEY_DRY_RUN")
    return any(os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"} for name in flags)


def refresh_published_data(
    *,
    data_dir: Path | None = None,
    fetch: Fetch | None = None,
) -> dict[str, Any]:
    """Match Git.refreshPublishedData. Never raises for network failure."""
    root = data_dir if data_dir is not None else srvsurvey_data_dir()
    pub = root / "pub"
    if pub_offline():
        return {"ok": False, "skipped": True, "reason": "offline", "next_build": None, "pub": str(pub)}
    getter = fetch if fetch is not None else _http_get
    try:
        status, body = getter(DATA_INDEX_URL)
        if status != 200:
            return _fail(pub, f"data.json HTTP {status}")
        index = json.loads(body.decode("utf-8"))
    except (OSError, ValueError, TimeoutError) as exc:
        return _fail(pub, str(exc))

    had_no_pub = not pub.is_dir()
    pub.mkdir(parents=True, exist_ok=True)
    (pub / "guardian").mkdir(parents=True, exist_ok=True)
    local = _load_versions(pub)
    actions: list[str] = []
    next_build = _newer_github_version(str(index.get("ghVer") or ""))

    if int(index.get("codexRef") or 0) > int(local.get("codexRef") or 0):
        if _save_text(getter, f"{RAW_ROOT}/docs/codexRef.json", root / "codexRef.json"):
            local["codexRef"] = int(index["codexRef"])
            actions.append("codexRef")

    remote_bio = int(index.get("bioCriteria") or 0)
    remote_engine = int(index.get("bioEngine") or 0)
    if had_no_pub or (remote_bio > int(local.get("bioCriteria") or 0) and BIO_ENGINE >= remote_engine):
        if _replace_zip(getter, f"{RAW_ROOT}/data/bio-criteria.zip", pub, "bio-criteria"):
            local["bioCriteria"] = remote_bio
            actions.append("bio-criteria")

    if had_no_pub or int(index.get("settlements") or 0) > int(local.get("settlements") or 0):
        if _replace_zip(getter, f"{RAW_ROOT}/data/settlements.zip", pub, "settlements"):
            local["settlements"] = int(index["settlements"])
            actions.append("settlements")

    remote_template = int(index.get("settlementTemplate") or 0)
    if had_no_pub or remote_template > int(local.get("settlementTemplate") or 0):
        name = "guardianSiteTemplates.json"
        if _save_text(getter, f"{RAW_ROOT}/SrvSurvey/{name}", pub / name):
            local["settlementTemplate"] = remote_template
            actions.append("settlementTemplate")

    names_path = pub / "Boxel.Names.txt"
    if not names_path.is_file():
        if _save_text(getter, f"{RAW_ROOT}/SrvSurvey/game/Boxel.Names.txt", names_path):
            actions.append("boxel-names")

    remote_guardian = int(index.get("guardian") or 0)
    if had_no_pub or remote_guardian > int(local.get("guardian") or 0):
        ruins_ok = _save_text(getter, f"{RAW_ROOT}/SrvSurvey/allRuins.json", pub / "allRuins.json")
        structures_ok = _save_text(
            getter, f"{RAW_ROOT}/SrvSurvey/allStructures.json", pub / "allStructures.json"
        )
        zip_ok = _replace_zip(getter, f"{RAW_ROOT}/data/guardian.zip", pub, "guardian")
        if ruins_ok and structures_ok and zip_ok:
            local["guardian"] = remote_guardian
            actions.append("guardian")

    if _nicknames_due(local, int(index.get("nicknames") or 0), pub / "nicknames.json"):
        if _save_nicknames(getter, pub / "nicknames.json"):
            local["nicknames"] = int(index.get("nicknames") or 0)
            local["lastNicknames"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            actions.append("nicknames")

    if not (pub / "ggg.json").is_file() or int(index.get("ggg") or 0) > int(local.get("ggg") or 0):
        if _save_text(getter, f"{RAW_ROOT}/SrvSurvey/ggg.json", pub / "ggg.json"):
            local["ggg"] = int(index.get("ggg") or 0)
            actions.append("ggg")

    _save_versions(pub, local)
    return {
        "ok": True,
        "skipped": False,
        "reason": "",
        "actions": actions,
        "next_build": next_build,
        "pub": str(pub),
        "installed": release_version(),
    }


def _fail(pub: Path, reason: str) -> dict[str, Any]:
    return {"ok": False, "skipped": False, "reason": reason, "next_build": None, "pub": str(pub)}


def _load_versions(pub: Path) -> dict[str, Any]:
    path = pub / "versions.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_versions(pub: Path, local: dict[str, Any]) -> None:
    (pub / "versions.json").write_text(json.dumps(local, indent=2) + "\n", encoding="utf-8")


def _newer_github_version(remote: str) -> str | None:
    if _version_tuple(remote) > _version_tuple(release_version()):
        return remote
    return None


def _version_tuple(text: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in (text or "").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _nicknames_due(local: dict[str, Any], remote: int, dest: Path) -> bool:
    if not dest.is_file() or remote > int(local.get("nicknames") or 0):
        return True
    stamp = str(local.get("lastNicknames") or "")
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - when).total_seconds() > 2 * 24 * 3600


def _save_text(fetch: Fetch, url: str, dest: Path) -> bool:
    try:
        status, body = fetch(url)
    except (OSError, TimeoutError, ValueError):
        return False
    if status != 200 or not body:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return True


def _replace_zip(fetch: Fetch, url: str, pub: Path, folder_name: str) -> bool:
    try:
        status, body = fetch(url)
    except (OSError, TimeoutError, ValueError):
        return False
    if status != 200 or not body:
        return False
    zip_path = pub / f"{folder_name}.zip"
    prior = pub / f"{folder_name}-prior.zip"
    if zip_path.is_file():
        prior.write_bytes(zip_path.read_bytes())
    dest = pub / folder_name
    if dest.is_dir():
        _rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        _extract_safe(body, dest)
    except (zipfile.BadZipFile, ValueError, OSError):
        return False
    zip_path.write_bytes(body)
    return True


def _extract_safe(payload: bytes, dest: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        root = dest.resolve()
        for info in archive.infolist():
            target = (dest / info.filename).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"zip slip: {info.filename}")
        archive.extractall(dest)


def _save_nicknames(fetch: Fetch, dest: Path) -> bool:
    try:
        status, body = fetch(NICKNAME_URL)
    except (OSError, TimeoutError, ValueError):
        return False
    if status != 200:
        return False
    try:
        rows = json.loads(body.decode("utf-8"))
    except ValueError:
        return False
    if not isinstance(rows, list):
        return False
    mapped: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        nickname = row.get("nickname")
        if isinstance(name, str) and isinstance(nickname, str):
            mapped[name] = nickname
    if dest.is_file():
        prior = dest.with_name("nicknames-prior.json")
        prior.write_bytes(dest.read_bytes())
    dest.write_text(json.dumps(mapped, indent=2) + "\n", encoding="utf-8")
    return True


def _rmtree(path: Path) -> None:
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file() or child.is_symlink():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    path.rmdir()


def _http_get(url: str) -> tuple[int, bytes]:
    req = Request(url, headers={"User-Agent": user_agent(), "Cache-Control": "no-cache"})
    try:
        with urlopen(req, timeout=30) as resp:
            return int(getattr(resp, "status", 200) or 200), resp.read()
    except HTTPError as exc:
        try:
            payload = exc.read()
        except Exception:
            payload = b""
        return int(exc.code), payload
    except (URLError, TimeoutError, OSError):
        return 0, b""


if __name__ == "__main__":
    print(json.dumps(refresh_published_data()))
