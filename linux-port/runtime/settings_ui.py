#!/usr/bin/env python3
"""GTK3 settings — Linux surface for Windows FormSettings toggles.

Tab names and order follow Windows FormSettings (General → About). Every
``GameSettings`` bool and numeric field is editable; Linux AppSettings (HUD
panels, hotkey) live on the General tab.
"""

from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from config import (
    PANEL_IDS,
    AppSettings,
    load_settings,
    primary_config_path,
    save_settings,
)
from game_settings import GameSettings
from key_chords import (
    ACTION_DESCRIPTIONS,
    DEFAULT_KEYS,
    LINUX_SUPPORTED_ACTIONS,
    merge_key_actions,
    normalize_windows_chord,
)
from settings_labels import (
    BIO_PLOT_SIZES,
    GUARDIAN_PLOT_SIZES,
    field_label,
)
from settings_lock import acquire_settings_lock, release_settings_lock, settings_is_open
from theme import (
    DEFAULT_BANNER_HEX,
    DEFAULT_CYAN_HEX,
    DEFAULT_DARK_CYAN_HEX,
    DEFAULT_ORANGE_DIM_HEX,
    DEFAULT_ORANGE_HEX,
    parse_hex,
    to_hex,
)

PANEL_LABELS = {
    "location": "Location / System",
    "sysstatus": "PlotSysStatus (DSS survey)",
    "survey": "Survey",
    "bio": "Bio Detail",
    "biostatus": "PlotBioStatus (Body Bio)",
    "biosystem": "PlotBioSystem (System Bio)",
    "fss": "FSS Info",
    "fsslast": "FSS Last Scan",
    "signals": "Signals",
    "jumpinfo": "PlotJumpInfo (Next Jump)",
    "galmap": "Galaxy Map",
    "bodyinfo": "Body Info",
    "guardian": "Guardian Summary",
    "guardians": "PlotGuardians (Site Map)",
    "guardiansystem": "PlotGuardianSystem",
    "guardianstatus": "PlotGuardianStatus",
    "ramtah": "PlotRamTah",
    "human": "Human Sites",
    "humansite": "PlotHumanSite",
    "priorscans": "Prior Scans",
    "trackers": "Bio Trackers",
    "tracktarget": "Track Target",
    "minitrack": "Mini Track",
    "massacre": "Massacre Missions",
    "floatie": "Floatie Messages",
    "footcombat": "Foot Combat",
    "grounded": "Surface Radar",
    "adjustvr": "VR Adjust",
    "pulse": "Journal Pulse",
    "questmini": "Quests Mini",
    "spherical": "Spherical Search",
    "station": "Station Info",
    "flightwarn": "Flight Warning",
    "colonisation": "Colonisation (Build List)",
    "route": "Route",
    "ship": "Ship",
    "materials": "Materials",
    "locker": "Ship Locker",
}

# FormSettings NumericUpDown ranges: name → (min, max, step, digits).
# digits=0 stores as int; digits>0 as float.
_SPIN_SPEC: dict[str, tuple[float, float, float, int]] = {
    "plotterOpacity": (0, 100, 1, 0),
    "plotterScale": (0, 4, 1, 0),
    "fadeInDuration": (0, 5000, 10, 0),
    "blinkDuration": (0, 30000, 100, 0),
    "bioPlotSize": (1, 5, 1, 0),
    "bodyInfoBubbleSize": (0, 1000, 10, 0),
    "plotHumanSiteWidth": (200, 1600, 100, 0),
    "plotHumanSiteHeight": (200, 1000, 100, 0),
    "humanSiteZoomShip": (0.5, 10, 0.05, 2),
    "humanSiteZoomSRV": (0.5, 10, 0.05, 2),
    "humanSiteZoomFoot": (0.5, 10, 0.05, 2),
    "humanSiteZoomInside": (0.5, 10, 0.05, 2),
    "humanSiteZoomTool": (0.5, 10, 0.05, 2),
    "skipLowValueAmount": (0, 6_000_000, 100_000, 0),
    "hideFssLowValueAmount": (0, 6_000_000, 10_000, 0),
    "skipHighDistanceDSSValue": (0, 6_000_000, 10_000, 0),
    "bioRingBucketOne": (0, 20, 0.5, 1),
    "bioRingBucketTwo": (0, 20, 0.5, 1),
    "bioRingBucketThree": (0, 20, 0.5, 1),
    "skipPriorScansLowValueAmount": (0, 20_000_000, 100_000, 0),
    "highGravityWarningLevel": (0, 50, 0.1, 2),
    "keepBioPlottersVisibleDuration": (0, 600, 1, 0),
    "minimumKeyLocationTrackingDistance": (0, 5000, 10, 0),
    "targetLat": (-90, 90, 0.0001, 4),
    "targetLong": (-180, 180, 0.0001, 4),
    "sphereLimitRadiusLy": (0, 100_000, 10, 1),
    "sphereLimitX": (-100_000, 100_000, 1, 1),
    "sphereLimitY": (-100_000, 100_000, 1, 1),
    "sphereLimitZ": (-100_000, 100_000, 1, 1),
    "watchFssYellowHorizontalTolerance": (0, 500, 1, 0),
    "watchFssYellowR": (0, 255, 1, 0),
    "watchFssYellowG": (0, 255, 1, 0),
    "watchFssYellowB": (0, 255, 1, 0),
    "watchFssYellowTolerance": (0, 255, 1, 0),
    "watchFssBlackTolerance": (0, 255, 1, 0),
    "watchFssWhiteTextTolerance": (0, 255, 1, 0),
    "watchFssYellowTextTolerance": (0, 255, 1, 0),
}

# One-sentence intros matching Windows FormSettings section intent.
_TAB_HELP: dict[str, str] = {
    "General": (
        "Overlay opacity, scale, theme, focus behaviour, and VR — "
        "plus Linux HUD panel toggles at the top."
    ),
    "Bio Scanning": (
        "Biological signal overlays, sample trackers, FSS bio panels, "
        "and species reward ring buckets."
    ),
    "Guardians": (
        "Guardian ruins maps, Ram Tah helpers, aerial alignment, and "
        "obelisk zoom behaviour."
    ),
    "Screenshots": (
        "Convert game screenshots, embed location banners, and choose "
        "source/target folders."
    ),
    "Exploration": (
        "System DSS status, body info, galaxy-map preview, jump info, "
        "and FSS value filters."
    ),
    "External Data": (
        "Download EDSM/Spansh/Canonn data, EDDN/GGG uploads, prior-scan "
        "guidance, and colonisation project options."
    ),
    "Settlements": (
        "Human settlement maps, POI dots, overlay size, and auto-zoom "
        "levels for ship, SRV, and on foot."
    ),
    "Key Chords": (
        "Enable and edit Windows-style keyActions chords (ALT F, ALT S, …)."
    ),
    "More": (
        "Flight warnings, massacre/mini-track helpers, notifications, "
        "and other toggles that do not fit the main tabs."
    ),
    "About": (
        "SrvSurvey is an unofficial Elite Dangerous companion — not "
        "affiliated with Frontier Developments."
    ),
}

