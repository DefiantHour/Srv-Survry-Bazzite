#!/usr/bin/env python3
"""Windows FormSettings control text keyed by Settings field name."""

from __future__ import annotations

# Exact Windows checkbox / numeric labels (FormSettings.Designer.cs).
FIELD_LABELS: dict[str, str] = {
    "themeMainBlack": "Black theme (experimental)",
    "displayVR": "Enable VR overlays",
    "minimizeToTray": "Minimize to system tray",
    "hideOverlaysFromMouseInFSS_TEST": "Hide overlays from mouse",
    "hidePlottersFromCombatSuits": "Dominator suit",
    "hidePlottersFromMaverickSuits": "Maverick suit",
    "plotterOpacity": "Overlay opacity",
    "focusGameAfterFsdJump": "Set focus on Elite Dangerous after each FSD jump.",
    "darkTheme": "Dark theme",
    "plotterScale": "Overlay scale",
    "hideJournalWriteTimer": "Hide 5 second journal file write timer",
    "focusGameOnStart": "Set focus on Elite Dangerous when starting Srv Survey.",
    "hideOverlaysFromMouse": "Prevent mouse entering overlay windows.",
    "focusGameOnMinimize": "Set focus on Elite Dangerous when minimizing Srv Survey.",
    "dimIfAnalyzed": "Dim if analyzed",
    "hideGeoCountInBioSystem": "Hide geo signals",
    "bioPlotSize": "Overlay size",
    "autoHideBioPlotNoGear": "Hide if landing gear is not deployed when flying.",
    "autoRemoveTrackerOnFinalSample": "Auto remove tracker locations upon final scan",
    "keepBioPlottersVisibleDuration": "seconds",
    "highlightRegionalFirsts": "Highlight regional firsts in gold",
    "drawBodyBiosOnlyWhenNear": "Show body bio signals only when target body is close by.",
    "keepBioPlottersVisibleEnabled": "Keep bio overlays visible after DSS scans for:",
    "autoShowPlotBioSystem": "Show whole system exo bio status",
    "autoRemoveTrackerOnSampling": "Auto remove tracker location sampling an organism within 250m.",
    "skipAnalyzedCompBioScans": "But not if that organism has already been analyzed.",
    "autoTrackCompBioScans": "Auto add tracker location when Composition scanning organisms.",
    "autoShowBioPlot": "Show sample scan exclusion zones",
    "autoShowBioSummary": "Show biological signal summary",
    "bioRingBucketOne": "Reward group 1 (M CR)",
    "bioRingBucketTwo": "Reward group 2 (M CR)",
    "bioRingBucketThree": "Reward group 3 (M CR)",
    "idxGuardianPlotter": "Overlay size",
    "autoZoomGuardianInTurret": "Auto zoom map when using SRV turret",
    "autoZoomGuardianNearObelisks": "Auto zoom map if within 30m of obelisks",
    "aerialAltGamma": "Gamma",
    "aerialAltBeta": "Beta",
    "aerialAltAlpha": "Alpha",
    "autoShowRamTah": "Show helper for Ram Tah missions",
    "autoShowGuardianSummary": "Show summary of Guardian sites",
    "rotateAndTruncateAlphaAerialScreenshots": "Rotate Alpha site screenshots by 90° and truncate.",
    "disableAerialAlignmentGrid": "Disable aerial screenshot alignment overlay.",
    "disableRuinsMeasurementGrid": "Disable site heading assistance overlay.",
    "enableGuardianSites": "Enable Guardian Ruins features",
    "preDownloadCodexImages": "Pre-download",
    "deleteScreenshotOriginal": "Remove original files after conversion",
    "screenshotSourceFolder": "Read screenshots from folder",
    "addBannerToScreenshots": "Embed location details within image, if known.",
    "processScreenshots": "Convert .bmp screenshots into .png files",
    "screenshotTargetFolder": "Save converted screenshots in folder",
    "screenshotBannerLocalTime": "Use local time",
    "useGuardianAerialScreenshotsFolder": (
        "Save ruins aerial screenshots into site-type specific sub-folders."
    ),
    "galMapFactions": "Show factions in gal-map",
    "plotJumpInfoMinimal": "Show hops only",
    "bodyInfoHideMats": "Hide body materials",
    "showPlotJumpInfoIfNextHop": "Show if destination is next hop in route",
    "hideGeoCountInFssInfo": "Hide geo signal counts",
    "useLastUpdatedFromSpanshNotEDSM": "Use last updated time from Spansh not EDSM",
    "showNonBodySignals": "Show non-body signals",
    "skipHighDistanceDSSValue": "LS from primary star",
    "skipLowValueAmount": "credits",
    "autoShowPlotFSSInfoInSystemMap": "Show list in system map",
    "autoShowPlotBodyInfoAtSurface": "When at planet surface and not in Combat mode",
    "autoShowPlotJumpInfo": "Show next system summary before FSD jumping (uses external data)",
    "autoHidePlotBodyInfoInBubble": "But keep it hidden when in the bubble <200ly from Sol.",
    "autoShowPlotBodyInfoInOrbit": "In orbit around a body",
    "autoShowPlotBodyInfoInMap": "In the System Map",
    "autoShowPlotBodyInfo": "Show body information panel",
    "autoShowPlotFSSInfo": "Show exploration values list",
    "autoShowPlotGalMap": "Show exploration preview in Galaxy Map (uses external data)",
    "skipHighDistanceDSS": "Skip bodies exceeding:",
    "skipLowValueDSS": "Skip bodies with estimated value below:",
    "skipRingsDSS": "Skip DSS of rings",
    "skipGasGiantDSS": "Skip DSS of gas giants",
    "autoShowPlotSysStatus": "Show system DSS remaining",
    "autoShowPlotFSS": "Show exploration values in FSS",
    "buildProjectsTrackShipCargo": "Track and publish cargo on ship (needs API key)",
    "buildProjectsSuppressOtherOverlays": "Suppress non-Colonisation overlays",
    "buildProjectsOnRightScreen": "Show when looking at right-hand panel",
    "autoShowPlotBuildCommodities": "Auto show colonisation overlay",
    "buildProjectsCollapseGroupsWithFCEnough_TEST": (
        "Collapse cargo groups when enough on FCs"
    ),
    "buildProjectsHighlightAlmostFC_TEST": (
        "Highlight if ship can load enough on FCs"
    ),
    "buildProjectsShowSumFCDelta_TEST": "Show delta vs sum",
    "buildProjectsInlineSumFC_TEST": "Share column with ship cargo counts",
    "buildProjectsShowSumFC_TEST": "Show Fleet Carrier aggregate counts",
    "buildProjects_TEST": "Enable colonisation features",
    "skipPriorScansLowValueAmount": "credits",
    "useExternalBioData": "Use downloaded bio data from Canonn and Spansh",
    "useSmallCirclesWithCanonn": "Use small circles",
    "showCanonnSignalsOnRadar": "Show bio signals from Canonn on the radar",
    "useExternalData": (
        "Download star system, bodies and organic signals data from EDSM, "
        "Spansh and Canonn"
    ),
    "skipPriorScansLowValue": "Skip signals with reward below:",
    "autoLoadPriorScans": "Show aiming guidance to bio signals from Canonn",
    "hideMyOwnCanonnSignals": "Hide my own scans. Uncheck to revisit signals after dying",
    "plotHumanSiteWidth": "Width",
    "plotHumanSiteHeight": "Height",
    "humanSiteShow_DataTerminal": "Data terminals",
    "humanSiteShow_Battery": "Battery packs",
    "humanSiteShow_Medkit": "Med kits",
    "humanSiteZoomFoot": "On-foot zoom level",
    "humanSiteZoomSRV": "SRV zoom level",
    "humanSiteZoomShip": "Ship zoom level",
    "humanSiteZoomTool": "Auto-zoom with analyzer tool",
    "humanSiteZoomInside": "Auto-zoom if inside buildings",
    "humanSiteAutoZoomTool": "Auto-zoom with analyzer tool",
    "humanSiteAutoZoomInside": "Auto-zoom if inside buildings",
    "humanSiteDotsOnCollection": (
        "Show dots when some material is collected. (This can lag when "
        "collecting things quickly.)"
    ),
    "autoShowHumanSitesTest": "Human settlement maps",
    "hookDirectX_TEST": "Enable controller/joystick key chords",
    "keyhook_TEST": "Enable key chords",
    "uploadGGG": "Upload GGG candidates",
    "disableWindowParentIsGame": "Disable game as parent window",
    "disableBetterAlphaBlending": (
        "Disable fancy alpha-blending (use if frame rate is impacted)"
    ),
    "viewJourneyGalacticTime": "Use future dates, eg: 3309",
    "disableLargeOverlay": "Disable single large overlay",
    "streamOneOverlay": "For streaming: use joined overlay",
    "hideMultiFloatie": "Hide multi-game Commander overlay",
    "highGravityWarningLevel": "When body gravity is above:",
    "autoShowFlightWarnings": "Show flight warnings",
    "autoShowPlotMiniTrack": "Mini trackers",
    "autoShowPlotMassacre_TEST": "Massacre mission helper (experimental)",
    "autoShowFloatie_TEST": "Allow timed notification messages",
    "materialCountAfterPickup": "Materials count after pickup",
    "cargoMissionRemaining": "Mission remaining cargo count",
    "currentBoxelSearchStatus": "Boxel search status",
    "showNextBoxelToSearch": "Next boxel to search",
    "showScreenshot": "Screenshot taken",
    "autoShowPlotStationInfo_TEST": "Show station/target details in left nav panel",
    "logDockToDockTimes": "Log dock-to-dock times to .csv file",
    "screenshotBannerColor": "Banner colour",
    "defaultOrange": "Primary colour",
    "defaultOrangeDim": "Primary colour (dim)",
    "defaultCyan": "Secondary colour",
    "defaultDarkCyan": "Secondary colour (dim)",
}

BIO_PLOT_SIZES: tuple[str, ...] = (
    "Small - 250 x 400",
    "Skiny - 250 x 500",
    "Medium - 320 x 440",
    "Large - 380 x 500",
    "Huge - 440 x 600",
)

GUARDIAN_PLOT_SIZES: tuple[str, ...] = (
    "Small - 300 x 400",
    "Medium - 500 x 500",
    "Large - 600 x 700",
    "Huge - 800 x 1000",
    "Massive - 1200 x 1200",
)


def field_label(name: str) -> str:
    if name in FIELD_LABELS:
        return FIELD_LABELS[name]
    cleaned = name.replace("_TEST", "").replace("_", " ")
    parts: list[str] = []
    buf = ""
    for ch in cleaned:
        if ch.isupper() and buf and not buf[-1].isupper():
            parts.append(buf)
            buf = ch
        else:
            buf += ch
    if buf:
        parts.append(buf)
    return " ".join(p.capitalize() if p.islower() else p for p in " ".join(parts).split())
