"""User settings for overlay presentation and HUD layout.

Present is allowed when any of these is true, in order:

1. CLI ``--allow-present``
2. Environment ``SRVSURVEY_ALLOW_PRESENT=1``
3. User config ``allow_present: true`` / ``allow_present=true``

Config files checked (first existing file wins as the primary settings file
for load/save; allow_present still scans the list for a set key):

- ``$XDG_CONFIG_HOME/srvsurvey/config`` (or ``~/.config/srvsurvey/config``)
- ``$XDG_CONFIG_HOME/srvsurvey/config.json``
- ``$XDG_DATA_HOME/srvsurvey/config.json``

Plain config uses ``key=value`` lines. JSON objects use the same keys.
Panel toggles use ``panel.<id>=true|false`` (or a JSON ``panels`` object).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from game_settings import GameSettings
from key_chords import DEFAULT_KEYS, merge_key_actions, normalize_windows_chord


PANEL_IDS: tuple[str, ...] = (
    "location",
    "sysstatus",
    "survey",
    "bio",
    "biostatus",
    "biosystem",
    "fss",
    "fsslast",
    "signals",
    "jumpinfo",
    "galmap",
    "bodyinfo",
    "guardian",
    "guardians",
    "guardiansystem",
    "guardianstatus",
    "ramtah",
    "human",
    "humansite",
    "priorscans",
    "trackers",
    "tracktarget",
    "minitrack",
    "massacre",
    "floatie",
    "footcombat",
    "grounded",
    "adjustvr",
    "pulse",
    "questmini",
    "spherical",
    "station",
    "flightwarn",
    "colonisation",
    "route",
    "ship",
    "materials",
    "locker",
)

DEFAULT_HOTKEY = "Pause"


def _default_panels() -> dict[str, bool]:
    panels = {pid: True for pid in PANEL_IDS}
    # Optional / heavy panels off by default.
    for pid in (
        "guardian",
        "guardians",
        "guardiansystem",
        "guardianstatus",
        "ramtah",
        "human",
        "priorscans",
        "colonisation",
        "locker",
        "massacre",
        "footcombat",
        "grounded",
        "adjustvr",
        "questmini",
        "spherical",
    ):
        if pid in panels:
            panels[pid] = False
    # FSS / jump / body / galmap / station / flightwarn / humansite follow
    # GameSettings autoShow* gates in panel_enabled (Windows defaults on).
    return panels


@dataclass
class AppSettings:
    """Persisted HUD / present settings + Windows GameSettings mirror."""

    allow_present: bool = False
    hotkey: str = DEFAULT_HOTKEY
    font_size: int = 28
    poll_seconds: float = 0.75
    hold_seconds: float = 0.0
    panel_scale: int = 1
    margin: int = 40
    # Extra inset/offset applied after margin (FormSettings overlay-position adjust).
    panel_offset_x: int = 0
    panel_offset_y: int = 0
    stack_gap: int = 12
    max_stack_fraction: float = 0.82
    overlay_visible: bool = True
    panels: dict[str, bool] = field(default_factory=_default_panels)
    game: GameSettings = field(default_factory=GameSettings)
    # Windows Settings.keyActions_TEST — chord strings like "ALT F".
    key_actions: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_KEYS))

    def panel_enabled(self, panel_id: str) -> bool:
        defaults = _default_panels()
        if panel_id not in defaults:
            return False
        if panel_id == "colonisation":
            if not self.game.autoShowPlotBuildCommodities:
                return False
            if self.panels.get("colonisation", defaults["colonisation"]):
                return True
            return bool(self.game.buildProjects_TEST)
        if panel_id == "biostatus":
            if not self.game.autoShowBioSummary:
                return False
            return bool(self.panels.get("biostatus", defaults["biostatus"]))
        if panel_id == "biosystem":
            if not self.game.autoShowPlotBioSystem:
                return False
            return bool(self.panels.get("biosystem", defaults["biosystem"]))
        if panel_id == "fss":
            if not self.game.autoShowPlotFSSInfo:
                return False
            return bool(self.panels.get("fss", defaults["fss"]))
        if panel_id == "fsslast":
            if not self.game.autoShowPlotFSS:
                return False
            return bool(self.panels.get("fsslast", defaults["fsslast"]))
        if panel_id == "jumpinfo":
            if not self.game.autoShowPlotJumpInfo:
                return False
            return bool(self.panels.get("jumpinfo", defaults["jumpinfo"]))
        if panel_id == "galmap":
            if not self.game.autoShowPlotGalMap:
                return False
            return bool(self.panels.get("galmap", defaults["galmap"]))
        if panel_id == "bodyinfo":
            if not self.game.autoShowPlotBodyInfo:
                return False
            return bool(self.panels.get("bodyinfo", defaults["bodyinfo"]))
        if panel_id == "guardian":
            if not self.game.enableGuardianSites:
                return False
            return bool(self.panels.get("guardian", defaults["guardian"]))
        if panel_id == "guardians":
            if not self.game.enableGuardianSites:
                return False
            if self.game.buildProjectsSuppressOtherOverlays:
                return False
            return bool(self.panels.get("guardians", defaults.get("guardians", True)))
        if panel_id == "guardiansystem":
            if not self.game.enableGuardianSites:
                return False
            if not self.game.autoShowGuardianSummary:
                return False
            if self.game.buildProjectsSuppressOtherOverlays:
                return False
            return bool(self.panels.get("guardiansystem", defaults["guardiansystem"]))
        if panel_id == "guardianstatus":
            if not self.game.enableGuardianSites:
                return False
            if self.game.buildProjectsSuppressOtherOverlays:
                return False
            return bool(self.panels.get("guardianstatus", defaults["guardianstatus"]))
        if panel_id == "ramtah":
            if not self.game.enableGuardianSites:
                return False
            if not self.game.autoShowRamTah:
                return False
            if self.game.buildProjectsSuppressOtherOverlays:
                return False
            return bool(self.panels.get("ramtah", defaults["ramtah"]))
        if panel_id == "station":
            if not self.game.autoShowPlotStationInfo_TEST:
                return False
            return bool(self.panels.get("station", defaults["station"]))
        if panel_id == "flightwarn":
            if not self.game.autoShowFlightWarnings:
                return False
            return bool(self.panels.get("flightwarn", defaults["flightwarn"]))
        if panel_id == "humansite":
            if not self.game.autoShowHumanSitesTest:
                return False
            return bool(self.panels.get("humansite", defaults["humansite"]))
        if panel_id == "priorscans":
            if not self.game.useExternalData or not self.game.autoLoadPriorScans:
                return False
            return bool(self.panels.get("priorscans", defaults["priorscans"]))
        if panel_id == "tracktarget":
            if not self.game.targetLatLongActive:
                return False
            return bool(self.panels.get("tracktarget", defaults["tracktarget"]))
        if panel_id == "trackers":
            if not self.game.autoShowBioPlot:
                return False
            return bool(self.panels.get("trackers", defaults["trackers"]))
        if panel_id == "minitrack":
            if not (
                self.game.autoShowPlotMiniTrack or self.game.autoShowPlotMiniTrackRhino
            ):
                return False
            return bool(self.panels.get("minitrack", defaults["minitrack"]))
        if panel_id == "massacre":
            if not self.game.autoShowPlotMassacre_TEST:
                return False
            return bool(self.panels.get("massacre", defaults["massacre"]))
        if panel_id == "floatie":
            if not self.game.autoShowFloatie_TEST:
                return False
            return bool(self.panels.get("floatie", defaults["floatie"]))
        if panel_id == "footcombat":
            if not self.game.autoShowFootCombat_TEST:
                return False
            return bool(self.panels.get("footcombat", defaults["footcombat"]))
        if panel_id == "grounded":
            if not self.game.autoShowBioPlot:
                return False
            return bool(self.panels.get("grounded", defaults["grounded"]))
        if panel_id == "adjustvr":
            if not self.game.displayVR:
                return False
            return bool(self.panels.get("adjustvr", defaults["adjustvr"]))
        if panel_id == "pulse":
            if self.game.hideJournalWriteTimer:
                return False
            return bool(self.panels.get("pulse", defaults["pulse"]))
        if panel_id == "questmini":
            if not self.game.enableQuests:
                return False
            return bool(self.panels.get("questmini", defaults["questmini"]))
        if panel_id == "spherical":
            if not (
                self.game.sphereLimitActive or self.game.boxelSearchActive
            ):
                return False
            return bool(self.panels.get("spherical", defaults["spherical"]))
        return bool(self.panels.get(panel_id, defaults[panel_id]))

    def with_updates(self, **kwargs: object) -> AppSettings:
        return replace(self, **kwargs)


def config_search_paths(
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> list[Path]:
    """Ordered list of config files that may set settings."""
    env = os.environ if environ is None else environ
    root = Path.home() if home is None else home
    xdg_config = env.get("XDG_CONFIG_HOME") or str(root / ".config")
    xdg_data = env.get("XDG_DATA_HOME") or str(root / ".local" / "share")
    return [
        Path(xdg_config) / "srvsurvey" / "config",
        Path(xdg_config) / "srvsurvey" / "config.json",
        Path(xdg_data) / "srvsurvey" / "config.json",
    ]


def primary_config_path(
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Path used when saving settings (creates ~/.config/srvsurvey/config)."""
    paths = config_search_paths(environ, home)
    for path in paths:
        if path.is_file():
            return path
    return paths[0]


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _as_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def parse_config_text(text: str, *, as_json: bool | None = None) -> dict[str, object]:
    """Parse JSON or simple ``key=value`` lines into a dict."""
    stripped = text.strip()
    if not stripped:
        return {}
    prefer_json = as_json if as_json is not None else stripped.startswith("{")
    if prefer_json:
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            return data
        if as_json:
            return {}
    out: dict[str, object] = {}
    for line in text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith(";"):
            continue
        if "=" not in raw:
            continue
        key, _, value = raw.partition("=")
        out[key.strip()] = value.strip()
    return out


