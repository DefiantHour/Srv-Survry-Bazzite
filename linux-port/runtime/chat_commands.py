#!/usr/bin/env python3
"""In-game chat dot-commands — Linux port of MsgCmd.cs handlers.

Parses journal ``SendText`` (and optional local inject). Mutates
``CommanderState.guardian`` / human headings; host calls ``process_cmdr_events``.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

from cmdr_state import (
    CommanderState,
    apply_journal_events,
    guardian_site_key as site_key_from_survey,
)
from companion import StatusSnapshot
from journal import SurveyState

# MsgCmd.cs constants
CMD_AERIAL = ".aerial"
CMD_MAP = ".map"
CMD_HEADING = ".heading"
CMD_SITE = ".site"
CMD_TO = ".to"
CMD_OS = ".os"
CMD_EMPTY = ".empty"
CMD_NOTE = ".note"
CMD_ADD = ".add"
CMD_REMOVE = ".remove"
CMD_SETTLEMENT = ".settlement"
CMD_THREAT = ".threat"
CMD_TARGET_HERE = ".target here"
CMD_TARGET_ON = ".target on"
CMD_TARGET_OFF = ".target off"
CMD_VISITED = ".visited"
CMD_FIRST_FOOT = ".firstfoot"
CMD_FF = ".ff"
CMD_TOWER = ".tower"
CMD_IMGS = ".imgs"
CMD_KILL = ".kill"
CMD_SHOW = ".show"
CMD_NEW = ".new"
CMD_Z = "z"

_SITE_ALIASES = {
    "a": "Alpha",
    "alpha": "Alpha",
    "b": "Beta",
    "beta": "Beta",
    "g": "Gamma",
    "gamma": "Gamma",
}

_STRUCTURE_TYPES = frozenset(
    {
        "Bear",
        "Bowl",
        "Crossroads",
        "Fistbump",
        "Hammerbot",
        "Lacrosse",
        "Robolobster",
        "Squid",
        "Stickyhand",
        "Turtle",
        "Alpha",
        "Beta",
        "Gamma",
    }
)

_POI_TYPE_CANON = {
    "obelisk": "obelisk",
    "brokeobelisk": "brokeObelisk",
    "relic": "relic",
    "pylon": "pylon",
    "component": "component",
    "casket": "casket",
    "orb": "orb",
    "tablet": "tablet",
    "totem": "totem",
    "urn": "urn",
}
_POI_TYPES = frozenset(_POI_TYPE_CANON.keys())


def _norm_msg(text: str) -> str:
    return " ".join((text or "").strip().split())


def _canonical_site_type(token: str) -> str | None:
    raw = (token or "").strip()
    if not raw:
        return None
    low = raw.lower()
    if low in _SITE_ALIASES:
        return _SITE_ALIASES[low]
    for name in _STRUCTURE_TYPES:
        if name.lower() == low:
            return name
    titled = raw[:1].upper() + raw[1:]
    return titled if titled else None


def _current_body(
    status: StatusSnapshot | None,
    survey: SurveyState | None,
) -> str | None:
    if status is not None and status.body_name:
        return str(status.body_name)
    if survey is not None:
        for row in survey.body_signals:
            if row.body_name:
                return row.body_name
        if survey.fss_bodies:
            return survey.fss_bodies[0].body_name
    return None


def _resolve_body_name(
    hint: str | None,
    status: StatusSnapshot | None,
    survey: SurveyState | None,
) -> str | None:
    """Best-effort body match for .visited / .firstFoot (Windows heuristics)."""
    if hint:
        needle = hint.strip().lower().replace(" ", "")
        if survey is not None:
            for body in survey.fss_bodies:
                short = body.short_name or body.body_name
                cands = {
                    body.body_name.lower(),
                    body.body_name.lower().replace(" ", ""),
                    (short or "").lower(),
                    (short or "").lower().replace(" ", ""),
                }
                if needle in cands:
                    return body.body_name
                if survey.system and body.body_name.lower().startswith(
                    survey.system.lower()
                ):
                    rest = body.body_name[len(survey.system) :].strip()
                    if rest.lower().replace(" ", "") == needle:
                        return body.body_name
        return hint.strip()
    return _current_body(status, survey)


def handle_send_text(
    message: str,
    *,
    cmdr: CommanderState,
    status: StatusSnapshot | None = None,
    survey: SurveyState | None = None,
    status_heading: float | None = None,
    market_id: int | None = None,
    poi_angle: float | None = None,
    poi_dist: float | None = None,
    poi_rot: float | None = None,
    nearest_overlay: str | None = None,
    guardian_site_key: str | None = None,
    persist: bool = True,
    on_floatie: Callable[[str], None] | None = None,
    config_path: Any = None,
    config_home: Any = None,
) -> str | None:
    """Apply a chat command. Returns a short status string or None if ignored."""

    def note(msg: str) -> str:
        if on_floatie is not None:
            try:
                on_floatie(msg)
            except Exception:
                pass
        return msg

    raw = _norm_msg(message)
    if not raw:
        return None
    lower = raw.lower()
    site_key = guardian_site_key
    if site_key is None and survey is not None:
        site = survey.current_guardian_site
        site_key = site_key_from_survey(site) if site else None
    if site_key:
        cmdr.active_guardian_site = site_key
    g = cmdr.guardian_for(site_key) if hasattr(cmdr, "guardian_for") else cmdr.guardian

    hdg = status_heading
    if hdg is None and status is not None:
        hdg = status.heading

    mid = market_id
    if mid is None and survey is not None and survey.system_station is not None:
        mid = survey.system_station.market_id

    # —— Main track-target (PlotTrackTarget / gs.target*) ——
    if lower == CMD_TARGET_HERE:
        if status is None or not status.has_lat_long:
            return note("No Status lat/long for .target here")
        lat = float(status.latitude or 0.0)
        lon = float(status.longitude or 0.0)
        try:
            from config import set_ground_target

            if persist:
                set_ground_target(
                    lat, lon, active=True, path=config_path, home=config_home
                )
            return note(f"Track target {lat:.4f}, {lon:.4f}")
        except Exception as exc:  # noqa: BLE001
            return note(f"Target here failed: {exc}")

    if lower == CMD_TARGET_ON:
        try:
            from config import set_ground_target_active

            if persist:
                set_ground_target_active(True, path=config_path, home=config_home)
            return note("Track target on")
        except Exception as exc:  # noqa: BLE001
            return note(f"Target on failed: {exc}")

    if lower == CMD_TARGET_OFF:
        try:
            from config import set_ground_target_active

            if persist:
                set_ground_target_active(False, path=config_path, home=config_home)
            return note("Track target off")
        except Exception as exc:  # noqa: BLE001
            return note(f"Target off failed: {exc}")

    # —— Body bookmarks (+name / -name / =name / --name / ---) ——
    if lower == "---":
        body = _current_body(status, survey)
        if not body:
            return note("No body for bookmark clear")
        msg = cmdr.clear_all_bookmarks(body)
        if persist:
            cmdr.save()
        return note(msg)

    if lower.startswith("--") and len(lower) > 2:
        name = raw[2:].strip()
        body = _current_body(status, survey)
        if not body or not name:
            return note("Usage: --name")
        msg = cmdr.remove_bookmark_name(body, name)
        if persist:
            cmdr.save()
        return note(msg)

    if raw[:1] in "+-=" and len(raw) > 1 and not raw.startswith("."):
        op = raw[0]
        name = raw[1:].strip()
        if not name:
            return note(f"Usage: {op}name")
        body = _current_body(status, survey)
        if not body:
            return note("No body for bookmark")
        if status is None or not status.has_lat_long:
            return note("Need Status lat/long")
        lat = float(status.latitude or 0.0)
        lon = float(status.longitude or 0.0)
        radius = float(status.planet_radius or 0.0)
        if op == "+":
            msg = cmdr.add_bookmark(body, name, lat, lon, radius_m=radius)
        else:
            msg = cmdr.remove_bookmark(
                body, name, lat, lon, nearest=(op == "-"), radius_m=radius
            )
        if persist and (
            msg.startswith("Bookmark")
            or msg.startswith("Removed")
            or msg.startswith("Cleared")
        ):
            cmdr.save()
        return note(msg)

    if lower == CMD_VISITED or lower.startswith(CMD_VISITED + " "):
        parts = raw.split(None, 1)
        hint = parts[1] if len(parts) > 1 else None
        body = _resolve_body_name(hint, status, survey)
        if not body:
            return note("Usage: .visited [body]")
        on = cmdr.toggle_body_flag(body, "visited")
        if persist:
            cmdr.save()
        return note(f"{'Visited' if on else 'Unvisited'} {body}")

    if (
        lower.startswith(CMD_FIRST_FOOT)
        or lower == CMD_FF
        or lower.startswith(CMD_FF + " ")
    ):
        parts = raw.split(None, 1)
        hint = parts[1] if len(parts) > 1 else None
        body = _resolve_body_name(hint, status, survey)
        if not body:
            return note("Usage: .firstFoot [body]")
        on = cmdr.toggle_body_flag(body, "first_foot")
        if persist:
            cmdr.save()
        return note(f"First footfall {'on' if on else 'off'}: {body}")

    if lower == CMD_TOWER or lower.startswith(CMD_TOWER + " "):
        rest = raw[len(CMD_TOWER) :].strip()
        degrees: int | None = None
        if rest:
            try:
                degrees = int(rest)
            except ValueError:
                return note("Usage: .tower [heading]")
        from plot_guardians import assign_tower_command

        message = assign_tower_command(g, survey, status, degrees, fallback_heading=hdg)
        if message.startswith("Relic tower") and persist:
            cmdr.save()
        return note(message)

    if lower == CMD_IMGS:
        try:
            import os
            import subprocess

            from config import load_settings

            cfg = (
                load_settings(home=config_home)
                if config_home is not None
                else load_settings()
            )
            folder = getattr(cfg.game, "screenshotTargetFolder", None) or ""
            if survey and survey.system and folder:
                candidate = os.path.join(folder, survey.system)
                if os.path.isdir(candidate):
                    folder = candidate
            if folder and os.path.isdir(folder):
                subprocess.Popen(  # noqa: S603
                    ["xdg-open", folder],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return note(f"Opened {folder}")
            return note("Screenshot folder not found")
        except Exception as exc:  # noqa: BLE001
            return note(f".imgs failed: {exc}")

    if lower == CMD_KILL:
        try:
            from paths import ensure_data_dir, srvsurvey_data_dir

            ensure_data_dir()
            (srvsurvey_data_dir() / "request-quit").write_text("1\n", encoding="utf-8")
            return note("Quit requested")
        except Exception as exc:  # noqa: BLE001
            return note(f".kill failed: {exc}")

    if lower == CMD_SHOW:
        active = None
        rest = raw[len(CMD_SHOW) :].strip() if lower.startswith(CMD_SHOW + " ") else ""
        if rest:
            active = rest
        elif survey is not None:
            for row in survey.organic_progress:
                if row.scan_type in ("Log", "Sample", "Analyse"):
                    active = row.genus or getattr(row, "species", None)
                    break
            if not active and survey.bookmarks:
                active = survey.bookmarks[0].name
        if active:
            try:
                from codex_ref import image_url_for_species

                url = image_url_for_species(str(active))
                if url:
                    import subprocess

                    subprocess.Popen(  # noqa: S603
                        ["xdg-open", url],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return note(f"Opened image for {active}")
            except Exception:
                pass
            return note(f"Show: {active} (no image_url — Codex → Show Species)")
        return note(".show: no active organic (pass a species name)")

    if lower == CMD_NEW or lower.startswith(CMD_NEW + " "):
        rest = raw[len(CMD_NEW) :].strip()
        if rest:
            return handle_send_text(
                f".add {rest}",
                cmdr=cmdr,
                status=status,
                survey=survey,
                status_heading=status_heading,
                market_id=market_id,
                poi_angle=poi_angle,
                poi_dist=poi_dist,
                poi_rot=poi_rot,
                nearest_overlay=nearest_overlay,
                guardian_site_key=site_key,
                persist=persist,
                on_floatie=on_floatie,
                config_path=config_path,
                config_home=config_home,
            )
        return note("Use .add <type> for overlay POI (or .new <type>)")

    # zoom: "z 1.5" or "z1.5"
    if lower.startswith(CMD_Z) and (
        len(lower) == 1
        or lower[1].isspace()
        or lower[1].isdigit()
        or lower[1] in ".-"
    ):
        rest = raw[1:].strip()
        try:
            zoom = float(rest)
        except ValueError:
            return note("Zoom needs a number")
        g.zoom = max(0.25, min(8.0, zoom))
        if persist:
            cmdr.save()
        return note(f"Zoom {g.zoom:.2f}")

    if lower == CMD_SETTLEMENT or lower.startswith(CMD_SETTLEMENT + " "):
        if hdg is None:
            return note("No heading (need Status lat/long)")
        if mid is None:
            return note("No settlement market id")
        cmdr.set_human_heading(mid, hdg)
        if persist:
            cmdr.save()
        return note(f"Settlement heading {hdg:.1f}°")

    if lower == CMD_AERIAL:
        g.plot_mode = "aerial"
        if persist:
            cmdr.save()
        return note("Guardian mode: aerial")

    if lower == CMD_MAP:
        g.plot_mode = "map"
        if persist:
            cmdr.save()
        return note("Guardian mode: map")

    if lower == CMD_HEADING or lower.startswith(CMD_HEADING + " "):
        rest = raw[len(CMD_HEADING) :].strip()
        if rest:
            try:
                new_heading = float(rest) % 360.0
            except ValueError:
                return note("Heading needs a number")
            g.heading = new_heading
            g.plot_mode = "map"
            if persist:
                cmdr.save()
            return note(f"Site heading {g.heading:.1f}°")
        if g.plot_mode == "heading" and hdg is not None:
            g.heading = float(hdg) % 360.0
            g.plot_mode = "map"
            if persist:
                cmdr.save()
            return note(f"Site heading {g.heading:.1f}°")
        g.plot_mode = "heading"
        if persist:
            cmdr.save()
        return note("Guardian mode: heading")

    if lower.startswith(CMD_SITE):
        parts = raw.split(None, 1)
        if len(parts) < 2:
            g.plot_mode = "site"
            if persist:
                cmdr.save()
            return note("Guardian mode: site")
        site_type = _canonical_site_type(parts[1].strip().split()[0])
        if not site_type:
            return note("Usage: .site Alpha")
        g.site_type = site_type
        g.plot_mode = "heading" if g.heading < 0 else "map"
        if persist:
            cmdr.save()
        return note(f"Site type {site_type}")

    if lower in _SITE_ALIASES or _canonical_site_type(raw) in _STRUCTURE_TYPES:
        if g.plot_mode == "site" or not g.site_type:
            site_type = _canonical_site_type(raw)
            if site_type:
                g.site_type = site_type
                g.plot_mode = "heading" if g.heading < 0 else "map"
                if persist:
                    cmdr.save()
                return note(f"Site type {site_type}")

    if g.plot_mode == "heading" and " " not in raw and not raw.startswith("."):
        try:
            new_heading = float(raw) % 360.0
        except ValueError:
            new_heading = None
        if new_heading is not None:
            g.heading = new_heading
            g.plot_mode = "map"
            if persist:
                cmdr.save()
            return note(f"Site heading {g.heading:.1f}°")

    if lower.startswith(CMD_TO):
        parts = raw.split(None, 1)
        if len(parts) < 2:
            g.target_obelisk = None
            if persist:
                cmdr.save()
            return note("Target obelisk cleared")
        g.target_obelisk = parts[1].strip().upper()
        if persist:
            cmdr.save()
        return note(f"Target obelisk {g.target_obelisk}")

    if lower == CMD_OS:
        ob = g.target_obelisk
        if not ob:
            return note("No target — .to <A01> first")
        added = cmdr.toggle_scanned_obelisk(ob)
        if cmdr.ram_tah_active:
            site = survey.current_guardian_site if survey else None
            is_ruins = True if site is None else bool(site.is_ruins)
            cmdr.toggle_decode_msg(ob, is_ruins=is_ruins)
        if persist:
            cmdr.save()
        return note(f"{'Scanned' if added else 'Unscanned'} {ob}")

    if lower.startswith(CMD_EMPTY):
        parts = raw.split(None, 1)
        name = parts[1].strip() if len(parts) > 1 else (nearest_overlay or "")
        if name:
            if name in g.empty_puddles:
                g.empty_puddles = [x for x in g.empty_puddles if x != name]
            else:
                g.empty_puddles = sorted({*g.empty_puddles, name})
            if persist:
                cmdr.save()
            return note(f"Empty puddle {name}")
        return note("Usage: .empty <poi>")

    if lower.startswith(CMD_ADD):
        parts = raw.split(None, 1)
        if len(parts) < 2:
            return note("Usage: .add totem")
        poi_key = parts[1].strip().split()[0].lower()
        if poi_key not in _POI_TYPES:
            return note(f"Unknown POI type: {poi_key}")
        poi_type = _POI_TYPE_CANON[poi_key]
        if poi_angle is None or poi_dist is None:
            try:
                from plot_guardians import poi_placement_from_status, site_context

                _site, pub, _st, site_hdg = site_context(
                    survey or SurveyState(), guardian_state=g
                )
                place = poi_placement_from_status(
                    status,
                    origin_lat=pub.latitude if pub else None,
                    origin_lon=pub.longitude if pub else None,
                    site_heading=float(site_hdg),
                )
                if place is not None:
                    poi_angle, poi_dist, poi_rot = place
            except Exception:
                pass
        if poi_angle is None or poi_dist is None:
            return note("Need lat/long + site heading to place POI")
        idx = len(g.extra_poi) + 1
        name = f"x{idx}"
        g.extra_poi = [
            *g.extra_poi,
            {
                "name": name,
                "type": poi_type,
                "angle": float(poi_angle),
                "dist": float(poi_dist),
                "rot": float(poi_rot or 0.0),
            },
        ]
        if persist:
            cmdr.save()
        return note(f"Added {poi_type} {name}")

    if lower == CMD_REMOVE or lower.startswith(CMD_REMOVE + " "):
        parts = raw.split(None, 1)
        name = parts[1].strip() if len(parts) > 1 else (nearest_overlay or "")
        if not name:
            return note("Usage: .remove x1")
        before = len(g.extra_poi)
        g.extra_poi = [p for p in g.extra_poi if str(p.get("name")) != name]
        if len(g.extra_poi) == before:
            return note(f"No overlay POI named {name}")
        g.empty_puddles = [x for x in g.empty_puddles if x != name]
        if persist:
            cmdr.save()
        return note(f"Removed {name}")

    if lower.startswith(CMD_NOTE):
        parts = raw.split(None, 1)
        text = parts[1] if len(parts) > 1 else ""
        g.notes = (g.notes + " " + text).strip() if text else g.notes
        if persist:
            cmdr.save()
        return note("Note saved")

    if lower.startswith(CMD_THREAT):
        rest = raw[len(CMD_THREAT) :].strip()
        if not rest.lstrip("-").isdigit():
            return note("Usage: .threat <level>  (example: .threat 2)")
        cmdr.settlement_threat = int(rest)
        if persist:
            cmdr.save()
        return note(f"Settlement threat {cmdr.settlement_threat}")

    if lower == ".edit" or lower.startswith(".edit "):
        cmdr.human_site_edit = True
        if persist:
            cmdr.save()
        return note("Human site edit mode on")

    if lower == ".start" or lower.startswith(".start "):
        cmdr.human_site_survey = "active"
        if persist:
            cmdr.save()
        return note("Human site survey started")

    if lower == ".stop" or lower.startswith(".stop "):
        cmdr.human_site_survey = "stopped"
        cmdr.human_site_edit = False
        if persist:
            cmdr.save()
        return note("Human site survey stopped")

    return None


def process_cmdr_events(
    cmdr: CommanderState,
    events: Sequence[dict[str, Any]],
    *,
    status: StatusSnapshot | None = None,
    survey: SurveyState | None = None,
    persist: bool = True,
    on_floatie: Callable[[str], None] | None = None,
) -> list[str]:
    """Apply mission + SendText journal events. Returns status notes."""
    notes: list[str] = []
    apply_journal_events(cmdr, [e for e in events if isinstance(e, dict)])

    nearest = None
    g = cmdr.guardian_for() if hasattr(cmdr, "guardian_for") else cmdr.guardian
    if g.extra_poi:
        last = g.extra_poi[-1]
        if isinstance(last, dict) and last.get("name"):
            nearest = str(last["name"])

    for entry in events:
        if not isinstance(entry, dict):
            continue
        if entry.get("event") != "SendText":
            continue
        msg = entry.get("Message") or entry.get("Message_Localised") or ""
        if not isinstance(msg, str):
            continue
        result = handle_send_text(
            msg,
            cmdr=cmdr,
            status=status,
            survey=survey,
            nearest_overlay=nearest,
            persist=persist,
            on_floatie=on_floatie,
        )
        if result:
            notes.append(result)
    return notes


# Back-compat aliases used by older tests / callers
def handle_journal_entry(
    entry: dict[str, Any],
    *,
    cmdr: CommanderState,
    status: StatusSnapshot | None = None,
    survey: SurveyState | None = None,
    status_heading: float | None = None,
    market_id: int | None = None,
    guardian_site_key: str | None = None,
    persist: bool = True,
    on_floatie: Callable[[str], None] | None = None,
    **_ignored: Any,
) -> str | None:
    """Dispatch Mission* and SendText. Extra kwargs kept for host/test callers."""
    event = entry.get("event")
    if event in (
        "MissionAccepted",
        "MissionCompleted",
        "MissionFailed",
        "MissionAbandoned",
        "Missions",
    ):
        from cmdr_state import apply_mission_journal, save_cmdr

        if apply_mission_journal(cmdr, entry) and persist:
            save_cmdr(cmdr)
        return None
    if event != "SendText":
        return None
    msg = entry.get("Message") or entry.get("Message_Localised") or ""
    if not isinstance(msg, str):
        return None
    return handle_send_text(
        msg,
        cmdr=cmdr,
        status=status,
        survey=survey,
        status_heading=status_heading,
        market_id=market_id,
        guardian_site_key=guardian_site_key,
        persist=persist,
        on_floatie=on_floatie,
    )
