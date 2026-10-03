#!/usr/bin/env python3
"""Windows Settings.cs mirror for Linux — defaults match upstream.

Persisted as ``gs.<name>=true|false`` (bool) or ``gs.<name>=<number>``
(int/float) lines in the user config.
This is the functional toggle surface for 1-1 plotter behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, asdict, field
from pathlib import Path
from typing import Any

from theme import (
    DEFAULT_BANNER_HEX,
    DEFAULT_CYAN_HEX,
    DEFAULT_DARK_CYAN_HEX,
    DEFAULT_ORANGE_DIM_HEX,
    DEFAULT_ORANGE_HEX,
)


def _default_screenshot_source() -> str:
    """Windows Elite.defaultScreenshotFolder → ~/Pictures/Frontier Developments/…"""
    return str(
        Path.home() / "Pictures" / "Frontier Developments" / "Elite Dangerous"
    )


def _default_screenshot_target() -> str:
    return str(Path(_default_screenshot_source()) / "converted")


@dataclass
class GameSettings:
    """Subset of SrvSurvey.Settings used by Linux plotters (Windows defaults)."""
    buildProjects_TEST: bool = False
    autoShowPlotBuildCommodities: bool = True
    buildProjectsShowSumFC_TEST: bool = True
    buildProjectsShowSumFCDelta_TEST: bool = False
    buildProjectsInlineSumFC_TEST: bool = False
    buildProjectsHighlightAlmostFC_TEST: bool = False
    buildProjectsCollapseGroupsWithFCEnough_TEST: bool = True
    buildProjectsOnRightScreen: bool = True
    buildProjectsSuppressOtherOverlays: bool = False
    buildProjectsTrackShipCargo: bool = False
    # Optional RavenColonial API base (Windows Settings.buildProjectsUrl_TEST).
    buildProjectsUrl_TEST: str | None = None
    hideJournalWriteTimer: bool = False
    minimizeToTray: bool = False
    targetLatLongActive: bool = False
    # Windows Settings.targetLatLong (LatLong2) — split for key=value config.
    targetLat: float = 0.0
    targetLong: float = 0.0
    autoShowBioSummary: bool = True
    autoShowBioPlot: bool = True
    autoHideBioPlotNoGear: bool = False
    autoHideBioPlotOnRepeat: bool = True
    autoShowPlotFSS: bool = True
    autoShowPlotFSSInfo: bool = True
    autoShowPlotFSSInfoInSystemMap: bool = False
    autoShowPlotFSSInfoInNavPanel: bool = False
    autoShowGuardianSummary: bool = True
    autoShowRamTah: bool = True
    autoShowPlotSysStatus: bool = True
    autoShowPlotBioSystem: bool = True
    drawBodyBiosOnlyWhenNear: bool = True
    highlightRegionalFirsts: bool = False
    dimIfAnalyzed: bool = True
    autoShowPlotGalMap: bool = True
    galMapFactions: bool = True
    autoShowPlotJumpInfo: bool = True
    showPlotJumpInfoIfNextHop: bool = False
    plotJumpInfoMinimal: bool = False
    useLastUpdatedFromSpanshNotEDSM: bool = False
    autoShowPlotBodyInfo: bool = True
    autoShowPlotBodyInfoInMap: bool = True
    autoShowPlotBodyInfoInOrbit: bool = True
    autoHidePlotBodyInfoInBubble: bool = True
    bodyInfoHideMats: bool = False
    autoShowPlotBodyInfoAtSurface: bool = False
    autoShowPlotMassacre_TEST: bool = False
    autoShowPlotMiniTrack: bool = True
    autoShowPlotMiniTrackRhino: bool = True
    autoShowPlotStationInfo_TEST: bool = True
    autoShowFloatie_TEST: bool = True
    autoShowFootCombat_TEST: bool = False
    autoShowHumanSitesTest: bool = True
    humanSiteAutoZoomInside: bool = True
    humanSiteAutoZoomTool: bool = True
    humanSiteShow_Medkit: bool = True
    humanSiteShow_Battery: bool = True
    humanSiteShow_DataTerminal: bool = True
    humanSiteDotsOnCollection: bool = True
    collectMatsCollectionStatsTest: bool = False
    skipGasGiantDSS: bool = True
    skipRingsDSS: bool = True
    skipLowValueDSS: bool = True
    skipHighDistanceDSS: bool = False
    showNonBodySignals: bool = False
    autoTrackCompBioScans: bool = True
    skipAnalyzedCompBioScans: bool = True
    autoRemoveTrackerOnSampling: bool = True
    autoRemoveTrackerOnFinalSample: bool = False
    tempRange_TEST: bool = False
    formPredictionsCurrentBodyOnly: bool = False
    useExternalData: bool = True
    useExternalBioData: bool = False
    autoLoadPriorScans: bool = True
    skipPriorScansLowValue: bool = False
    showCanonnSignalsOnRadar: bool = True
    useSmallCirclesWithCanonn: bool = True
    hideMyOwnCanonnSignals: bool = True
    focusGameOnStart: bool = True
    focusGameOnMinimize: bool = True
    focusGameAfterFsdJump: bool = False
    enableGuardianSites: bool = True
    autoZoomGuardianNearObelisks: bool = True
    autoZoomGuardianInTurret: bool = False
    guardianComponentMaterials_TEST: bool = False
    disableRuinsMeasurementGrid: bool = False
    disableAerialAlignmentGrid: bool = False
    # Windows Settings aerial altitudes + plotter size / zoom (PlotGuardians).
    aerialAltAlpha: float = 1200.0
    aerialAltBeta: float = 1550.0
    aerialAltGamma: float = 1600.0
    idxGuardianPlotter: int = 0
    guardianZoom: float = 1.0
    # Force survey mode when chat is unavailable: map | aerial | heading | site.
    forceGuardianSurveyMode: str = ""
    hidePlottersFromCombatSuits: bool = False
    hidePlottersFromMaverickSuits: bool = False
    hideOverlaysFromMouse: bool = True
    hideOverlaysFromMouseInFSS_TEST: bool = False
    hideGeoCountInFssInfo: bool = False
    hideGeoCountInBioSystem: bool = False
    autoShowFlightWarnings: bool = True
    mapShowNotes: bool = True
    mapShowLegend: bool = True
    processScreenshots: bool = False
    addBannerToScreenshots: bool = True
    deleteScreenshotOriginal: bool = False
    useGuardianAerialScreenshotsFolder: bool = True
    rotateAndTruncateAlphaAerialScreenshots: bool = True
    screenshotBannerLocalTime: bool = False
    migratedAlphaSiteHeading: bool = False
    # Windows Settings screenshot folders (Elite.defaultScreenshotFolder + /converted).
    screenshotSourceFolder: str = field(default_factory=_default_screenshot_source)
    screenshotTargetFolder: str = field(default_factory=_default_screenshot_target)
    # Theme colours as #RRGGBB (Windows Settings.defaultOrange / … / screenshotBannerColor).
    defaultOrange: str = DEFAULT_ORANGE_HEX
    defaultOrangeDim: str = DEFAULT_ORANGE_DIM_HEX
    defaultCyan: str = DEFAULT_CYAN_HEX
    defaultDarkCyan: str = DEFAULT_DARK_CYAN_HEX
    screenshotBannerColor: str = DEFAULT_BANNER_HEX
    keepBioPlottersVisibleEnabled: bool = True
    formGenusShowRingGuide: bool = True
    preDownloadCodexImages: bool = False
    darkTheme: bool = False
    themeMainBlack: bool = False
    useSystemNickNames: bool = False
    keyhook_TEST: bool = False
    hookDirectX_TEST: bool = False
    keepOverlays: bool = False
    systemNotesTopMost: bool = False
    viewJourneyTopMost: bool = False
    viewJourneyGalacticTime: bool = True
    logDockToDockTimes: bool = False
    forceRefocusOnPlotterActivate: bool = False
    hideMultiFloatie: bool = False
    streamOneOverlay: bool = False
    disableLargeOverlay: bool = True
    disableBetterAlphaBlending: bool = True
    disableWindowParentIsGame: bool = False
    displayVR: bool = False
    enableQuests: bool = False
    # Linux: attempt X11 screen grab for FSS pixel-watch (Windows watchFssSettings_TEST).
    # Soft-fails on Wayland; PlotFSS stays journal-driven when grab is unavailable.
    watchFssPixel_TEST: bool = False
    watchFssSaveDebugImages: bool = False
    watchFssYellowHorizontalTolerance: int = 100
    watchFssYellowR: int = 193
    watchFssYellowG: int = 156
    watchFssYellowB: int = 65
    watchFssYellowTolerance: int = 60
    watchFssBlackTolerance: int = 30
    watchFssWhiteTextTolerance: int = 50
    watchFssYellowTextTolerance: int = 50
    eddnUpload: bool = False
    # Windows Settings.eddnEnvironment — "dev" | "beta" | "live" (None → EDDN default dev).
    eddnEnvironment: str | None = None
    disableBioPredictions: bool = False
    uploadGGG: bool = False
    # Flat mirror of Windows Settings.allowNotifications nested class.
    materialCountAfterPickup: bool = True
    cargoMissionRemaining: bool = True
    currentBoxelSearchStatus: bool = True
    showNextBoxelToSearch: bool = True
    showScreenshot: bool = True
    # PlotSphericalSearch — Linux mirror of cmdr.sphereLimit / boxelSearch.active
    sphereLimitActive: bool = False
    sphereLimitRadiusLy: float = 1000.0
    sphereLimitX: float = 0.0
    sphereLimitY: float = 0.0
    sphereLimitZ: float = 0.0
    boxelSearchActive: bool = False
    # Minimal boxel search strings (Windows CommanderSettings.boxelSearch)
    boxelSearchPrefix: str = ""
    boxelSearchCurrent: str = ""
    boxelSearchNextSystem: str = ""
    fadeInDuration: int = 150
    bioPlotSize: int = 3
    bodyInfoBubbleSize: int = 200
    plotHumanSiteWidth: int = 500
    plotHumanSiteHeight: int = 600
    humanSiteZoomShip: float = 1.0
    humanSiteZoomSRV: float = 1.5
    humanSiteZoomFoot: float = 2.0
    humanSiteZoomInside: float = 4.0
    humanSiteZoomTool: float = 6.0
    skipLowValueAmount: int = 1000000
    hideFssLowValueAmount: int = 10000
    skipHighDistanceDSSValue: int = 100000
    bioRingBucketOne: float = 3.0
    bioRingBucketTwo: float = 7.0
    bioRingBucketThree: float = 12.0
    skipPriorScansLowValueAmount: int = 1000000
    highGravityWarningLevel: float = 1.0
    plotterOpacity: float = 50.0
    plotterScale: float = 0.0
    blinkDuration: int = 3000
    keepBioPlottersVisibleDuration: int = 120
    minimumKeyLocationTrackingDistance: int = 50


    def to_flat(self) -> dict[str, Any]:
        return asdict(self)


    @classmethod
    def from_flat(cls, data: dict[str, Any]) -> GameSettings:
        known = {f.name: f for f in fields(cls)}
        kwargs: dict[str, Any] = {}
        for key, raw in data.items():
            name = key[3:] if key.startswith("gs.") else key
            if name not in known:
                continue
            f = known[name]
            if f.type is bool or f.type == "bool":
                if isinstance(raw, bool):
                    kwargs[name] = raw
                else:
                    kwargs[name] = str(raw).strip().lower() in {"1", "true", "yes", "on"}
            elif f.type is int or f.type == "int":
                try:
                    kwargs[name] = int(float(str(raw).replace(",", "")))
                except (TypeError, ValueError):
                    pass
            elif f.type is float or f.type == "float":
                try:
                    kwargs[name] = float(str(raw).replace(",", ""))
                except (TypeError, ValueError):
                    pass
            elif f.type is str or f.type == "str" or (
                isinstance(f.type, str) and "str" in f.type
            ):
                text = "" if raw is None else str(raw).strip()
                type_text = f.type if isinstance(f.type, str) else str(f.type)
                if "None" in type_text:
                    kwargs[name] = text or None
                elif text:
                    kwargs[name] = text
        return cls(**kwargs)