# FormSettings-style groups in Windows tab order: (title, field names).
# Colonisation lives under External Data (as on Windows). Combat helpers
# and notifications live under More.
_TAB_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    (
        "General",
        (
            "plotterOpacity",
            "plotterScale",
            "keepOverlays",
            "displayVR",
            "hideOverlaysFromMouse",
            "hideOverlaysFromMouseInFSS_TEST",
            "streamOneOverlay",
            "disableLargeOverlay",
            "disableBetterAlphaBlending",
            "disableWindowParentIsGame",
            "forceRefocusOnPlotterActivate",
            "hideMultiFloatie",
            "focusGameOnStart",
            "focusGameOnMinimize",
            "focusGameAfterFsdJump",
            "minimizeToTray",
            "darkTheme",
            "themeMainBlack",
            "useSystemNickNames",
            "enableQuests",
            "keyhook_TEST",
            "hookDirectX_TEST",
            "fadeInDuration",
            "hidePlottersFromCombatSuits",
            "hidePlottersFromMaverickSuits",
        ),
    ),
    (
        "Bio Scanning",
        (
            "autoShowBioSummary",
            "autoShowBioPlot",
            "autoHideBioPlotNoGear",
            "autoHideBioPlotOnRepeat",
            "autoShowPlotBioSystem",
            "drawBodyBiosOnlyWhenNear",
            "highlightRegionalFirsts",
            "dimIfAnalyzed",
            "hideGeoCountInBioSystem",
            "keepBioPlottersVisibleEnabled",
            "disableBioPredictions",
            "autoTrackCompBioScans",
            "skipAnalyzedCompBioScans",
            "autoRemoveTrackerOnSampling",
            "autoRemoveTrackerOnFinalSample",
            "tempRange_TEST",
            "bioRingBucketOne",
            "bioRingBucketTwo",
            "bioRingBucketThree",
            "keepBioPlottersVisibleDuration",
            "bioPlotSize",
            "minimumKeyLocationTrackingDistance",
        ),
    ),
    (
        "Guardians",
        (
            "enableGuardianSites",
            "autoShowGuardianSummary",
            "autoShowRamTah",
            "autoZoomGuardianNearObelisks",
            "autoZoomGuardianInTurret",
            "guardianComponentMaterials_TEST",
            "disableRuinsMeasurementGrid",
            "disableAerialAlignmentGrid",
            "aerialAltAlpha",
            "aerialAltBeta",
            "aerialAltGamma",
            "idxGuardianPlotter",
            "guardianZoom",
            "forceGuardianSurveyMode",
            "mapShowNotes",
            "mapShowLegend",
            "blinkDuration",
        ),
    ),
    (
        "Screenshots",
        (
            "processScreenshots",
            "addBannerToScreenshots",
            "deleteScreenshotOriginal",
            "useGuardianAerialScreenshotsFolder",
            "rotateAndTruncateAlphaAerialScreenshots",
            "screenshotBannerLocalTime",
            "migratedAlphaSiteHeading",
            "screenshotSourceFolder",
            "screenshotTargetFolder",
            "screenshotBannerColor",
        ),
    ),
    (
        "Exploration",
        (
            "autoShowPlotSysStatus",
            "autoShowPlotFSS",
            "autoShowPlotFSSInfo",
            "autoShowPlotFSSInfoInSystemMap",
            "autoShowPlotFSSInfoInNavPanel",
            "hideGeoCountInFssInfo",
            "hideFssLowValueAmount",
            "autoShowPlotGalMap",
            "galMapFactions",
            "autoShowPlotJumpInfo",
            "showPlotJumpInfoIfNextHop",
            "plotJumpInfoMinimal",
            "autoShowPlotBodyInfo",
            "autoShowPlotBodyInfoInMap",
            "autoShowPlotBodyInfoInOrbit",
            "autoHidePlotBodyInfoInBubble",
            "bodyInfoHideMats",
            "autoShowPlotBodyInfoAtSurface",
            "useLastUpdatedFromSpanshNotEDSM",
            "showNonBodySignals",
            "skipGasGiantDSS",
            "skipRingsDSS",
            "skipLowValueDSS",
            "skipHighDistanceDSS",
            "skipLowValueAmount",
            "skipHighDistanceDSSValue",
            "bodyInfoBubbleSize",
            "targetLat",
            "targetLong",
            "watchFssPixel_TEST",
            "watchFssSaveDebugImages",
            "watchFssYellowHorizontalTolerance",
            "watchFssYellowR",
            "watchFssYellowG",
            "watchFssYellowB",
            "watchFssYellowTolerance",
            "watchFssBlackTolerance",
            "watchFssWhiteTextTolerance",
            "watchFssYellowTextTolerance",
        ),
    ),
    (
        "External Data",
        (
            # External sources (Windows External Data top)
            "useExternalData",
            "useExternalBioData",
            # EDDN / GGG (grouped clearly for Linux)
            "eddnUpload",
            "eddnEnvironment",
            "uploadGGG",
            # Prior scans / Canonn
            "autoLoadPriorScans",
            "skipPriorScansLowValue",
            "showCanonnSignalsOnRadar",
            "useSmallCirclesWithCanonn",
            "hideMyOwnCanonnSignals",
            "preDownloadCodexImages",
            "skipPriorScansLowValueAmount",
            # Colonisation (Windows group on External Data)
            "buildProjects_TEST",
            "autoShowPlotBuildCommodities",
            "buildProjectsShowSumFC_TEST",
            "buildProjectsShowSumFCDelta_TEST",
            "buildProjectsInlineSumFC_TEST",
            "buildProjectsHighlightAlmostFC_TEST",
            "buildProjectsCollapseGroupsWithFCEnough_TEST",
            "buildProjectsOnRightScreen",
            "buildProjectsSuppressOtherOverlays",
            "buildProjectsTrackShipCargo",
        ),
    ),
    (
        "Settlements",
        (
            "autoShowHumanSitesTest",
            "humanSiteAutoZoomInside",
            "humanSiteAutoZoomTool",
            "humanSiteShow_Medkit",
            "humanSiteShow_Battery",
            "humanSiteShow_DataTerminal",
            "humanSiteDotsOnCollection",
            "collectMatsCollectionStatsTest",
            "plotHumanSiteWidth",
            "plotHumanSiteHeight",
            "humanSiteZoomShip",
            "humanSiteZoomSRV",
            "humanSiteZoomFoot",
            "humanSiteZoomInside",
            "humanSiteZoomTool",
        ),
    ),
    (
        "More",
        (
            # Windows "More" helpers
            "autoShowPlotMassacre_TEST",
            "autoShowPlotMiniTrack",
            "autoShowPlotMiniTrackRhino",
            "autoShowPlotStationInfo_TEST",
            "autoShowFloatie_TEST",
            "autoShowFootCombat_TEST",
            "autoShowFlightWarnings",
            "highGravityWarningLevel",
            "logDockToDockTimes",
            "hideJournalWriteTimer",
            "systemNotesTopMost",
            "viewJourneyTopMost",
            "viewJourneyGalacticTime",
            "formPredictionsCurrentBodyOnly",
            "formGenusShowRingGuide",
            "targetLatLongActive",
            # Notifications (Windows allowNotifications.*)
            "materialCountAfterPickup",
            "cargoMissionRemaining",
            "currentBoxelSearchStatus",
            "showNextBoxelToSearch",
            "showScreenshot",
            # Boxel / sphere search (editable; no dedicated WinForms tab)
            "boxelSearchActive",
            "boxelSearchPrefix",
            "boxelSearchCurrent",
            "boxelSearchNextSystem",
            "sphereLimitActive",
            "sphereLimitRadiusLy",
            "sphereLimitX",
            "sphereLimitY",
            "sphereLimitZ",
            "buildProjectsUrl_TEST",
        ),
    ),
]

# External Data section headings (field name → insert heading before it).
_EXTERNAL_SECTION_BEFORE: dict[str, str] = {
    "useExternalData": "External Sources",
    "eddnUpload": "EDDN & GGG",
    "autoLoadPriorScans": "Prior Scans / Canonn",
    "buildProjects_TEST": "Colonisation",
}

