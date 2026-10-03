#!/usr/bin/env python3
"""Headless SrvSurvey slice: find the Proton journal and present HUD panels.

This does not map a window by default. Overlay presentation stays behind
--present, which is refused unless the user opts in via --allow-present,
SRVSURVEY_ALLOW_PRESENT=1, or allow_present in a user config file.

While --present is held, the host polls Elite window geometry, tails the
journal, and re-reads companion JSON so panels reposition and refresh.
Default --hold 0 keeps the overlay up until Ctrl-C.

Main-monitor HUD chip, Pause hotkey, or SIGUSR1 toggles overlay visibility without stopping
journal watch. Open settings with --settings (GTK3).
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass, fields
from pathlib import Path

from companion import (
    CargoSnapshot,
    NavRouteSnapshot,
    ShipLockerSnapshot,
    StatusSnapshot,
)
from config import (
    AppSettings,
    load_settings,
    present_is_allowed,
    refuse_present_message,
    save_settings,
)
from elite import EliteWindowWatch, ensure_session_display, find_elite_window, game_rect_usable
from game_settings import GameSettings
from hotkey import HotkeyToggle
from journal import CommanderLocation, SurveyState, latest_journal_file
from key_chords import (
    ForceShowState,
    LINUX_SUPPORTED_ACTIONS,
    do_key_action,
    find_action_for_chord,
)
from panel import (
    compose_hud_stack,
    render_bio_bitmap,
    render_colonisation_bitmap,
    render_guardian_bitmap,
    render_human_bitmap,
    render_locker_bitmap,
    render_materials_bitmap,
    render_route_bitmap,
    render_ship_bitmap,
    render_signals_bitmap,
    render_status_bitmap,
    render_survey_bitmap,
    set_hud_font_size,
)
from paths import (
    default_library_vdf_paths,
    ensure_data_dir,
    journal_dir_for_libraries,
    srvsurvey_data_dir,
    steam_libraries,
    write_runtime_state,
)
from screenshot import (
    ScreenshotFolderWatcher,
    context_from_location_status,
)
from watcher import JournalWatcher

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "overlay-presenter"))
from presenter import (  # noqa: E402
    OverlayPresenter,
    Panel,
    PresenterMode,
    Rect,
    detect_display,
    layout_overlay,
    should_park_overlays,
)


# Top-right inset inside the Elite window (game-local pixels).
PRESENT_MARGIN = 40
PRESENT_STACK_GAP = 12
# 0 = hold until Ctrl-C (useful for play). Positive = seconds then close.
PRESENT_HOLD_SECONDS = 0.0
PRESENT_POLL_SECONDS = 0.75
# Present at native bitmap size. Readability comes from font size in panel.py.
PRESENT_PANEL_SCALE = 1

# Build order / drop priority when the stack would exceed max height.
PANEL_ORDER: tuple[str, ...] = (
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
    "flightwarn",
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
    "colonisation",
    "route",
    "ship",
    "materials",
    "locker",
)


def load_libraries(vdf_path: Path):
    return steam_libraries(vdf_path.read_text(encoding="utf-8", errors="replace"))


def discover(home: Path | None = None, vdf_path: Path | None = None):
    """Return (data_dir, journal_folder or None, vdf path used or None)."""
    data_dir = srvsurvey_data_dir(home=home)
    if vdf_path is not None:
        candidates = [vdf_path]
    else:
        candidates = default_library_vdf_paths(home)
    for candidate in candidates:
        if not candidate.is_file():
            continue
        folder = journal_dir_for_libraries(load_libraries(candidate))
        return data_dir, folder, candidate
    return data_dir, None, None


def plan(location: CommanderLocation, game: Rect) -> dict:
    rgba, width, height = render_status_bitmap(location)
    panel = Panel(16, 16, width, height, rgba)
    local = Rect(panel.x, panel.y, panel.width, panel.height)
    return {
        "location": location,
        "panel": panel,
        "session": layout_overlay(PresenterMode.SESSION_X11, game, [local]),
        "gamescope": layout_overlay(PresenterMode.GAMESCOPE, game, [local]),
    }


def top_right_inset(game_width: int, panel_width: int, margin: int = PRESENT_MARGIN) -> int:
    """Game-local X for a panel pinned to the top-right with an inset."""
    return max(0, game_width - panel_width - margin)


def stack_top_right(
    bitmaps: list[tuple[bytes, int, int]],
    game: Rect,
    *,
    margin: int = PRESENT_MARGIN,
    gap: int = PRESENT_STACK_GAP,
) -> list[Panel]:
    """Place panels in a vertical stack inset from the top-right corner."""
    panels: list[Panel] = []
    y = margin
    for rgba, width, height in bitmaps:
        x = top_right_inset(game.width, width, margin)
        panels.append(Panel(x, y, width, height, rgba))
        y += height + gap
    return panels


def did_location_change(before: CommanderLocation, after: CommanderLocation) -> bool:
    """True when commander, system, or body changed (journal refresh trigger)."""
    return (
        before.commander != after.commander
        or before.system != after.system
        or before.body != after.body
    )


def did_game_rect_change(before: Rect, after: Rect) -> bool:
    """True when the Elite window moved or was resized (reposition trigger)."""
    return (
        before.x != after.x
        or before.y != after.y
        or before.width != after.width
        or before.height != after.height
    )


def did_survey_change(before: SurveyState, after: SurveyState) -> bool:
    return before != after


# Status.json rewrites these many times a second while docked, landed, or in
# a station. PlotGrounded, PlotBodyInfo, PlotHumanSite, and colonisation draw
# them, but Windows does not rebuild every plotter or restack on each write.
_STATUS_LIVE_FIELDS = frozenset({
    "fuel_main",
    "fuel_reservoir",
    "latitude",
    "longitude",
    "altitude",
    "heading",
    "planet_radius",
})


def did_status_change(before: StatusSnapshot | None, after: StatusSnapshot | None) -> bool:
    """True when a plotter allow() gate or static row changed.

    Fuel and lat/long/heading/altitude are ignored. Those fields update on
    every Status.json write while docked at a planet or inside a station, and
    treating them as a HUD change was PutImage/ConfigureWindow on every poll.
    """
    if before is None or after is None:
        return before is not after
    for field in fields(StatusSnapshot):
        if field.name in _STATUS_LIVE_FIELDS:
            continue
        if getattr(before, field.name) != getattr(after, field.name):
            return True
    return False


def did_cargo_change(before: CargoSnapshot | None, after: CargoSnapshot | None) -> bool:
    return before != after


def did_locker_change(
    before: ShipLockerSnapshot | None,
    after: ShipLockerSnapshot | None,
) -> bool:
    return before != after


def did_nav_change(
    before: NavRouteSnapshot | None,
    after: NavRouteSnapshot | None,
) -> bool:
    return before != after


@dataclass(frozen=True)
class HudState:
    location: CommanderLocation
    survey: SurveyState
    status: StatusSnapshot | None
    cargo: CargoSnapshot | None
    locker: ShipLockerSnapshot | None = None
    nav_route: NavRouteSnapshot | None = None


@dataclass(frozen=True)
class PresentTick:
    """What the hold loop should do after one poll."""

    reposition: bool
    repaint: bool

    @property
    def needs_present(self) -> bool:
        return self.reposition or self.repaint


def present_tick(
    prev_game: Rect,
    game: Rect,
    prev: HudState,
    nxt: HudState,
) -> PresentTick:
    """Decide whether to reposition and/or re-render after a poll."""
    repaint = (
        did_location_change(prev.location, nxt.location)
        or did_survey_change(prev.survey, nxt.survey)
        or did_status_change(prev.status, nxt.status)
        or did_cargo_change(prev.cargo, nxt.cargo)
        or did_locker_change(prev.locker, nxt.locker)
        or did_nav_change(prev.nav_route, nxt.nav_route)
    )
    return PresentTick(
        reposition=did_game_rect_change(prev_game, game),
        repaint=repaint,
    )


_FC_CARGO_CACHE: dict[str, tuple[float, dict[str, int], int]] = {}
_FC_CARGO_TTL = 60.0


def _cached_fc_cargo(cmdr: str, svc_uri: str | None) -> tuple[dict[str, int], int]:
    """One Raven Colonial read per minute. Not on every docked Status.json tick."""
    now = time.monotonic()
    hit = _FC_CARGO_CACHE.get(cmdr)
    if hit is not None and now - hit[0] < _FC_CARGO_TTL:
        return hit[1], hit[2]
    from raven_colonial import linked_fc_cargo_for_cmdr

    cargo, count = linked_fc_cargo_for_cmdr(cmdr, svc_uri=svc_uri)
    _FC_CARGO_CACHE[cmdr] = (now, cargo, count)
    return cargo, count


def status_panel_top_right(
    location: CommanderLocation,
    game: Rect,
    margin: int = PRESENT_MARGIN,
    scale: int = 1,
) -> Panel:
    """Build a status bitmap anchored to the top-right of the game window."""
    rgba, width, height = render_status_bitmap(location, scale=scale)
    x = top_right_inset(game.width, width, margin)
    y = margin
    return Panel(x, y, width, height, rgba)


def _render_named_panel(
    panel_id: str,
    location: CommanderLocation,
    survey: SurveyState,
    status: StatusSnapshot | None,
    cargo: CargoSnapshot | None,
    locker: ShipLockerSnapshot | None,
    nav_route: NavRouteSnapshot | None,
    *,
    scale: int,
    font_size: int,
    journal_path: Path | None = None,
    journal_folder: Path | None = None,
    game_settings: "GameSettings | None" = None,
    force_show: bool = False,
    colony_collapse: bool | None = None,
    cmdr=None,
    last_journal_write_monotonic: float | None = None,
    quest_rows: list | None = None,
) -> tuple[bytes, int, int] | None:
    if panel_id == "location":
        return render_status_bitmap(location, scale=scale, font_size=font_size)
    if panel_id == "sysstatus":
        from config import load_settings
        from plot_sys_status import render_sys_status_bitmap, sys_status_allowed

        gs = game_settings if game_settings is not None else load_settings().game
        if not sys_status_allowed(gs, survey, status, force_show=force_show):
            return None
        return render_sys_status_bitmap(
            survey,
            status,
            show_bio_inline=not gs.autoShowPlotBioSystem,
            show_non_body=bool(gs.showNonBodySignals),
            game=gs,
            frame=False,
        )
    if panel_id == "jumpinfo":
        from config import load_settings
        from plot_jump_info import jump_info_allowed, render_jump_info_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        if not force_show and not jump_info_allowed(gs, status, survey, nav_route):
            return None
        return render_jump_info_bitmap(
            survey,
            status,
            nav_route,
            game=gs,
            force_show=force_show,
        )
    if panel_id == "survey":
        return render_survey_bitmap(survey, scale=scale, font_size=font_size)
    if panel_id == "bio":
        return render_bio_bitmap(survey, location, scale=scale, font_size=font_size)
    if panel_id == "biostatus":
        from config import load_settings
        from plot_bio_status import render_bio_status_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_bio_status_bitmap(
            survey, location, game=gs, status=status
        )
    if panel_id == "biosystem":
        from config import load_settings
        from plot_bio_system import render_bio_system_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_bio_system_bitmap(
            survey,
            location,
            game=gs,
            status=status,
            force_show=force_show,
        )
    if panel_id == "fss":
        from config import load_settings
        from plot_fss_info import render_fss_info_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_fss_info_bitmap(
            survey, game=gs, status=status, force_show=force_show
        )
    if panel_id == "fsslast":
        from config import load_settings
        from plot_fss import render_fss_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_fss_bitmap(survey, game=gs, status=status)
    if panel_id == "galmap":
        from config import load_settings
        from plot_gal_map import render_gal_map_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_gal_map_bitmap(
            survey,
            status=status,
            nav_route=nav_route,
            game=gs,
        )
    if panel_id == "bodyinfo":
        try:
            from plot_body_info import render_body_info_bitmap
        except ImportError:
            return None
        from config import load_settings

        gs = game_settings if game_settings is not None else load_settings().game
        return render_body_info_bitmap(
            survey,
            location,
            status=status,
            game=gs,
            force_show=force_show,
        )
    if panel_id == "signals":
        return render_signals_bitmap(survey, scale=scale, font_size=font_size)
    if panel_id == "flightwarn":
        from config import load_settings
        from plot_flight_warning import render_flight_warning_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_flight_warning_bitmap(
            survey, location=location, status=status, game=gs
        )
    if panel_id == "guardian":
        return render_guardian_bitmap(survey, scale=scale, font_size=font_size)
    if panel_id == "guardians":
        from config import load_settings
        from plot_guardians import render_guardians_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_guardians_bitmap(
            survey, status=status, game=gs, force_show=force_show, cmdr=cmdr
        )
    if panel_id == "guardiansystem":
        from config import load_settings
        from plot_guardian_system import render_guardian_system_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_guardian_system_bitmap(survey, game=gs, status=status)
    if panel_id == "guardianstatus":
        from config import load_settings
        from plot_guardian_status import render_guardian_status_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_guardian_status_bitmap(
            survey, game=gs, status=status, cmdr=cmdr, force_show=force_show
        )
    if panel_id == "ramtah":
        from config import load_settings
        from plot_ram_tah import render_ram_tah_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_ram_tah_bitmap(
            survey, game=gs, status=status, cmdr=cmdr
        )
    if panel_id == "human":
        return render_human_bitmap(survey, scale=scale, font_size=font_size)
    if panel_id == "humansite":
        from config import load_settings
        from plot_human_site import render_human_site_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_human_site_bitmap(
            survey, status, game=gs, cmdr=cmdr
        )
    if panel_id == "priorscans":
        from config import load_settings
        from plot_prior_scans import render_prior_scans_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_prior_scans_bitmap(survey, location, status, game=gs)
    if panel_id == "trackers":
        from config import load_settings
        from plot_trackers import render_trackers_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_trackers_bitmap(
            survey, location, status, game=gs, force_show=force_show
        )
    if panel_id == "tracktarget":
        from config import load_settings
        from plot_trackers import render_track_target_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_track_target_bitmap(
            survey, status=status, game=gs, force_show=force_show
        )
    if panel_id == "minitrack":
        from config import load_settings
        from plot_trackers import render_mini_track_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_mini_track_bitmap(
            survey, location, status, cargo, game=gs, force_show=force_show
        )
    if panel_id == "massacre":
        from config import load_settings
        from plot_massacre import render_massacre_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_massacre_bitmap(
            survey, status=status, game=gs, force_show=force_show
        )
    if panel_id == "floatie":
        from config import load_settings
        from plot_floatie import render_floatie_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_floatie_bitmap(game=gs, force_show=force_show)
    if panel_id == "footcombat":
        from config import load_settings
        from plot_foot_combat import render_foot_combat_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_foot_combat_bitmap(
            survey, status=status, game=gs, force_show=force_show
        )
    if panel_id == "grounded":
        from config import load_settings
        from plot_grounded import render_grounded_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_grounded_bitmap(
            survey, location, status, game=gs, force_show=force_show
        )
    if panel_id == "adjustvr":
        from config import load_settings
        from plot_adjust_vr import render_adjust_vr_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_adjust_vr_bitmap(game=gs, force_show=force_show)
    if panel_id == "pulse":
        from config import load_settings
        from plot_pulse import render_pulse_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_pulse_bitmap(
            status=status,
            game=gs,
            force_show=force_show,
            last_journal_write_monotonic=last_journal_write_monotonic,
        )
    if panel_id == "questmini":
        from config import load_settings
        from plot_quest_mini import load_local_quests, render_quest_mini_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        quests = quest_rows if quest_rows is not None else load_local_quests()
        return render_quest_mini_bitmap(
            status=status,
            game=gs,
            force_show=force_show,
            active_quest_count=len(quests),
            quests=quests,
        )
    if panel_id == "spherical":
        from config import load_settings
        from plot_spherical_search import render_spherical_search_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_spherical_search_bitmap(
            survey,
            status=status,
            nav_route=nav_route,
            game=gs,
            force_show=force_show,
        )
    if panel_id == "station":
        from config import load_settings
        from plot_station_info import render_station_info_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        return render_station_info_bitmap(
            survey, status=status, game=gs, force_show=force_show
        )
    if panel_id == "colonisation":
        from colony import BuildListModel, cargo_counts, latest_depot_from_file, latest_depot_from_folder
        from config import load_settings
        from panel_build import build_commodities_allowed, render_build_commodities_bitmap

        gs = game_settings if game_settings is not None else load_settings().game
        title = "Primary port"
        depot = None
        if journal_folder is not None:
            depot = latest_depot_from_folder(journal_folder, title=title)
        elif journal_path is not None and journal_path.is_file():
            depot = latest_depot_from_file(journal_path, title=title)
        has_projects = bool(
            depot is not None and not depot.complete and depot.sum_remaining
        )
        if not build_commodities_allowed(
            gs,
            status,
            survey,
            force_show=force_show,
            has_projects=has_projects,
        ):
            return None
        header = "Colonisation"
        if depot is not None:
            header = depot.title

        fc_cargo: dict[str, int] = {}
        fc_count = 0
        cmdr = (location.commander or "").strip()
        if gs.buildProjectsShowSumFC_TEST and cmdr:
            try:
                fc_cargo, fc_count = _cached_fc_cargo(cmdr, gs.buildProjectsUrl_TEST)
            except Exception:
                fc_cargo, fc_count = {}, 0
            try:
                from paths import ensure_data_dir, srvsurvey_data_dir

                ensure_data_dir()
                summary_path = srvsurvey_data_dir() / "fc-cargo-summary.txt"
                json_path = srvsurvey_data_dir() / "fc-cargo.json"
                if fc_count > 0:
                    lines = [
                        f"Commander {cmdr}: {fc_count} linked FC(s), "
                        f"{len(fc_cargo)} cargo line(s)."
                    ]
                    for name, qty in sorted(fc_cargo.items())[:40]:
                        lines.append(f"  {name}: {qty}")
                    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    import json as _json

                    json_path.write_text(
                        _json.dumps(
                            {
                                "summary": lines[0],
                                "fcCount": fc_count,
                                "cargo": fc_cargo,
                                "commander": cmdr,
                            },
                            indent=2,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
            except Exception:
                pass
            if fc_count > 0 and depot is not None and not depot.complete:
                header = depot.title

        model = BuildListModel(
            header=header,
            depot=depot,
            ship_cargo=cargo_counts(cargo),
            fc_cargo=fc_cargo,
            fc_count=fc_count,
            cargo_capacity=int(getattr(survey, "cargo_capacity", 0) or 0),
            build_id=None,
            sort_alpha=bool(status is not None and status.docked),
            warning=None,
            pending_updates=0,
        )
        try:
            from raven_colonial import pending_count

            model.pending_updates = int(pending_count())
        except Exception:
            model.pending_updates = 0
        return render_build_commodities_bitmap(
            model,
            show_fc=bool(gs.buildProjectsShowSumFC_TEST),
            show_fc_delta=bool(gs.buildProjectsShowSumFCDelta_TEST),
            collapse_when_fc_enough=(
                bool(gs.buildProjectsCollapseGroupsWithFCEnough_TEST)
                if colony_collapse is None
                else bool(colony_collapse)
            ),
            inline_fc=bool(gs.buildProjectsInlineSumFC_TEST),
            highlight_almost_fc=bool(gs.buildProjectsHighlightAlmostFC_TEST),
            game=gs,
        )
    if panel_id == "route":
        return render_route_bitmap(
            survey, status, nav_route, scale=scale, font_size=font_size
        )
    if panel_id == "ship":
        return render_ship_bitmap(
            survey, status, cargo, scale=scale, font_size=font_size
        )
    if panel_id == "materials":
        return render_materials_bitmap(survey, scale=scale, font_size=font_size)
    if panel_id == "locker":
        return render_locker_bitmap(locker, scale=scale, font_size=font_size)
    return None


def _append_vertical_stripe(panels: list[Panel], game: Rect, status: StatusSnapshot | None, gs: GameSettings, cmdr: object) -> None:
    """PlotVerticalStripe: its own centered window, not a plotters.json anchor."""
    if cmdr is None or game.width < 40 or game.height < 40:
        return
    try:
        guardian = cmdr.guardian  # type: ignore[attr-defined]
        from plot_vertical_stripe import render_vertical_stripe

        rendered = render_vertical_stripe(
            mode=str(getattr(guardian, "mode", "") or ""),
            site_type=getattr(guardian, "site_type", None),
            game_width=game.width,
            game_height=game.height,
            altitude=None if status is None else status.altitude,
            heading=None if status is None else status.heading,
            landed=bool(status is not None and status.landed),
            in_srv=bool(status is not None and status.in_srv),
            on_foot=bool(status is not None and status.on_foot),
            disable_ruins_grid=bool(gs.disableRuinsMeasurementGrid),
            disable_aerial_grid=bool(gs.disableAerialAlignmentGrid),
            aerial_alpha=float(gs.aerialAltAlpha),
            aerial_beta=float(gs.aerialAltBeta),
            aerial_gamma=float(gs.aerialAltGamma),
        )
    except Exception:
        return
    if rendered is None:
        return
    rgba, width, height = rendered
    panels.append(Panel(max(0, (game.width // 2) - (width // 2)), 0, width, height, rgba))


def build_present_panels(
    location: CommanderLocation,
    game: Rect,
    *,
    survey: SurveyState | None = None,
    status: StatusSnapshot | None = None,
    cargo: CargoSnapshot | None = None,
    locker: ShipLockerSnapshot | None = None,
    nav_route: NavRouteSnapshot | None = None,
    settings: AppSettings | None = None,
    margin: int | None = None,
    scale: int | None = None,
    journal_path: Path | None = None,
    journal_folder: Path | None = None,
    force_show: ForceShowState | None = None,
    last_journal_write_monotonic: float | None = None,
    quest_rows: list | None = None,
    location_fallback: bool = True,
) -> list[Panel]:
    """Build one window per Windows plotter, anchored from plotters.json.

    Location, Survey, Bio, Signals, Route, and Ship are not Windows plotters.
    They are not combined into a second box beside the build list.
    """
    cfg = settings if settings is not None else AppSettings()
    survey_state = survey if survey is not None else SurveyState(system=location.system)
    cmdr = commander_for_location(location)
    if cmdr is not None:
        try:
            from cmdr_state import apply_cmdr_to_survey

            survey_state = apply_cmdr_to_survey(survey_state, cmdr)
        except Exception:
            pass
    use_margin = cfg.margin if margin is None else margin
    use_scale = cfg.panel_scale if scale is None else scale
    set_hud_font_size(cfg.font_size)
    forces = force_show if force_show is not None else ForceShowState()

    panels: list[Panel] = []
    ox = int(getattr(cfg, "panel_offset_x", 0) or 0)
    oy = int(getattr(cfg, "panel_offset_y", 0) or 0)

    def _want(panel_id: str) -> bool:
        if forces.is_forced(panel_id):
            return True
        return cfg.panel_enabled(panel_id)

    from plot_pos import LINUX_ONLY_PANELS, PLOT_NAME, plotter_origin, trackers_origin

    suppress_others = (
        _want("colonisation")
        and cfg.game.buildProjectsSuppressOtherOverlays
    )
    _suppress_exempt = frozenset(
        {"galmap", "minitrack", "floatie", "pulse", "questmini", "spherical", "adjustvr"}
    )

    placed_index: dict[str, int] = {}

    def _place(panel_id: str, rgba: bytes, width: int, height: int) -> None:
        name = PLOT_NAME.get(panel_id, "")
        if panel_id == "trackers":
            origin = trackers_origin(width, height, game.width, game.height)
        else:
            origin = plotter_origin(name, width, height, game.width, game.height)
        if origin is None:
            x = top_right_inset(game.width, width, use_margin) + ox
            y = use_margin + oy
        else:
            x, y = origin
            x += ox
            y += oy
        from plot_pos import plotter_opacity, scale_rgba_alpha

        custom = plotter_opacity(name) if name else None
        if custom is not None:
            factor = custom
        else:
            raw = float(getattr(cfg.game, "plotterOpacity", 50.0) or 50.0)
            factor = max(0.0, min(1.0, raw / 100.0))
        if factor <= 0:
            return
        if factor < 0.999:
            rgba = scale_rgba_alpha(rgba, factor)
        panels.append(Panel(max(0, x), max(0, y), width, height, rgba))
        placed_index[panel_id] = len(panels) - 1

    for panel_id in PANEL_ORDER:
        if panel_id in LINUX_ONLY_PANELS and not forces.is_forced(panel_id):
            continue
        forced = forces.is_forced(panel_id)
        if suppress_others and panel_id not in _suppress_exempt and panel_id != "colonisation" and not forced:
            continue
        if not _want(panel_id):
            continue
        rendered = _render_named_panel(
            panel_id,
            location,
            survey_state,
            status,
            cargo,
            locker,
            nav_route,
            scale=use_scale,
            font_size=cfg.font_size,
            journal_path=journal_path,
            journal_folder=journal_folder,
            game_settings=cfg.game,
            force_show=forced or panel_id == "colonisation" and forces.is_forced("colonisation"),
            colony_collapse=forces.colony_collapse_effective(
                bool(cfg.game.buildProjectsCollapseGroupsWithFCEnough_TEST)
            )
            if panel_id == "colonisation"
            else None,
            cmdr=cmdr,
            last_journal_write_monotonic=last_journal_write_monotonic,
            quest_rows=quest_rows,
        )
        if rendered is None:
            continue
        rgba, width, height = rendered
        _place(panel_id, rgba, width, height)

    tracker_i = placed_index.get("trackers")
    grounded_i = placed_index.get("grounded")
    if tracker_i is not None and grounded_i is not None:
        ground = panels[grounded_i]
        track = panels[tracker_i]
        panels[tracker_i] = Panel(
            ground.x,
            ground.y + ground.height + 4,
            track.width,
            track.height,
            track.rgba,
        )

    if not panels and location_fallback:
        rgba, width, height = render_status_bitmap(
            location, scale=use_scale, font_size=cfg.font_size
        )
        _place("location", rgba, width, height)
    _append_vertical_stripe(panels, game, status, cfg.game, cmdr)
    return panels


def format_plan(
    result: dict,
    data_dir: Path,
    journal_folder: Path | None,
    *,
    panel_count: int = 1,
) -> str:
    location: CommanderLocation = result["location"]
    panel: Panel = result["panel"]
    session = result["session"][0]
    gamescope = result["gamescope"][0]
    lines = [
        f"data: {data_dir}",
        f"journal: {journal_folder if journal_folder else 'not found'}",
        f"commander: {location.commander or '-'}",
        f"system: {location.system or '-'}",
        f"body: {location.body or '-'}",
        f"panels: {panel_count}",
        f"panel: {panel.width}x{panel.height} at ({panel.x},{panel.y}) inside the game window",
        f"session window: {session.window.width}x{session.window.height} "
        f"at ({session.window.x},{session.window.y}) click-through={session.click_through}",
        f"gamescope window: {gamescope.window.width}x{gamescope.window.height} "
        f"at ({gamescope.window.x},{gamescope.window.y})",
        "present: suppressed",
    ]
    return "\n".join(lines)


def load_location(journal_folder: Path | None) -> CommanderLocation:
    snapshot = load_hud(journal_folder)
    return snapshot.location


def load_hud(journal_folder: Path | None) -> HudState:
    if journal_folder is None or not journal_folder.is_dir():
        return HudState(
            CommanderLocation(None, None, None),
            SurveyState(),
            None,
            None,
        )
    watcher = JournalWatcher(journal_folder)
    snap = watcher.poll()
    return HudState(
        snap.session.location,
        snap.session.survey,
        snap.status,
        snap.cargo,
        snap.locker,
        snap.nav_route,
    )


def process_external_uploads(
    events: tuple[dict, ...] | list[dict],
    *,
    location: CommanderLocation,
    survey: SurveyState,
    status: StatusSnapshot | None,
    game: GameSettings,
) -> None:
    """Fail-soft EDDN + GGG + Inara uploads for new journal events (never raises)."""
    if not events:
        return
    try:
        from eddn import EddnContext, process_journal_events
        from ggg import maybe_upload_from_scan
    except Exception:
        return

    body_name = None
    body_id = None
    if status is not None:
        body_name = getattr(status, "body_name", None)
        raw_body = getattr(status, "body", None)
        if isinstance(raw_body, (int, float)):
            body_id = int(raw_body)

    ctx = EddnContext(
        system_name=survey.system or location.system,
        system_address=survey.system_address,
        star_pos=survey.star_pos,
        body_name=body_name if isinstance(body_name, str) else None,
        body_id=body_id,
    )
    try:
        if game.eddnUpload:
            process_journal_events(
                events,
                eddn_upload=True,
                environment=game.eddnEnvironment,
                ctx=ctx,
            )
        else:
            process_journal_events(
                events,
                eddn_upload=False,
                environment=game.eddnEnvironment,
                ctx=ctx,
            )
    except Exception:
        pass

    try:
        from inara import is_upload_enabled, process_journal_events as inara_process

        # Windows: API-key presence is the opt-in (no gs.inaraUpload).
        if is_upload_enabled():
            station = None
            for entry in reversed(tuple(events)):
                if isinstance(entry, dict) and entry.get("event") == "Docked":
                    raw_st = entry.get("StationName")
                    if isinstance(raw_st, str):
                        station = raw_st
                    break
            ship_type = getattr(survey, "ship_type", None)
            inara_process(
                events,
                commander=location.commander,
                frontier_id=getattr(location, "fid", None),
                system_name=survey.system or location.system,
                station_name=station,
                body_name=(
                    body_name if isinstance(body_name, str) else location.body
                ),
                ship_type=ship_type if isinstance(ship_type, str) else None,
                odyssey=True,
            )
    except Exception:
        pass

    _maybe_publish_ship_cargo(events, location=location, survey=survey, game=game)

    if not game.uploadGGG:
        return
    cmdr = location.commander
    star_pos = survey.star_pos
    for entry in events:
        if not isinstance(entry, dict) or entry.get("event") != "Scan":
            continue
        try:
            maybe_upload_from_scan(
                entry,
                upload_ggg_enabled=True,
                commander=cmdr,
                star_pos=star_pos,
                svc_uri=game.buildProjectsUrl_TEST,
            )
        except Exception:
            pass


_SHIP_CARGO_EVENTS = frozenset(
    {
        "Cargo",
        "MarketBuy",
        "MarketSell",
        "CollectCargo",
        "EjectCargo",
        "CargoTransfer",
        "MiningRefined",
        "BuyDrones",
        "SellDrones",
    }
)


def _maybe_publish_ship_cargo(
    events: tuple[dict, ...] | list[dict],
    *,
    location: CommanderLocation,
    survey: SurveyState,
    game: GameSettings,
) -> None:
    """POST current ship cargo when Windows ColonyData.publishCurrentShip would."""
    if not game.buildProjects_TEST or not game.buildProjectsTrackShipCargo:
        return
    if not any(
        isinstance(entry, dict) and entry.get("event") in _SHIP_CARGO_EVENTS
        for entry in events
    ):
        return
    cmdr = (location.commander or "").strip()
    fid = (location.fid or "").strip()
    if not cmdr or not fid:
        return
    cargo: dict[str, int] = {}
    for entry in events:
        if not isinstance(entry, dict) or entry.get("event") != "Cargo":
            continue
        if entry.get("Vessel") not in (None, "Ship"):
            continue
        inventory = entry.get("Inventory")
        if not isinstance(inventory, list):
            continue
        cargo = {}
        for item in inventory:
            if not isinstance(item, dict):
                continue
            name = item.get("Name")
            count = item.get("Count")
            if isinstance(name, str) and isinstance(count, (int, float)):
                cargo[name] = int(count)
    try:
        from raven_colonial import publish_current_ship

        publish_current_ship(
            fid,
            {
                "cmdr": cmdr,
                "name": survey.ship or survey.ship_ident or "",
                "type": survey.ship_type or "",
                "maxCargo": int(survey.cargo_capacity or 0),
                "cargo": cargo,
            },
        )
    except Exception:
        return


def process_cmdr_chat_events(
    events: tuple[dict, ...] | list[dict],
    *,
    location: CommanderLocation,
    survey: SurveyState,
    status: StatusSnapshot | None,
) -> object | None:
    """Fail-soft SendText / Ram Tah mission → cmdr_state + chat_commands.

    Uses ``process_cmdr_events`` so Guardian ``.add`` / ``.map`` / zoom and
    mission Active flags share one path. Returns live CmdrState (or None).
    """
    try:
        from chat_commands import process_cmdr_events
        from cmdr_state import load_cmdr
    except Exception:
        return None

    cmdr_name = (location.commander or "").strip() or None
    fid = getattr(location, "fid", None)
    if isinstance(fid, str):
        fid = fid.strip() or None
    else:
        fid = None
    if not cmdr_name and not fid:
        return None

    try:
        cmdr = load_cmdr(fid or cmdr_name or "unknown", fid=fid)
        if cmdr_name:
            cmdr.commander = cmdr_name
    except Exception:
        return None

    try:
        from cmdr_state import guardian_site_key

        site_key = guardian_site_key(survey.current_guardian_site)
        if site_key:
            cmdr.active_guardian_site = site_key
    except Exception:
        pass

    try:
        from plot_floatie import show_message

        process_cmdr_events(
            cmdr,
            [e for e in (events or ()) if isinstance(e, dict)],
            status=status,
            survey=survey,
            persist=True,
            on_floatie=show_message,
        )
    except Exception:
        pass
    return cmdr


def commander_for_location(location: CommanderLocation):
    """Load cached commander state for panel rendering (no event processing)."""
    try:
        from cmdr_state import load_cmdr
    except Exception:
        return None
    cmdr_name = (location.commander or "").strip() or None
    fid = getattr(location, "fid", None)
    if isinstance(fid, str):
        fid = fid.strip() or None
    else:
        fid = None
    if not cmdr_name and not fid:
        return None
    try:
        cmdr = load_cmdr(fid or cmdr_name or "unknown", fid=fid)
        if cmdr_name:
            cmdr.commander = cmdr_name
        return cmdr
    except Exception:
        return None


def _prefetch_canonn(location: CommanderLocation, game: GameSettings) -> None:
    """Warm Canonn SystemPoi. PlotSysStatus.allowed treats a cached POI as honked."""
    if not game.useExternalData:
        return
    system = (location.system or "").strip()
    if not system:
        return
    try:
        from canonn import get_system_poi, peek_cached_poi

        if peek_cached_poi(system, location.commander or "") is not None:
            return
        get_system_poi(system, location.commander or "")
    except Exception:
        return


def _hold_message(hold_seconds: float) -> str:
    if hold_seconds <= 0:
        return "hold until Ctrl-C"
    return f"hold {hold_seconds:.0f}s or Ctrl-C"


def present_status_panel(
    journal_folder: Path | None,
    game: Rect,
    display_name: str,
    hold_seconds: float = PRESENT_HOLD_SECONDS,
    poll_seconds: float = PRESENT_POLL_SECONDS,
    data_dir: Path | None = None,
    settings: AppSettings | None = None,
    mode: PresenterMode | None = None,
) -> None:
    """Map HUD panels, poll for Elite move/resize and journal changes, then close.

    hold_seconds <= 0 means run until Ctrl-C. Timeout and Ctrl-C both exit
    through presenter.close(). Hotkey / SIGUSR1 hide panels while watching.
    """
    cfg = settings if settings is not None else load_settings()
    set_hud_font_size(cfg.font_size)
    poll = poll_seconds if poll_seconds != PRESENT_POLL_SECONDS else cfg.poll_seconds
    hold = hold_seconds if hold_seconds != PRESENT_HOLD_SECONDS else cfg.hold_seconds

    watcher = JournalWatcher(journal_folder)
    snap = watcher.poll()
    journal_path = snap.journal_path
    hud = HudState(
        snap.session.location,
        snap.session.survey,
        snap.status,
        snap.cargo,
        snap.locker,
        snap.nav_route,
    )
    force_show = ForceShowState()
    last_journal_write_monotonic = snap.last_journal_write_monotonic
    from quests import apply_journal_events, load_quests, save_quests

    quest_list = load_quests()
    quest_rows = quest_list.active_rows()
    _prefetch_canonn(hud.location, cfg.game)
    panels = build_present_panels(
        hud.location,
        game,
        survey=hud.survey,
        status=hud.status,
        cargo=hud.cargo,
        locker=hud.locker,
        nav_route=hud.nav_route,
        settings=cfg,
        journal_path=journal_path,
        journal_folder=journal_folder,
        force_show=force_show,
        last_journal_write_monotonic=last_journal_write_monotonic,
        quest_rows=quest_rows,
        location_fallback=False,
    )
    def _vehicle_label(status: StatusSnapshot | None) -> str | None:
        if status is None:
            return None
        if status.on_foot:
            return "OnFoot"
        if status.in_srv:
            return "SRV"
        if status.in_fighter:
            return "Fighter"
        if status.in_taxi:
            return "Taxi"
        if status.in_main_ship:
            return "MainShip"
        return status.mode_label()

    def _write_main_state(
        *,
        journal_path: Path | None,
        location: CommanderLocation | None = None,
        status: StatusSnapshot | None = None,
        host_pid: int | None = None,
        present_active: bool | None = None,
        overlay_visible: bool | None = None,
    ) -> None:
        if data_dir is None:
            return
        loc = location or hud.location
        st = status if status is not None else hud.status
        write_runtime_state(
            data_dir,
            journal_folder=journal_folder,
            journal_file=journal_path,
            host_pid=host_pid,
            present_active=present_active,
            commander=loc.commander if loc else None,
            system=loc.system if loc else None,
            body=loc.body if loc else None,
            mode=st.mode_label() if st is not None else None,
            vehicle=_vehicle_label(st),
            overlay_visible=overlay_visible,
        )

    _write_main_state(
        journal_path=snap.journal_path,
        host_pid=os.getpid(),
        present_active=True,
        overlay_visible=cfg.overlay_visible,
    )
    presenter_mode = mode if mode is not None else PresenterMode.SESSION_X11
    pass_clicks = bool(getattr(cfg.game, "hideOverlaysFromMouse", True))
    print(
        f"presenter mode={presenter_mode.value} display={display_name} "
        f"click_through={pass_clicks}",
        flush=True,
    )
    presenter = OverlayPresenter(presenter_mode, display_name)

    def _persist_visibility(state: bool) -> None:
        updated = cfg.with_updates(overlay_visible=state)
        try:
            save_settings(updated)
        except OSError as exc:
            print(f"could not save overlay_visible: {exc}", flush=True)
        _write_main_state(
            journal_path=journal_path,
            host_pid=os.getpid(),
            present_active=True,
            overlay_visible=state,
        )

    def _open_settings() -> None:
        import subprocess

        from settings_lock import settings_is_open

        if settings_is_open():
            print("settings already open; close that window first", flush=True)
            return
        root = Path(__file__).resolve().parent.parent
        subprocess.Popen(
            [sys.executable, str(root / "srvsurvey-linux"), "--settings"],
            start_new_session=True,
        )

    quit_flag = {"stop": False}
    wake = threading.Event()
    hotkey_ref: dict[str, HotkeyToggle | None] = {"hk": None}

    def _request_quit() -> None:
        quit_flag["stop"] = True
        wake.set()

    def _on_term(_signum: int, _frame: object) -> None:
        _request_quit()

    signal.signal(signal.SIGTERM, _on_term)

    def _toggle_image_embed() -> None:
        from dataclasses import replace

        flipped = not bool(cfg.game.addBannerToScreenshots)
        cfg.game = replace(cfg.game, addBannerToScreenshots=flipped)
        try:
            save_settings(cfg)
        except OSError as exc:
            print(f"could not save addBannerToScreenshots: {exc}", flush=True)
        msg = (
            "Adding embedded banner to future screenshots"
            if flipped
            else "Future screenshots will have no embedded banner"
        )
        print(f"chord toggleImageEmbed: {msg}", flush=True)
        try:
            from plot_floatie import show_message

            show_message(msg)
        except Exception:  # noqa: BLE001
            pass
        force_show.mark_dirty()

    def _refresh_colony() -> None:
        try:
            from raven_colonial import clear_cache

            clear_cache()
        except Exception:  # noqa: BLE001
            pass
        force_show.mark_dirty()
        print("chord refreshColonyData: cache cleared", flush=True)

    def _copy_next_boxel() -> bool:
        from boxel_search import copy_next_boxel_system

        gui = hud.status.gui_focus if hud.status is not None else None
        ok = copy_next_boxel_system(cfg.game, gui_focus=gui)
        nxt = (cfg.game.boxelSearchNextSystem or "").strip() or "(empty)"
        print(
            f"chord copyNextBoxel: {'copied ' + nxt if ok else 'skipped (' + nxt + ')'}",
            flush=True,
        )
        if ok:
            force_show.mark_dirty()
        return ok

    def _adjust_vr() -> None:
        from dataclasses import replace

        cfg.game = replace(cfg.game, displayVR=True)
        cfg.panels["adjustvr"] = True
        try:
            save_settings(cfg)
        except OSError as exc:
            print(f"could not save displayVR: {exc}", flush=True)
        print("chord adjustVR: displayVR on + adjustvr panel", flush=True)

    def _vr_nudge_opacity(delta: float) -> None:
        from plot_adjust_vr import nudge_plotter_opacity

        cfg.game = nudge_plotter_opacity(cfg.game, delta)
        try:
            save_settings(cfg)
        except OSError as exc:
            print(f"could not save plotterOpacity: {exc}", flush=True)
        print(
            f"VR opacity → {int(cfg.game.plotterOpacity)}%",
            flush=True,
        )

    def _vr_nudge_scale(delta: float) -> None:
        from plot_adjust_vr import nudge_plotter_scale

        cfg.game = nudge_plotter_scale(cfg.game, delta)
        try:
            save_settings(cfg)
        except OSError as exc:
            print(f"could not save plotterScale: {exc}", flush=True)
        print(f"VR scale nudge → {cfg.game.plotterScale:+.0f}", flush=True)

    def _map_zoom(action: str) -> None:
        from key_chords import MAP_ZOOM_AUTO, MAP_ZOOM_IN, MAP_ZOOM_OUT
        from plot_guardians import adjust_guardian_zoom

        cmdr = commander_for_location(hud.location)
        if cmdr is None:
            return
        if action == MAP_ZOOM_IN:
            z = adjust_guardian_zoom(cmdr, zoom_in=True)
        elif action == MAP_ZOOM_OUT:
            z = adjust_guardian_zoom(cmdr, zoom_in=False)
        elif action == MAP_ZOOM_AUTO:
            z = adjust_guardian_zoom(cmdr, absolute=1.0)
        else:
            return
        print(f"guardian zoom → {z:.2f}", flush=True)

    def _on_action_chord(chord_label: str) -> None:
        action = find_action_for_chord(chord_label, cfg.key_actions)
        if action is None:
            return
        hk = hotkey_ref["hk"]

        def _overlay_toggle() -> None:
            if hk is not None:
                hk.toggle()

        do_key_action(
            action,
            force_show=force_show,
            on_toggle_overlay=_overlay_toggle,
            on_toggle_image_embed=_toggle_image_embed,
            on_refresh_colony=_refresh_colony,
            on_copy_next_boxel=_copy_next_boxel,
            on_adjust_vr=_adjust_vr,
            on_vr_nudge_opacity=_vr_nudge_opacity,
            on_vr_nudge_scale=_vr_nudge_scale,
            on_map_zoom=_map_zoom,
        )
        print(f"chord:{chord_label} => {action}", flush=True)
        if hk is not None:
            hk.request_refresh()
        wake.set()

    action_bindings: list[tuple[str, object]] = []
    if cfg.game.keyhook_TEST:
        for action, chord in cfg.key_actions.items():
            if action not in LINUX_SUPPORTED_ACTIONS:
                continue
            if not (chord or "").strip():
                continue
            action_bindings.append((chord, _on_action_chord))

    hotkey = HotkeyToggle(
        cfg.hotkey,
        display_name=display_name,
        game_x=game.x,
        game_y=game.y,
        game_w=game.width,
        game_h=game.height,
        initially_visible=cfg.overlay_visible,
        on_visibility_saved=_persist_visibility,
        on_open_settings=_open_settings,
        on_toggle=lambda: wake.set(),
        action_bindings=action_bindings if action_bindings else None,
    )
    hotkey_ref["hk"] = hotkey
    backend = hotkey.start()
    if cfg.game.keyhook_TEST:
        print(
            f"key chords enabled ({len(action_bindings)} Linux-supported binding(s))",
            flush=True,
        )
    tray = None
    try:
        from tray import TrayController

        tray = TrayController(
            on_toggle=lambda: (hotkey.toggle(), wake.set()),
            on_settings=_open_settings,
            on_quit=_request_quit,
        )
        if tray.start():
            print("tray: available", flush=True)
        else:
            tray = None
            print("tray: unavailable (optional)", flush=True)
    except Exception as exc:  # noqa: BLE001
        tray = None
        print(f"tray: unavailable ({exc})", flush=True)
    if not panels:
        print(
            "presenting 0 panel(s); docked station has no Windows plotter, "
            "so no override-redirect window is left on the game; "
            f"poll every {poll:.2f}s; "
            f"toggle via {backend} (HUD chip is inside the bottom-right of Elite, "
            f"off the plotters.json anchors; right-click opens settings); "
            f"hotkey={cfg.hotkey}; start_visible={cfg.overlay_visible}; {_hold_message(hold)}",
            flush=True,
        )
    else:
        first = panels[0]
        screen_x = game.x + first.x
        screen_y = game.y + first.y
        print(
            f"presenting {len(panels)} panel(s); primary {first.width}x{first.height} "
            f"at game-local ({first.x},{first.y}) screen ({screen_x},{screen_y}) "
            f"on elite {game.width}x{game.height} @({game.x},{game.y}); "
            f"poll every {poll:.2f}s; "
            f"toggle via {backend} (HUD chip is inside the bottom-right of Elite, "
            f"off the plotters.json anchors; right-click opens settings); "
            f"hotkey={cfg.hotkey}; start_visible={cfg.overlay_visible}; {_hold_message(hold)}",
            flush=True,
        )
    deadline = None if hold <= 0 else time.monotonic() + hold
    visible = hotkey.visible
    screenshot_watch = ScreenshotFolderWatcher()
    elite_watch = EliteWindowWatch(display_name)
    print(
        "elite window cached; idle polls read that window only "
        "(no root-tree walk, no present unless a plotter changes)",
        flush=True,
    )
    try:
        if visible:
            presenter.present(game, panels, pass_clicks=pass_clicks)
        else:
            print("starting hidden (overlay_visible=false); click chip to show", flush=True)
        # Chip must sit above HUD panels so real pointer hits land on it.
        hotkey.reassert_chip()
        missing_game = 0
        parked = False
        while True:
            if quit_flag["stop"]:
                print("quit requested; closing overlay", flush=True)
                break
            try:
                from paths import srvsurvey_data_dir

                quit_path = srvsurvey_data_dir() / "request-quit"
                if quit_path.is_file():
                    try:
                        quit_path.unlink()
                    except OSError:
                        pass
                    print(".kill / request-quit; closing overlay", flush=True)
                    break
            except Exception:
                pass
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                # Wake on chip/hotkey/SIGUSR1/tray immediately (not after a full poll).
                hotkey.wait_changed(min(poll, remaining))
                wake.wait(0)
                wake.clear()
            else:
                hotkey.wait_changed(poll)
                wake.wait(0)
                wake.clear()

            # Thread-safe flag from chip / GrabKey / SIGUSR1; keep panels
            # unmapped while hidden (do not remount on journal ticks).
            want = hotkey.visible
            if want != visible:
                visible = want
                if visible:
                    # Remount with latest bitmaps after a hide period.
                    panels = build_present_panels(
                        hud.location,
                        game,
                        survey=hud.survey,
                        status=hud.status,
                        cargo=hud.cargo,
                        locker=hud.locker,
                        nav_route=hud.nav_route,
                        settings=cfg,
                        journal_path=journal_path,
                        journal_folder=journal_folder,
                        force_show=force_show,
                        last_journal_write_monotonic=last_journal_write_monotonic,
                        quest_rows=quest_rows,
                        location_fallback=False,
                    )
                    presenter.present(game, panels, pass_clicks=pass_clicks)
                    print("overlay panels shown", flush=True)
                else:
                    presenter.hide()
                    print("overlay panels hidden", flush=True)
                hotkey.reassert_chip()

            # Key-chord force-show / collapse / refresh — rebuild panels in place.
            if visible and force_show.consume_dirty():
                panels = build_present_panels(
                    hud.location,
                    game,
                    survey=hud.survey,
                    status=hud.status,
                    cargo=hud.cargo,
                    locker=hud.locker,
                    nav_route=hud.nav_route,
                    settings=cfg,
                    journal_path=journal_path,
                    journal_folder=journal_folder,
                    force_show=force_show,
                    last_journal_write_monotonic=last_journal_write_monotonic,
                    quest_rows=quest_rows,
                    location_fallback=False,
                )
                presenter.present(game, panels, pass_clicks=pass_clicks)
                hotkey.reassert_chip()

            elite = elite_watch.poll()
            if elite is None or not game_rect_usable(elite):
                missing_game += 1
                try:
                    screenshot_watch.poll(
                        cfg.game,
                        context_from_location_status(hud.location, hud.status),
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"screenshot poll: {exc}", flush=True)
                if (
                    visible
                    and not parked
                    and should_park_overlays(missing_game)
                ):
                    presenter.hide()
                    parked = True
                    print("elite window gone; overlays parked", flush=True)
                continue
            missing_game = 0
            unpark = False
            if parked and visible:
                parked = False
                unpark = True
                print("elite window back; remounting overlays", flush=True)
            snap = watcher.poll()
            if snap.last_journal_write_monotonic is not None:
                last_journal_write_monotonic = snap.last_journal_write_monotonic
            if snap.new_events:
                process_external_uploads(
                    snap.new_events,
                    location=snap.session.location,
                    survey=snap.session.survey,
                    status=snap.status,
                    game=cfg.game,
                )
                process_cmdr_chat_events(
                    snap.new_events,
                    location=snap.session.location,
                    survey=snap.session.survey,
                    status=snap.status,
                )
                if cfg.game.enableQuests:
                    if apply_journal_events(quest_list, snap.new_events):
                        try:
                            save_quests(quest_list)
                        except OSError as exc:
                            print(f"could not save quests: {exc}", flush=True)
                        quest_rows = quest_list.active_rows()
                        force_show.mark_dirty()
                    try:
                        from quests import process_live_journal_events

                        process_live_journal_events(
                            snap.new_events,
                            journal_folder=getattr(watcher, "journal_folder", None),
                            status=snap.status,
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(f"quest script: {exc}", file=sys.stderr)
            next_hud = HudState(
                snap.session.location,
                snap.session.survey,
                snap.status,
                snap.cargo,
                snap.locker,
                snap.nav_route,
            )
            try:
                screenshot_watch.poll(
                    cfg.game,
                    context_from_location_status(
                        next_hud.location,
                        next_hud.status,
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                print(f"screenshot poll: {exc}", flush=True)
            tick = present_tick(game, elite, hud, next_hud)
            # Do not rebuild or restack on the pulse shimmer. A raise on every
            # poll keeps Mutter compositing the game and drops the frame rate.
            if tick.needs_present or unpark:
                if tick.reposition:
                    print(
                        f"elite moved/resized → {elite.width}x{elite.height} "
                        f"@({elite.x},{elite.y}); repositioning",
                        flush=True,
                    )
                if tick.repaint and did_location_change(hud.location, next_hud.location):
                    print(
                        f"hud refresh → "
                        f"cmdr={next_hud.location.commander or '-'} "
                        f"system={next_hud.location.system or '-'} "
                        f"body={next_hud.location.body or '-'} "
                        f"fss={next_hud.survey.fss_progress!r} "
                        f"cargo={next_hud.cargo.count if next_hud.cargo else '-'}",
                        flush=True,
                    )
                _prefetch_canonn(next_hud.location, cfg.game)
                game = elite
                hud = next_hud
                journal_path = snap.journal_path
                if tick.reposition:
                    hotkey.reposition_for_game(game.x, game.y, game.width, game.height)
                if visible:
                    panels = build_present_panels(
                        hud.location,
                        game,
                        survey=hud.survey,
                        status=hud.status,
                        cargo=hud.cargo,
                        locker=hud.locker,
                        nav_route=hud.nav_route,
                        settings=cfg,
                        journal_path=journal_path,
                        journal_folder=journal_folder,
                        force_show=force_show,
                        last_journal_write_monotonic=last_journal_write_monotonic,
                        quest_rows=quest_rows,
                        location_fallback=False,
                    )
                    presenter.present(
                        game,
                        panels,
                        raise_windows=tick.reposition,
                        pass_clicks=pass_clicks,
                    )
                if tick.reposition:
                    hotkey.reassert_chip()
                if data_dir is not None:
                    _write_main_state(
                        journal_path=snap.journal_path,
                        location=hud.location,
                        status=hud.status,
                        host_pid=os.getpid(),
                        present_active=True,
                        overlay_visible=hotkey.visible,
                    )
            # Idle polls do not restack. Override-redirect windows stay above
            # the game without a ConfigureWindow on every tick.
    except KeyboardInterrupt:
        print("interrupted; closing overlay", flush=True)
    finally:
        if tray is not None:
            tray.stop()
        hotkey.stop()
        elite_watch.close()
        presenter.close()
        _write_main_state(
            journal_path=journal_path,
            host_pid=0,
            present_active=False,
            overlay_visible=False,
        )
    print("present closed", flush=True)


def _start_published_data_refresh(data_dir: Path) -> None:
    """Git.refreshPublishedData. Background so the HUD is not blocked on GitHub."""

    def run() -> None:
        try:
            from pub_data import refresh_published_data

            refresh_published_data(data_dir=data_dir)
        except Exception:
            return

    threading.Thread(target=run, name="srvsurvey-pub-data", daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Headless SrvSurvey journal HUD (Linux port slice)",
    )
    parser.add_argument("--vdf", type=Path, default=None, help="libraryfolders.vdf to read")
    parser.add_argument(
        "--present",
        action="store_true",
        help=(
            "map overlay panels on the current display "
            "(requires --allow-present, SRVSURVEY_ALLOW_PRESENT=1, or config opt-in)"
        ),
    )
    parser.add_argument(
        "--allow-present",
        action="store_true",
        help="explicit one-shot opt-in to map overlays (same as config allow_present)",
    )
    parser.add_argument(
        "--hold",
        type=float,
        default=None,
        help=(
            "seconds to keep --present up; 0 means until Ctrl-C. "
            "Default comes from config (0). Timeout and Ctrl-C both close overlays."
        ),
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="long-running path: ensure XDG data dir, watch journals, present if gated",
    )
    parser.add_argument(
        "--settings",
        action="store_true",
        help="open the GTK settings window and exit",
    )
    args = parser.parse_args(argv)

    if args.settings:
        from settings_ui import run_settings_ui

        return run_settings_ui()

    settings = load_settings()
    hold = PRESENT_HOLD_SECONDS if args.hold is None else args.hold

    gated = present_is_allowed(cli_allow=args.allow_present)
    if args.present and not gated:
        print(refuse_present_message(), file=sys.stderr)
        return 2

    want_present = args.present or (args.watch and gated)
    if args.watch and not want_present and not args.present:
        pass

    if want_present:
        print("present gate ok; locating journal and Elite window…", flush=True)

    data_dir, journal_folder, _vdf = discover(vdf_path=args.vdf)
    data_dir = ensure_data_dir(data_dir)
    journal_file = latest_journal_file(journal_folder) if journal_folder else None
    write_runtime_state(data_dir, journal_folder=journal_folder, journal_file=journal_file)
    _start_published_data_refresh(data_dir)

    if want_present:
        print(
            f"journal: {journal_folder if journal_folder else 'not found'}; reading location…",
            flush=True,
        )
    hud = load_hud(journal_folder)
    location = hud.location

    if want_present:
        ensure_session_display()
        detected = detect_display()
        if detected.name:
            os.environ["DISPLAY"] = detected.name
        print(
            f"display={os.environ.get('DISPLAY')} "
            f"xauthority={os.environ.get('XAUTHORITY', '(none)')} "
            f"mode={detected.mode.value} ({detected.reason})",
            flush=True,
        )
        if detected.mode == PresenterMode.DESKTOP_FALLBACK:
            print(
                f"Elite overlay display not reachable: {detected.reason}",
                file=sys.stderr,
            )
            return 1
        elite = find_elite_window(detected.name or None)
        if elite is not None and not game_rect_usable(elite):
            elite = None
        if elite is None:
            print(
                f"Elite window not found on display {detected.name or os.environ.get('DISPLAY')}.",
                file=sys.stderr,
            )
            return 1
        game = elite
        print(
            f"elite found {game.width}x{game.height} @({game.x},{game.y})",
            flush=True,
        )
    else:
        game = Rect(0, 0, 1920, 1080)

    if args.watch and not want_present:
        return _watch_only(journal_folder, data_dir, hold_seconds=hold)

    panels = build_present_panels(
        location,
        game,
        survey=hud.survey,
        status=hud.status,
        cargo=hud.cargo,
        locker=hud.locker,
        nav_route=hud.nav_route,
        settings=settings,
        journal_path=journal_file,
        journal_folder=journal_folder,
    )
    panel = panels[0]
    locals_rects = [Rect(p.x, p.y, p.width, p.height) for p in panels]
    result = {
        "location": location,
        "panel": panel,
        "session": layout_overlay(PresenterMode.SESSION_X11, game, locals_rects),
        "gamescope": layout_overlay(PresenterMode.GAMESCOPE, game, locals_rects),
    }
    if want_present:
        text = format_plan(
            result, data_dir, journal_folder, panel_count=len(panels)
        ).replace("present: suppressed", "present: allowed")
        print(text, flush=True)
        present_status_panel(
            journal_folder,
            game,
            detected.name or os.environ["DISPLAY"],
            hold_seconds=hold,
            poll_seconds=settings.poll_seconds,
            data_dir=data_dir,
            settings=settings,
            mode=detected.mode,
        )
        return 0

    print(format_plan(result, data_dir, journal_folder, panel_count=len(panels)))
    return 0


def _watch_only(
    journal_folder: Path | None,
    data_dir: Path,
    hold_seconds: float = 0.0,
) -> int:
    """Tail journals without mapping overlays (no present gate required)."""
    cfg = load_settings()
    watcher = JournalWatcher(journal_folder)
    screenshot_watch = ScreenshotFolderWatcher()
    snap = watcher.poll()
    write_runtime_state(
        data_dir,
        journal_folder=journal_folder,
        journal_file=snap.journal_path,
    )
    loc = snap.session.location
    print(
        f"watching journal={snap.journal_path or 'none'} "
        f"system={loc.system or '-'} cmdr={loc.commander or '-'} "
        f"data={data_dir}; {_hold_message(hold_seconds)}",
        flush=True,
    )
    deadline = None if hold_seconds <= 0 else time.monotonic() + hold_seconds
    try:
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                break
            time.sleep(PRESENT_POLL_SECONDS)
            snap = watcher.poll()
            try:
                screenshot_watch.poll(
                    cfg.game,
                    context_from_location_status(
                        snap.session.location,
                        snap.status,
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                print(f"screenshot poll: {exc}", flush=True)
            if snap.new_events:
                process_external_uploads(
                    snap.new_events,
                    location=snap.session.location,
                    survey=snap.session.survey,
                    status=snap.status,
                    game=cfg.game,
                )
                process_cmdr_chat_events(
                    snap.new_events,
                    location=snap.session.location,
                    survey=snap.session.survey,
                    status=snap.status,
                )
                for entry in snap.new_events:
                    event = entry.get("event", "?")
                    print(f"event {event}", flush=True)
                write_runtime_state(
                    data_dir,
                    journal_folder=journal_folder,
                    journal_file=snap.journal_path,
                )
    except KeyboardInterrupt:
        print("interrupted; stopping watch", flush=True)
    print("watch closed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
