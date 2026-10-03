#!/usr/bin/env python3
"""Windows wire identity — Program.userAgent / FileVersion.

SrvSurvey/Program.cs sets ``userAgent`` to ``SrvSurvey-{FileVersion}`` from
``SrvSurvey/SrvSurvey.csproj``. Every HTTP client on Windows sends that
header. Linux must send the same string so Inara, EDDN, Raven Colonial,
Canonn, Spansh, and EDSM see the same client.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_FALLBACK_VERSION = "2.0.95.0"


def _csproj_path() -> Path:
    # linux-port/runtime/client_identity.py → repo / SrvSurvey / SrvSurvey.csproj
    return Path(__file__).resolve().parents[2] / "SrvSurvey" / "SrvSurvey.csproj"


@lru_cache(maxsize=1)
def release_version() -> str:
    """Assembly FileVersion (Windows ``Program.releaseVersion``)."""
    path = _csproj_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return _FALLBACK_VERSION
    match = re.search(r"<FileVersion>\s*([^<]+?)\s*</FileVersion>", text)
    if not match:
        return _FALLBACK_VERSION
    version = match.group(1).strip()
    return version or _FALLBACK_VERSION


def user_agent() -> str:
    """Windows ``Program.userAgent``."""
    return f"SrvSurvey-{release_version()}"