_THEME_COLOUR_FIELDS: tuple[tuple[str, str], ...] = (
    ("defaultOrange", "Theme Orange"),
    ("defaultOrangeDim", "Theme Orange Dim"),
    ("defaultCyan", "Theme Cyan"),
    ("defaultDarkCyan", "Theme Dark Cyan"),
)

_SCREENSHOT_PATH_FIELDS: tuple[tuple[str, str], ...] = (
    ("screenshotSourceFolder", "Source Folder"),
    ("screenshotTargetFolder", "Target Folder"),
)


def _field_is_numeric(field_type: object) -> bool:
    text = field_type if isinstance(field_type, str) else getattr(field_type, "__name__", str(field_type))
    return text in {"int", "float"} or field_type in {int, float}


def _field_is_int(field_type: object) -> bool:
    text = field_type if isinstance(field_type, str) else getattr(field_type, "__name__", str(field_type))
    return text == "int" or field_type is int


def _make_spin(name: str, value: float | int, field_type: object) -> Gtk.SpinButton:
    """Build a SpinButton for a GameSettings numeric field."""
    if name in _SPIN_SPEC:
        lo, hi, step, digits = _SPIN_SPEC[name]
    elif _field_is_int(field_type):
        lo, hi, step, digits = (0, 100_000_000, 1, 0)
    else:
        lo, hi, step, digits = (-1_000_000, 1_000_000, 0.1, 2)
    spin = Gtk.SpinButton.new_with_range(lo, hi, step)
    spin.set_digits(digits)
    spin.set_numeric(True)
    clamped = max(lo, min(hi, float(value)))
    spin.set_value(clamped)
    spin.set_tooltip_text(name)
    return spin


def _labelize(name: str) -> str:
    return field_label(name)


def _field_is_str(field_type: object) -> bool:
    """True for str / Optional[str] / str | None GameSettings fields."""
    if field_type is str:
        return True
    text = field_type if isinstance(field_type, str) else getattr(field_type, "__name__", str(field_type))
    if text == "str":
        return True
    # Annotations like "str | None" or "Optional[str]"
    if "str" in str(text) and "bool" not in str(text):
        return True
    return False


def _hex_to_rgba(hex_color: str, fallback_hex: str) -> Gdk.RGBA:
    r, g, b, a = parse_hex(hex_color, parse_hex(fallback_hex))
    rgba = Gdk.RGBA()
    rgba.red = r / 255.0
    rgba.green = g / 255.0
    rgba.blue = b / 255.0
    rgba.alpha = a / 255.0
    return rgba


def _rgba_to_hex(rgba: Gdk.RGBA) -> str:
    return to_hex(
        (
            max(0, min(255, int(round(rgba.red * 255)))),
            max(0, min(255, int(round(rgba.green * 255)))),
            max(0, min(255, int(round(rgba.blue * 255)))),
            max(0, min(255, int(round(rgba.alpha * 255)))),
        )
    )


def _make_color_button(hex_color: str, fallback_hex: str) -> Gtk.ColorButton:
    btn = Gtk.ColorButton.new_with_rgba(_hex_to_rgba(hex_color, fallback_hex))
    btn.set_use_alpha(False)
    btn.set_title("Pick Colour")
    return btn


def _section_heading(text: str) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0)
    label.set_markup(f"<b>{text}</b>")
    return label


def _tab_help_label(title: str) -> Gtk.Label:
    help_text = _TAB_HELP.get(title, "")
    label = Gtk.Label(label=help_text, xalign=0)
    label.set_line_wrap(True)
    label.set_margin_bottom(8)
    label.get_style_context().add_class("settings-lede")
    return label


