#!/usr/bin/env python3
"""XDG secrets for API keys — never written into the main config file.

Stored as ``key=value`` lines under
``$XDG_CONFIG_HOME/srvsurvey/secrets`` (mode 0600 when possible).
"""

from __future__ import annotations

import os
from pathlib import Path

INARA_API_KEY = "inara_api_key"
RCC_API_KEY = "rcc_api_key"

_KNOWN_KEYS = frozenset({INARA_API_KEY, RCC_API_KEY})


def secrets_path(
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    env = os.environ if environ is None else environ
    root = Path.home() if home is None else home
    xdg = env.get("XDG_CONFIG_HOME") or str(root / ".config")
    return Path(xdg) / "srvsurvey" / "secrets"


def load_secrets(
    path: Path | None = None,
    *,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> dict[str, str]:
    """Return known secret keys present in the secrets file."""
    target = path if path is not None else secrets_path(environ=environ, home=home)
    if not target.is_file():
        return {}
    out: dict[str, str] = {}
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    for line in text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, _, value = raw.partition("=")
        key = key.strip()
        if key in _KNOWN_KEYS:
            out[key] = value.strip()
    return out


def get_secret(
    key: str,
    *,
    path: Path | None = None,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> str | None:
    value = load_secrets(path, environ=environ, home=home).get(key, "").strip()
    return value or None


def save_secrets(
    updates: dict[str, str | None],
    *,
    path: Path | None = None,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Merge ``updates`` into the secrets file. Empty/None clears a key."""
    target = path if path is not None else secrets_path(environ=environ, home=home)
    current = load_secrets(target)
    for key, value in updates.items():
        if key not in _KNOWN_KEYS:
            continue
        text = (value or "").strip()
        if text:
            current[key] = text
        else:
            current.pop(key, None)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# SrvSurvey Linux secrets — do not commit",
        "# Keys: inara_api_key, rcc_api_key",
    ]
    for key in sorted(current):
        lines.append(f"{key}={current[key]}")
    lines.append("")
    target.write_text("\n".join(lines), encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return target
