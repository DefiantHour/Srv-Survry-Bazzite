#!/usr/bin/env python3
"""Codex biology reward lookup — Linux port of Coderef reward table usage.

Loads ``docs/codexRef.json`` (Canonn-style map keyed by entry id). Used by
PlotBioSystem / PlotBodyInfo volume bars and reward footers.
"""

from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _REPO_ROOT / "docs" / "codexRef.json"

_lock = threading.Lock()
_loaded_path: Path | None = None
_by_entry: dict[str, dict[str, Any]] = {}
_by_english: dict[str, int] = {}
_genus_max: dict[str, int] = {}
_genus_min: dict[str, int] = {}


def _norm(text: str) -> str:
    return " ".join(text.strip().lower().split())


def reset_cache() -> None:
    """Test helper — drop loaded tables."""
    global _loaded_path, _by_entry, _by_english, _genus_max, _genus_min
    with _lock:
        _loaded_path = None
        _by_entry = {}
        _by_english = {}
        _genus_max = {}
        _genus_min = {}
        reward_for_species.cache_clear()
        max_reward_for_genus.cache_clear()
        min_reward_for_genus.cache_clear()


def load_codex_ref(path: Path | None = None) -> int:
    """Load (or reload) the Codex reward JSON. Returns Biology entry count."""
    global _loaded_path, _by_entry, _by_english, _genus_max, _genus_min
    target = path if path is not None else _DEFAULT_PATH
    with _lock:
        if _loaded_path == target and _by_entry:
            return sum(
                1
                for v in _by_entry.values()
                if v.get("hud_category") == "Biology" and (v.get("reward") or 0) > 0
            )
        by_entry: dict[str, dict[str, Any]] = {}
        by_english: dict[str, int] = {}
        genus_max: dict[str, int] = {}
        genus_min: dict[str, int] = {}
        if target.is_file():
            raw = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key, val in raw.items():
                    if not isinstance(val, dict):
                        continue
                    by_entry[str(key)] = val
                    if val.get("hud_category") != "Biology":
                        continue
                    reward = val.get("reward")
                    if not isinstance(reward, (int, float)) or reward <= 0:
                        continue
                    reward_i = int(reward)
                    en = val.get("english_name")
                    if isinstance(en, str) and en.strip():
                        by_english[_norm(en)] = reward_i
                        # Genus is typically the trailing words after colour prefix
                        # ("Roseum Brain Tree" → "Brain Tree"; "Fonticulua Campestris"
                        # is species — also index first token as genus family).
                        parts = en.strip().split()
                        if len(parts) >= 2:
                            for genus_cand in (
                                " ".join(parts[1:]),
                                parts[0],
                            ):
                                g = _norm(genus_cand)
                                if not g:
                                    continue
                                prev = genus_max.get(g, 0)
                                if reward_i > prev:
                                    genus_max[g] = reward_i
                                lo = genus_min.get(g)
                                if lo is None or reward_i < lo:
                                    genus_min[g] = reward_i
        _by_entry = by_entry
        _by_english = by_english
        _genus_max = genus_max
        _genus_min = genus_min
        _loaded_path = target
        reward_for_species.cache_clear()
        max_reward_for_genus.cache_clear()
        min_reward_for_genus.cache_clear()
        return sum(
            1
            for v in by_entry.values()
            if v.get("hud_category") == "Biology" and (v.get("reward") or 0) > 0
        )


def ensure_loaded(path: Path | None = None) -> None:
    if _loaded_path is None or (path is not None and path != _loaded_path):
        load_codex_ref(path)


@lru_cache(maxsize=512)
def reward_for_species(name: str | None) -> int:
    """Exact english_name / species match → reward credits (0 if unknown)."""
    if not name or not str(name).strip():
        return 0
    ensure_loaded()
    return int(_by_english.get(_norm(str(name)), 0))


@lru_cache(maxsize=256)
def max_reward_for_genus(genus: str | None) -> int:
    """Highest Biology reward whose english_name contains this genus."""
    if not genus or not str(genus).strip():
        return 0
    ensure_loaded()
    key = _norm(str(genus))
    hit = _genus_max.get(key)
    if hit:
        return int(hit)
    # Fallback: substring scan (journal "Brain Trees" vs "Brain Tree")
    best = 0
    for en, reward in _by_english.items():
        if key in en or en in key:
            if reward > best:
                best = reward
    return int(best)


@lru_cache(maxsize=256)
def min_reward_for_genus(genus: str | None) -> int:
    if not genus or not str(genus).strip():
        return 0
    ensure_loaded()
    key = _norm(str(genus))
    hit = _genus_min.get(key)
    if hit:
        return int(hit)
    best: int | None = None
    for en, reward in _by_english.items():
        if key in en or en in key:
            if best is None or reward < best:
                best = reward
    return int(best or 0)


def format_credits(value: int) -> str:
    """Match Windows Util.credits style: 1,593,700 cr."""
    if value <= 0:
        return "—"
    return f"{value:,} cr"


def reward_for_progress(genus: str | None, species: str | None = None) -> tuple[int, int]:
    """Return (known_reward, max_genus_reward) for volume bars.

    When species is known, known_reward is the species payout and max matches it.
    When only genus is known, known_reward is 0 (prediction) and max is genus max.
    """
    if species:
        sp = reward_for_species(species)
        if sp > 0:
            return sp, sp
    mx = max_reward_for_genus(genus)
    return 0, mx


def image_url_for_species(name: str | None) -> str | None:
    """Return image_url from codexRef for a species english name, if any."""
    if not name or not str(name).strip():
        return None
    ensure_loaded()
    key = _norm(name)
    with _lock:
        for val in _by_entry.values():
            if not isinstance(val, dict):
                continue
            en = val.get("english_name")
            if isinstance(en, str) and _norm(en) == key:
                url = val.get("image_url")
                return url if isinstance(url, str) and url.strip() else None
    return None


def list_biology_genera(*, limit: int = 80) -> list[tuple[str, int]]:
    """Return [(genus, max_reward), ...] sorted by reward desc."""
    ensure_loaded()
    with _lock:
        items = sorted(_genus_max.items(), key=lambda kv: (-kv[1], kv[0]))
    return items[: max(1, limit)]