def _apply_settings_css(window: Gtk.Window) -> None:
    """Paper studio theme — not the Windows orange-on-black overlay palette."""
    css = Gtk.CssProvider()
    css.load_from_data(
        b"""
        window.settings-shell {
            background-color: #F3EEE4;
            color: #1F1A14;
        }
        window.settings-shell * {
            font-family: "Noto Sans", "Liberation Sans", sans-serif;
            font-size: 13px;
        }
        window.settings-shell label.settings-lede {
            color: #5C564C;
            font-size: 12px;
        }
        window.settings-shell notebook {
            background-color: #F3EEE4;
        }
        window.settings-shell notebook > header {
            background-color: #E8E1D4;
            border-bottom: 1px solid #C9C0B0;
        }
        window.settings-shell notebook > header > tabs > tab {
            padding: 8px 12px;
            color: #5C564C;
            background-color: transparent;
            border: none;
            font-weight: 600;
        }
        window.settings-shell notebook > header > tabs > tab:checked {
            color: #1F1A14;
            background-color: #F3EEE4;
            border-bottom: 2px solid #2A5348;
        }
        window.settings-shell frame {
            border: 1px solid #C9C0B0;
            border-radius: 2px;
            background-color: #FAF6EE;
            margin-top: 8px;
            margin-bottom: 8px;
        }
        window.settings-shell frame > label {
            font-family: "Noto Serif", "Liberation Serif", serif;
            font-size: 13px;
            color: #2A5348;
            padding: 0 6px;
        }
        window.settings-shell checkbutton,
        window.settings-shell label {
            color: #1F1A14;
        }
        window.settings-shell entry, window.settings-shell spinbutton,
        window.settings-shell combobox {
            background-color: #FFFDF8;
            color: #1F1A14;
            border: 1px solid #C9C0B0;
            min-height: 28px;
        }
        window.settings-shell button {
            background-image: none;
            background-color: #E8E1D4;
            color: #1F1A14;
            border: 1px solid #A89F90;
            border-radius: 2px;
            padding: 6px 14px;
            font-weight: 600;
        }
        window.settings-shell button:hover {
            background-color: #DDD5C6;
        }
        window.settings-shell button.suggested-action {
            background-color: #A34B28;
            color: #F3EEE4;
            border-color: #7A351C;
        }
        window.settings-shell button.suggested-action:hover {
            background-color: #8B3E21;
        }
        window.settings-shell .settings-footer {
            background-color: #E8E1D4;
            border-top: 1px solid #C9C0B0;
            padding: 10px 0 0 0;
        }
        """
    )
    Gtk.StyleContext.add_provider_for_screen(
        window.get_screen(),
        css,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


def _api_key_dialog(
    parent: Gtk.Window,
    *,
    title: str,
    label: str,
    initial: str,
    help_url: str | None = None,
) -> str | None:
    """Modal Entry dialog for an API key. Returns trimmed text or None on cancel."""
    dialog = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    dialog.add_buttons(
        Gtk.STOCK_CANCEL,
        Gtk.ResponseType.CANCEL,
        Gtk.STOCK_SAVE,
        Gtk.ResponseType.OK,
    )
    dialog.set_default_response(Gtk.ResponseType.OK)
    box = dialog.get_content_area()
    box.set_spacing(8)
    box.set_border_width(10)
    box.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
    entry = Gtk.Entry()
    entry.set_text(initial or "")
    entry.set_visibility(False)
    entry.set_invisible_char("*")
    entry.set_activates_default(True)
    entry.set_width_chars(40)
    box.pack_start(entry, False, False, 0)
    show = Gtk.CheckButton(label="Show key")
    show.connect(
        "toggled",
        lambda btn: entry.set_visibility(btn.get_active()),
    )
    box.pack_start(show, False, False, 0)
    if help_url:
        link = Gtk.LinkButton(uri=help_url, label="Open help page")
        box.pack_start(link, False, False, 0)
    hint = Gtk.Label(
        label="Saved to XDG secrets file (not the main config). Never commit secrets.",
        xalign=0,
    )
    hint.set_line_wrap(True)
    box.pack_start(hint, False, False, 0)
    dialog.show_all()
    response = dialog.run()
    text = entry.get_text().strip() if response == Gtk.ResponseType.OK else None
    dialog.destroy()
    return text


def run_settings_ui(
    *,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> int:
    """Show a modal settings dialog; return 0 on close."""
    if settings_is_open(environ=environ, home=home):
        print("Settings is already open. Close that window first.", flush=True)
        return 2
    if not acquire_settings_lock(environ=environ, home=home):
        print("Settings is already open. Close that window first.", flush=True)
        return 2

    settings = load_settings(environ=environ, home=home)
    path = primary_config_path(environ=environ, home=home)

    window = Gtk.Window(title="SrvSurvey Settings")
    window.set_border_width(16)
    window.set_default_size(860, 720)
    window.get_style_context().add_class("settings-shell")
    _apply_settings_css(window)

    def _on_destroy(_win: Gtk.Window) -> None:
        release_settings_lock(environ=environ, home=home)
        Gtk.main_quit()

    window.connect("destroy", _on_destroy)

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    window.add(root)

    intro = Gtk.Label(label=f"Config: {path}", xalign=0)
    intro.set_line_wrap(True)
    root.pack_start(intro, False, False, 0)

    notebook = Gtk.Notebook()
    root.pack_start(notebook, True, True, 0)

    status = Gtk.Label(label="", xalign=0)

    game_checks: dict[str, Gtk.CheckButton] = {}
    game_spins: dict[str, Gtk.SpinButton] = {}
    game_colours: dict[str, Gtk.ColorButton] = {}
    game_entries: dict[str, Gtk.Entry] = {}
    game_combos: dict[str, Gtk.ComboBoxText] = {}
    _COMBO_FIELDS = frozenset({"bioPlotSize", "idxGuardianPlotter"})
    known_fields = {f.name: f for f in fields(GameSettings)}
    colour_fallbacks = {
        "defaultOrange": DEFAULT_ORANGE_HEX,
        "defaultOrangeDim": DEFAULT_ORANGE_DIM_HEX,
        "defaultCyan": DEFAULT_CYAN_HEX,
        "defaultDarkCyan": DEFAULT_DARK_CYAN_HEX,
        "screenshotBannerColor": DEFAULT_BANNER_HEX,
    }
    path_field_names = {n for n, _ in _SCREENSHOT_PATH_FIELDS}

    def _make_check(name: str) -> Gtk.CheckButton | None:
        if name in game_checks:
            return game_checks[name]
        value = getattr(settings.game, name)
        if not isinstance(value, bool):
            return None
        check = Gtk.CheckButton(label=field_label(name))
        check.set_active(bool(value))
        check.set_tooltip_text(name)
        game_checks[name] = check
        return check

    def _pack_bool(box: Gtk.Box, name: str) -> Gtk.CheckButton | None:
        check = _make_check(name)
        if check is None or check.get_parent() is not None:
            return check
        box.pack_start(check, False, False, 0)
        return check

    def _indent(parent: Gtk.Box, widget: Gtk.Widget, px: int = 24) -> None:
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wrap.set_margin_start(px)
        wrap.pack_start(widget, False, False, 0)
        parent.pack_start(wrap, False, False, 0)

    def _frame(title: str) -> tuple[Gtk.Frame, Gtk.Box]:
        frame = Gtk.Frame(label=title)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        inner.set_border_width(10)
        frame.add(inner)
        return frame, inner

    def _bind_parent(parent: Gtk.CheckButton, children: list[Gtk.Widget]) -> None:
        def _sync(_btn: Gtk.CheckButton | None = None) -> None:
            on = parent.get_active()
            for child in children:
                child.set_sensitive(on)

        parent.connect("toggled", _sync)
        _sync()

    def _pack_combo(box: Gtk.Box, name: str, items: tuple[str, ...], label: str) -> Gtk.ComboBoxText:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
        combo = Gtk.ComboBoxText()
        for item in items:
            combo.append_text(item)
        raw = getattr(settings.game, name, 0)
        idx = int(raw) if isinstance(raw, (int, float)) else 0
        combo.set_active(max(0, min(len(items) - 1, idx)))
        combo.set_tooltip_text(name)
        row.pack_start(combo, False, False, 0)
        box.pack_start(row, False, False, 0)
        game_combos[name] = combo
        return combo

    def _pack_spins(box: Gtk.Box, names: list[str]) -> None:
        numeric_names = [
            n
            for n in names
            if n in known_fields
            and n not in game_spins
            and n not in _COMBO_FIELDS
            and _field_is_numeric(known_fields[n].type)
        ]
        if not numeric_names:
            return
        grid = Gtk.Grid(column_spacing=10, row_spacing=4)
        box.pack_start(grid, False, False, 4)
        for row, name in enumerate(numeric_names):
            f = known_fields[name]
            value = getattr(settings.game, name)
            spin = _make_spin(name, value if isinstance(value, (int, float)) else 0, f.type)
            label = Gtk.Label(label=field_label(name), xalign=0)
            label.set_tooltip_text(name)
            grid.attach(label, 0, row, 1, 1)
            grid.attach(spin, 1, row, 1, 1)
            game_spins[name] = spin

    def _pack_string_entries(box: Gtk.Box, names: list[str]) -> None:
        """Plain string settings (eddnEnvironment, boxel*, etc.)."""
        skip = set(colour_fallbacks) | path_field_names
        string_names = [
            n
            for n in names
            if n in known_fields
            and n not in skip
            and n not in game_entries
            and _field_is_str(known_fields[n].type)
        ]
        if not string_names:
            return
        grid = Gtk.Grid(column_spacing=10, row_spacing=4)
        box.pack_start(grid, False, False, 4)
        for row, name in enumerate(string_names):
            value = getattr(settings.game, name)
            entry = Gtk.Entry()
            entry.set_text("" if value is None else str(value))
            entry.set_tooltip_text(name)
            entry.set_hexpand(True)
            if name == "eddnEnvironment":
                entry.set_placeholder_text("dev | beta | live")
            label = Gtk.Label(label=field_label(name), xalign=0)
            label.set_tooltip_text(name)
            grid.attach(label, 0, row, 1, 1)
            grid.attach(entry, 1, row, 1, 1)
            game_entries[name] = entry

    def _pack_colour_rows(box: Gtk.Box, rows: tuple[tuple[str, str], ...]) -> None:
        grid = Gtk.Grid(column_spacing=10, row_spacing=4)
        box.pack_start(grid, False, False, 4)
        for row, (name, label_text) in enumerate(rows):
            raw = getattr(settings.game, name, "") or colour_fallbacks[name]
            btn = _make_color_button(str(raw), colour_fallbacks[name])
            btn.set_tooltip_text(name)
            entry = Gtk.Entry()
            entry.set_text(str(raw))
            entry.set_width_chars(10)
            entry.set_tooltip_text(f"{name} (#RRGGBB)")

            def _sync_entry_from_btn(
                color_btn: Gtk.ColorButton, hex_entry: Gtk.Entry = entry
            ) -> None:
                hex_entry.set_text(_rgba_to_hex(color_btn.get_rgba()))

            def _sync_btn_from_entry(
                hex_entry: Gtk.Entry,
                color_btn: Gtk.ColorButton = btn,
                fallback: str = colour_fallbacks[name],
            ) -> None:
                color_btn.set_rgba(_hex_to_rgba(hex_entry.get_text(), fallback))

            btn.connect("color-set", _sync_entry_from_btn)
            entry.connect("changed", _sync_btn_from_entry)
            label = Gtk.Label(label=label_text, xalign=0)
            label.set_tooltip_text(name)
            grid.attach(label, 0, row, 1, 1)
            grid.attach(btn, 1, row, 1, 1)
            grid.attach(entry, 2, row, 1, 1)
            game_colours[name] = btn
            game_entries[name] = entry

    def _pack_path_rows(box: Gtk.Box, rows: tuple[tuple[str, str], ...]) -> None:
        grid = Gtk.Grid(column_spacing=10, row_spacing=4)
        box.pack_start(grid, False, False, 4)
        for row, (name, label_text) in enumerate(rows):
            raw = getattr(settings.game, name, "") or ""
            entry = Gtk.Entry()
            entry.set_text(str(raw))
            entry.set_width_chars(42)
            entry.set_tooltip_text(name)
            entry.set_hexpand(True)
            label = Gtk.Label(label=label_text, xalign=0)
            label.set_tooltip_text(name)
            grid.attach(label, 0, row, 1, 1)
            grid.attach(entry, 1, row, 1, 1)
            game_entries[name] = entry

    def _pack_game_fields(box: Gtk.Box, names: tuple[str, ...] | list[str], *, external: bool = False) -> None:
        """Pack fields; External Data inserts section headings and keeps field order."""
        if external:
            for name in names:
                if name not in known_fields:
                    continue
                if name in _EXTERNAL_SECTION_BEFORE:
                    box.pack_start(
                        _section_heading(_EXTERNAL_SECTION_BEFORE[name]), False, False, 6
                    )
                if name in colour_fallbacks or name in path_field_names or name in _COMBO_FIELDS:
                    continue
                ftype = known_fields[name].type
                if _field_is_numeric(ftype):
                    _pack_spins(box, [name])
                elif _field_is_str(ftype):
                    _pack_string_entries(box, [name])
                else:
                    _pack_bool(box, name)
            return

        pending_numeric: list[str] = []
        pending_string: list[str] = []
        for name in names:
            if name not in known_fields:
                continue
            if name in colour_fallbacks or name in path_field_names or name in _COMBO_FIELDS:
                continue
            ftype = known_fields[name].type
            if _field_is_numeric(ftype):
                pending_numeric.append(name)
                continue
            if _field_is_str(ftype):
                pending_string.append(name)
                continue
            _pack_bool(box, name)
        _pack_spins(box, pending_numeric)
        _pack_string_entries(box, pending_string)

    def _new_tab_box(title: str) -> tuple[Gtk.ScrolledWindow, Gtk.Box]:
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(8)
        scroller.add(box)
        box.pack_start(_tab_help_label(title), False, False, 0)
        notebook.append_page(scroller, Gtk.Label(label=title))
        return scroller, box

    # --- General = Windows General + Linux AppSettings (HUD) ---
    _, general_box = _new_tab_box("General")
    general_box.pack_start(_section_heading("Linux Overlay (AppSettings)"), False, False, 4)

    grid = Gtk.Grid(column_spacing=10, row_spacing=6)
    general_box.pack_start(grid, False, False, 0)

    def add_row(row: int, label: str, widget: Gtk.Widget) -> None:
        grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
        grid.attach(widget, 1, row, 1, 1)

    allow = Gtk.CheckButton(label="Allow overlay present")
    allow.set_active(settings.allow_present)
    add_row(0, "Present", allow)

    hotkey = Gtk.Entry()
    hotkey.set_text(settings.hotkey)
    add_row(1, "Hotkey", hotkey)

    font = Gtk.SpinButton.new_with_range(12, 48, 1)
    font.set_value(settings.font_size)
    add_row(2, "Font size", font)

    poll = Gtk.SpinButton.new_with_range(0.2, 5.0, 0.05)
    poll.set_digits(2)
    poll.set_value(settings.poll_seconds)
    add_row(3, "Poll (s)", poll)

    hold = Gtk.SpinButton.new_with_range(0, 3600, 1)
    hold.set_value(settings.hold_seconds)
    add_row(4, "Hold (s, 0=forever)", hold)

    margin = Gtk.SpinButton.new_with_range(0, 200, 1)
    margin.set_value(settings.margin)
    add_row(5, "Margin (px)", margin)

    offset_x = Gtk.SpinButton.new_with_range(-800, 800, 1)
    offset_x.set_value(settings.panel_offset_x)
    add_row(6, "Panel offset X", offset_x)

    offset_y = Gtk.SpinButton.new_with_range(-800, 800, 1)
    offset_y.set_value(settings.panel_offset_y)
    add_row(7, "Panel offset Y", offset_y)

    scale = Gtk.SpinButton.new_with_range(1, 3, 1)
    scale.set_value(settings.panel_scale)
    add_row(8, "Panel scale", scale)

    gap = Gtk.SpinButton.new_with_range(0, 40, 1)
    gap.set_value(settings.stack_gap)
    add_row(9, "Stack gap (px)", gap)

    fraction = Gtk.SpinButton.new_with_range(0.4, 1.0, 0.01)
    fraction.set_digits(2)
    fraction.set_value(settings.max_stack_fraction)
    add_row(10, "Max stack fraction", fraction)

    general_box.pack_start(_section_heading("Linux HUD Plotters"), False, False, 4)
    panel_checks: dict[str, Gtk.CheckButton] = {}
    for pid in PANEL_IDS:
        check = Gtk.CheckButton(label=PANEL_LABELS.get(pid, pid))
        if pid == "colonisation":
            check.set_active(bool(settings.panels.get(pid, False)))
        else:
            check.set_active(settings.panel_enabled(pid))
        panel_checks[pid] = check
        general_box.pack_start(check, False, False, 0)

    # Overlay position + VR Adjust (Windows btnAdjustOverlays / btnAdjustVR).
    general_box.pack_start(_section_heading("Overlay Position / VR"), False, False, 8)
    pos_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    general_box.pack_start(pos_row, False, False, 0)

    def _on_overlay_position(_btn: Gtk.Button) -> None:
        from adjust_overlay import open_adjust_overlay

        status.set_text(open_adjust_overlay(window))

    def _on_vr_adjust(_btn: Gtk.Button) -> None:
        if "displayVR" in game_checks:
            game_checks["displayVR"].set_active(True)
        if "adjustvr" in panel_checks:
            panel_checks["adjustvr"].set_active(True)
        status.set_text(
            "VR Adjust: displayVR on, adjustvr panel enabled. "
            "OpenVR headset inject is N/A on Wayland — use opacity/scale "
            "(CTRL+/- while ALT V panel is open)."
        )

    btn_pos = Gtk.Button(label="Adjust Overlay Position")
    btn_pos.set_tooltip_text("Place each plotter: left, center, right, or screen, plus optional opacity")
    btn_pos.connect("clicked", _on_overlay_position)
    pos_row.pack_start(btn_pos, False, False, 0)
    btn_vr = Gtk.Button(label="VR Adjust")
    btn_vr.set_tooltip_text("Enable displayVR and open PlotAdjustVR guidance")
    btn_vr.connect("clicked", _on_vr_adjust)
    pos_row.pack_start(btn_vr, False, False, 0)

    general_box.pack_start(_section_heading("Overlay Opacity / Scale / Behaviour"), False, False, 8)
    general_names = next(names for title, names in _TAB_GROUPS if title == "General")
    _pack_game_fields(general_box, general_names)
    general_box.pack_start(_section_heading("Theme Colours"), False, False, 8)
    _pack_colour_rows(general_box, _THEME_COLOUR_FIELDS)

    def _build_bio_tab(box: Gtk.Box) -> None:
        _pack_bool(box, "autoShowBioSummary")
        _pack_bool(box, "autoShowBioPlot")
        _pack_combo(box, "bioPlotSize", BIO_PLOT_SIZES, "Overlay size:")
        _pack_bool(box, "autoHideBioPlotNoGear")
        track = _pack_bool(box, "autoTrackCompBioScans")
        skip = _make_check("skipAnalyzedCompBioScans")
        if skip is not None:
            _indent(box, skip)
        if track is not None and skip is not None:
            _bind_parent(track, [skip])
        _pack_bool(box, "autoRemoveTrackerOnSampling")
        _pack_bool(box, "autoRemoveTrackerOnFinalSample")
        keep = _pack_bool(box, "keepBioPlottersVisibleEnabled")
        dur_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        if "keepBioPlottersVisibleDuration" not in game_spins:
            _pack_spins(dur_row, ["keepBioPlottersVisibleDuration"])
        box.pack_start(dur_row, False, False, 0)
        if keep is not None:
            _bind_parent(keep, [dur_row])
        system = _pack_bool(box, "autoShowPlotBioSystem")
        near = _make_check("drawBodyBiosOnlyWhenNear")
        hide_geo = _make_check("hideGeoCountInBioSystem")
        if near is not None:
            _indent(box, near)
        if hide_geo is not None:
            _indent(box, hide_geo)
        if system is not None:
            kids = [w for w in (near, hide_geo) if w is not None]
            _bind_parent(system, kids)
        rings, inner = _frame("Species Reward Groups")
        inner.pack_start(
            Gtk.Label(
                label="Choose the reward level per group by millions of credits:",
                xalign=0,
            ),
            False,
            False,
            0,
        )
        _pack_spins(
            inner,
            ["bioRingBucketOne", "bioRingBucketTwo", "bioRingBucketThree"],
        )
        box.pack_start(rings, False, False, 4)
        gold_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        _pack_bool(gold_row, "highlightRegionalFirsts")
        _pack_bool(gold_row, "dimIfAnalyzed")
        box.pack_start(gold_row, False, False, 4)

    def _build_guardian_tab(box: Gtk.Box) -> None:
        enable = _pack_bool(box, "enableGuardianSites")
        kids_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        kids_box.set_margin_start(24)
        _pack_bool(kids_box, "autoShowGuardianSummary")
        _pack_bool(kids_box, "autoShowRamTah")
        _pack_bool(kids_box, "autoZoomGuardianNearObelisks")
        _pack_bool(kids_box, "autoZoomGuardianInTurret")
        box.pack_start(kids_box, False, False, 0)
        box.pack_start(
            Gtk.Label(
                label="Preferred altitude for aerial screenshots (fit each site on your monitor):",
                xalign=0,
            ),
            False,
            False,
            6,
        )
        _pack_spins(box, ["aerialAltAlpha", "aerialAltBeta", "aerialAltGamma"])
        _pack_bool(box, "disableRuinsMeasurementGrid")
        _pack_bool(box, "disableAerialAlignmentGrid")
        _pack_combo(box, "idxGuardianPlotter", GUARDIAN_PLOT_SIZES, "Overlay size:")
        _pack_bool(box, "rotateAndTruncateAlphaAerialScreenshots")
        extra, extra_inner = _frame("Additional Guardian Options")
        _pack_game_fields(
            extra_inner,
            (
                "guardianComponentMaterials_TEST",
                "guardianZoom",
                "forceGuardianSurveyMode",
                "mapShowNotes",
                "mapShowLegend",
                "blinkDuration",
            ),
        )
        box.pack_start(extra, False, False, 4)
        if enable is not None:
            _bind_parent(enable, [kids_box, extra])

    def _build_screenshot_tab(box: Gtk.Box) -> None:
        _pack_bool(box, "processScreenshots")
        box.pack_start(_section_heading("Folders"), False, False, 6)
        _pack_path_rows(box, _SCREENSHOT_PATH_FIELDS)
        _pack_bool(box, "deleteScreenshotOriginal")
        _pack_bool(box, "addBannerToScreenshots")
        sample = Gtk.Label(
            label=(
                "Body: nearest body name\n"
                "System: system name\n"
                "Cmdr: commander name — timestamp\n"
                "Lat / Long when known"
            ),
            xalign=0,
        )
        sample.get_style_context().add_class("settings-lede")
        box.pack_start(sample, False, False, 4)
        _pack_bool(box, "screenshotBannerLocalTime")
        _pack_colour_rows(box, (("screenshotBannerColor", "Change colour"),))
        _pack_bool(box, "useGuardianAerialScreenshotsFolder")
        _pack_bool(box, "preDownloadCodexImages")

    def _build_exploration_tab(box: Gtk.Box) -> None:
        _pack_bool(box, "autoShowPlotFSS")
        values = _pack_bool(box, "autoShowPlotFSSInfo")
        sysmap = _make_check("autoShowPlotFSSInfoInSystemMap")
        hide_geo = _make_check("hideGeoCountInFssInfo")
        if sysmap is not None:
            _indent(box, sysmap)
        if hide_geo is not None:
            _indent(box, hide_geo)
        if values is not None:
            _bind_parent(values, [w for w in (sysmap, hide_geo) if w is not None])
        _pack_bool(box, "useLastUpdatedFromSpanshNotEDSM")
        _pack_bool(box, "autoShowPlotSysStatus")
        _pack_bool(box, "skipGasGiantDSS")
        _pack_bool(box, "skipRingsDSS")
        _pack_bool(box, "showNonBodySignals")
        low = _pack_bool(box, "skipLowValueDSS")
        low_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        _pack_spins(low_row, ["skipLowValueAmount"])
        box.pack_start(low_row, False, False, 0)
        if low is not None:
            _bind_parent(low, [low_row])
        high = _pack_bool(box, "skipHighDistanceDSS")
        high_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        _pack_spins(high_row, ["skipHighDistanceDSSValue"])
        box.pack_start(high_row, False, False, 0)
        if high is not None:
            _bind_parent(high, [high_row])
        body = _pack_bool(box, "autoShowPlotBodyInfo")
        body_kids = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        body_kids.set_margin_start(24)
        _pack_bool(body_kids, "autoShowPlotBodyInfoInMap")
        _pack_bool(body_kids, "autoShowPlotBodyInfoInOrbit")
        _pack_bool(body_kids, "autoShowPlotBodyInfoAtSurface")
        _pack_bool(body_kids, "autoHidePlotBodyInfoInBubble")
        _pack_bool(body_kids, "bodyInfoHideMats")
        box.pack_start(body_kids, False, False, 0)
        if body is not None:
            _bind_parent(body, [body_kids])
        _pack_bool(box, "autoShowPlotGalMap")
        _pack_bool(box, "autoShowPlotJumpInfo")
        _pack_bool(box, "showPlotJumpInfoIfNextHop")
        _pack_bool(box, "plotJumpInfoMinimal")
        _pack_bool(box, "galMapFactions")

    def _build_settlement_tab(box: Gtk.Box) -> None:
        human = _pack_bool(box, "autoShowHumanSitesTest")
        size, size_inner = _frame("Overlay Size (Pixels)")
        _pack_spins(size_inner, ["plotHumanSiteWidth", "plotHumanSiteHeight"])
        zoom, zoom_inner = _frame("Zoom Levels")
        _pack_spins(
            zoom_inner,
            [
                "humanSiteZoomShip",
                "humanSiteZoomSRV",
                "humanSiteZoomFoot",
                "humanSiteZoomInside",
                "humanSiteZoomTool",
            ],
        )
        _pack_bool(zoom_inner, "humanSiteAutoZoomInside")
        _pack_bool(zoom_inner, "humanSiteAutoZoomTool")
        poi, poi_inner = _frame("Show POI")
        _pack_bool(poi_inner, "humanSiteShow_Medkit")
        _pack_bool(poi_inner, "humanSiteShow_Battery")
        _pack_bool(poi_inner, "humanSiteShow_DataTerminal")
        note = Gtk.Label(
            label=(
                "POI are randomly generated at each settlement. Locations "
                "shown on the map may not be correct."
            ),
            xalign=0,
        )
        note.set_line_wrap(True)
        poi_inner.pack_start(note, False, False, 0)
        box.pack_start(size, False, False, 4)
        box.pack_start(zoom, False, False, 4)
        box.pack_start(poi, False, False, 4)
        _pack_bool(box, "humanSiteDotsOnCollection")
        if human is not None:
            _bind_parent(human, [size, zoom, poi])

    def _build_more_tab(box: Gtk.Box) -> None:
        _pack_bool(box, "autoShowPlotStationInfo_TEST")
        _pack_bool(box, "logDockToDockTimes")
        _pack_bool(box, "autoShowPlotMassacre_TEST")
        _pack_bool(box, "autoShowPlotMiniTrack")
        flight = _pack_bool(box, "autoShowFlightWarnings")
        grav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        grav.set_margin_start(24)
        _pack_spins(grav, ["highGravityWarningLevel"])
        box.pack_start(grav, False, False, 0)
        if flight is not None:
            _bind_parent(flight, [grav])
        _pack_bool(box, "hideMultiFloatie")
        _pack_bool(box, "streamOneOverlay")
        _pack_bool(box, "disableBetterAlphaBlending")
        _pack_bool(box, "disableLargeOverlay")
        _pack_bool(box, "disableWindowParentIsGame")
        notes = _pack_bool(box, "autoShowFloatie_TEST")
        notify, notify_inner = _frame("Timed Notifications")
        _pack_bool(notify_inner, "materialCountAfterPickup")
        _pack_bool(notify_inner, "cargoMissionRemaining")
        _pack_bool(notify_inner, "currentBoxelSearchStatus")
        _pack_bool(notify_inner, "showNextBoxelToSearch")
        _pack_bool(notify_inner, "showScreenshot")
        box.pack_start(notify, False, False, 4)
        if notes is not None:
            _bind_parent(notes, [notify])
        _pack_bool(box, "uploadGGG")
        _pack_bool(box, "viewJourneyGalacticTime")

    # --- Remaining Windows-ordered GameSettings tabs (skip General; already built) ---
    for title, names in _TAB_GROUPS:
        if title == "General":
            continue
        _, box = _new_tab_box(title)
        if title == "Bio Scanning":
            _build_bio_tab(box)
            continue
        if title == "Guardians":
            _build_guardian_tab(box)
            continue
        if title == "Screenshots":
            _build_screenshot_tab(box)
            continue
        if title == "Exploration":
            _build_exploration_tab(box)
            continue
        if title == "Settlements":
            _build_settlement_tab(box)
            continue
        if title == "More":
            _build_more_tab(box)
            continue
        _pack_game_fields(box, names, external=(title == "External Data"))
        if title == "External Data":
            box.pack_start(_section_heading("API Keys (XDG Secrets)"), False, False, 8)
            api_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.pack_start(api_row, False, False, 0)

            def _save_inara(_btn: Gtk.Button) -> None:
                from secrets_store import INARA_API_KEY, get_secret, save_secrets

                current = get_secret(INARA_API_KEY, environ=environ, home=home) or ""
                text = _api_key_dialog(
                    window,
                    title="Inara API Key",
                    label="Inara API key (per-commander on Windows; Linux stores in XDG secrets)",
                    initial=current,
                    help_url="https://inara.cz/settings-api/",
                )
                if text is None:
                    return
                save_secrets(
                    {INARA_API_KEY: text or None},
                    environ=environ,
                    home=home,
                )
                status.set_text(
                    "Saved Inara API key to XDG secrets"
                    if text
                    else "Cleared Inara API key"
                )

            def _save_rcc(_btn: Gtk.Button) -> None:
                from secrets_store import RCC_API_KEY, get_secret, save_secrets

                current = get_secret(RCC_API_KEY, environ=environ, home=home) or ""
                text = _api_key_dialog(
                    window,
                    title="RavenColonial API Key",
                    label="RavenColonial (RCC) API key",
                    initial=current,
                    help_url="https://ravencolonial.com/user",
                )
                if text is None:
                    return
                save_secrets(
                    {RCC_API_KEY: text or None},
                    environ=environ,
                    home=home,
                )
                status.set_text(
                    "Saved RavenColonial API key to XDG secrets"
                    if text
                    else "Cleared RavenColonial API key"
                )

            btn_inara = Gtk.Button(label="Inara API Key…")
            btn_inara.connect("clicked", _save_inara)
            api_row.pack_start(btn_inara, False, False, 0)
            btn_rcc = Gtk.Button(label="RavenColonial API Key…")
            btn_rcc.connect("clicked", _save_rcc)
            api_row.pack_start(btn_rcc, False, False, 0)
            colonise = game_checks.get("buildProjects_TEST")
            auto_col = game_checks.get("autoShowPlotBuildCommodities")
            fc_sum = game_checks.get("buildProjectsShowSumFC_TEST")
            col_kids = [
                game_checks[n]
                for n in (
                    "autoShowPlotBuildCommodities",
                    "buildProjectsOnRightScreen",
                    "buildProjectsShowSumFC_TEST",
                    "buildProjectsShowSumFCDelta_TEST",
                    "buildProjectsInlineSumFC_TEST",
                    "buildProjectsHighlightAlmostFC_TEST",
                    "buildProjectsCollapseGroupsWithFCEnough_TEST",
                    "buildProjectsSuppressOtherOverlays",
                    "buildProjectsTrackShipCargo",
                )
                if n in game_checks
            ]
            if colonise is not None:
                _bind_parent(colonise, col_kids)
            if auto_col is not None and colonise is not None:
                def _sync_col_auto(_btn: Gtk.CheckButton | None = None) -> None:
                    on = colonise.get_active() and auto_col.get_active()
                    for name in (
                        "buildProjectsOnRightScreen",
                        "buildProjectsShowSumFC_TEST",
                    ):
                        if name in game_checks:
                            game_checks[name].set_sensitive(on)

                colonise.connect("toggled", _sync_col_auto)
                auto_col.connect("toggled", _sync_col_auto)
                _sync_col_auto()
            if fc_sum is not None:
                fc_kids = [
                    game_checks[n]
                    for n in (
                        "buildProjectsShowSumFCDelta_TEST",
                        "buildProjectsInlineSumFC_TEST",
                        "buildProjectsHighlightAlmostFC_TEST",
                        "buildProjectsCollapseGroupsWithFCEnough_TEST",
                    )
                    if n in game_checks
                ]
                _bind_parent(fc_sum, fc_kids)
    # Catch-all leftovers appended to More (any future field not listed above)
    listed = {n for _t, names in _TAB_GROUPS for n in names}
    listed.update(name for name, _ in _THEME_COLOUR_FIELDS)
    leftover_bool: list[str] = []
    leftover_numeric: list[str] = []
    leftover_string: list[str] = []
    for f in fields(GameSettings):
        if f.name in listed or f.name in game_checks or f.name in game_spins:
            continue
        if f.name in game_colours or f.name in game_entries or f.name in game_combos:
            continue
        if _field_is_numeric(f.type):
            leftover_numeric.append(f.name)
        elif _field_is_str(f.type):
            leftover_string.append(f.name)
        else:
            value = getattr(settings.game, f.name)
            if isinstance(value, bool):
                leftover_bool.append(f.name)

    # --- Key Chords (Windows order: after Settlements, before More) ---
    # Move More page after Key Chords by reordering notebook children.
    # Build Key Chords now, then ensure More is last before About.
    chord_scroll = Gtk.ScrolledWindow()
    chord_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    chord_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    chord_box.set_border_width(8)
    chord_scroll.add(chord_box)
    chord_box.pack_start(_tab_help_label("Key Chords"), False, False, 0)

    keyhook_check = Gtk.CheckButton(label="Enable Key Chords (keyhook_TEST)")
    keyhook_check.set_active(bool(settings.game.keyhook_TEST))
    keyhook_check.set_tooltip_text("gs.keyhook_TEST — X11 GrabKey for action chords")
    chord_box.pack_start(keyhook_check, False, False, 0)
    if "keyhook_TEST" in game_checks:

        def _sync_keyhook_from_tab(_btn: Gtk.CheckButton) -> None:
            game_checks["keyhook_TEST"].set_active(keyhook_check.get_active())

        def _sync_keyhook_from_game(_btn: Gtk.CheckButton) -> None:
            keyhook_check.set_active(game_checks["keyhook_TEST"].get_active())

        keyhook_check.connect("toggled", _sync_keyhook_from_tab)
        game_checks["keyhook_TEST"].connect("toggled", _sync_keyhook_from_game)

    chord_entries: dict[str, Gtk.Entry] = {}
    chord_grid = Gtk.Grid(column_spacing=8, row_spacing=4)
    chord_box.pack_start(chord_grid, False, False, 0)
    chord_grid.attach(Gtk.Label(label="Action", xalign=0), 0, 0, 1, 1)
    chord_grid.attach(Gtk.Label(label="Chord", xalign=0), 1, 0, 1, 1)
    ordered = sorted(
        merge_key_actions(settings.key_actions).keys(),
        key=lambda a: (0 if a in LINUX_SUPPORTED_ACTIONS else 1, a),
    )
    for row, action in enumerate(ordered, start=1):
        desc = ACTION_DESCRIPTIONS.get(action, action)
        label = Gtk.Label(label=action, xalign=0)
        label.set_tooltip_text(desc)
        if action in LINUX_SUPPORTED_ACTIONS:
            label.set_markup(f"<b>{action}</b>")
            label.set_tooltip_text(f"{desc} (Linux-supported)")
        entry = Gtk.Entry()
        entry.set_text(settings.key_actions.get(action, DEFAULT_KEYS.get(action, "")))
        entry.set_placeholder_text("ALT F / empty to unbind")
        entry.set_width_chars(18)
        entry.set_tooltip_text(desc)
        chord_grid.attach(label, 0, row, 1, 1)
        chord_grid.attach(entry, 1, row, 1, 1)
        chord_entries[action] = entry

    # Reorder: insert Key Chords before More (Windows: Settlements, Key Chords, More, About)
    more_page_index = None
    for i in range(notebook.get_n_pages()):
        page = notebook.get_nth_page(i)
        tab_label = notebook.get_tab_label_text(page)
        if tab_label == "More":
            more_page_index = i
            break
    if more_page_index is not None:
        notebook.insert_page(chord_scroll, Gtk.Label(label="Key Chords"), more_page_index)
    else:
        notebook.append_page(chord_scroll, Gtk.Label(label="Key Chords"))

    # Append any leftover fields onto More
    if leftover_bool or leftover_numeric or leftover_string:
        for i in range(notebook.get_n_pages()):
            page = notebook.get_nth_page(i)
            if notebook.get_tab_label_text(page) != "More":
                continue
            # page is ScrolledWindow → child Box
            more_inner = page.get_child()
            if isinstance(more_inner, Gtk.Viewport):
                more_inner = more_inner.get_child()
            if more_inner is None:
                break
            more_inner.pack_start(_section_heading("Other Fields"), False, False, 8)
            for name in leftover_bool:
                _pack_bool(more_inner, name)
            _pack_spins(more_inner, leftover_numeric)
            _pack_string_entries(more_inner, leftover_string)
            break

    # --- About ---
    _, about_box = _new_tab_box("About")
    about_body = Gtk.Label(
        label=(
            "SrvSurvey is not an official tool for Elite Dangerous and is not "
            "affiliated with Frontier Developments. All trademarks and copyright "
            "are acknowledged as the property of their respective owners.\n\n"
            "Linux port: GTK FormSettings groups mirror Windows tabs. "
            "API keys live in the XDG secrets file. OpenVR headset inject "
            "is N/A on Wayland; VR Adjust nudges overlay opacity/scale."
        ),
        xalign=0,
    )
    about_body.set_line_wrap(True)
    about_box.pack_start(about_body, False, False, 0)

    buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    buttons.get_style_context().add_class("settings-footer")
    root.pack_end(buttons, False, False, 0)
    save_btn = Gtk.Button(label="Save")
    save_btn.get_style_context().add_class("suggested-action")
    close_btn = Gtk.Button(label="Cancel")
    buttons.pack_end(close_btn, False, False, 0)
    buttons.pack_end(save_btn, False, False, 0)
    root.pack_end(status, False, False, 0)

    def collect() -> AppSettings:
        panels = {pid: panel_checks[pid].get_active() for pid in PANEL_IDS}
        updates: dict[str, object] = {
            name: check.get_active() for name, check in game_checks.items()
        }
        updates["keyhook_TEST"] = keyhook_check.get_active()
        for name, combo in game_combos.items():
            updates[name] = max(0, int(combo.get_active()))
        for name, spin in game_spins.items():
            f = known_fields[name]
            raw = spin.get_value()
            updates[name] = int(raw) if _field_is_int(f.type) else float(raw)
        for name, entry in game_entries.items():
            text = entry.get_text().strip()
            if name in colour_fallbacks:
                updates[name] = text or colour_fallbacks[name]
            elif name == "eddnEnvironment" or (
                name in known_fields and "None" in str(known_fields[name].type)
            ):
                updates[name] = text or None
            else:
                updates[name] = text
        for name, btn in game_colours.items():
            if name not in updates or not updates[name]:
                updates[name] = _rgba_to_hex(btn.get_rgba())
        if panels.get("colonisation"):
            updates["buildProjects_TEST"] = True
            updates["autoShowPlotBuildCommodities"] = True
        game = replace(settings.game, **updates)
        chords: dict[str, str] = {}
        for action, entry in chord_entries.items():
            chords[action] = normalize_windows_chord(entry.get_text())
        return AppSettings(
            allow_present=allow.get_active(),
            hotkey=hotkey.get_text().strip() or settings.hotkey,
            font_size=int(font.get_value()),
            poll_seconds=float(poll.get_value()),
            hold_seconds=float(hold.get_value()),
            panel_scale=int(scale.get_value()),
            margin=int(margin.get_value()),
            panel_offset_x=int(offset_x.get_value()),
            panel_offset_y=int(offset_y.get_value()),
            stack_gap=int(gap.get_value()),
            max_stack_fraction=float(fraction.get_value()),
            overlay_visible=settings.overlay_visible,
            panels=panels,
            game=game,
            key_actions=merge_key_actions(chords),
        )

    def on_save(_btn: Gtk.Button) -> None:
        updated = collect()
        saved = save_settings(updated, path)
        try:
            from theme import clear_cache

            clear_cache()
        except Exception:
            pass
        status.set_text(
            f"Saved {saved} ({len(game_checks)} toggles, "
            f"{len(game_spins)} numbers, {len(game_colours)} colours, "
            f"{len(chord_entries)} chords)"
        )

    save_btn.connect("clicked", on_save)
    close_btn.connect("clicked", lambda _b: window.destroy())

    window.show_all()
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_settings_ui())