def _panels_from_raw(data: dict[str, object]) -> dict[str, bool]:
    panels = _default_panels()
    nested = data.get("panels")
    if isinstance(nested, dict):
        for key, value in nested.items():
            if key in panels:
                panels[key] = _truthy(value)
    for key, value in data.items():
        if key.startswith("panel."):
            pid = key[len("panel.") :]
            if pid in panels:
                panels[pid] = _truthy(value)
        elif key.startswith("panel_") and key[len("panel_") :] in panels:
            panels[key[len("panel_") :]] = _truthy(value)
    return panels


def _key_actions_from_raw(data: dict[str, object]) -> dict[str, str]:
    """Load chord.<action>=… / keyActions object into a merged map."""
    overrides: dict[str, str] = {}
    nested = data.get("key_actions") or data.get("keyActions") or data.get("keyActions_TEST")
    if isinstance(nested, dict):
        for key, value in nested.items():
            overrides[str(key)] = "" if value is None else str(value).strip()
    for key, value in data.items():
        if key.startswith("chord."):
            action = key[len("chord.") :]
            overrides[action] = "" if value is None else str(value).strip()
        elif key.startswith("keyAction."):
            action = key[len("keyAction.") :]
            overrides[action] = "" if value is None else str(value).strip()
    # Normalize stored chords to Windows FormSettings shape.
    cleaned = {
        action: normalize_windows_chord(chord) if chord else ""
        for action, chord in overrides.items()
    }
    return merge_key_actions(cleaned)


def settings_from_dict(data: dict[str, object]) -> AppSettings:
    """Build AppSettings from a parsed config dict."""
    base = AppSettings()
    game = GameSettings.from_flat(data)
    # Nested JSON object ``game`` / ``gs`` also accepted
    nested = data.get("game") or data.get("gs")
    if isinstance(nested, dict):
        game = GameSettings.from_flat({**asdict(game), **nested})
    panels = _panels_from_raw(data)
    key_actions = _key_actions_from_raw(data)
    # Sync colonisation panel with Windows master toggles when unset in file
    if "panel.colonisation" not in data and "panels" not in data:
        panels["colonisation"] = bool(
            game.buildProjects_TEST and game.autoShowPlotBuildCommodities
        )
    return AppSettings(
        allow_present=_truthy(data["allow_present"])
        if "allow_present" in data
        else base.allow_present,
        hotkey=str(data.get("hotkey") or base.hotkey).strip() or base.hotkey,
        font_size=max(10, min(72, _as_int(data.get("font_size"), base.font_size))),
        poll_seconds=max(0.1, _as_float(data.get("poll_seconds"), base.poll_seconds)),
        hold_seconds=max(0.0, _as_float(data.get("hold_seconds"), base.hold_seconds)),
        panel_scale=max(1, min(4, _as_int(data.get("panel_scale"), base.panel_scale))),
        margin=max(0, min(400, _as_int(data.get("margin"), base.margin))),
        panel_offset_x=max(
            -2000, min(2000, _as_int(data.get("panel_offset_x"), base.panel_offset_x))
        ),
        panel_offset_y=max(
            -2000, min(2000, _as_int(data.get("panel_offset_y"), base.panel_offset_y))
        ),
        stack_gap=max(0, min(80, _as_int(data.get("stack_gap"), base.stack_gap))),
        max_stack_fraction=max(
            0.3,
            min(1.0, _as_float(data.get("max_stack_fraction"), base.max_stack_fraction)),
        ),
        overlay_visible=_truthy(data["overlay_visible"])
        if "overlay_visible" in data
        else base.overlay_visible,
        panels=panels,
        game=game,
        key_actions=key_actions,
    )


def load_settings(
    *,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
    config_paths: list[Path] | None = None,
) -> AppSettings:
    """Load settings from the first readable config file, else defaults."""
    merged: dict[str, object] = {}
    for path in config_paths if config_paths is not None else config_search_paths(environ, home):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        as_json = path.suffix.lower() == ".json"
        data = parse_config_text(text, as_json=as_json)
        if data:
            merged.update(data)
            break
    return settings_from_dict(merged)


def settings_to_key_value(settings: AppSettings) -> str:
    """Serialize settings to ``key=value`` lines for ~/.config/srvsurvey/config."""
    lines = [
        "# SrvSurvey Linux settings",
        f"allow_present={'true' if settings.allow_present else 'false'}",
        f"hotkey={settings.hotkey}",
        f"font_size={settings.font_size}",
        f"poll_seconds={settings.poll_seconds}",
        f"hold_seconds={settings.hold_seconds}",
        f"panel_scale={settings.panel_scale}",
        f"margin={settings.margin}",
        f"panel_offset_x={settings.panel_offset_x}",
        f"panel_offset_y={settings.panel_offset_y}",
        f"stack_gap={settings.stack_gap}",
        f"max_stack_fraction={settings.max_stack_fraction}",
        f"overlay_visible={'true' if settings.overlay_visible else 'false'}",
    ]
    for pid in PANEL_IDS:
        enabled = settings.panels.get(pid, True)
        lines.append(f"panel.{pid}={'true' if enabled else 'false'}")
    lines.append("# Windows KeyChords / keyActions_TEST (chord.<action>=ALT F)")
    for action in sorted(settings.key_actions.keys()):
        chord = settings.key_actions.get(action, "")
        lines.append(f"chord.{action}={chord}")
    lines.append("# Windows Settings.cs mirror (gs.*)")
    for key, value in settings.game.to_flat().items():
        if value is None:
            continue
        if isinstance(value, bool):
            lines.append(f"gs.{key}={'true' if value else 'false'}")
        elif isinstance(value, int) and not isinstance(value, bool):
            lines.append(f"gs.{key}={value}")
        elif isinstance(value, float):
            # Prefer compact form (50 not 50.0) when integral.
            if value.is_integer():
                lines.append(f"gs.{key}={int(value)}")
            else:
                lines.append(f"gs.{key}={value}")
        else:
            lines.append(f"gs.{key}={value}")
    lines.append("")
    return "\n".join(lines)


def settings_to_json(settings: AppSettings) -> str:
    payload = asdict(settings)
    return json.dumps(payload, indent=2) + "\n"


def save_settings(
    settings: AppSettings,
    path: Path | None = None,
    *,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Write settings to the primary config path (key=value unless path ends in .json)."""
    target = path if path is not None else primary_config_path(environ, home)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() == ".json":
        target.write_text(settings_to_json(settings), encoding="utf-8")
    else:
        target.write_text(settings_to_key_value(settings), encoding="utf-8")
    return target


def patch_config_keys(
    updates: dict[str, str],
    path: Path | None = None,
    *,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Upsert individual ``key=value`` lines without wiping unrelated keys.

    Mirrors Avalonia ``AppConfigStore.SetKey`` for chat MsgCmd target tracking.
    Always writes a key=value file (never JSON).
    """
    target = path if path is not None else primary_config_path(environ, home)
    if target.suffix.lower() == ".json":
        target = target.parent / "config"
    target.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str]
    if target.is_file():
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    else:
        lines = ["# SrvSurvey Linux settings"]

    remaining = dict(updates)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        eq = line.find("=")
        if eq <= 0:
            continue
        key = line[:eq].strip()
        if key not in remaining:
            continue
        lines[i] = f"{key}={remaining.pop(key)}"

    for key, value in remaining.items():
        lines.append(f"{key}={value}")

    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def set_ground_target(
    lat: float,
    lon: float,
    *,
    active: bool = True,
    path: Path | None = None,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Persist ``gs.targetLat`` / ``gs.targetLong`` / ``gs.targetLatLongActive``."""
    return patch_config_keys(
        {
            "gs.targetLat": f"{float(lat):.10g}",
            "gs.targetLong": f"{float(lon):.10g}",
            "gs.targetLatLongActive": "true" if active else "false",
        },
        path=path,
        environ=environ,
        home=home,
    )


def set_ground_target_active(
    active: bool,
    *,
    path: Path | None = None,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Toggle track-target plotter without clearing stored lat/long."""
    return patch_config_keys(
        {"gs.targetLatLongActive": "true" if active else "false"},
        path=path,
        environ=environ,
        home=home,
    )


def read_allow_present_from_files(
    paths: list[Path] | None = None,
    *,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> bool | None:
    """Return True/False if a config file sets allow_present, else None."""
    for path in paths if paths is not None else config_search_paths(environ, home):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        as_json = path.suffix.lower() == ".json"
        data = parse_config_text(text, as_json=as_json)
        if "allow_present" not in data:
            continue
        return _truthy(data["allow_present"])
    return None


def env_allows_present(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get("SRVSURVEY_ALLOW_PRESENT") == "1"


def present_is_allowed(
    *,
    cli_allow: bool = False,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
    config_paths: list[Path] | None = None,
) -> bool:
    """True when the user has explicitly opted in to mapping overlays."""
    if cli_allow:
        return True
    if env_allows_present(environ):
        return True
    from_file = read_allow_present_from_files(
        config_paths,
        environ=environ,
        home=home,
    )
    return bool(from_file)


def refuse_present_message() -> str:
    return (
        "Refusing to open a window. Opt in with --allow-present, "
        "SRVSURVEY_ALLOW_PRESENT=1, or allow_present=true in "
        "~/.config/srvsurvey/config or ~/.local/share/srvsurvey/config.json."
    )
