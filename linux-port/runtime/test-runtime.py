#!/usr/bin/env python3
"""Path, journal, panel, companion, and watcher checks. No display / window."""

import json
import math
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "overlay-presenter"))

from companion import (  # noqa: E402
    FLAG_DOCKED,
    FLAG_IN_DANGER,
    FLAG_LOW_FUEL,
    parse_cargo,
    parse_nav_route,
    parse_ship_locker,
    parse_status,
)
from config import (  # noqa: E402
    AppSettings,
    load_settings,
    parse_config_text,
    present_is_allowed,
    read_allow_present_from_files,
    save_settings,
    settings_from_dict,
)
from game_settings import GameSettings  # noqa: E402
from host import (  # noqa: E402
    PRESENT_HOLD_SECONDS,
    PRESENT_PANEL_SCALE,
    HudState,
    build_present_panels,
    did_game_rect_change,
    did_location_change,
    format_plan,
    main,
    plan,
    present_tick,
    stack_top_right,
    top_right_inset,
)
from hotkey import normalize_chord, parse_chord, place_toggle_chip  # noqa: E402
from journal import (  # noqa: E402
    CommanderLocation,
    SurveyState,
    read_location,
    read_session,
)
from panel import (  # noqa: E402
    bio_panel_lines,
    locker_panel_lines,
    materials_panel_lines,
    render_ship_bitmap,
    render_signals_bitmap,
    render_status_bitmap,
    render_survey_bitmap,
    route_panel_lines,
    ship_panel_lines,
    signals_panel_lines,
    survey_panel_lines,
)
from paths import (  # noqa: E402
    ensure_data_dir,
    journal_dir,
    journal_dir_for_libraries,
    parse_vdf,
    srvsurvey_data_dir,
    steam_libraries,
    write_runtime_state,
)
from presenter import PresenterMode, Rect, layout_overlay  # noqa: E402
from watcher import JournalWatcher  # noqa: E402


VDF = """
"libraryfolders"
{
	"0"
	{
		"path"		"/home/cmdr/.local/share/Steam"
		"apps"
		{
			"228980"		"10"
		}
	}
	"1"
	{
		"path"		"/mnt/games/SteamLibrary"
		"apps"
		{
			"359320"		"58055995280"
		}
	}
}
"""

JOURNAL = "\n".join([
    json.dumps({"timestamp": "2026-09-26T00:00:00Z", "event": "Fileheader", "part": 1}),
    json.dumps({
        "timestamp": "2026-09-26T00:00:01Z",
        "event": "LoadGame",
        "Commander": "Sample",
        "FID": "F0001",
        "Ship": "Asp",
        "Ship_Localised": "Asp Explorer",
        "ShipIdent": "SRVEY",
        "FuelCapacity": 32.0,
    }),
    json.dumps({
        "timestamp": "2026-09-26T00:00:02Z",
        "event": "Materials",
        "Raw": [
            {"Name": "iron", "Count": 40},
            {"Name": "sulphur", "Name_Localised": "Sulphur", "Count": 22},
        ],
        "Manufactured": [
            {"Name": "focuscrystals", "Name_Localised": "Focus Crystals", "Count": 8},
        ],
        "Encoded": [
            {"Name": "emissiondata", "Name_Localised": "Emission Data", "Count": 15},
        ],
    }),
    json.dumps({
        "timestamp": "2026-09-26T00:01:00Z",
        "event": "Location",
        "StarSystem": "Sol",
        "SystemAddress": 10477373803,
        "Body": "Earth",
    }),
    json.dumps({
        "timestamp": "2026-09-26T00:30:00Z",
        "event": "FSDJump",
        "StarSystem": "Shinrarta Dezhra",
        "SystemAddress": 3932277478106,
        "Body": "Shinrarta Dezhra A 1",
    }),
    json.dumps({
        "timestamp": "2026-09-26T00:31:00Z",
        "event": "FSSDiscoveryScan",
        "Progress": 0.42,
        "BodyCount": 10,
        "NonBodyCount": 3,
        "SystemName": "Shinrarta Dezhra",
        "SystemAddress": 3932277478106,
    }),
    json.dumps({
        "timestamp": "2026-09-26T00:31:30Z",
        "event": "FSSSignalDiscovered",
        "SystemAddress": 3932277478106,
        "SignalName": "Jameson Memorial",
        "SignalType": "Orbis",
        "IsStation": True,
    }),
    json.dumps({
        "timestamp": "2026-09-26T00:31:31Z",
        "event": "FSSSignalDiscovered",
        "SystemAddress": 3932277478106,
        "SignalName": "$USS_HighGradeEmissions;",
        "SignalName_Localised": "Unidentified signal source",
        "SignalType": "USS",
        "ThreatLevel": 2,
    }),
    json.dumps({
        "timestamp": "2026-09-26T00:32:00Z",
        "event": "Scan",
        "BodyName": "Shinrarta Dezhra A 1",
        "BodyID": 1,
        "StarSystem": "Shinrarta Dezhra",
        "SystemAddress": 3932277478106,
        "ScanType": "Detailed",
        "PlanetClass": "High metal content body",
        "Landable": True,
        "MassEM": 0.45,
        "DistanceFromArrivalLS": 412.0,
        "WasDiscovered": False,
        "WasMapped": False,
        "TerraformState": "",
    }),
    json.dumps({
        "timestamp": "2026-09-26T00:33:00Z",
        "event": "FSSBodySignals",
        "BodyName": "Shinrarta Dezhra A 1",
        "BodyID": 1,
        "SystemAddress": 3932277478106,
        "Signals": [
            {"Type": "$SAA_SignalType_Biological;", "Type_Localised": "Biological", "Count": 2},
            {"Type": "$SAA_SignalType_Geological;", "Type_Localised": "Geological", "Count": 1},
        ],
        "Genuses": [
            {"Genus": "$Codex_Ent_Bacterial_Genus_Name;", "Genus_Localised": "Bacterium"},
            {"Genus": "$Codex_Ent_Fonticulua_Genus_Name;", "Genus_Localised": "Fonticulua"},
        ],
    }),
    json.dumps({
        "timestamp": "2026-09-26T00:33:30Z",
        "event": "SAASignalsFound",
        "BodyName": "Shinrarta Dezhra A 2",
        "BodyID": 2,
        "SystemAddress": 3932277478106,
        "Signals": [
            {"Type": "$SAA_SignalType_Geological;", "Type_Localised": "Geological", "Count": 3},
        ],
    }),
    json.dumps({
        "timestamp": "2026-09-26T00:34:00Z",
        "event": "SAAScanComplete",
        "BodyName": "Shinrarta Dezhra A 1",
        "BodyID": 1,
        "SystemAddress": 3932277478106,
    }),
    json.dumps({
        "timestamp": "2026-09-26T00:34:30Z",
        "event": "ScanOrganic",
        "ScanType": "Sample",
        "Genus": "$Codex_Ent_Bacterial_Genus_Name;",
        "Genus_Localised": "Bacterium",
        "Species": "$Codex_Ent_Bacterial_01_Name;",
        "Species_Localised": "Bacterium Auris",
        "SystemAddress": 3932277478106,
        "Body": 1,
    }),
    json.dumps({
        "timestamp": "2026-09-26T00:34:45Z",
        "event": "SellOrganicData",
        "BioData": [
            {
                "Genus": "$Codex_Ent_Bacterial_Genus_Name;",
                "Genus_Localised": "Bacterium",
                "Species": "$Codex_Ent_Bacterial_01_Name;",
                "Species_Localised": "Bacterium Auris",
                "Value": 100000,
                "Bonus": 5000,
            }
        ],
    }),
    json.dumps({
        "timestamp": "2026-09-26T00:35:00Z",
        "event": "CodexEntry",
        "EntryID": 2100605,
        "Name": "$Codex_Ent_Sample;",
        "Name_Localised": "Rubeum Ice Crystals",
        "SubCategory": "$Codex_SubCategory_Organic_Structures;",
        "SubCategory_Localised": "Organic structures",
        "Category": "$Codex_Category_Biology;",
        "Category_Localised": "Biological and Geological",
        "System": "Shinrarta Dezhra",
        "SystemAddress": 3932277478106,
        "IsNewEntry": True,
    }),
    "{not json",
])

STATUS_JSON = json.dumps({
    "timestamp": "2026-09-26T00:40:00Z",
    "event": "Status",
    "Flags": FLAG_DOCKED | FLAG_LOW_FUEL,
    "Flags2": 0,
    "Fuel": {"FuelMain": 4.5, "FuelReservoir": 0.3},
    "Cargo": 12.0,
    "LegalState": "Clean",
    "Balance": 1000,
    "Destination": {"System": 1, "Body": 0, "Name": "Jameson Memorial"},
})

CARGO_JSON = json.dumps({
    "timestamp": "2026-09-26T00:40:00Z",
    "event": "Cargo",
    "Vessel": "Ship",
    "Count": 12,
    "Inventory": [
        {"Name": "gold", "Name_Localised": "Gold", "Count": 8, "Stolen": 0},
        {"Name": "silver", "Count": 4, "Stolen": 0},
    ],
})

LOCKER_JSON = json.dumps({
    "timestamp": "2026-09-26T00:40:00Z",
    "event": "ShipLocker",
    "Items": [{"Name": "graphene", "Name_Localised": "Graphene", "Count": 3}],
    "Components": [],
    "Consumables": [{"Name": "healthpack", "Name_Localised": "Medkit", "Count": 2}],
    "Data": [],
})

NAV_ROUTE_JSON = json.dumps({
    "timestamp": "2026-09-26T00:40:00Z",
    "event": "NavRoute",
    "Route": [
        {"StarSystem": "Shinrarta Dezhra", "SystemAddress": 1},
        {"StarSystem": "Sol", "SystemAddress": 2},
        {"StarSystem": "Alioth", "SystemAddress": 3},
    ],
})


class PathTests(unittest.TestCase):
    def test_data_dir_uses_xdg_and_not_appdata(self):
        path = srvsurvey_data_dir({"XDG_DATA_HOME": "/tmp/xdg"}, home=Path("/home/cmdr"))
        self.assertEqual(path, Path("/tmp/xdg/srvsurvey"))
        self.assertNotIn("AppData", str(path))
        self.assertNotIn("\\", str(path))

    def test_data_dir_defaults_under_local_share(self):
        path = srvsurvey_data_dir({}, home=Path("/home/cmdr"))
        self.assertEqual(path, Path("/home/cmdr/.local/share/srvsurvey"))

    def test_ensure_data_dir_creates_and_writes_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "srvsurvey"
            created = ensure_data_dir(data)
            self.assertTrue(created.is_dir())
            state = write_runtime_state(
                created,
                journal_folder=Path("/journals"),
                journal_file=Path("/journals/Journal.x.log"),
            )
            self.assertTrue(state.is_file())
            payload = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(payload["journal_folder"], "/journals")

    def test_elite_library_is_the_one_containing_the_app_id(self):
        libraries = steam_libraries(VDF)
        self.assertEqual(len(libraries), 2)
        folder = journal_dir_for_libraries(libraries)
        expected = journal_dir("/mnt/games/SteamLibrary")
        self.assertEqual(folder, expected)
        self.assertIn("359320", str(folder))
        self.assertNotIn("\\", str(folder))

    def test_vdf_root_is_libraryfolders(self):
        parsed = parse_vdf(VDF)
        self.assertIn("libraryfolders", parsed)


class JournalTests(unittest.TestCase):
    def test_latest_jump_wins_over_earlier_location(self):
        location = read_location(JOURNAL)
        self.assertEqual(location.commander, "Sample")
        self.assertEqual(location.system, "Shinrarta Dezhra")
        self.assertEqual(location.body, "Shinrarta Dezhra A 1")

    def test_broken_line_is_skipped(self):
        location = read_location(
            '{"event":"LoadGame","Commander":"A"}\nNOT\n{"event":"FSDJump","StarSystem":"Sol"}\n'
        )
        self.assertEqual(location.commander, "A")
        self.assertEqual(location.system, "Sol")

    def test_survey_tracks_fss_bio_and_dss(self):
        session = read_session(JOURNAL)
        survey = session.survey
        self.assertEqual(survey.system, "Shinrarta Dezhra")
        self.assertAlmostEqual(survey.fss_progress or 0, 0.42)
        self.assertEqual(survey.body_count, 10)
        self.assertEqual(survey.scanned_count, 1)
        self.assertEqual(survey.mapped_count, 1)
        self.assertEqual(survey.total_bio_signals, 2)
        self.assertEqual(survey.total_geo_signals, 4)
        self.assertEqual(survey.ship, "Asp Explorer")
        self.assertEqual(survey.ship_ident, "SRVEY")
        self.assertEqual(survey.fuel_capacity, 32.0)

    def test_parses_fss_signals_codex_and_materials(self):
        survey = read_session(JOURNAL).survey
        self.assertEqual(len(survey.fss_signals), 2)
        self.assertEqual(survey.fss_signals[0].name, "Jameson Memorial")
        self.assertTrue(survey.fss_signals[0].is_station)
        self.assertEqual(survey.fss_signals[1].name, "Unidentified signal source")
        self.assertEqual(survey.fss_signals[1].threat_level, 2)
        self.assertEqual(len(survey.codex_entries), 1)
        self.assertEqual(survey.codex_entries[0].name, "Rubeum Ice Crystals")
        self.assertTrue(survey.codex_entries[0].is_new)
        assert survey.materials is not None
        self.assertEqual(survey.materials.raw[0].name, "iron")
        self.assertEqual(survey.materials.top(1)[0].name, "iron")
        self.assertEqual(survey.materials.top(1)[0].count, 40)
        self.assertEqual(survey.organic_scans, 1)
        self.assertEqual(len(survey.organic_progress), 1)
        self.assertEqual(survey.organic_progress[0].genus, "Bacterium")
        self.assertEqual(survey.organic_progress[0].scan_type, "Sample")
        self.assertEqual(survey.organic_sales, 1)
        self.assertEqual(survey.organic_sale_value, 105000)
        body = next(b for b in survey.body_signals if "A 1" in b.body_name)
        self.assertIn("Bacterium", body.genuses)

    def test_system_jump_resets_survey(self):
        text = JOURNAL + "\n" + json.dumps({
            "timestamp": "2026-09-26T01:00:00Z",
            "event": "FSDJump",
            "StarSystem": "Alioth",
            "SystemAddress": 1109989017963,
            "Body": "Alioth",
        })
        survey = read_session(text).survey
        self.assertEqual(survey.system, "Alioth")
        self.assertIsNone(survey.fss_progress)
        self.assertEqual(survey.scanned_count, 0)
        self.assertEqual(survey.total_bio_signals, 0)
        self.assertEqual(survey.fss_signals, ())
        self.assertEqual(survey.codex_entries, ())
        # Materials persist across jumps (commander inventory).
        assert survey.materials is not None
        self.assertEqual(survey.materials.top(1)[0].count, 40)

    def test_leave_body_clears_body(self):
        text = "\n".join([
            json.dumps({"event": "LoadGame", "Commander": "A"}),
            json.dumps({
                "event": "Location",
                "StarSystem": "Sol",
                "SystemAddress": 1,
                "Body": "Earth",
            }),
            json.dumps({
                "event": "LeaveBody",
                "StarSystem": "Sol",
                "SystemAddress": 1,
                "Body": "Earth",
                "BodyID": 1,
            }),
        ])
        location = read_session(text).location
        self.assertEqual(location.system, "Sol")
        self.assertIsNone(location.body)


class CompanionTests(unittest.TestCase):
    def test_parse_status_flags_and_fuel(self):
        status = parse_status(STATUS_JSON)
        assert status is not None
        self.assertTrue(status.docked)
        self.assertTrue(status.low_fuel)
        self.assertFalse(status.in_danger)
        self.assertEqual(status.mode_label(), "Docked")
        self.assertEqual(status.fuel_main, 4.5)
        self.assertEqual(status.destination, "Jameson Memorial")

    def test_parse_cargo_inventory(self):
        cargo = parse_cargo(CARGO_JSON)
        assert cargo is not None
        self.assertEqual(cargo.count, 12)
        self.assertEqual(len(cargo.inventory), 2)
        self.assertEqual(cargo.inventory[0].name, "Gold")

    def test_danger_mode_label(self):
        status = parse_status(json.dumps({
            "Flags": FLAG_IN_DANGER,
            "Flags2": 0,
            "Fuel": {"FuelMain": 10, "FuelReservoir": 0.5},
            "LegalState": "Wanted",
        }))
        assert status is not None
        self.assertTrue(status.in_danger)
        self.assertEqual(status.legal_state, "Wanted")

    def test_parse_ship_locker_and_nav_route(self):
        locker = parse_ship_locker(LOCKER_JSON)
        assert locker is not None
        self.assertEqual(locker.total_count, 5)
        self.assertEqual(locker.consumables[0].name, "Medkit")
        route = parse_nav_route(NAV_ROUTE_JSON)
        assert route is not None
        self.assertEqual(route.hops[0], "Shinrarta Dezhra")
        self.assertEqual(route.remaining, 2)


class PanelTests(unittest.TestCase):
    def test_bitmap_matches_panel_size_and_gamescope_window(self):
        location = read_location(JOURNAL)
        rgba, width, height = render_status_bitmap(location)
        self.assertEqual(len(rgba), width * height * 4)
        self.assertGreater(width, 40)
        self.assertGreater(height, 16)
        game = Rect(0, 0, 1920, 1080)
        panel = Rect(16, 16, width, height)
        session = layout_overlay(PresenterMode.SESSION_X11, game, [panel])
        gamescope = layout_overlay(PresenterMode.GAMESCOPE, game, [panel])
        self.assertEqual(session[0].window.width, width)
        self.assertEqual(session[0].window.height, height)
        self.assertEqual(session[0].window, Rect(16, 16, width, height))
        self.assertTrue(session[0].click_through)
        self.assertEqual(gamescope[0].window.width, width)
        self.assertEqual(gamescope[0].window.height, height)
        self.assertTrue(gamescope[0].click_through)
        blocked = layout_overlay(
            PresenterMode.SESSION_X11, game, [panel], pass_clicks=False,
        )
        self.assertFalse(blocked[0].click_through)

    def test_host_plan_does_not_ask_to_present(self):
        location = read_location(JOURNAL)
        result = plan(location, Rect(0, 0, 1280, 720))
        text = format_plan(result, Path("/tmp/xdg/srvsurvey"), Path("/journals"))
        self.assertIn("present: suppressed", text)
        self.assertIn("Shinrarta Dezhra", text)

    def test_present_flag_is_refused_without_an_explicit_environment_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            vdf = Path(tmp) / "libraryfolders.vdf"
            vdf.write_text(VDF, encoding="utf-8")
            env = {
                k: v
                for k, v in os.environ.items()
                if k != "SRVSURVEY_ALLOW_PRESENT"
            }
            env["HOME"] = str(home)
            env["XDG_CONFIG_HOME"] = str(home / ".config")
            env["XDG_DATA_HOME"] = str(home / ".local" / "share")
            old = dict(os.environ)
            try:
                os.environ.clear()
                os.environ.update(env)
                code = main(["--vdf", str(vdf), "--present"])
            finally:
                os.environ.clear()
                os.environ.update(old)
        self.assertEqual(code, 2)

    def test_present_allowed_via_cli_flag_without_env(self):
        self.assertTrue(present_is_allowed(cli_allow=True, environ={}))

    def test_present_allowed_via_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.json"
            cfg.write_text('{"allow_present": true}\n', encoding="utf-8")
            self.assertTrue(
                present_is_allowed(
                    cli_allow=False,
                    environ={},
                    config_paths=[cfg],
                )
            )
            self.assertTrue(read_allow_present_from_files([cfg]))

    def test_config_key_value_and_json_parsers(self):
        self.assertEqual(parse_config_text("allow_present=true\n"), {"allow_present": "true"})
        self.assertEqual(parse_config_text('{"allow_present": true}'), {"allow_present": True})
        self.assertFalse(
            present_is_allowed(
                cli_allow=False,
                environ={},
                config_paths=[],
            )
        )

    def test_settings_round_trip_and_hotkey_parse(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config"
            settings = AppSettings(
                allow_present=True,
                hotkey="Super+Shift+S",
                font_size=30,
                panels={"location": True, "survey": False, "bio": True,
                        "signals": True, "route": True, "ship": True,
                        "materials": False, "locker": True},
            )
            saved = save_settings(settings, path)
            loaded = load_settings(config_paths=[saved])
            self.assertTrue(loaded.allow_present)
            self.assertEqual(loaded.hotkey, "Super+Shift+S")
            self.assertEqual(loaded.font_size, 30)
            self.assertFalse(loaded.panel_enabled("survey"))
            self.assertTrue(loaded.panel_enabled("bio"))
            self.assertEqual(loaded.key_actions["showFssInfo"], "ALT F")
            self.assertEqual(loaded.key_actions["showColonyShopping"], "ALT S")
        self.assertEqual(normalize_chord("super-shift-s"), "Super+Shift+S")
        chord = parse_chord("Pause")
        self.assertEqual(chord.label, "Pause")
        self.assertEqual(chord.keyname, "Pause")
        self.assertEqual(normalize_chord("f9"), "F9")
        self.assertEqual(parse_chord("Scroll_Lock").keyname, "Scroll_Lock")
        chip = place_toggle_chip(1080, 480, 3440, 1440, 5600, 1920)
        # Inside the game, bottom-right, clear of PlotBodyInfo at the top-left.
        self.assertGreaterEqual(chip.x, 1080)
        self.assertLessEqual(chip.x + chip.width, 1080 + 3440)
        self.assertGreater(chip.x, 1080 + 1000)
        self.assertGreaterEqual(chip.y, 480)
        self.assertLessEqual(chip.y + chip.height, 480 + 1440)
        self.assertGreater(chip.y, 480 + 400)
        fullscreen = place_toggle_chip(0, 0, 1920, 1080, 1920, 1080)
        self.assertGreaterEqual(fullscreen.x, 0)
        self.assertLessEqual(fullscreen.x + fullscreen.width, 1920)
        self.assertGreater(fullscreen.x, 1000)
        self.assertGreaterEqual(fullscreen.y, 0)
        self.assertLessEqual(fullscreen.y + fullscreen.height, 1080)

    def test_settings_from_panel_dot_keys(self):
        parsed = settings_from_dict({
            "allow_present": "true",
            "hotkey": "Pause",
            "panel.locker": "false",
            "font_size": "24",
        })
        self.assertTrue(parsed.allow_present)
        self.assertFalse(parsed.panel_enabled("locker"))
        self.assertEqual(parsed.font_size, 24)

    def test_default_hold_is_until_ctrl_c(self):
        self.assertEqual(PRESENT_HOLD_SECONDS, 0.0)

    def test_status_panel_anchors_top_right(self):
        from host import status_panel_top_right

        location = read_location(JOURNAL)
        game = Rect(1080, 480, 3440, 1440)
        panel = status_panel_top_right(location, game, margin=40)
        self.assertEqual(panel.y, 40)
        self.assertEqual(panel.x, game.width - panel.width - 40)
        session = layout_overlay(
            PresenterMode.SESSION_X11,
            game,
            [Rect(panel.x, panel.y, panel.width, panel.height)],
        )
        self.assertEqual(len(session), 1)
        self.assertEqual(session[0].window.width, panel.width)
        self.assertEqual(session[0].window.height, panel.height)
        self.assertTrue(session[0].click_through)

    def test_bitmap_includes_body_when_distinct_from_system(self):
        location = read_location(JOURNAL)
        self.assertNotEqual(location.body, location.system)
        rgba, width, height = render_status_bitmap(location)
        without_body = CommanderLocation(location.system, location.commander, location.system)
        _, _, short_h = render_status_bitmap(without_body)
        self.assertGreater(height, short_h)
        self.assertEqual(len(rgba), width * height * 4)

    def test_survey_and_ship_line_layouts_are_useful(self):
        survey = read_session(JOURNAL).survey
        lines = survey_panel_lines(survey)
        joined = " ".join(text for text, _ in lines)
        self.assertIn("FSS", joined)
        self.assertIn("Bio", joined)
        self.assertIn("Geo", joined)
        self.assertIn("DSS", joined)

        signal_lines = signals_panel_lines(survey)
        signal_joined = " ".join(text for text, _ in signal_lines)
        self.assertIn("bio 2", signal_joined)
        self.assertIn("geo", signal_joined)
        self.assertIn("Jameson Memorial", signal_joined)
        self.assertIn("Rubeum Ice Crystals", signal_joined)

        status = parse_status(STATUS_JSON)
        cargo = parse_cargo(CARGO_JSON)
        ship_lines = ship_panel_lines(survey, status, cargo)
        ship_joined = " ".join(text for text, _ in ship_lines)
        self.assertIn("Asp Explorer", ship_joined)
        self.assertIn("Docked", ship_joined)
        self.assertIn("Fuel", ship_joined)
        self.assertIn("Cargo", ship_joined)

        loc = read_location(JOURNAL)
        bio_joined = " ".join(text for text, _ in bio_panel_lines(survey, loc))
        self.assertIn("Bacterium", bio_joined)
        self.assertIn("Sample", bio_joined)
        self.assertIn("105,000", bio_joined)

        mat_joined = " ".join(text for text, _ in materials_panel_lines(survey))
        self.assertIn("Raw", mat_joined)
        self.assertIn("iron", mat_joined)

        route = parse_nav_route(NAV_ROUTE_JSON)
        route_joined = " ".join(text for text, _ in route_panel_lines(survey, status, route))
        self.assertIn("Jameson Memorial", route_joined)
        self.assertIn("Sol", route_joined)

        locker = parse_ship_locker(LOCKER_JSON)
        locker_joined = " ".join(text for text, _ in locker_panel_lines(locker))
        self.assertIn("Medkit", locker_joined)

    def test_survey_and_ship_bitmaps_size(self):
        survey = read_session(JOURNAL).survey
        status = parse_status(STATUS_JSON)
        cargo = parse_cargo(CARGO_JSON)
        for rgba, width, height in (
            render_survey_bitmap(survey),
            render_signals_bitmap(survey),
            render_ship_bitmap(survey, status, cargo),
        ):
            self.assertEqual(len(rgba), width * height * 4)
            self.assertGreater(width, 40)
            self.assertGreater(height, 20)


class PresentLoopHelperTests(unittest.TestCase):
    def test_top_right_inset_math(self):
        self.assertEqual(top_right_inset(3440, 498, 40), 3440 - 498 - 40)
        self.assertEqual(top_right_inset(100, 200, 40), 0)

    def test_stack_top_right_vertical(self):
        game = Rect(0, 0, 1920, 1080)
        bitmaps = [
            (b"\x00" * (10 * 8 * 4), 10, 8),
            (b"\x00" * (12 * 6 * 4), 12, 6),
        ]
        panels = stack_top_right(bitmaps, game, margin=40, gap=12)
        self.assertEqual(len(panels), 2)
        self.assertEqual(panels[0].y, 40)
        self.assertEqual(panels[1].y, 40 + 8 + 12)
        self.assertEqual(panels[0].x, 1920 - 10 - 40)
        self.assertEqual(panels[1].x, 1920 - 12 - 40)

    def test_location_change_detects_system_body_commander(self):
        base = CommanderLocation("Sol", "Sample", "Earth")
        self.assertFalse(did_location_change(base, CommanderLocation("Sol", "Sample", "Earth")))
        self.assertTrue(did_location_change(base, CommanderLocation("Alioth", "Sample", "Earth")))
        self.assertTrue(did_location_change(base, CommanderLocation("Sol", "Other", "Earth")))
        self.assertTrue(did_location_change(base, CommanderLocation("Sol", "Sample", "Mars")))

    def test_game_rect_change_detects_move_and_resize(self):
        base = Rect(0, 0, 1920, 1080)
        self.assertFalse(did_game_rect_change(base, Rect(0, 0, 1920, 1080)))
        self.assertTrue(did_game_rect_change(base, Rect(10, 0, 1920, 1080)))
        self.assertTrue(did_game_rect_change(base, Rect(0, 0, 2560, 1080)))

    def test_present_tick_flags_reposition_and_repaint(self):
        game = Rect(0, 0, 1920, 1080)
        loc = CommanderLocation("Sol", "Sample", "Earth")
        hud = HudState(loc, SurveyState(system="Sol"), None, None)
        idle = present_tick(game, game, hud, hud)
        self.assertFalse(idle.needs_present)
        moved = present_tick(game, Rect(100, 0, 1920, 1080), hud, hud)
        self.assertTrue(moved.reposition)
        self.assertFalse(moved.repaint)
        jumped = present_tick(
            game,
            game,
            hud,
            HudState(CommanderLocation("Alioth", "Sample", None), SurveyState(system="Alioth"), None, None),
        )
        self.assertFalse(jumped.reposition)
        self.assertTrue(jumped.repaint)

    def test_docked_telemetry_does_not_repaint(self):
        """Fuel and lat/long writes while docked must not rebuild the HUD."""
        from companion import FLAG_DOCKED, StatusSnapshot

        game = Rect(0, 0, 1920, 1080)
        loc = CommanderLocation("Sol", "Sample", "Earth")
        docked = StatusSnapshot(
            flags=FLAG_DOCKED,
            flags2=0,
            fuel_main=8.0,
            fuel_reservoir=0.30,
            cargo_mass=0.0,
            legal_state=None,
            balance=None,
            destination="Jameson Memorial",
            body_name="Earth",
            gui_focus=0,
            latitude=1.25,
            longitude=-2.5,
            altitude=0.0,
            heading=90.0,
        )
        jitter = StatusSnapshot(
            flags=FLAG_DOCKED,
            flags2=0,
            fuel_main=7.99,
            fuel_reservoir=0.41,
            cargo_mass=0.0,
            legal_state=None,
            balance=None,
            destination="Jameson Memorial",
            body_name="Earth",
            gui_focus=0,
            latitude=1.2504,
            longitude=-2.5002,
            altitude=0.2,
            heading=90.4,
        )
        hud = HudState(loc, SurveyState(system="Sol"), docked, None)
        tick = present_tick(game, game, hud, HudState(loc, SurveyState(system="Sol"), jitter, None))
        self.assertFalse(tick.repaint)
        self.assertFalse(tick.needs_present)
        from presenter import click_through_hits_panel

        self.assertFalse(click_through_hits_panel(32, 32))
        self.assertFalse(click_through_hits_panel(320, 50))
        self.assertFalse(click_through_hits_panel(3440, 1408))
        from presenter import should_unmap_all

        self.assertTrue(should_unmap_all([], []))
        self.assertFalse(should_unmap_all([object()], []))
        from presenter import should_park_overlays

        self.assertFalse(should_park_overlays(1))
        self.assertFalse(should_park_overlays(2))
        self.assertTrue(should_park_overlays(3))
        self.assertTrue(should_park_overlays(8))
        from plot_pulse import pulse_allowed
        from game_settings import GameSettings

        self.assertFalse(pulse_allowed(GameSettings(), docked))
        flying = StatusSnapshot(
            flags=0,
            flags2=0,
            fuel_main=8.0,
            fuel_reservoir=0.30,
            cargo_mass=0.0,
            legal_state=None,
            balance=None,
            destination=None,
            body_name=None,
            gui_focus=0,
            latitude=None,
            longitude=None,
            altitude=None,
            heading=None,
        )
        self.assertTrue(pulse_allowed(GameSettings(), flying))
        services = StatusSnapshot(
            flags=FLAG_DOCKED,
            flags2=0,
            fuel_main=8.0,
            fuel_reservoir=0.30,
            cargo_mass=0.0,
            legal_state=None,
            balance=None,
            destination="Jameson Memorial",
            body_name="Earth",
            gui_focus=5,
            latitude=1.25,
            longitude=-2.5,
            altitude=0.0,
            heading=90.0,
        )
        opened = present_tick(
            game, game, hud, HudState(loc, SurveyState(system="Sol"), services, None),
        )
        self.assertTrue(opened.repaint)

    def test_build_present_panels_uses_windows_anchors(self):
        self.assertEqual(PRESENT_PANEL_SCALE, 1)
        session = read_session(JOURNAL)
        game = Rect(0, 0, 3440, 1440)
        status = parse_status(STATUS_JSON)
        cargo = parse_cargo(CARGO_JSON)
        all_ids = tuple(AppSettings().panels)
        linux_only = AppSettings(
            panels={pid: pid in {"location", "survey", "bio", "signals", "route", "ship"} for pid in all_ids}
        )
        few = build_present_panels(
            session.location,
            game,
            survey=session.survey,
            status=status,
            cargo=cargo,
            settings=linux_only,
        )
        self.assertEqual(len(few), 1)
        self.assertEqual(few[0].x, top_right_inset(game.width, few[0].width, 40))

        with_build = AppSettings(
            panels={pid: pid == "colonisation" for pid in all_ids},
            game=GameSettings(
                buildProjectsShowSumFC_TEST=False,
                buildProjects_TEST=True,
                autoShowPlotBuildCommodities=True,
            ),
        )
        from dataclasses import replace

        colony_survey = replace(
            session.survey,
            docked=True,
            docked_station="Orbital Construction Site: Alpha",
        )
        colony = build_present_panels(
            session.location,
            game,
            survey=colony_survey,
            status=status,
            cargo=cargo,
            settings=with_build,
        )
        self.assertEqual(len(colony), 1)
        self.assertEqual(colony[0].y, 8)
        self.assertEqual(colony[0].x, game.width - colony[0].width - 8)

        from plot_pos import plotter_origin

        sys_at = plotter_origin("PlotSysStatus", 200, 80, game.width, game.height)
        self.assertEqual(sys_at, (8, game.height - 80 - 44))
        from plot_pos import trackers_origin

        # Screenshot plotters. plotters.json wins over the picture corner.
        self.assertEqual(
            plotter_origin("PlotBioStatus", 480, 80, game.width, game.height)[1],
            8,
        )
        self.assertEqual(
            plotter_origin("PlotGuardianStatus", 200, 40, game.width, game.height)[1],
            8,
        )
        self.assertEqual(
            plotter_origin("PlotRamTah", 180, 200, game.width, game.height)[0],
            game.width - 180 - 8,
        )
        self.assertEqual(
            plotter_origin("PlotSphericalSearch", 220, 60, game.width, game.height),
            (game.width - 220 - 8, 8),
        )
        self.assertEqual(
            plotter_origin("PlotGalMap", 240, 80, game.width, game.height)[:1],
            (8,),
        )
        self.assertEqual(
            plotter_origin("PlotBuildCommodities", 200, 300, game.width, game.height),
            (game.width - 200 - 8, 8),
        )
        self.assertEqual(
            plotter_origin("PlotGuardians", 280, 280, game.width, game.height)[0],
            8,
        )
        self.assertEqual(
            plotter_origin("PlotMiniTrack", 240, 80, game.width, game.height),
            (game.width - 240 - 8, 8),
        )
        bio_y = plotter_origin("PlotBioSystem", 200, 120, game.width, game.height)
        self.assertEqual(bio_y, (8, game.height - 120 - 144))
        alone = trackers_origin(200, 80, game.width, game.height)
        self.assertEqual(
            alone,
            plotter_origin("PlotGrounded", 200, 80, game.width, game.height),
        )
        under = trackers_origin(200, 40, game.width, game.height, (100, 200, 320, 440))
        self.assertEqual(under, (100, 644))

    def test_sys_status_treats_cached_canonn_as_honk(self):
        from canonn import clear_cache, empty_system_poi
        from canonn import _cache_set
        from companion import FLAG_SUPERCRUISE, StatusSnapshot
        from game_settings import GameSettings
        from plot_sys_status import sys_status_allowed

        flying = StatusSnapshot(
            flags=FLAG_SUPERCRUISE,
            flags2=0,
            fuel_main=8.0,
            fuel_reservoir=0.3,
            cargo_mass=0.0,
            legal_state=None,
            balance=None,
            destination=None,
            body_name=None,
            gui_focus=0,
        )
        survey = SurveyState(system="Sol")
        game = GameSettings(autoShowPlotSysStatus=True, useExternalData=True)
        clear_cache()
        self.assertFalse(sys_status_allowed(game, survey, flying))
        _cache_set("poi:sol/unknown", empty_system_poi("Sol", "Unknown"))
        self.assertTrue(sys_status_allowed(game, survey, flying))
        _cache_set("poi:sol/unknown", empty_system_poi("Sol", "Unknown"), ttl=0.0)
        self.assertTrue(sys_status_allowed(game, survey, flying))
        clear_cache()

    def test_build_commodities_uses_last_docked_station(self):
        from companion import FLAG_DOCKED, StatusSnapshot
        from game_settings import GameSettings
        from journal import SurveyState
        from panel_build import build_commodities_allowed

        docked_now = StatusSnapshot(
            flags=FLAG_DOCKED,
            flags2=0,
            fuel_main=8.0,
            fuel_reservoir=0.3,
            cargo_mass=0.0,
            legal_state=None,
            balance=None,
            destination=None,
            body_name=None,
            gui_focus=0,
        )
        flying = StatusSnapshot(
            flags=0,
            flags2=0,
            fuel_main=8.0,
            fuel_reservoir=0.3,
            cargo_mass=0.0,
            legal_state=None,
            balance=None,
            destination=None,
            body_name=None,
            gui_focus=0,
        )
        game = GameSettings(
            autoShowPlotBuildCommodities=True,
            buildProjects_TEST=True,
        )
        after_undock = SurveyState(
            last_docked_station="Orbital Construction Site: Alpha",
        )
        self.assertFalse(build_commodities_allowed(game, flying, after_undock))
        self.assertTrue(build_commodities_allowed(game, docked_now, after_undock))

    def test_build_commodities_shows_on_construction_destination(self):
        from companion import FLAG_DOCKED, FLAG_SUPERCRUISE, StatusSnapshot
        from game_settings import GameSettings
        from journal import SurveyState
        from panel_build import build_commodities_allowed

        game = GameSettings(
            autoShowPlotBuildCommodities=True,
            buildProjects_TEST=True,
        )
        site = "$EXT_PANEL_ColonisationShip; Gibbins Beacon"
        sc_to_site = StatusSnapshot(
            flags=FLAG_SUPERCRUISE,
            flags2=0,
            fuel_main=116.0,
            fuel_reservoir=0.5,
            cargo_mass=1232.0,
            legal_state=None,
            balance=None,
            destination=site,
            body_name=None,
            gui_focus=0,
        )
        haul = SurveyState(
            system="Slegeae CG-C a81-0",
            in_supercruise=True,
            last_construction_station=site,
        )
        self.assertTrue(build_commodities_allowed(game, sc_to_site, haul))
        self.assertTrue(
            build_commodities_allowed(game, sc_to_site, haul, has_projects=True)
        )
        fc_pad = StatusSnapshot(
            flags=FLAG_DOCKED,
            flags2=0,
            fuel_main=116.0,
            fuel_reservoir=0.5,
            cargo_mass=0.0,
            legal_state=None,
            balance=None,
            destination=None,
            body_name=None,
            gui_focus=0,
        )
        at_fc = SurveyState(
            docked=True,
            docked_station="G0M-7QH",
            last_docked_station="G0M-7QH",
            last_construction_station=site,
        )
        self.assertTrue(
            build_commodities_allowed(game, fc_pad, at_fc, has_projects=True)
        )
        galmap = StatusSnapshot(
            flags=FLAG_SUPERCRUISE,
            flags2=0,
            fuel_main=116.0,
            fuel_reservoir=0.5,
            cargo_mass=1232.0,
            legal_state=None,
            balance=None,
            destination=site,
            body_name=None,
            gui_focus=6,
        )
        self.assertFalse(build_commodities_allowed(game, galmap, haul))
        from journal import read_session

        persisted = read_session(
            "\n".join(
                [
                    '{"event":"Docked","StationName":"$EXT_PANEL_ColonisationShip; Gibbins Beacon","SystemAddress":1,"MarketID":2}',
                    '{"event":"Undocked","StationName":"$EXT_PANEL_ColonisationShip; Gibbins Beacon"}',
                    '{"event":"Docked","StationName":"G0M-7QH","StationType":"FleetCarrier","SystemAddress":1,"MarketID":3}',
                    '{"event":"Undocked","StationName":"G0M-7QH"}',
                ]
            )
        )
        self.assertEqual(
            persisted.survey.last_construction_station,
            "$EXT_PANEL_ColonisationShip; Gibbins Beacon",
        )
        self.assertEqual(persisted.survey.last_docked_station, "G0M-7QH")
        self.assertFalse(persisted.survey.docked)


class WatcherTests(unittest.TestCase):
    def test_watcher_tails_new_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            path = folder / "Journal.2026-09-26T120000.01.log"
            path.write_text(JOURNAL + "\n", encoding="utf-8")
            (folder / "Status.json").write_text(STATUS_JSON, encoding="utf-8")
            (folder / "Cargo.json").write_text(CARGO_JSON, encoding="utf-8")
            (folder / "ShipLocker.json").write_text(LOCKER_JSON, encoding="utf-8")
            (folder / "NavRoute.json").write_text(NAV_ROUTE_JSON, encoding="utf-8")
            watcher = JournalWatcher(folder)
            first = watcher.poll()
            self.assertEqual(first.session.location.system, "Shinrarta Dezhra")
            self.assertIsNotNone(first.status)
            self.assertIsNotNone(first.cargo)
            self.assertEqual(first.cargo.count, 12)
            self.assertIsNotNone(first.locker)
            self.assertEqual(first.locker.total_count, 5)
            self.assertIsNotNone(first.nav_route)
            self.assertEqual(len(first.nav_route.hops), 3)

            extra = json.dumps({
                "timestamp": "2026-09-26T01:10:00Z",
                "event": "FSDJump",
                "StarSystem": "Alioth",
                "SystemAddress": 1109989017963,
            })
            with path.open("a", encoding="utf-8") as handle:
                handle.write(extra + "\n")
            # Ensure mtime can differ on coarse filesystems.
            time.sleep(0.01)
            second = watcher.poll()
            self.assertEqual(second.session.location.system, "Alioth")
            self.assertTrue(any(e.get("event") == "FSDJump" for e in second.new_events))


class PlotFssInfoTests(unittest.TestCase):
    def test_fss_info_lines_and_force_render(self):
        from journal import FssBodyEntry, SurveyState
        from plot_fss_info import fss_info_lines, render_fss_info_bitmap

        body = FssBodyEntry(
            body_id=1,
            body_name="Demo 1",
            short_name="1",
            body_type="LandableBody",
            planet_class="High metal content body",
            terraformable=True,
            landable=True,
            was_discovered=False,
            reward=50_000,
            dss_reward=200_000,
            bio_signal_count=2,
        )
        survey = SurveyState(system="Demo", fss_bodies=(body,))
        rows = fss_info_lines(survey)
        self.assertTrue(any("Demo" in r[0] for r in rows))
        self.assertTrue(any("(T)" in r[0] for r in rows))
        rendered = render_fss_info_bitmap(survey, force_show=True)
        self.assertIsNotNone(rendered)
        rgba, w, h = rendered
        self.assertGreater(w, 100)
        self.assertGreater(h, 40)
        self.assertEqual(len(rgba), w * h * 4)

    def test_fss_last_scan_panel(self):
        from journal import FssBodyEntry, SurveyState
        from plot_fss import render_fss_bitmap

        body = FssBodyEntry(
            body_id=2,
            body_name="Demo 2",
            short_name="2",
            body_type="SolidBody",
            planet_class="Icy body",
            reward=12_000,
            dss_reward=40_000,
            distance_from_arrival_ls=450.0,
        )
        survey = SurveyState(system="Demo", fss_bodies=(body,))
        self.assertIsNone(render_fss_bitmap(survey))
        rendered = render_fss_bitmap(survey, force_show=True)
        self.assertIsNotNone(rendered)
        rgba, w, h = rendered
        self.assertEqual(len(rgba), w * h * 4)

    def test_human_site_approach_overlay(self):
        from companion import FLAG_HAS_LAT_LONG, FLAG_IN_MAIN_SHIP, parse_status
        from journal import HumanStation, SurveyState, read_session
        from plot_human_site import (
            human_site_allowed,
            human_site_lines,
            render_human_site_bitmap,
        )

        journal = "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-09-26T02:00:00Z",
                        "event": "Location",
                        "StarSystem": "Yami",
                        "SystemAddress": 2868367467953,
                        "Body": "Yami A 1",
                        "Factions": [
                            {
                                "Name": "Yami & Co",
                                "Influence": 0.42,
                                "MyReputation": 50.0,
                            }
                        ],
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-09-26T02:01:00Z",
                        "event": "ApproachSettlement",
                        "Name": "Omenuko Extraction Base",
                        "MarketID": 3928215040,
                        "StationFaction": {
                            "Name": "Yami & Co",
                            "FactionState": "None",
                        },
                        "StationGovernment": "$government_Corporate;",
                        "StationGovernment_Localised": "Corporate",
                        "StationServices": [
                            "dock",
                            "autodock",
                            "commodities",
                            "facilitator",
                        ],
                        "StationEconomy": "$economy_Extraction;",
                        "StationEconomy_Localised": "Extraction",
                        "SystemAddress": 2868367467953,
                        "BodyID": 5,
                        "BodyName": "Yami A 1",
                        "Latitude": 0.550911,
                        "Longitude": -31.254198,
                    }
                ),
            ]
        )
        survey = read_session(journal).survey
        self.assertIsNotNone(survey.system_station)
        assert survey.system_station is not None
        self.assertEqual(survey.system_station.name, "Omenuko Extraction Base")
        self.assertEqual(survey.system_station.faction_name, "Yami & Co")
        self.assertAlmostEqual(survey.system_station.reputation or 0, 50.0)

        status = parse_status(
            json.dumps(
                {
                    "Flags": FLAG_HAS_LAT_LONG | FLAG_IN_MAIN_SHIP,
                    "Flags2": 0,
                    "Latitude": 0.56,
                    "Longitude": -31.25,
                    "Altitude": 1200,
                    "PlanetRadius": 3200000,
                    "BodyName": "Yami A 1",
                }
            )
        )
        gs = GameSettings()
        self.assertTrue(human_site_allowed(gs, status, survey))
        rows = human_site_lines(survey, status)
        joined = " ".join(r[0] for r in rows)
        self.assertIn("Omenuko Extraction Base", joined)
        self.assertIn("On approach", joined)
        self.assertIn("Yami & Co", joined)
        rendered = render_human_site_bitmap(survey, status, game=gs)
        self.assertIsNotNone(rendered)
        rgba, w, h = rendered
        self.assertEqual(len(rgba), w * h * 4)
        self.assertGreater(w, 100)
        self.assertGreater(h, 40)

        empty = SurveyState(system="Yami")
        self.assertFalse(human_site_allowed(gs, status, empty))
        self.assertIsNone(render_human_site_bitmap(empty, status, game=gs))
        forced = render_human_site_bitmap(
            SurveyState(
                system="Yami",
                system_station=HumanStation(
                    name="Test Site",
                    market_id=1,
                    latitude=1.0,
                    longitude=2.0,
                ),
            ),
            status,
            game=gs,
            force_show=True,
        )
        self.assertIsNotNone(forced)


class BioStatusPlotterTests(unittest.TestCase):
    def test_bio_status_lines_and_bitmap(self):
        from companion import FLAG_SUPERCRUISE
        from plot_bio_status import (
            bio_status_allowed,
            bio_status_lines,
            meters_to_string,
            render_bio_status_bitmap,
        )

        session = read_session(JOURNAL)
        loc = session.location
        survey = session.survey
        rows = bio_status_lines(survey, loc)
        joined = " ".join(text for text, _colour, _strike in rows)
        self.assertIn("Biological signals", joined)
        # Sample in progress → current-genus view (species), not full genus list
        self.assertIn("Bacterium", joined)
        self.assertIn("Sample", joined)
        self.assertNotIn("Fonticulua", joined)

        docked = parse_status(STATUS_JSON)
        self.assertFalse(
            bio_status_allowed(GameSettings(), survey, loc, docked)
        )
        self.assertIsNone(
            render_bio_status_bitmap(survey, loc, status=docked)
        )

        flying = parse_status(
            json.dumps(
                {
                    "timestamp": "2026-09-26T00:40:00Z",
                    "event": "Status",
                    "Flags": FLAG_SUPERCRUISE,
                    "Flags2": 0,
                    "Fuel": {"FuelMain": 4.5, "FuelReservoir": 0.3},
                    "Cargo": 0,
                    "LegalState": "Clean",
                    "BodyName": loc.body,
                }
            )
        )
        self.assertTrue(
            bio_status_allowed(GameSettings(), survey, loc, flying)
        )
        rendered = render_bio_status_bitmap(survey, loc, status=flying)
        self.assertIsNotNone(rendered)
        rgba, w, h = rendered
        self.assertGreaterEqual(w, 200)
        self.assertGreaterEqual(h, 40)
        self.assertEqual(len(rgba), w * h * 4)

        off = GameSettings(autoShowBioSummary=False)
        self.assertFalse(AppSettings(game=off).panel_enabled("biostatus"))
        self.assertTrue(AppSettings().panel_enabled("biostatus"))
        self.assertEqual(meters_to_string(500), "500m")
        self.assertEqual(meters_to_string(1500), "1.5km")


class BioSystemPlotterTests(unittest.TestCase):
    def test_bio_system_lines_bitmap_and_gate(self):
        from companion import FLAG_HAS_LAT_LONG, FLAG_IN_MAIN_SHIP, FLAG_SUPERCRUISE
        from plot_bio_system import (
            bio_system_allowed,
            bio_system_lines,
            get_min_max_credits,
            render_bio_system_bitmap,
        )

        session = read_session(JOURNAL)
        loc = session.location
        survey = session.survey

        # Docked → not allowed (wrong mode)
        docked = parse_status(STATUS_JSON)
        self.assertFalse(
            bio_system_allowed(GameSettings(), survey, loc, docked)
        )
        self.assertIsNone(
            render_bio_system_bitmap(survey, loc, status=docked)
        )

        # Supercruise → system overview
        sc = parse_status(
            json.dumps(
                {
                    "timestamp": "2026-09-26T00:40:00Z",
                    "event": "Status",
                    "Flags": FLAG_SUPERCRUISE,
                    "Flags2": 0,
                    "Fuel": {"FuelMain": 4.5, "FuelReservoir": 0.3},
                    "Cargo": 0,
                    "LegalState": "Clean",
                    "BodyName": loc.body,
                }
            )
        )
        self.assertTrue(bio_system_allowed(GameSettings(), survey, loc, sc))
        rows = bio_system_lines(survey, loc, status=sc)
        joined = " ".join(text for text, _c, _s in rows)
        self.assertIn("Bio signals:", joined)
        self.assertTrue("A 1" in joined or "A1" in joined)
        rendered = render_bio_system_bitmap(survey, loc, status=sc)
        self.assertIsNotNone(rendered)
        rgba, w, h = rendered
        self.assertGreaterEqual(w, 160)
        self.assertGreaterEqual(h, 40)
        self.assertEqual(len(rgba), w * h * 4)

        # Surface fix on bio body → body detail view
        surface = parse_status(
            json.dumps(
                {
                    "timestamp": "2026-09-26T00:40:00Z",
                    "event": "Status",
                    "Flags": FLAG_IN_MAIN_SHIP | FLAG_HAS_LAT_LONG,
                    "Flags2": 0,
                    "Fuel": {"FuelMain": 4.5, "FuelReservoir": 0.3},
                    "Cargo": 0,
                    "LegalState": "Clean",
                    "BodyName": loc.body,
                    "Latitude": 10.0,
                    "Longitude": 20.0,
                }
            )
        )
        self.assertTrue(
            bio_system_allowed(GameSettings(), survey, loc, surface)
        )
        body_rows = bio_system_lines(survey, loc, status=surface)
        body_joined = " ".join(text for text, _c, _s in body_rows)
        self.assertIn("Body", body_joined)
        self.assertIn("Bacterium", body_joined)
        self.assertIn("Fonticulua", body_joined)
        body_bmp = render_bio_system_bitmap(survey, loc, status=surface)
        self.assertIsNotNone(body_bmp)

        off = GameSettings(autoShowPlotBioSystem=False)
        self.assertFalse(AppSettings(game=off).panel_enabled("biosystem"))
        self.assertTrue(AppSettings().panel_enabled("biosystem"))
        self.assertEqual(get_min_max_credits(0, 0), "")
        self.assertIn("K", get_min_max_credits(5_000, 5_000))
        self.assertIn("~", get_min_max_credits(1_000_000, 5_000_000))


class RavenColonialTests(unittest.TestCase):
    def test_sum_cargo_merges_normalized_keys(self):
        from raven_colonial import FleetCarrier, clear_cache, sum_cargo

        clear_cache()
        fcs = [
            FleetCarrier(
                market_id=1,
                name="A-AAA",
                display_name="Alpha",
                cargo={"Steel": 10, "liquid oxygen": 2},
            ),
            FleetCarrier(
                market_id=2,
                name="B-BBB",
                display_name="Beta",
                cargo={"steel": 5, "LiquidOxygen": 3},
            ),
        ]
        self.assertEqual(sum_cargo(fcs), {"steel": 15, "liquidoxygen": 5})

    def test_pending_updates_counter(self):
        from raven_colonial import end_pending, pending_count, start_pending

        while pending_count() > 0:
            end_pending()
        self.assertEqual(pending_count(), 0)
        start_pending()
        start_pending()
        self.assertEqual(pending_count(), 2)
        end_pending()
        self.assertEqual(pending_count(), 1)
        end_pending()
        self.assertEqual(pending_count(), 0)
        end_pending()
        self.assertEqual(pending_count(), 0)

    def test_offline_env_skips_http(self):
        from raven_colonial import clear_cache, get_cmdr_fleet_carriers, get_fc

        clear_cache()
        prev = os.environ.get("SRVSURVEY_RCC_OFFLINE")
        os.environ["SRVSURVEY_RCC_OFFLINE"] = "1"
        try:
            self.assertEqual(get_cmdr_fleet_carriers("Anyone"), [])
            self.assertIsNone(get_fc(12345))
        finally:
            if prev is None:
                os.environ.pop("SRVSURVEY_RCC_OFFLINE", None)
            else:
                os.environ["SRVSURVEY_RCC_OFFLINE"] = prev

    def test_build_projects_url_setting_parses(self):
        gs = GameSettings.from_flat(
            {"gs.buildProjectsUrl_TEST": "https://example.test/rcc"}
        )
        self.assertEqual(gs.buildProjectsUrl_TEST, "https://example.test/rcc")

    def test_game_settings_numeric_from_flat(self):
        gs = GameSettings.from_flat(
            {
                "gs.plotterOpacity": "75",
                "gs.skipLowValueAmount": "2500000",
                "gs.hideFssLowValueAmount": "50000",
                "gs.bioRingBucketOne": "4.5",
                "gs.humanSiteZoomSRV": "2.25",
                "gs.highGravityWarningLevel": "1.5",
                "gs.bodyInfoBubbleSize": "250",
            }
        )
        self.assertEqual(gs.plotterOpacity, 75.0)
        self.assertEqual(gs.skipLowValueAmount, 2_500_000)
        self.assertEqual(gs.hideFssLowValueAmount, 50_000)
        self.assertEqual(gs.bioRingBucketOne, 4.5)
        self.assertEqual(gs.humanSiteZoomSRV, 2.25)
        self.assertEqual(gs.highGravityWarningLevel, 1.5)
        self.assertEqual(gs.bodyInfoBubbleSize, 250)
        # Defaults preserved when key absent
        self.assertEqual(gs.skipHighDistanceDSSValue, 100_000)

    def test_theme_hex_parse_and_defaults(self):
        from theme import (
            DEFAULT_BANNER,
            DEFAULT_CYAN,
            DEFAULT_DARK_CYAN,
            DEFAULT_ORANGE,
            DEFAULT_ORANGE_DIM,
            banner,
            clear_cache,
            cyan,
            dark_cyan,
            orange,
            orange_dim,
            parse_hex,
            to_hex,
        )

        clear_cache()
        self.assertEqual(parse_hex("#FF6F00"), DEFAULT_ORANGE)
        self.assertEqual(parse_hex("FF6F00"), DEFAULT_ORANGE)
        self.assertEqual(parse_hex("#F60"), (255, 102, 0, 255))
        self.assertEqual(parse_hex("#80FF6F00"), (255, 111, 0, 128))
        self.assertEqual(parse_hex("not-a-colour", DEFAULT_CYAN), DEFAULT_CYAN)
        self.assertEqual(parse_hex(None, DEFAULT_ORANGE_DIM), DEFAULT_ORANGE_DIM)
        self.assertEqual(to_hex(DEFAULT_ORANGE), "#FF6F00")
        self.assertEqual(to_hex((255, 111, 0, 128), include_alpha=True), "#80FF6F00")

        self.assertEqual(orange(), DEFAULT_ORANGE)
        self.assertEqual(orange_dim(), DEFAULT_ORANGE_DIM)
        self.assertEqual(cyan(), DEFAULT_CYAN)
        self.assertEqual(dark_cyan(), DEFAULT_DARK_CYAN)
        self.assertEqual(banner(), DEFAULT_BANNER)

        custom = GameSettings(
            defaultOrange="#112233",
            defaultOrangeDim="#445566",
            defaultCyan="#778899",
            defaultDarkCyan="#AABBCC",
            screenshotBannerColor="#FFFF00",
        )
        self.assertEqual(orange(custom), (0x11, 0x22, 0x33, 255))
        self.assertEqual(orange_dim(custom), (0x44, 0x55, 0x66, 255))
        self.assertEqual(cyan(custom), (0x77, 0x88, 0x99, 255))
        self.assertEqual(dark_cyan(custom), (0xAA, 0xBB, 0xCC, 255))
        self.assertEqual(banner(custom), DEFAULT_BANNER)

    def test_game_settings_colour_and_screenshot_from_flat(self):
        from theme import DEFAULT_ORANGE_HEX, orange

        gs = GameSettings.from_flat(
            {
                "gs.defaultOrange": "#AABBCC",
                "gs.defaultCyan": "#12DEFA",
                "gs.screenshotBannerColor": "#FFFF00",
                "gs.screenshotSourceFolder": "/tmp/ed-shots",
                "gs.screenshotTargetFolder": "/tmp/ed-shots/converted",
                "gs.materialCountAfterPickup": "false",
                "gs.showScreenshot": "0",
            }
        )
        self.assertEqual(gs.defaultOrange, "#AABBCC")
        self.assertEqual(gs.defaultCyan, "#12DEFA")
        self.assertEqual(gs.screenshotBannerColor, "#FFFF00")
        self.assertEqual(gs.screenshotSourceFolder, "/tmp/ed-shots")
        self.assertEqual(gs.screenshotTargetFolder, "/tmp/ed-shots/converted")
        self.assertFalse(gs.materialCountAfterPickup)
        self.assertFalse(gs.showScreenshot)
        self.assertEqual(orange(gs), (0xAA, 0xBB, 0xCC, 255))

        defaults = GameSettings()
        self.assertEqual(defaults.defaultOrange, DEFAULT_ORANGE_HEX)
        self.assertTrue(defaults.screenshotSourceFolder.endswith("Elite Dangerous"))
        self.assertTrue(defaults.screenshotTargetFolder.endswith("converted"))
        self.assertTrue(defaults.cargoMissionRemaining)
        self.assertTrue(defaults.currentBoxelSearchStatus)
        self.assertTrue(defaults.showNextBoxelToSearch)

    def test_game_settings_numeric_round_trip(self):
        from config import settings_to_key_value

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config"
            settings = AppSettings(
                game=GameSettings(
                    plotterOpacity=80.0,
                    skipLowValueAmount=1_500_000,
                    hideFssLowValueAmount=25_000,
                    bioRingBucketTwo=8.5,
                    humanSiteZoomInside=5.5,
                    highGravityWarningLevel=2.0,
                    bodyInfoBubbleSize=300,
                )
            )
            saved = save_settings(settings, path)
            text = saved.read_text(encoding="utf-8")
            self.assertIn("gs.plotterOpacity=80", text)
            self.assertIn("gs.skipLowValueAmount=1500000", text)
            self.assertIn("gs.hideFssLowValueAmount=25000", text)
            self.assertIn("gs.bioRingBucketTwo=8.5", text)
            self.assertIn("gs.humanSiteZoomInside=5.5", text)
            self.assertIn("gs.highGravityWarningLevel=2", text)
            self.assertIn("gs.bodyInfoBubbleSize=300", text)
            loaded = load_settings(config_paths=[saved])
            self.assertEqual(loaded.game.plotterOpacity, 80.0)
            self.assertEqual(loaded.game.skipLowValueAmount, 1_500_000)
            self.assertEqual(loaded.game.hideFssLowValueAmount, 25_000)
            self.assertEqual(loaded.game.bioRingBucketTwo, 8.5)
            self.assertEqual(loaded.game.humanSiteZoomInside, 5.5)
            self.assertEqual(loaded.game.highGravityWarningLevel, 2.0)
            self.assertEqual(loaded.game.bodyInfoBubbleSize, 300)
            again = settings_to_key_value(loaded)
            self.assertIn("gs.plotterOpacity=80", again)

    def test_settings_windows_labels_and_lock(self):
        from settings_labels import BIO_PLOT_SIZES, FIELD_LABELS, field_label
        from settings_lock import (
            acquire_settings_lock,
            release_settings_lock,
            settings_is_open,
            settings_lock_path,
        )

        self.assertEqual(
            field_label("autoShowBioSummary"),
            "Show biological signal summary",
        )
        self.assertEqual(
            field_label("buildProjects_TEST"),
            "Enable colonisation features",
        )
        self.assertEqual(
            field_label("humanSiteShow_Medkit"),
            "Med kits",
        )
        self.assertIn("Large - 380 x 500", BIO_PLOT_SIZES)
        for name in (
            "autoShowBioPlot",
            "enableGuardianSites",
            "processScreenshots",
            "autoShowPlotFSS",
            "autoShowHumanSitesTest",
            "autoShowFlightWarnings",
        ):
            self.assertIn(name, FIELD_LABELS)

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            env = {
                "XDG_DATA_HOME": str(home / "share"),
                "XDG_CONFIG_HOME": str(home / "config"),
            }
            path = settings_lock_path(environ=env, home=home)
            self.assertEqual(path, Path(env["XDG_CONFIG_HOME"]) / "srvsurvey" / "settings.lock")
            self.assertFalse(path.is_file())
            self.assertTrue(acquire_settings_lock(environ=env, home=home, pid=1))
            self.assertTrue(path.is_file())
            self.assertIn("srvsurvey-settings", path.read_text(encoding="utf-8"))
            self.assertFalse(settings_is_open(environ=env, home=home))
            data_copy = Path(env["XDG_DATA_HOME"]) / "srvsurvey" / "settings.lock"
            self.assertTrue(data_copy.is_file())
            release_settings_lock(environ=env, home=home, pid=1)
            self.assertFalse(path.is_file())
            self.assertFalse(data_copy.is_file())


class CodexRefTests(unittest.TestCase):
    def test_brain_tree_and_fonticulua_rewards(self):
        from codex_ref import (
            format_credits,
            max_reward_for_genus,
            reset_cache,
            reward_for_species,
        )

        reset_cache()
        self.assertEqual(reward_for_species("Roseum Brain Tree"), 1_593_700)
        self.assertEqual(max_reward_for_genus("Brain Tree"), 1_593_700)
        self.assertGreaterEqual(max_reward_for_genus("Fonticulua"), 1_000_000)
        self.assertEqual(format_credits(1_593_700), "1,593,700 cr")
        self.assertEqual(format_credits(0), "—")

    def test_body_info_bio_reward_range(self):
        from journal import (
            BodySignals,
            FssBodyEntry,
            OrganicProgress,
            SurveyState,
        )
        from plot_body_info import bio_reward_range, format_bio_reward_credits, genuses_for_body

        body = FssBodyEntry(
            body_id=1,
            body_name="Demo A 1",
            short_name="A 1",
            body_type="LandableBody",
            bio_signal_count=2,
        )
        survey = SurveyState(
            body_signals=(
                BodySignals(
                    body_name="Demo A 1",
                    bio_count=2,
                    geo_count=0,
                    genuses=("Brain Tree", "Bacterium"),
                ),
            ),
            organic_progress=(
                OrganicProgress(
                    genus="Brain Tree",
                    species="Roseum Brain Tree",
                    scan_type="Log",
                    body_name="Demo A 1",
                ),
            ),
        )
        genuses = genuses_for_body(survey, body)
        self.assertEqual(genuses, ["Brain Tree", "Bacterium"])
        lo2, hi2 = bio_reward_range(survey, ["Brain Tree"])
        self.assertEqual(lo2, 1_593_700)
        self.assertEqual(hi2, 1_593_700)
        lo, hi = bio_reward_range(survey, genuses)
        self.assertGreaterEqual(lo, 1_593_700)
        self.assertGreaterEqual(hi, lo)
        txt = format_bio_reward_credits(lo2, hi2)
        self.assertTrue(txt)
        self.assertNotIn("—", txt)

    def test_pending_footer_renders(self):
        from colony import BuildListModel, ConstructionDepot, DepotNeed
        from panel_build import render_build_commodities_bitmap

        depot = ConstructionDepot(
            market_id=1,
            progress=0.1,
            complete=False,
            failed=False,
            needs=(DepotNeed(key="steel", label="Steel", need=100, required=100, provided=0),),
            title="Test Site",
        )
        model = BuildListModel(
            header="Test",
            depot=depot,
            pending_updates=1,
            assigned_me=frozenset({"steel"}),
        )
        raw, w, h = render_build_commodities_bitmap(model, show_fc=False)
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)
        self.assertGreater(len(raw), 100)

    def test_build_list_ship_column_is_hold_count_not_delta(self):
        from panel_build import fc_column_value, ship_column_value, trips_needed

        self.assertIsNone(ship_column_value(0))
        self.assertEqual(ship_column_value(1232), 1232)
        self.assertEqual(fc_column_value(4382, 0, show_delta=False), ("abs", 0))
        self.assertEqual(fc_column_value(100, 40, show_delta=True), ("delta", -60))
        self.assertEqual(trips_needed(3631, 1232), 3)
        self.assertEqual(trips_needed(3631, 720), 6)
        self.assertEqual(trips_needed(3631, 0), 0)

    def test_build_list_marks_gathered_commodities_green(self):
        from colony import cargo_counts, cargo_qty
        from companion import parse_cargo
        from panel_build import SURPLUS, commodity_gathered

        cargo = parse_cargo(
            '{"event":"Cargo","Vessel":"Ship","Count":3,'
            '"Inventory":['
            '{"Name":"steel","Count":686},'
            '{"Name":"computercomponents","Name_Localised":"Computer Components","Count":41}'
            "]}"
        )
        counts = cargo_counts(cargo)
        self.assertEqual(counts["steel"], 686)
        self.assertEqual(counts["computercomponents"], 41)
        self.assertEqual(cargo_qty({"microbialfurnaces": 4}, "heliostaticfurnaces"), 4)

        ship_enough, fc_enough, have_enough = commodity_gathered(686, 686)
        self.assertTrue(ship_enough)
        self.assertFalse(fc_enough)
        self.assertTrue(have_enough)

        ship_enough, fc_enough, have_enough = commodity_gathered(
            62, 41, 174, use_fc=True
        )
        self.assertFalse(ship_enough)
        self.assertTrue(fc_enough)
        self.assertTrue(have_enough)
        self.assertEqual(SURPLUS[1], 255)

        ship_enough, fc_enough, have_enough = commodity_gathered(
            13, 0, 13, use_fc=True
        )
        self.assertTrue(have_enough)
        self.assertTrue(fc_enough)

        ship_enough, _, have_enough = commodity_gathered(100, 40, 60, use_fc=True)
        self.assertFalse(ship_enough)
        self.assertTrue(have_enough)

    def test_build_list_keeps_single_commodity_visible(self):
        from panel_build import category_should_collapse

        one = [("computercomponents", 8)]
        two = [("computercomponents", 8), ("muonimager", 4)]
        fc = {"computercomponents": 174, "muonimager": 10}
        empty: dict[str, int] = {}
        self.assertFalse(
            category_should_collapse(
                one, fc, empty, collapse_enabled=True, use_fc=True
            )
        )
        self.assertTrue(
            category_should_collapse(
                two, fc, empty, collapse_enabled=True, use_fc=True
            )
        )
        self.assertFalse(
            category_should_collapse(
                two,
                fc,
                {"computercomponents": 1},
                collapse_enabled=True,
                use_fc=True,
            )
        )


class StationAndFlightWarningTests(unittest.TestCase):
    def test_station_info_from_docked_and_render(self):
        from companion import StatusSnapshot
        from journal import LandingPads, SurveyState, station_from_docked
        from plot_station_info import (
            render_station_info_bitmap,
            station_info_allowed,
            station_info_lines,
        )

        docked = {
            "timestamp": "2026-09-26T12:00:00Z",
            "event": "Docked",
            "StationName": "Jameson Memorial",
            "StationType": "Orbis",
            "MarketID": 128666762,
            "StationEconomy_Localised": "High Tech",
            "StationGovernment_Localised": "Democracy",
            "StationFaction": {"Name": "Pilots Federation Local", "FactionState": "None"},
            "StationServices": ["shipyard", "outfitting", "refuel", "commodities", "techBroker"],
            "StationEconomies": [
                {"Name_Localised": "High Tech", "Proportion": 0.7},
                {"Name_Localised": "Industrial", "Proportion": 0.3},
            ],
            "LandingPads": {"Small": 4, "Medium": 4, "Large": 4},
        }
        station = station_from_docked(docked)
        self.assertIsNotNone(station)
        assert station is not None
        self.assertEqual(station.name, "Jameson Memorial")
        self.assertEqual(station.landing_pads, LandingPads(4, 4, 4))
        self.assertIn("Technology Broker", station.services)

        rows = station_info_lines(station, ship_type="sidewinder")
        joined = " ".join(t for t, _ in rows)
        self.assertIn("Jameson Memorial", joined)
        self.assertIn("Pads: Large", joined)
        self.assertIn("High Tech", joined)
        self.assertIn("Technology Broker", joined)

        survey = SurveyState(
            system="Shinrarta Dezhra",
            system_address=3932277478106,
            stations=(station,),
            ship_type="sidewinder",
        )
        status = StatusSnapshot(
            flags=0,
            flags2=0,
            fuel_main=None,
            fuel_reservoir=None,
            cargo_mass=None,
            legal_state=None,
            balance=None,
            destination="Jameson Memorial",
            body_name=None,
            gui_focus=2,
            destination_system=3932277478106,
        )
        self.assertTrue(station_info_allowed(GameSettings(), survey, status))
        rendered = render_station_info_bitmap(survey, status=status)
        self.assertIsNotNone(rendered)
        rgba, w, h = rendered
        self.assertEqual(len(rgba), w * h * 4)

        # Construction sites are ignored
        bad = StatusSnapshot(
            flags=0,
            flags2=0,
            fuel_main=None,
            fuel_reservoir=None,
            cargo_mass=None,
            legal_state=None,
            balance=None,
            destination="Orbital Construction Site: Demo",
            body_name=None,
            gui_focus=2,
            destination_system=3932277478106,
        )
        self.assertFalse(station_info_allowed(GameSettings(), survey, bad))

    def test_flight_warning_high_gravity(self):
        from companion import FLAG_IN_MAIN_SHIP, FLAG_SUPERCRUISE, StatusSnapshot
        from journal import CommanderLocation, FssBodyEntry, SurveyState
        from plot_flight_warning import (
            flight_warning_allowed,
            render_flight_warning_bitmap,
            warning_text,
        )

        body = FssBodyEntry(
            body_id=3,
            body_name="Demo A",
            short_name="A",
            body_type="LandableBody",
            landable=True,
            surface_gravity=25.0,  # 2.5g
        )
        survey = SurveyState(system="Demo", fss_bodies=(body,))
        loc = CommanderLocation("Demo", "Cmdr", "Demo A")
        status = StatusSnapshot(
            flags=FLAG_SUPERCRUISE | FLAG_IN_MAIN_SHIP,
            flags2=0,
            fuel_main=None,
            fuel_reservoir=None,
            cargo_mass=None,
            legal_state=None,
            balance=None,
            destination=None,
            body_name="Demo A",
            gui_focus=0,
        )
        self.assertEqual(warning_text(25.0), "Warning: Surface gravity 2.50g")
        self.assertTrue(
            flight_warning_allowed(GameSettings(), survey, location=loc, status=status)
        )
        rendered = render_flight_warning_bitmap(
            survey, location=loc, status=status
        )
        self.assertIsNotNone(rendered)
        rgba, w, h = rendered
        self.assertEqual(len(rgba), w * h * 4)

        low = FssBodyEntry(
            body_id=4,
            body_name="Demo B",
            short_name="B",
            body_type="LandableBody",
            landable=True,
            surface_gravity=5.0,  # 0.5g
        )
        low_survey = SurveyState(system="Demo", fss_bodies=(low,))
        low_status = StatusSnapshot(
            flags=FLAG_SUPERCRUISE | FLAG_IN_MAIN_SHIP,
            flags2=0,
            fuel_main=None,
            fuel_reservoir=None,
            cargo_mass=None,
            legal_state=None,
            balance=None,
            destination=None,
            body_name="Demo B",
            gui_focus=0,
        )
        self.assertFalse(
            flight_warning_allowed(
                GameSettings(), low_survey, status=low_status
            )
        )

    def test_station_flightwarn_panel_gates(self):
        settings = AppSettings()
        self.assertTrue(settings.panel_enabled("station"))
        self.assertTrue(settings.panel_enabled("flightwarn"))
        off = settings_from_dict(
            {
                "gs.autoShowPlotStationInfo_TEST": "false",
                "gs.autoShowFlightWarnings": "false",
            }
        )
        self.assertFalse(off.panel_enabled("station"))
        self.assertFalse(off.panel_enabled("flightwarn"))


class PriorScansTrackersFloatieTests(unittest.TestCase):
    def test_canonn_offline_stub(self):
        from canonn import clear_cache, get_system_poi, has_local_bio_signals

        clear_cache()
        prev = os.environ.get("SRVSURVEY_CANONN_OFFLINE")
        os.environ["SRVSURVEY_CANONN_OFFLINE"] = "1"
        try:
            poi = get_system_poi("Colonia", "Test")
            self.assertEqual(poi.system, "Colonia")
            self.assertEqual(poi.codex, [])
            self.assertFalse(has_local_bio_signals(poi, "A 1"))
        finally:
            if prev is None:
                os.environ.pop("SRVSURVEY_CANONN_OFFLINE", None)
            else:
                os.environ["SRVSURVEY_CANONN_OFFLINE"] = prev
            clear_cache()

    def test_prior_scans_render_with_injected_poi(self):
        from canonn import CodexPoi, SystemPoi
        from companion import FLAG_HAS_LAT_LONG, FLAG_IN_MAIN_SHIP, StatusSnapshot
        from journal import CommanderLocation, SurveyState
        from plot_prior_scans import build_prior_signals, render_prior_scans_bitmap

        poi = SystemPoi(
            system="Demo",
            codex=[
                CodexPoi(
                    body="A 1",
                    english_name="Bacterium Informem - Lime",
                    entry_id=2320103,
                    hud_category="Biology",
                    latitude=10.0,
                    longitude=20.0,
                )
            ],
        )
        status = StatusSnapshot(
            flags=FLAG_HAS_LAT_LONG | FLAG_IN_MAIN_SHIP,
            flags2=0,
            fuel_main=None,
            fuel_reservoir=None,
            cargo_mass=None,
            legal_state=None,
            balance=None,
            destination=None,
            body_name="Demo A 1",
            gui_focus=0,
            latitude=10.1,
            longitude=20.1,
            heading=90.0,
            altitude=100.0,
            planet_radius=3_000_000.0,
        )
        loc = CommanderLocation("Demo", "Cmdr", "Demo A 1")
        survey = SurveyState(system="Demo")
        signals = build_prior_signals(
            poi, body_short="A 1", status=status, game=GameSettings()
        )
        self.assertEqual(len(signals), 1)
        rendered = render_prior_scans_bitmap(
            survey, loc, status, game=GameSettings(), poi=poi, force_show=True
        )
        self.assertIsNotNone(rendered)
        rgba, w, h = rendered
        self.assertEqual(len(rgba), w * h * 4)

    def test_trackers_from_bookmarks_and_codex_journal(self):
        from companion import FLAG_HAS_LAT_LONG, FLAG_IN_MAIN_SHIP, StatusSnapshot
        from journal import (
            CommanderLocation,
            SurveyState,
            TrackerBookmark,
            read_session,
        )
        from plot_trackers import render_track_target_bitmap, render_trackers_bitmap

        # CodexEntry with organic lat/long → bookmarks
        journal = "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-09-26T00:00:00Z",
                        "event": "Location",
                        "StarSystem": "TrackSys",
                        "SystemAddress": 1,
                        "Body": "TrackSys 1",
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-09-26T00:01:00Z",
                        "event": "CodexEntry",
                        "SystemAddress": 1,
                        "Name": "$Codex_Ent_Bacterial_Name;",
                        "Name_Localised": "Bacterium Informem - Lime",
                        "SubCategory": "$Codex_SubCategory_Organic_Structures;",
                        "Category": "$Codex_Category_Biology;",
                        "Latitude": 12.5,
                        "Longitude": -40.0,
                        "EntryID": 2320103,
                        "Genus_Localised": "Bacterium",
                    }
                ),
            ]
        )
        session = read_session(journal)
        self.assertEqual(len(session.survey.bookmarks), 1)
        self.assertEqual(session.survey.bookmarks[0].name, "Bacterium")

        status = StatusSnapshot(
            flags=FLAG_HAS_LAT_LONG | FLAG_IN_MAIN_SHIP,
            flags2=0,
            fuel_main=None,
            fuel_reservoir=None,
            cargo_mass=None,
            legal_state=None,
            balance=None,
            destination=None,
            body_name="TrackSys 1",
            gui_focus=0,
            latitude=12.6,
            longitude=-40.1,
            heading=0.0,
            altitude=50.0,
            planet_radius=2_500_000.0,
        )
        loc = CommanderLocation("TrackSys", "Cmdr", "TrackSys 1")
        rendered = render_trackers_bitmap(
            session.survey, loc, status, game=GameSettings(), force_show=True
        )
        self.assertIsNotNone(rendered)

        target_gs = GameSettings(
            targetLatLongActive=True, targetLat=12.0, targetLong=-40.0
        )
        target = render_track_target_bitmap(
            session.survey, status, game=target_gs, force_show=True
        )
        self.assertIsNotNone(target)

        # Manual bookmark inject
        survey = SurveyState(
            system="TrackSys",
            bookmarks=(
                TrackerBookmark("Tussock", 1.0, 2.0, body_name="TrackSys 1"),
            ),
        )
        self.assertIsNotNone(
            render_trackers_bitmap(survey, loc, status, force_show=True)
        )

    def test_floatie_show_and_expire(self):
        from datetime import datetime, timedelta

        from plot_floatie import (
            active_messages,
            clear_messages,
            render_floatie_bitmap,
            show_message,
        )

        clear_messages()
        show_message("Hello CMDR", duration_seconds=6)
        self.assertEqual(len(active_messages()), 1)
        rendered = render_floatie_bitmap(game=GameSettings())
        self.assertIsNotNone(rendered)
        rgba, w, h = rendered
        self.assertEqual(len(rgba), w * h * 4)
        # Expired
        self.assertEqual(
            len(active_messages(now=datetime.now() + timedelta(seconds=10))),
            0,
        )
        clear_messages()
        off = GameSettings(autoShowFloatie_TEST=False)
        show_message("Nope")
        self.assertIsNone(render_floatie_bitmap(game=off))
        clear_messages()

    def test_panel_gates_priorscans_trackers_floatie(self):
        settings = AppSettings()
        self.assertFalse(settings.panel_enabled("priorscans"))  # off by default
        self.assertTrue(settings.panel_enabled("trackers"))
        self.assertTrue(settings.panel_enabled("floatie"))
        self.assertTrue(settings.panel_enabled("minitrack"))
        self.assertTrue(settings.panel_enabled("pulse"))
        self.assertFalse(settings.panel_enabled("massacre"))  # off by default
        self.assertFalse(settings.panel_enabled("footcombat"))
        self.assertFalse(settings.panel_enabled("grounded"))
        self.assertFalse(settings.panel_enabled("adjustvr"))
        self.assertFalse(settings.panel_enabled("questmini"))
        self.assertFalse(settings.panel_enabled("tracktarget"))  # needs active target
        on = settings_from_dict(
            {
                "panel.priorscans": "true",
                "panel.massacre": "true",
                "panel.footcombat": "true",
                "panel.grounded": "true",
                "panel.adjustvr": "true",
                "panel.questmini": "true",
                "gs.useExternalData": "true",
                "gs.autoLoadPriorScans": "true",
                "gs.targetLatLongActive": "true",
                "gs.autoShowPlotMassacre_TEST": "true",
                "gs.autoShowFootCombat_TEST": "true",
                "gs.enableQuests": "true",
                "gs.displayVR": "true",
            }
        )
        self.assertTrue(on.panel_enabled("priorscans"))
        self.assertTrue(on.panel_enabled("tracktarget"))
        self.assertTrue(on.panel_enabled("massacre"))
        self.assertTrue(on.panel_enabled("footcombat"))
        self.assertTrue(on.panel_enabled("grounded"))
        self.assertTrue(on.panel_enabled("adjustvr"))
        self.assertTrue(on.panel_enabled("questmini"))
        off = settings_from_dict(
            {
                "panel.priorscans": "true",
                "panel.adjustvr": "true",
                "gs.useExternalData": "false",
                "gs.autoShowFloatie_TEST": "false",
                "gs.autoShowPlotMiniTrack": "false",
                "gs.autoShowPlotMiniTrackRhino": "false",
                "gs.hideJournalWriteTimer": "true",
                "gs.displayVR": "false",
            }
        )
        self.assertFalse(off.panel_enabled("priorscans"))
        self.assertFalse(off.panel_enabled("floatie"))
        self.assertFalse(off.panel_enabled("adjustvr"))
        self.assertFalse(off.panel_enabled("minitrack"))
        self.assertFalse(off.panel_enabled("pulse"))

    def test_massacre_journal_and_render(self):
        from companion import FLAG_IN_MAIN_SHIP, StatusSnapshot
        from journal import read_session
        from plot_massacre import massacre_allowed, render_massacre_bitmap

        journal = "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-09-26T01:00:00Z",
                        "event": "MissionAccepted",
                        "Name": "Mission_Massacre",
                        "Faction": "Giver Inc",
                        "TargetFaction": "Pirate Clan",
                        "KillCount": 5,
                        "MissionID": 42,
                        "Expiry": "2026-09-27T01:00:00Z",
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-09-26T01:05:00Z",
                        "event": "Bounty",
                        "VictimFaction": "Pirate Clan",
                        "TotalReward": 1000,
                    }
                ),
            ]
        )
        survey = read_session(journal).survey
        self.assertEqual(len(survey.track_massacres), 1)
        self.assertEqual(survey.track_massacres[0].remaining, 4)
        gs = GameSettings(autoShowPlotMassacre_TEST=True)
        status = StatusSnapshot(
            flags=FLAG_IN_MAIN_SHIP,
            flags2=0,
            fuel_main=None,
            fuel_reservoir=None,
            cargo_mass=None,
            legal_state=None,
            balance=None,
            destination=None,
            body_name=None,
            gui_focus=0,
        )
        self.assertTrue(massacre_allowed(gs, survey, status))
        rendered = render_massacre_bitmap(survey, status=status, game=gs)
        self.assertIsNotNone(rendered)
        rgba, w, h = rendered
        self.assertEqual(len(rgba), w * h * 4)

    def test_minitrack_and_foot_combat_render(self):
        from companion import (
            FLAG_HAS_LAT_LONG,
            FLAG_IN_SRV,
            FLAG2_ON_FOOT,
            StatusSnapshot,
        )
        from journal import (
            CommanderLocation,
            HumanStation,
            SurveyState,
            TrackerBookmark,
        )
        from plot_foot_combat import foot_combat_allowed, render_foot_combat_bitmap
        from plot_trackers import render_mini_track_bitmap

        loc = CommanderLocation("Demo", "Cmdr", "Demo 1")
        survey = SurveyState(
            system="Demo",
            bookmarks=(
                TrackerBookmark("#1", 10.0, 20.0, body_name="Demo 1"),
                TrackerBookmark("#2", 10.1, 20.1, body_name="Demo 1"),
            ),
            srv_type="mev_rhino",
        )
        status = StatusSnapshot(
            flags=FLAG_HAS_LAT_LONG | FLAG_IN_SRV,
            flags2=0,
            fuel_main=None,
            fuel_reservoir=None,
            cargo_mass=None,
            legal_state=None,
            balance=None,
            destination=None,
            body_name="Demo 1",
            gui_focus=0,
            latitude=10.05,
            longitude=20.05,
            heading=45.0,
            altitude=5.0,
            planet_radius=3_000_000.0,
        )
        mini = render_mini_track_bitmap(
            survey, loc, status, game=GameSettings(), force_show=True
        )
        self.assertIsNotNone(mini)

        combat_survey = SurveyState(
            system="Demo",
            system_station=HumanStation(
                name="War Settlement",
                market_id=1,
                latitude=0.0,
                longitude=0.0,
                faction_state="War",
            ),
            foot_combat_kills=3,
        )
        foot_status = StatusSnapshot(
            flags=0,
            flags2=FLAG2_ON_FOOT,
            fuel_main=None,
            fuel_reservoir=None,
            cargo_mass=None,
            legal_state=None,
            balance=None,
            destination=None,
            body_name="Demo 1",
            gui_focus=0,
            altitude=20.0,
        )
        gs = GameSettings(autoShowFootCombat_TEST=True)
        self.assertTrue(foot_combat_allowed(gs, combat_survey, foot_status))
        combat = render_foot_combat_bitmap(
            combat_survey, status=foot_status, game=gs
        )
        self.assertIsNotNone(combat)

    def test_stub_plotters_force_show(self):
        from companion import StatusSnapshot
        from journal import SurveyState, TrackerBookmark
        from plot_adjust_vr import render_adjust_vr_bitmap
        from plot_grounded import render_grounded_bitmap
        from plot_pulse import render_pulse_bitmap
        from plot_quest_mini import render_quest_mini_bitmap

        survey = SurveyState(
            bookmarks=(TrackerBookmark("X", 1.0, 2.0),),
        )
        status = StatusSnapshot(
            flags=0,
            flags2=0,
            fuel_main=None,
            fuel_reservoir=None,
            cargo_mass=None,
            legal_state=None,
            balance=None,
            destination=None,
            body_name=None,
            gui_focus=0,
        )
        self.assertIsNotNone(
            render_grounded_bitmap(survey, status=status, force_show=True)
        )
        self.assertIsNotNone(render_pulse_bitmap(status=status, force_show=True))
        self.assertIsNotNone(
            render_quest_mini_bitmap(status=status, force_show=True)
        )
        self.assertIsNotNone(render_adjust_vr_bitmap(force_show=True))


class BoxelAndSphericalTests(unittest.TestCase):
    def test_clipboard_helper_uses_injected_setter(self):
        from boxel_search import copy_next_boxel_system, set_clipboard_text
        from game_settings import GameSettings

        captured: list[str] = []

        def fake_set(text: str) -> bool:
            captured.append(text)
            return True

        gs = GameSettings(
            boxelSearchActive=True,
            boxelSearchNextSystem="Col 285 Sector AB-C d1",
        )
        self.assertTrue(
            copy_next_boxel_system(gs, gui_focus=6, set_text=fake_set)
        )
        self.assertEqual(captured, ["Col 285 Sector AB-C d1"])

        # Not active → no copy
        captured.clear()
        self.assertFalse(
            copy_next_boxel_system(
                GameSettings(boxelSearchActive=False, boxelSearchNextSystem="X"),
                gui_focus=6,
                set_text=fake_set,
            )
        )
        self.assertEqual(captured, [])

        # Wrong GuiFocus → no copy
        self.assertFalse(
            copy_next_boxel_system(gs, gui_focus=0, set_text=fake_set)
        )

        # Empty next → no copy
        self.assertFalse(
            copy_next_boxel_system(
                GameSettings(boxelSearchActive=True, boxelSearchNextSystem=""),
                gui_focus=6,
                set_text=fake_set,
            )
        )

        # Setter failure fails soft
        self.assertFalse(
            copy_next_boxel_system(gs, gui_focus=6, set_text=lambda _t: False)
        )

        # set_clipboard_text with empty fails soft without raising
        self.assertFalse(set_clipboard_text(""))

    def test_spherical_boxel_allowed_and_render(self):
        from companion import StatusSnapshot
        from game_settings import GameSettings
        from journal import SurveyState
        from key_chords import COPY_NEXT_BOXEL, ForceShowState, do_key_action
        from plot_spherical_search import (
            render_spherical_search_bitmap,
            spherical_search_allowed,
        )

        status_gal = StatusSnapshot(
            flags=0,
            flags2=0,
            fuel_main=None,
            fuel_reservoir=None,
            cargo_mass=None,
            legal_state=None,
            balance=None,
            destination=None,
            body_name=None,
            gui_focus=6,
        )
        status_other = StatusSnapshot(
            flags=0,
            flags2=0,
            fuel_main=None,
            fuel_reservoir=None,
            cargo_mass=None,
            legal_state=None,
            balance=None,
            destination=None,
            body_name=None,
            gui_focus=0,
        )
        gs = GameSettings(
            boxelSearchActive=True,
            boxelSearchPrefix="Col 285 Sector AB-C d",
            boxelSearchCurrent="Col 285 Sector AB-C d",
            boxelSearchNextSystem="Col 285 Sector AB-C d14",
            currentBoxelSearchStatus=True,
            showNextBoxelToSearch=True,
        )
        survey = SurveyState(system="Somewhere", star_pos=(1.0, 2.0, 3.0))

        self.assertTrue(spherical_search_allowed(gs, status_gal))
        self.assertFalse(spherical_search_allowed(gs, status_other))
        self.assertTrue(
            spherical_search_allowed(gs, status_other, force_show=True)
        )

        rendered = render_spherical_search_bitmap(
            survey, status=status_gal, game=gs
        )
        self.assertIsNotNone(rendered)
        rgba, w, h = rendered
        self.assertEqual(len(rgba), w * h * 4)
        self.assertGreater(w, 40)
        self.assertGreater(h, 20)

        # Notification toggles hide next line
        gs_hide_next = GameSettings(
            boxelSearchActive=True,
            boxelSearchPrefix="AA-A a",
            boxelSearchNextSystem="AA-A a0",
            currentBoxelSearchStatus=True,
            showNextBoxelToSearch=False,
        )
        self.assertIsNotNone(
            render_spherical_search_bitmap(
                survey, status=status_gal, game=gs_hide_next
            )
        )

        # Chord dispatches copy callback
        copied = {"ok": False}

        def on_copy() -> bool:
            copied["ok"] = True
            return True

        force = ForceShowState()
        self.assertTrue(
            do_key_action(
                COPY_NEXT_BOXEL,
                force_show=force,
                on_copy_next_boxel=on_copy,
            )
        )
        self.assertTrue(copied["ok"])

    def test_pulse_intensity_varies_with_time(self):
        from plot_pulse import pulse_intensity, render_pulse_bitmap

        # Fresh write → brighter than aged write.
        fresh = pulse_intensity(10.0, last_journal_write_monotonic=9.5)
        aged = pulse_intensity(10.0, last_journal_write_monotonic=0.0)
        self.assertGreater(fresh, aged)
        warm = pulse_intensity(2.0, last_journal_write_monotonic=1.5)
        cool = pulse_intensity(8.0, last_journal_write_monotonic=1.5)
        self.assertGreater(warm, cool)
        low = render_pulse_bitmap(
            force_show=True, now=10.0, last_journal_write_monotonic=0.0
        )
        high = render_pulse_bitmap(
            force_show=True, now=10.0, last_journal_write_monotonic=9.8
        )
        self.assertIsNotNone(low)
        self.assertIsNotNone(high)
        self.assertNotEqual(low[0], high[0])

    def test_grounded_status_strip_and_quest_json(self):
        from companion import FLAG_HAS_LAT_LONG, StatusSnapshot
        from game_settings import GameSettings
        from geo import offset_meters
        from journal import OrganicProgress, SurveyState, TrackerBookmark
        from plot_adjust_vr import (
            adjust_vr_allowed,
            nudge_plotter_opacity,
            nudge_plotter_scale,
            render_adjust_vr_bitmap,
        )
        from plot_grounded import grounded_allowed, render_grounded_bitmap
        from plot_quest_mini import load_local_quests, render_quest_mini_bitmap
        from quests import (
            QuestList,
            apply_journal_event,
            load_quests,
            publish_quest_stub,
            save_quests,
        )

        survey = SurveyState(
            bookmarks=(
                TrackerBookmark("Bacterium", -12.3400, 98.7650, body_name="Demo 1"),
                TrackerBookmark("X", 1.0, 2.0),
            ),
            organic_progress=(OrganicProgress(genus="Bacterium", scan_type="Log"),),
        )
        status = StatusSnapshot(
            flags=FLAG_HAS_LAT_LONG,
            flags2=0,
            fuel_main=None,
            fuel_reservoir=None,
            cargo_mass=None,
            legal_state=None,
            balance=None,
            destination=None,
            body_name="Demo 1",
            gui_focus=0,
            latitude=-12.3456,
            longitude=98.76,
            altitude=120.0,
            heading=45.0,
            planet_radius=1_800_000.0,
        )
        gs = GameSettings(autoShowBioPlot=True)
        self.assertTrue(grounded_allowed(gs, survey, status))
        rendered = render_grounded_bitmap(survey, status=status, game=gs)
        self.assertIsNotNone(rendered)
        rgba, w, h = rendered
        self.assertGreaterEqual(w, 200)
        self.assertGreaterEqual(h, 300)
        self.assertEqual(len(rgba), w * h * 4)

        dx, dy = offset_meters(-12.3456, 98.76, -12.3400, 98.7650, 1_800_000.0)
        self.assertNotAlmostEqual(dx, 0.0, places=1)
        self.assertGreater(math.hypot(dx, dy), 100.0)

        self.assertFalse(adjust_vr_allowed(GameSettings(displayVR=False)))
        self.assertTrue(adjust_vr_allowed(GameSettings(displayVR=True)))
        vr = render_adjust_vr_bitmap(game=GameSettings(displayVR=True, plotterOpacity=80))
        self.assertIsNotNone(vr)
        bumped = nudge_plotter_opacity(GameSettings(plotterOpacity=50), 5)
        self.assertEqual(bumped.plotterOpacity, 55.0)
        scaled = nudge_plotter_scale(GameSettings(plotterScale=0), 1)
        self.assertEqual(scaled.plotterScale, 1.0)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quests.json"
            path.write_text(
                json.dumps(
                    {
                        "quests": [
                            {"title": "Find Beacon", "objective": "Scan AA-A"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            quests = load_local_quests(path)
            self.assertEqual(len(quests), 1)
            q = render_quest_mini_bitmap(
                game=GameSettings(enableQuests=True),
                quests=quests,
                active_quest_count=len(quests),
            )
            self.assertIsNotNone(q)

            ql = QuestList()
            self.assertTrue(
                apply_journal_event(
                    ql,
                    {
                        "event": "MissionAccepted",
                        "MissionID": 99,
                        "Name": "Mission_Courier",
                        "LocalisedName": "Courier Run",
                        "DestinationSystem": "Sol",
                        "Faction": "Federation",
                    },
                )
            )
            save_quests(ql, path)
            loaded = load_quests(path)
            self.assertEqual(len(loaded.quests), 1)
            self.assertEqual(loaded.quests[0].title, "Courier Run")
            self.assertTrue(
                apply_journal_event(
                    loaded, {"event": "MissionCompleted", "MissionID": 99}
                )
            )
            self.assertEqual(len(loaded.quests), 0)
            pub = publish_quest_stub("F123", {"id": "q1"}, dry_run=True)
            self.assertTrue(pub["skipped"] or pub["dry_run"] or pub["ok"])

    def test_secrets_and_fss_pixel_watch_soft_fail(self):
        from fss_pixel_watch import try_grab_screen
        from game_settings import GameSettings
        from secrets_store import INARA_API_KEY, RCC_API_KEY, load_secrets, save_secrets

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            env = {"XDG_CONFIG_HOME": str(home / ".config")}
            path = save_secrets(
                {INARA_API_KEY: "inara-test", RCC_API_KEY: "rcc-test"},
                environ=env,
                home=home,
            )
            self.assertTrue(path.is_file())
            loaded = load_secrets(environ=env, home=home)
            self.assertEqual(loaded[INARA_API_KEY], "inara-test")
            self.assertEqual(loaded[RCC_API_KEY], "rcc-test")
            save_secrets({INARA_API_KEY: None}, environ=env, home=home)
            again = load_secrets(environ=env, home=home)
            self.assertNotIn(INARA_API_KEY, again)

        off = try_grab_screen(GameSettings(watchFssPixel_TEST=False))
        self.assertFalse(off.available)
        # Soft-fail path (no crash) when enabled without a usable grab.
        on = try_grab_screen(
            GameSettings(watchFssPixel_TEST=True),
            environ={"DISPLAY": ""},
        )
        self.assertFalse(on.available)

    def test_screencast_token_session_display_and_survey_header(self):
        import os

        from elite import choose_xauthority, ensure_session_display
        from guardian_templates import SitePoi
        from plot_guardians import (
            _draw_poi_dot,
            confirm_counts,
            survey_header,
            survey_progress,
        )
        from screencast_grab import (
            frame_pipeline,
            read_restore_token,
            select_source_options,
            write_restore_token,
        )

        self.assertNotIn("restore_token", select_source_options(None))
        opted = select_source_options("token-1")
        self.assertEqual(opted["restore_token"], ("s", "token-1"))
        self.assertEqual(opted["persist_mode"], ("u", 2))
        self.assertEqual(opted["types"], ("u", 1))
        cmd = frame_pipeline(7, 42, "/tmp/frame.png")
        self.assertIn("fd=7", cmd)
        self.assertIn("target-object=42", cmd)
        self.assertIn("num-buffers=1", cmd)
        from fss_pixel_watch import ffmpeg_grab_command

        grab = ffmpeg_grab_command("ffmpeg", ":0", "/tmp/f.png", (10, 20, 30, 40), None)
        self.assertIsNotNone(grab)
        assert grab is not None
        self.assertIn("x11grab", grab)
        self.assertIn("30x40", grab)
        self.assertIn(":0+10,20", grab)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "srvsurvey" / "screencast-restore-token"
            write_restore_token(path, "restore-me")
            self.assertEqual(read_restore_token(path), "restore-me")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            older = os.path.join(tmp, "auth-old")
            newer = os.path.join(tmp, "auth-new")
            Path(older).write_text("old", encoding="utf-8")
            Path(newer).write_text("new", encoding="utf-8")
            os.utime(older, (1, 100))
            os.utime(newer, (1, 200))
            self.assertEqual(choose_xauthority([older, newer, os.path.join(tmp, "missing")]), newer)
            saved = os.environ.get("XAUTHORITY")
            os.environ.pop("XAUTHORITY", None)
            try:
                ensure_session_display([older, newer])
                self.assertEqual(os.environ.get("XAUTHORITY"), newer)
                self.assertTrue(os.environ.get("DISPLAY"))
            finally:
                if saved is None:
                    os.environ.pop("XAUTHORITY", None)
                else:
                    os.environ["XAUTHORITY"] = saved

        pois = [
            SitePoi("r1", "relic", 0, 1),
            SitePoi("r2", "relic", 10, 1),
            SitePoi("p1", "pylon", 20, 1),
            SitePoi("c1", "component", 30, 1),
            SitePoi("o1", "obelisk", 40, 1),
        ]

        def status_for(name: str) -> str:
            return "present" if name in ("r1", "p1") else "unknown"

        self.assertEqual(confirm_counts(pois, status_for), (2, 1, 2, 1))
        # 4 survey POIs + site heading + 1 present relic tower = 6. Score is 2.
        self.assertEqual(
            survey_progress(
                pois,
                status_for,
                site_heading=-1,
                relic_heading=-1,
                is_ruins=False,
            ),
            33,
        )
        self.assertEqual(
            survey_header(33, 1, 2, 1, 2),
            "Survey: 33% | 1/2 relics, 1/2 items",
        )
        # Present relic r1 has a tower heading: score 3 of 6 → 50.
        self.assertEqual(
            survey_progress(
                pois,
                status_for,
                site_heading=-1,
                relic_heading=-1,
                is_ruins=False,
                relic_headings={"r1": 90},
            ),
            50,
        )
        from guardian_templates import parse_relic_tower_headings, relic_heading_for
        from elite import game_rect_usable
        from presenter import Rect
        from body_value import main_star_honk_reward
        from journal import FssBodyEntry
        from cmdr_state import GuardianSurveyState
        from plot_guardians import _compass_offset

        self.assertEqual(parse_relic_tower_headings("t11:123, t2:40"), {"t11": 123, "t2": 40})
        self.assertEqual(relic_heading_for("t11", local={"t11": 9}, pub=None), 9)
        self.assertFalse(game_rect_usable(Rect(-40_000, 0, 100, 100)))
        self.assertTrue(game_rect_usable(Rect(0, 0, 1920, 1080)))
        from elite import EliteWindowWatch

        watch = EliteWindowWatch()
        watch._dpy = object()
        watch._win = object()
        watch._rect_calls = 0

        def _rect(_dpy, _win):
            watch._rect_calls += 1
            return Rect(10, 20, 3440, 1408)

        def _scan():
            raise AssertionError("idle poll walked the root tree")

        watch_mod = __import__("elite")
        saved = watch_mod._rect_of
        watch_mod._rect_of = _rect
        watch._scan = _scan
        try:
            got = watch.poll()
            watch_mod._rect_of = lambda _dpy, _win: Rect(80, 90, 3440, 1408)
            moved = watch.poll()
        finally:
            watch_mod._rect_of = saved
        self.assertEqual(got, Rect(10, 20, 3440, 1408))
        self.assertEqual(moved, Rect(80, 90, 3440, 1408))
        self.assertEqual(watch.scans, 0)
        self.assertEqual(watch._rect_calls, 1)
        north = _compass_offset(0, -100, 0)
        self.assertAlmostEqual(north[0], 0, places=3)
        self.assertAlmostEqual(north[1], -100, places=3)
        east = _compass_offset(0, -100, 90)
        self.assertAlmostEqual(east[0], 100, places=3)
        self.assertAlmostEqual(east[1], 0, places=3)
        loaded = GuardianSurveyState.from_dict({"relic_headings": {"t1": 15}, "relicHeadings": {"t9": 1}})
        self.assertEqual(loaded.relic_headings["t1"], 15)
        star = FssBodyEntry(0, "Sol", "0", "Star", star_type="G", is_main_star=True, mass=1.0, was_discovered=True)
        rock = FssBodyEntry(1, "Sol 1", "1", "SolidBody", planet_class="Rocky body", mass=1.0, was_discovered=False)
        hit = main_star_honk_reward([star, rock], 3)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit[1], 3018)
        from PIL import Image, ImageDraw

        image = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        _draw_poi_dot(draw, 16, 16, "pylon", "present")
        _draw_poi_dot(draw, 32, 32, "component", "present")
        self.assertEqual(image.size, (48, 48))
        from quests import journal_handler_fragment

        bare = journal_handler_fragment({"event": "Docked"})
        self.assertIn("function on_Docked(entry)", bare)
        self.assertIn("-- TODO: your code", bare)
        matched = journal_handler_fragment(
            {"event": "Docked", "StationName": "Jameson", "MarketID": 128},
            ["StationName", "MarketID"],
        )
        self.assertIn('entry.StationName == "Jameson"', matched)
        self.assertIn("entry.MarketID == 128", matched)
        self.assertIn(" and ", matched)

    def test_panel_offsets_persist(self):
        from config import settings_from_dict, settings_to_key_value

        settings = settings_from_dict(
            {"panel_offset_x": "12", "panel_offset_y": "-8", "margin": "50"}
        )
        self.assertEqual(settings.panel_offset_x, 12)
        self.assertEqual(settings.panel_offset_y, -8)
        text = settings_to_key_value(settings)
        self.assertIn("panel_offset_x=12", text)
        self.assertIn("panel_offset_y=-8", text)


class KeyChordTests(unittest.TestCase):
    def test_defaults_match_windows_actions(self):
        from key_chords import (
            DEFAULT_KEYS,
            SHOW_BODY_INFO,
            SHOW_COLONY_SHOPPING,
            SHOW_FSS_INFO,
            TOGGLE_ALL_VISIBILITY,
            merge_key_actions,
            normalize_windows_chord,
            windows_chord_to_linux,
        )

        self.assertEqual(DEFAULT_KEYS[TOGGLE_ALL_VISIBILITY], "ALT F2")
        self.assertEqual(DEFAULT_KEYS[SHOW_FSS_INFO], "ALT F")
        self.assertEqual(DEFAULT_KEYS[SHOW_BODY_INFO], "ALT B")
        self.assertEqual(DEFAULT_KEYS[SHOW_COLONY_SHOPPING], "ALT S")
        merged = merge_key_actions({"showFssInfo": "alt+f"})
        self.assertEqual(merged[SHOW_FSS_INFO], "ALT F")
        self.assertEqual(normalize_windows_chord("alt+ctrl+s"), "ALT CTRL S")
        self.assertEqual(windows_chord_to_linux("ALT F"), "Alt+F")
        linux = windows_chord_to_linux("ALT CTRL S")
        parsed = parse_chord(linux)
        self.assertEqual(parsed.keyname, "S")
        self.assertIn("Ctrl", parsed.label)
        self.assertIn("Alt", parsed.label)
    def test_force_show_and_chord_dispatch(self):
        from key_chords import (
            COLLAPSE_COLONY_DATA,
            SHOW_BODY_INFO,
            SHOW_COLONY_SHOPPING,
            SHOW_FSS_INFO,
            TOGGLE_ALL_VISIBILITY,
            ForceShowState,
            do_key_action,
            find_action_for_chord,
            merge_key_actions,
        )

        actions = merge_key_actions(None)
        self.assertEqual(
            find_action_for_chord("ALT F", actions), SHOW_FSS_INFO
        )
        self.assertEqual(
            find_action_for_chord("alt+s", actions), SHOW_COLONY_SHOPPING
        )
        force = ForceShowState()
        toggled = {"n": 0}

        def on_overlay() -> None:
            toggled["n"] += 1

        self.assertTrue(
            do_key_action(
                TOGGLE_ALL_VISIBILITY,
                force_show=force,
                on_toggle_overlay=on_overlay,
            )
        )
        self.assertEqual(toggled["n"], 1)
        do_key_action(SHOW_FSS_INFO, force_show=force)
        self.assertTrue(force.fss_info)
        self.assertTrue(force.is_forced("fss"))
        do_key_action(SHOW_BODY_INFO, force_show=force)
        self.assertTrue(force.is_forced("bodyinfo"))
        do_key_action(SHOW_COLONY_SHOPPING, force_show=force)
        self.assertTrue(force.is_forced("colonisation"))
        do_key_action(COLLAPSE_COLONY_DATA, force_show=force)
        self.assertTrue(force.colony_collapse_toggle)
        self.assertFalse(force.colony_collapse_effective(True))
        self.assertTrue(force.consume_dirty())

    def test_chord_config_round_trip(self):
        from key_chords import merge_key_actions

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config"
            settings = AppSettings(
                allow_present=True,
                key_actions=merge_key_actions(
                    {"showFssInfo": "ALT SHIFT F", "showBodyInfo": ""}
                ),
            )
            saved = save_settings(settings, path)
            text = saved.read_text(encoding="utf-8")
            self.assertIn("chord.showFssInfo=ALT SHIFT F", text)
            self.assertIn("chord.showBodyInfo=", text)
            loaded = load_settings(config_paths=[saved])
            self.assertEqual(loaded.key_actions["showFssInfo"], "ALT SHIFT F")
            self.assertEqual(loaded.key_actions["showBodyInfo"], "")
            self.assertEqual(loaded.key_actions["showColonyShopping"], "ALT S")

    def test_gtk_trigger_matches_windows_chords(self) -> None:
        from global_shortcuts import gtk_trigger, shortcut_id

        self.assertEqual(gtk_trigger("ALT F2"), "<Alt>F2")
        self.assertEqual(gtk_trigger("Alt+F2"), "<Alt>F2")
        self.assertEqual(gtk_trigger("CTRL SHIFT N"), "<Control><Shift>N")
        self.assertEqual(gtk_trigger("CTRL +"), "<Control>plus")
        self.assertEqual(gtk_trigger("ALT CTRL S"), "<Alt><Control>S")
        self.assertEqual(shortcut_id("ALT F"), "chord-ALT-F")

    def test_force_show_builds_colony_panel(self):
        from key_chords import ForceShowState

        force = ForceShowState()
        force.colony = True
        loc = CommanderLocation("Sol", "Cmdr", "Earth")
        game = Rect(0, 0, 1920, 1080)
        panels_off = {pid: False for pid in AppSettings().panels}
        settings = AppSettings(
            panels=panels_off,
            game=GameSettings(
                buildProjects_TEST=False,
                autoShowPlotBuildCommodities=False,
            ),
        )
        plain = build_present_panels(loc, game, settings=settings)
        self.assertEqual(len(plain), 1)  # fallback status
        forced = build_present_panels(
            loc, game, settings=settings, force_show=force
        )
        self.assertGreaterEqual(len(forced), 1)


class NetSysDataTests(unittest.TestCase):
    def test_offline_env_skips_http(self):
        from net_sys_data import clear_cache, get_net_sys_data

        clear_cache()
        prev_net = os.environ.get("SRVSURVEY_NET_OFFLINE")
        prev_spansh = os.environ.get("SRVSURVEY_SPANSH_OFFLINE")
        os.environ["SRVSURVEY_NET_OFFLINE"] = "1"
        try:
            data = get_net_sys_data("Colonia", 3238296097059)
            self.assertEqual(data.system_name, "Colonia")
            self.assertEqual(data.system_address, 3238296097059)
            self.assertIsNone(data.discovery_status)
            self.assertIsNone(data.spansh_dump)
            self.assertEqual(data.stations, [])
        finally:
            if prev_net is None:
                os.environ.pop("SRVSURVEY_NET_OFFLINE", None)
            else:
                os.environ["SRVSURVEY_NET_OFFLINE"] = prev_net
            if prev_spansh is None:
                os.environ.pop("SRVSURVEY_SPANSH_OFFLINE", None)
            else:
                os.environ["SRVSURVEY_SPANSH_OFFLINE"] = prev_spansh
            clear_cache()

    def test_spansh_offline_still_allows_edsm_path(self):
        from net_sys_data import clear_cache, get_net_sys_data, spansh_offline

        clear_cache()
        prev = os.environ.get("SRVSURVEY_SPANSH_OFFLINE")
        os.environ["SRVSURVEY_SPANSH_OFFLINE"] = "1"
        try:
            self.assertTrue(spansh_offline())
            # force_offline so we never hit EDSM either in CI
            data = get_net_sys_data("Sol", 10477373803, force_offline=True)
            self.assertIsNone(data.spansh_dump)
        finally:
            if prev is None:
                os.environ.pop("SRVSURVEY_SPANSH_OFFLINE", None)
            else:
                os.environ["SRVSURVEY_SPANSH_OFFLINE"] = prev
            clear_cache()

    def test_discovery_status_and_poi_from_processed_dump(self):
        from net_sys_data import (
            NetSysData,
            _process_edsm_bodies,
            _process_edsm_traffic,
            _process_spansh_dump,
            station_info_from_spansh_station,
        )

        data = NetSysData(system_name="Demo", system_address=0)
        _process_edsm_bodies(
            data,
            {
                "id64": 42,
                "bodyCount": 3,
                "bodies": [
                    {
                        "isMainStar": True,
                        "spectralClass": "G2 V",
                        "discovery": {
                            "commander": "FirstCmdr",
                            "date": "3301-01-02T00:00:00Z",
                        },
                        "updateTime": "3308-05-01T12:00:00Z",
                    },
                    {"isMainStar": False},
                    {"isMainStar": False},
                ],
            },
            use_spansh_last_updated=False,
        )
        self.assertEqual(data.star_class, "G")
        self.assertEqual(data.discovered_by, "FirstCmdr")
        self.assertEqual(data.discovered_date, "3301-01-02")
        self.assertEqual(data.total_body_count, 3)
        self.assertEqual(data.scan_body_count, 3)
        self.assertEqual(data.discovery_status, "Discovered, 3 bodies")

        _process_edsm_traffic(
            data,
            {
                "id64": 42,
                "traffic": {"day": 1, "week": 10, "total": 100},
            },
        )
        self.assertIsNotNone(data.traffic)
        assert data.traffic is not None
        self.assertEqual(data.traffic.total, 100)

        _process_spansh_dump(
            data,
            {
                "id64": 42,
                "bodyCount": 5,
                "coords": {"x": 1.0, "y": 2.0, "z": 3.0},
                "bodies": [
                    {
                        "mainStar": True,
                        "spectralClass": "K0",
                        "type": "Star",
                        "signals": {
                            "signals": {"$SAA_SignalType_Biological;": 2}
                        },
                    },
                    {"type": "Planet", "stations": []},
                    {"type": "Barycentre"},
                ],
                "stations": [
                    {
                        "name": "Demo Port",
                        "id": 99,
                        "type": "Orbis Starport",
                        "primaryEconomy": "High Tech",
                        "services": ["Shipyard", "Material Trader"],
                        "landingPads": {"Small": 2, "Medium": 2, "Large": 4},
                        "economies": {"High Tech": 0.7, "Military": 0.3},
                    }
                ],
                "factions": [
                    {"name": "A", "state": "War"},
                    {"name": "B", "state": "War"},
                ],
            },
        )
        self.assertEqual(data.star_pos, (1.0, 2.0, 3.0))
        self.assertEqual(data.genus_count, 2)
        self.assertEqual(data.count_poi["StarPorts"], 1)
        self.assertEqual(data.count_poi["Wars"], 1)
        self.assertEqual(data.discovery_status, "Discovered (3 of 5)")
        self.assertTrue(any("Demo Port" == s.name for s in data.stations))
        st = station_info_from_spansh_station(
            {
                "name": "Demo Port",
                "id": 99,
                "type": "Orbis Starport",
                "primaryEconomy": "High Tech",
                "services": ["Shipyard"],
                "landingPads": {"Large": 4},
            }
        )
        self.assertIsNotNone(st)
        assert st is not None
        self.assertEqual(st.landing_pads.large if st.landing_pads else 0, 4)

    def test_jump_and_galmap_offline_enrichment(self):
        from companion import NavRouteSnapshot, RouteHop, StatusSnapshot
        from net_sys_data import NetSysData, clear_cache
        from plot_gal_map import gal_map_rows, render_gal_map_bitmap
        from plot_jump_info import render_jump_info_bitmap

        clear_cache()
        prev = os.environ.get("SRVSURVEY_NET_OFFLINE")
        os.environ["SRVSURVEY_NET_OFFLINE"] = "1"
        try:
            net = NetSysData(
                system_name="NextSys",
                system_address=99,
                star_class="K",
                star_pos=(10.0, 0.0, 0.0),
                discovered=True,
                total_body_count=4,
                scan_body_count=2,
                genus_count=3,
                discovered_by="CmdrX",
                discovered_date="3307-01-01",
            )
            survey = SurveyState(
                system="Here",
                system_address=1,
                fsd_target_name="NextSys",
                fsd_target_address=99,
                fsd_target_star_class=None,
                body_count=2,
            )
            status = StatusSnapshot(
                flags=0,
                flags2=0,
                fuel_main=None,
                fuel_reservoir=None,
                cargo_mass=None,
                legal_state=None,
                balance=None,
                destination=None,
                body_name=None,
                gui_focus=0,
            )
            route = NavRouteSnapshot(
                route=(
                    RouteHop("Here", 1, "G", (0.0, 0.0, 0.0)),
                    RouteHop("NextSys", 99, None, None),
                    RouteHop("Final", 100, "F", (20.0, 0.0, 0.0)),
                )
            )
            jump = render_jump_info_bitmap(
                survey,
                status,
                route,
                game=GameSettings(plotJumpInfoMinimal=False),
                net_data=net,
                force_show=True,
            )
            self.assertIsNotNone(jump)
            rgba, w, h = jump
            self.assertEqual(len(rgba), w * h * 4)

            rows, _dist, _jumps = gal_map_rows(
                survey, route, game=GameSettings(), net_lookup=False
            )
            self.assertTrue(any(r.discovery_status == "..." for r in rows))

            # Injected net via optional path when looking up remote hop
            from plot_gal_map import _row_for_hop

            row = _row_for_hop(
                RouteHop("NextSys", 99),
                "Next jump:",
                survey,
                net_data=net,
            )
            self.assertIn("Discovered", row.discovery_status)
            self.assertEqual(row.genus_count, 3)

            gal = render_gal_map_bitmap(
                survey,
                status=StatusSnapshot(
                    flags=0,
                    flags2=0,
                    fuel_main=None,
                    fuel_reservoir=None,
                    cargo_mass=None,
                    legal_state=None,
                    balance=None,
                    destination=None,
                    body_name=None,
                    gui_focus=6,  # galaxy map
                ),
                nav_route=route,
                game=GameSettings(),
                force_show=True,
            )
            self.assertIsNotNone(gal)
        finally:
            if prev is None:
                os.environ.pop("SRVSURVEY_NET_OFFLINE", None)
            else:
                os.environ["SRVSURVEY_NET_OFFLINE"] = prev
            clear_cache()


class EddnGggTests(unittest.TestCase):
    def tearDown(self) -> None:
        from eddn import clear_state, set_post_hook
        from raven_colonial import set_put_hook

        clear_state()
        set_post_hook(None)
        set_put_hook(None)
        for key in (
            "SRVSURVEY_NET_OFFLINE",
            "SRVSURVEY_EDDN_OFFLINE",
            "SRVSURVEY_EDDN_DRYRUN",
            "SRVSURVEY_RCC_OFFLINE",
            "SRVSURVEY_GGG_OFFLINE",
            "SRVSURVEY_GGG_DRYRUN",
        ):
            os.environ.pop(key, None)

    def test_eddn_offline_skips_post(self):
        from eddn import (
            EddnContext,
            clear_state,
            handle_journal_entry,
            set_header_from_load_game,
            set_post_hook,
        )

        clear_state()
        posted: list[tuple[str, str]] = []

        def hook(url: str, payload: str) -> tuple[int, str]:
            posted.append((url, payload))
            return 200, "ok"

        set_post_hook(hook)
        set_header_from_load_game("Cmdr Test", "4.0.0.1904", "r1")
        os.environ["SRVSURVEY_EDDN_OFFLINE"] = "1"
        result = handle_journal_entry(
            {
                "event": "Scan",
                "timestamp": "2026-09-26T12:00:00Z",
                "SystemAddress": 1,
                "BodyName": "Demo A",
                "BodyID": 1,
                "StarSystem": "Demo",
            },
            eddn_upload=True,
            environment="dev",
            ctx=EddnContext(
                system_name="Demo",
                system_address=1,
                star_pos=(1.0, 2.0, 3.0),
            ),
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.skipped)
        self.assertEqual(result.reason, "offline")
        self.assertEqual(posted, [])

        os.environ.pop("SRVSURVEY_EDDN_OFFLINE", None)
        os.environ["SRVSURVEY_NET_OFFLINE"] = "1"
        result2 = handle_journal_entry(
            {
                "event": "FSDJump",
                "timestamp": "2026-09-26T12:01:00Z",
                "SystemAddress": 1,
                "StarSystem": "Demo",
                "StarPos": [1.0, 2.0, 3.0],
            },
            eddn_upload=True,
            ctx=EddnContext(system_address=1, star_pos=(1.0, 2.0, 3.0)),
        )
        self.assertIsNotNone(result2)
        assert result2 is not None
        self.assertTrue(result2.skipped)
        self.assertEqual(posted, [])

    def test_eddn_dryrun_builds_payload_without_post(self):
        from eddn import (
            EddnContext,
            clear_state,
            handle_journal_entry,
            note_fileheader,
            process_journal_events,
            set_post_hook,
        )

        clear_state()
        posted: list[str] = []
        set_post_hook(lambda url, payload: posted.append(payload) or (200, "ok"))
        os.environ["SRVSURVEY_EDDN_DRYRUN"] = "1"

        events = [
            {
                "event": "Fileheader",
                "part": 1,
                "Odyssey": True,
                "gameversion": "4.0.0.1904",
                "build": "r301487/r0",
            },
            {
                "event": "LoadGame",
                "Commander": "Dry Cmdr",
                "FID": "F123",
            },
            {
                "event": "Scan",
                "timestamp": "2026-09-26T12:00:00Z",
                "SystemAddress": 99,
                "BodyName": "Demo A",
                "BodyID": 2,
                "StarSystem": "Demo",
                "PlanetClass_Localised": "should-trim",
                "PlanetClass": "Icy body",
            },
        ]
        results = process_journal_events(
            events,
            eddn_upload=True,
            environment="dev",
            ctx=EddnContext(
                system_name="Demo",
                system_address=99,
                star_pos=(10.0, 20.0, 30.0),
            ),
        )
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertTrue(result.dry_run)
        self.assertEqual(posted, [])
        payload = result.payload
        self.assertEqual(
            payload["$schemaRef"],
            "https://eddn.edcd.io/schemas/journal/1/test",
        )
        self.assertEqual(payload["header"]["uploaderID"], "Dry Cmdr")
        self.assertEqual(payload["header"]["gameVersion"], "4.0.0.1904")
        self.assertEqual(payload["header"]["gamebuild"], "r301487/r0")
        message = payload["message"]
        self.assertEqual(message["event"], "Scan")
        self.assertNotIn("PlanetClass_Localised", message)
        self.assertEqual(message["StarPos"], [10.0, 20.0, 30.0])
        self.assertTrue(message.get("odyssey"))

        # Header also set via note_fileheader path used before LoadGame
        note_fileheader(events[0])
        solo = handle_journal_entry(
            {
                "event": "Docked",
                "SystemAddress": 99,
                "StationName": "Outpost",
                "Wanted": False,
            },
            eddn_upload=True,
            environment="beta",
            ctx=EddnContext(system_address=99, star_pos=(10.0, 20.0, 30.0)),
        )
        self.assertIsNotNone(solo)
        assert solo is not None
        self.assertTrue(solo.dry_run)
        self.assertIn("/test", solo.payload["$schemaRef"])
        self.assertNotIn("Wanted", solo.payload["message"])

    def test_eddn_environment_setting_parses(self):
        gs = GameSettings.from_flat({"gs.eddnEnvironment": "live"})
        self.assertEqual(gs.eddnEnvironment, "live")
        gs2 = GameSettings.from_flat({"gs.eddnEnvironment": ""})
        self.assertIsNone(gs2.eddnEnvironment)

    def test_ggg_tag_match_with_inline_stub(self):
        from ggg import get_tag_for_ggg, maybe_upload_from_scan
        from raven_colonial import set_put_hook

        table = {
            "delta": 0.001,
            "knownGGGTemps": {
                "Sudarsky class I gas giant": [130.0, 140.0],
            },
            "theorizedGGGTemps": {
                "Sudarsky class III gas giant": [400.0],
            },
        }
        self.assertEqual(
            get_tag_for_ggg("Sudarsky class I gas giant", 130.0, table=table),
            "likely",
        )
        self.assertEqual(
            get_tag_for_ggg("Sudarsky class I gas giant", 130.0005, table=table),
            "likely-approx",
        )
        self.assertEqual(
            get_tag_for_ggg("Sudarsky class III gas giant", 400.0, table=table),
            "potential",
        )
        self.assertIsNone(
            get_tag_for_ggg("Sudarsky class I gas giant", 999.0, table=table)
        )
        self.assertIsNone(get_tag_for_ggg("Icy body", 130.0, table=table))

        puts: list[tuple[str, str]] = []
        set_put_hook(lambda url, body: puts.append((url, body)) or (200, "ok"))
        os.environ["SRVSURVEY_GGG_DRYRUN"] = "1"
        scan = {
            "event": "Scan",
            "BodyName": "Demo 2",
            "PlanetClass": "Sudarsky class I gas giant",
            "SurfaceTemperature": 130.0,
            "SystemAddress": 1,
        }
        tag = maybe_upload_from_scan(
            scan,
            upload_ggg_enabled=True,
            commander="Cmdr GGG",
            star_pos=(1.0, 2.0, 3.0),
            table=table,
        )
        self.assertEqual(tag, "likely")
        self.assertEqual(puts, [])  # dry-run never hits PUT hook

        os.environ.pop("SRVSURVEY_GGG_DRYRUN", None)
        os.environ["SRVSURVEY_RCC_OFFLINE"] = "1"
        tag2 = maybe_upload_from_scan(
            scan,
            upload_ggg_enabled=True,
            commander="Cmdr GGG",
            star_pos=(1.0, 2.0, 3.0),
            table=table,
        )
        # Offline still returns the matched tag after attempting upload_ggg
        # (upload_ggg skips HTTP); maybe_upload_from_scan returns tag on success path.
        self.assertEqual(tag2, "likely")
        self.assertEqual(puts, [])

    def test_upload_ggg_offline_no_put(self):
        from raven_colonial import set_put_hook, upload_ggg

        puts: list[str] = []
        set_put_hook(lambda url, body: puts.append(body) or (200, "ok"))
        os.environ["SRVSURVEY_NET_OFFLINE"] = "1"
        result = upload_ggg(
            "Cmdr",
            "likely",
            [1.0, 2.0, 3.0],
            '{"event":"Scan"}',
        )
        self.assertTrue(result["skipped"])
        self.assertEqual(result["body"], "offline")
        self.assertEqual(puts, [])


class ScreenshotProcessorTests(unittest.TestCase):
    def _tiny_png(self, path: Path, *, colour=(20, 40, 60)) -> Path:
        from PIL import Image

        Image.new("RGB", (32, 24), colour).save(path, format="PNG")
        return path

    def test_safe_filename_and_banner_lines(self):
        from screenshot import ScreenshotContext, build_banner_lines, safe_filename

        self.assertEqual(safe_filename('A/B:C*?"<>|'), "A-B-C------")
        ctx = ScreenshotContext(
            system="Sol",
            body="Earth",
            commander="Sample",
            taken_at=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        game = GameSettings(screenshotBannerLocalTime=False)
        big, small = build_banner_lines(ctx, game)
        self.assertEqual(big, "Body: Earth")
        self.assertIn("System: Sol", small)
        self.assertIn("Cmdr: Sample", small)
        self.assertIn("2024-06-01", small)

    def test_process_screenshot_with_banner_and_delete(self):
        from PIL import Image

        from screenshot import ScreenshotContext, process_screenshot

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._tiny_png(root / "shot.png")
            target = root / "converted"
            game = GameSettings(
                processScreenshots=True,
                addBannerToScreenshots=True,
                deleteScreenshotOriginal=True,
                showScreenshot=False,
                screenshotSourceFolder=str(root),
                screenshotTargetFolder=str(target),
                screenshotBannerColor="#FFFF00",
            )
            ctx = ScreenshotContext(
                system="Alpha Centauri",
                body="Proxima",
                commander="Cmdr Test",
                taken_at=datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
            )
            out = process_screenshot(source, game, ctx)
            self.assertIsNotNone(out)
            assert out is not None
            self.assertTrue(out.is_file())
            self.assertEqual(out.parent.name, "Alpha Centauri")
            self.assertIn("Proxima", out.name)
            self.assertFalse(source.exists())
            with Image.open(out) as img:
                # Banner fills a black box; yellow text may be anti-aliased.
                self.assertEqual(img.getpixel((12, 12))[:3], (0, 0, 0))
                yellowish = 0
                for y in range(img.height):
                    for x in range(img.width):
                        p = img.getpixel((x, y))
                        if p[0] > 180 and p[1] > 180 and p[2] < 80:
                            yellowish += 1
                self.assertGreater(yellowish, 0)

    def test_process_skipped_when_disabled(self):
        from screenshot import ScreenshotContext, process_screenshot

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._tiny_png(root / "shot.png")
            target = root / "out"
            game = GameSettings(
                processScreenshots=False,
                screenshotTargetFolder=str(target),
            )
            out = process_screenshot(
                source,
                game,
                ScreenshotContext(system="Sol", body="Earth"),
            )
            self.assertIsNone(out)
            self.assertFalse(target.exists())

    def test_folder_watcher_seeds_then_processes_new(self):
        from screenshot import (
            ScreenshotContext,
            ScreenshotFolderWatcher,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src"
            target = root / "dst"
            source.mkdir()
            target.mkdir()
            existing = self._tiny_png(source / "old.png", colour=(1, 2, 3))
            game = GameSettings(
                processScreenshots=True,
                addBannerToScreenshots=False,
                showScreenshot=False,
                deleteScreenshotOriginal=False,
                screenshotSourceFolder=str(source),
                screenshotTargetFolder=str(target),
            )
            ctx = ScreenshotContext(system="Sol", body="Earth", commander="A")
            watch = ScreenshotFolderWatcher()
            # First poll seeds; must not convert the existing gallery file.
            self.assertEqual(watch.poll(game, ctx), [])
            self.assertEqual(list(target.rglob("*.png")), [])

            new_shot = self._tiny_png(source / "new.png", colour=(9, 9, 9))
            # Ensure mtime is distinct and "new" for the watcher.
            now = time.time() + 2
            os.utime(new_shot, (now, now))
            written = watch.poll(game, ctx)
            self.assertEqual(len(written), 1)
            self.assertTrue(written[0].is_file())
            self.assertTrue(existing.exists())
            # Idempotent — second poll does nothing.
            self.assertEqual(watch.poll(game, ctx), [])

    def test_toggle_image_embed_chord(self):
        from key_chords import TOGGLE_IMAGE_EMBED, ForceShowState, do_key_action

        flipped = {"n": 0}

        def on_toggle() -> None:
            flipped["n"] += 1

        self.assertTrue(
            do_key_action(
                TOGGLE_IMAGE_EMBED,
                force_show=ForceShowState(),
                on_toggle_image_embed=on_toggle,
            )
        )
        self.assertEqual(flipped["n"], 1)


class SiteTemplateAndGuardiansTests(unittest.TestCase):
    def test_guardian_templates_load_and_render(self):
        from companion import FLAG_HAS_LAT_LONG, FLAG_IN_MAIN_SHIP, StatusSnapshot
        from journal import GuardianSiteSummary, SurveyState
        from plot_guardians import guardians_allowed, render_guardians_bitmap
        from site_templates import clear_template_caches, get_guardian_template

        clear_template_caches()
        tmpl = get_guardian_template("Alpha")
        self.assertIsNotNone(tmpl)
        assert tmpl is not None
        self.assertGreater(len(tmpl.poi), 10)

        survey = SurveyState(
            current_guardian_site=GuardianSiteSummary(
                name="$Ancient_Tiny_003:#index=1;",
                display_text="Demo: Fistbump",
                site_type="Fistbump",
            )
        )
        gs = GameSettings(enableGuardianSites=True, autoShowGuardianSummary=True)
        status = StatusSnapshot(
            flags=FLAG_HAS_LAT_LONG | FLAG_IN_MAIN_SHIP,
            flags2=0,
            fuel_main=None,
            fuel_reservoir=None,
            cargo_mass=None,
            legal_state=None,
            balance=None,
            destination=None,
            body_name="Body",
            gui_focus=0,
            latitude=1.0,
            longitude=2.0,
            heading=45.0,
        )
        self.assertTrue(guardians_allowed(gs, survey, status))
        rendered = render_guardians_bitmap(survey, status=status, game=gs)
        self.assertIsNotNone(rendered)
        assert rendered is not None
        self.assertGreater(rendered[1], 50)

    def test_human_site_templates_and_map(self):
        from companion import FLAG_HAS_LAT_LONG, FLAG2_ON_FOOT, StatusSnapshot
        from human_site_templates import load_templates, reset_cache
        from journal import HumanStation, SurveyState
        from plot_human_site import render_human_site_bitmap

        reset_cache()
        templates = load_templates()
        self.assertGreater(len(templates), 5)
        station = HumanStation(
            name="Test Port",
            market_id=1,
            latitude=0.0,
            longitude=0.0,
            system_address=1,
            economy="$economy_Agriculture;",
            economy_localized="Agriculture",
            sub_type=1,
            heading=10.0,
            has_landed=True,
            template_name=templates[0].name if templates else None,
        )
        survey = SurveyState(system_station=station)
        status = StatusSnapshot(
            flags=FLAG_HAS_LAT_LONG,
            flags2=FLAG2_ON_FOOT,
            fuel_main=None,
            fuel_reservoir=None,
            cargo_mass=None,
            legal_state=None,
            balance=None,
            destination=None,
            body_name="Body",
            gui_focus=0,
            latitude=0.1,
            longitude=0.2,
            heading=90.0,
        )
        mapped = render_human_site_bitmap(
            survey, status, game=GameSettings(autoShowHumanSitesTest=True)
        )
        self.assertIsNotNone(mapped)
        from plot_human_site import render_human_site_map_bitmap

        mapped2 = render_human_site_map_bitmap(
            survey, status, game=GameSettings(autoShowHumanSitesTest=True)
        )
        self.assertIsNotNone(mapped2)

    def test_ram_tah_decode_from_pub_ao(self):
        from companion import FLAG_HAS_LAT_LONG, FLAG_IN_SRV, StatusSnapshot
        from guardian_templates import load_pub
        from journal import GuardianSiteSummary, SurveyState
        from plot_ram_tah import ram_tah_allowed, ram_tah_rows, render_ram_tah_bitmap
        from ram_tah_decode import items_for_msg, log_display_name

        self.assertEqual(items_for_msg("C4"), ("to", "ur"))
        self.assertIn("Culture", log_display_name("C4"))

        pub = load_pub("2MASS J10444160-5947046 1 b", 1, True)
        self.assertIsNotNone(pub)
        assert pub is not None
        self.assertGreater(len(pub.active_obelisks), 0)

        survey = SurveyState(
            current_guardian_site=GuardianSiteSummary(
                name="$Ancient:#index=1;",
                display_text="1 b: Ruins #1",
                body_name="2MASS J10444160-5947046 1 b",
                is_ruins=True,
                index=1,
                site_type=pub.site_type,
            )
        )
        rows = ram_tah_rows(survey)
        self.assertGreater(len(rows), 0)
        status = StatusSnapshot(
            flags=FLAG_HAS_LAT_LONG | FLAG_IN_SRV,
            flags2=0,
            fuel_main=None,
            fuel_reservoir=None,
            cargo_mass=None,
            legal_state=None,
            balance=None,
            destination=None,
            body_name="2MASS J10444160-5947046 1 b",
            gui_focus=0,
            latitude=-41.67,
            longitude=-122.35,
        )
        gs = GameSettings(enableGuardianSites=True, autoShowRamTah=True)
        self.assertTrue(ram_tah_allowed(gs, survey, status))
        rendered = render_ram_tah_bitmap(survey, game=gs, status=status)
        self.assertIsNotNone(rendered)
        all_msgs = frozenset(m for m, _, _ in ram_tah_rows(survey, max_rows=100))
        empty = ram_tah_rows(survey, decoded=all_msgs)
        self.assertEqual(empty, [])


class CmdrStateAndChatCommandTests(unittest.TestCase):
    def tearDown(self):
        from cmdr_state import clear_commander_cache

        clear_commander_cache()

    def test_cmdr_round_trip_and_settlement_heading(self):
        from chat_commands import handle_send_text
        from cmdr_state import clear_commander_cache, get_commander

        clear_commander_cache()
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            state = get_commander(commander="Tester", data_dir=data, reload=True)
            state.toggle_decode_msg("A01", is_ruins=True)
            state.toggle_decode_msg("#12", is_ruins=False)
            state.save()
            clear_commander_cache()
            loaded = get_commander(commander="Tester", data_dir=data, reload=True)
            self.assertIn("A01", loaded.decode_the_ruins)
            self.assertIn("#12", loaded.decode_the_logs)
            msg = handle_send_text(
                ".settlement",
                cmdr=loaded,
                status_heading=123.4,
                market_id=42,
                persist=True,
            )
            self.assertIsNotNone(msg)
            self.assertAlmostEqual(loaded.human_heading(42) or 0.0, 123.4, places=1)
            handle_send_text(".site Alpha", cmdr=loaded, persist=True)
            self.assertEqual(loaded.guardian.site_type, "Alpha")
            handle_send_text(".to A01", cmdr=loaded, persist=True)
            handle_send_text(".os", cmdr=loaded, persist=True)
            self.assertIn("A01", loaded.guardian.scanned_obelisks)

    def test_ram_tah_mission_active_and_decode_toggle(self):
        from chat_commands import handle_journal_entry
        from cmdr_state import (
            TahMissionStatus,
            apply_cmdr_to_survey,
            clear_commander_cache,
            get_commander,
        )
        from journal import HumanStation, SurveyState

        clear_commander_cache()
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            cmdr = get_commander(commander="RamTah", data_dir=data, reload=True)
            handle_journal_entry(
                {
                    "event": "MissionAccepted",
                    "Name": "Mission_TheDead",
                    "MissionID": 1,
                },
                cmdr=cmdr,
                persist=True,
            )
            self.assertEqual(
                cmdr.decode_the_ruins_mission_active, TahMissionStatus.Active
            )
            self.assertTrue(cmdr.ram_tah_active)
            handle_journal_entry(
                {
                    "event": "MissionCompleted",
                    "Name": "Mission_TheDead",
                    "MissionID": 1,
                },
                cmdr=cmdr,
                persist=True,
            )
            self.assertEqual(
                cmdr.decode_the_ruins_mission_active, TahMissionStatus.Complete
            )

            self.assertTrue(cmdr.toggle_decode_msg("C4", is_ruins=True))
            self.assertIn("C4", cmdr.decode_the_ruins)
            self.assertFalse(cmdr.toggle_decode_msg("C4", is_ruins=True))
            self.assertNotIn("C4", cmdr.decode_the_ruins)

            cmdr.set_human_heading(99, 45.0)
            survey = SurveyState(
                system_station=HumanStation(
                    name="Pad",
                    market_id=99,
                    latitude=0.0,
                    longitude=0.0,
                    heading=-1.0,
                )
            )
            merged = apply_cmdr_to_survey(survey, cmdr)
            self.assertEqual(merged.system_station.heading, 45.0)


class PlotGuardiansSurveyModeTests(unittest.TestCase):
    def tearDown(self):
        from cmdr_state import clear_commander_cache

        clear_commander_cache()

    def _status(self, **kwargs):
        from companion import FLAG_HAS_LAT_LONG, FLAG_IN_SRV, StatusSnapshot

        base = dict(
            flags=FLAG_HAS_LAT_LONG | FLAG_IN_SRV,
            flags2=0,
            fuel_main=None,
            fuel_reservoir=None,
            cargo_mass=None,
            legal_state=None,
            balance=None,
            destination=None,
            body_name="Body",
            gui_focus=0,
            latitude=1.0,
            longitude=2.0,
            heading=45.0,
            altitude=1100.0,
            planet_radius=3000000.0,
        )
        base.update(kwargs)
        return StatusSnapshot(**base)

    def test_modes_site_heading_aerial_map_and_target(self):
        from chat_commands import handle_send_text, process_cmdr_events
        from cmdr_state import clear_commander_cache, get_commander, guardian_site_key
        from journal import GuardianSiteSummary, SurveyState
        from plot_guardians import (
            adjust_guardian_zoom,
            aerial_guidance_lines,
            effective_poi_status,
            guardians_lines,
            overlay_pois_from_state,
            render_guardians_bitmap,
            resolve_survey_mode,
            should_label_poi,
        )
        from guardian_templates import SitePoi

        clear_commander_cache()
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            cmdr = get_commander(commander="GMode", data_dir=data, reload=True)
            site = GuardianSiteSummary(
                name="$Ancient:#index=1;",
                display_text="Body: Ruins #1",
                body_name="Body",
                is_ruins=True,
                index=1,
                site_type=None,
            )
            survey = SurveyState(current_guardian_site=site)
            key = guardian_site_key(site)
            g = cmdr.guardian_for(key)
            gs = GameSettings(enableGuardianSites=True)
            status = self._status()

            site_lines = guardians_lines(
                survey, status, guardian_state=g, game=gs
            )
            self.assertTrue(any("Alpha" in t for t, _ in site_lines))
            self.assertTrue(any(".site" in t for t, _ in site_lines))

            mode = resolve_survey_mode(
                site_type=None, heading=-1, guardian_state=g, game=gs
            )
            self.assertEqual(mode, "site")
            rendered = render_guardians_bitmap(
                survey, status=status, game=gs, cmdr=cmdr, force_show=True
            )
            self.assertIsNotNone(rendered)

            handle_send_text(".site Alpha", cmdr=cmdr, survey=survey, persist=True)
            g = cmdr.guardian_for(key)
            self.assertEqual(g.site_type, "Alpha")
            self.assertEqual(g.mode, "heading")
            hdg_lines = guardians_lines(
                survey, status, guardian_state=g, game=gs
            )
            self.assertTrue(
                any("heading" in t.lower() or "Align" in t for t, _ in hdg_lines)
            )

            handle_send_text(".heading 90", cmdr=cmdr, survey=survey, persist=True)
            g = cmdr.guardian_for(key)
            self.assertEqual(g.heading, 90.0)
            self.assertEqual(g.mode, "map")

            handle_send_text(".aerial", cmdr=cmdr, survey=survey, persist=True)
            g = cmdr.guardian_for(key)
            self.assertEqual(g.mode, "aerial")
            lines = aerial_guidance_lines(
                site_type="Alpha", altitude=1100.0, game=gs
            )
            self.assertTrue(any("Target altitude" in t for t, _ in lines))
            aerial = render_guardians_bitmap(
                survey, status=status, game=gs, cmdr=cmdr, force_show=True
            )
            self.assertIsNotNone(aerial)

            handle_send_text(".map", cmdr=cmdr, survey=survey, persist=True)
            handle_send_text(".to B09", cmdr=cmdr, survey=survey, persist=True)
            handle_send_text("z 2", cmdr=cmdr, survey=survey, persist=True)
            g = cmdr.guardian_for(key)
            self.assertEqual(g.target_obelisk, "B09")
            self.assertEqual(g.zoom, 2.0)
            z = adjust_guardian_zoom(cmdr, key, zoom_in=True, persist=True)
            self.assertGreater(z, 2.0)
            hdr = guardians_lines(survey, status, guardian_state=g, game=gs)
            self.assertTrue(any("B09" in t for t, _ in hdr))
            self.assertTrue(any(".add" in t for t, _ in hdr))

            notes = process_cmdr_events(
                cmdr,
                [{"event": "SendText", "Message": ".add totem"}],
                status=status,
                survey=survey,
            )
            handle_send_text(
                ".add totem",
                cmdr=cmdr,
                survey=survey,
                poi_angle=10.0,
                poi_dist=50.0,
                poi_rot=0.0,
                persist=True,
            )
            g = cmdr.guardian_for(key)
            self.assertEqual(len(g.extra_poi), 1)
            name = g.extra_poi[0]["name"]
            self.assertEqual(g.extra_poi[0]["type"], "totem")
            overlays = overlay_pois_from_state(g)
            self.assertEqual(overlays[0].name, name)
            handle_send_text(f".empty {name}", cmdr=cmdr, survey=survey, persist=True)
            g = cmdr.guardian_for(key)
            self.assertIn(name, g.empty_puddles)
            self.assertEqual(effective_poi_status(None, name, g), "empty")
            self.assertTrue(
                should_label_poi(
                    SitePoi(name=name, poi_type="totem", angle=10, dist=50, rot=0),
                    status="empty",
                    highlight=False,
                    is_overlay=True,
                )
            )

            clear_commander_cache()
            reloaded = get_commander(commander="GMode", data_dir=data, reload=True)
            rg = reloaded.guardian_for(key)
            self.assertEqual(len(rg.extra_poi), 1)
            self.assertIn(name, rg.empty_puddles)

            handle_send_text(
                f".remove {name}", cmdr=reloaded, survey=survey, persist=True
            )
            rg = reloaded.guardian_for(key)
            self.assertEqual(rg.extra_poi, [])
            self.assertNotIn(name, rg.empty_puddles)

            mapped = render_guardians_bitmap(
                survey, status=status, game=gs, cmdr=reloaded, force_show=True
            )
            self.assertIsNotNone(mapped)
            self.assertIsInstance(notes, list)
            self.assertTrue(
                should_label_poi(
                    SitePoi(name="B09", poi_type="obelisk", angle=0, dist=10, rot=0),
                    status="present",
                    highlight=True,
                    is_overlay=False,
                )
            )

    def test_force_guardian_survey_mode_setting(self):
        from cmdr_state import GuardianSurveyState
        from journal import GuardianSiteSummary, SurveyState
        from plot_guardians import render_guardians_bitmap, resolve_survey_mode

        g = GuardianSurveyState(site_type="Beta", heading=45.0, mode="map")
        gs = GameSettings(forceGuardianSurveyMode="aerial")
        self.assertEqual(
            resolve_survey_mode(
                site_type="Beta", heading=45, guardian_state=g, game=gs
            ),
            "aerial",
        )
        survey = SurveyState(
            current_guardian_site=GuardianSiteSummary(
                name="$Ancient:#index=1;",
                display_text="Ruins",
                is_ruins=True,
                index=1,
                site_type="Beta",
            )
        )
        out = render_guardians_bitmap(
            survey,
            status=self._status(),
            game=gs,
            guardian_state=g,
            force_show=True,
        )
        self.assertIsNotNone(out)


class MsgCmdTargetAndBookmarkTests(unittest.TestCase):
    def tearDown(self):
        from cmdr_state import clear_commander_cache

        clear_commander_cache()

    def _status(self, lat=10.0, lon=-20.0, body="Sol 3", radius=6_371_000.0):
        from companion import FLAG_HAS_LAT_LONG, FLAG_IN_SRV, StatusSnapshot

        return StatusSnapshot(
            flags=FLAG_HAS_LAT_LONG | FLAG_IN_SRV,
            flags2=0,
            fuel_main=None,
            fuel_reservoir=None,
            cargo_mass=None,
            legal_state=None,
            balance=None,
            destination=None,
            body_name=body,
            gui_focus=0,
            latitude=lat,
            longitude=lon,
            heading=90.0,
            altitude=5.0,
            planet_radius=radius,
        )

    def test_target_here_on_off_persists_gs_keys(self):
        from chat_commands import handle_send_text
        from cmdr_state import clear_commander_cache, get_commander
        from config import load_settings

        clear_commander_cache()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            cfg_dir = home / ".config" / "srvsurvey"
            cfg_dir.mkdir(parents=True)
            cfg_path = cfg_dir / "config"
            cfg_path.write_text("allow_present=true\n", encoding="utf-8")
            cmdr = get_commander(
                commander="Targeter", data_dir=home / "share", reload=True
            )
            status = self._status()

            msg = handle_send_text(
                ".target here",
                cmdr=cmdr,
                status=status,
                persist=True,
                config_path=cfg_path,
                config_home=home,
            )
            self.assertIsNotNone(msg)
            text = cfg_path.read_text(encoding="utf-8")
            self.assertIn("gs.targetLatLongActive=true", text)
            self.assertIn("gs.targetLat=", text)
            self.assertIn("gs.targetLong=", text)

            handle_send_text(
                ".target off",
                cmdr=cmdr,
                status=status,
                persist=True,
                config_path=cfg_path,
                config_home=home,
            )
            text = cfg_path.read_text(encoding="utf-8")
            self.assertIn("gs.targetLatLongActive=false", text)

            handle_send_text(
                ".target on",
                cmdr=cmdr,
                status=status,
                persist=True,
                config_path=cfg_path,
                config_home=home,
            )
            text = cfg_path.read_text(encoding="utf-8")
            self.assertIn("gs.targetLatLongActive=true", text)

            loaded = load_settings(home=home)
            self.assertTrue(loaded.game.targetLatLongActive)
            self.assertAlmostEqual(loaded.game.targetLat, 10.0, places=4)
            self.assertAlmostEqual(loaded.game.targetLong, -20.0, places=4)

    def test_bookmark_plus_minus_persist_and_merge(self):
        from chat_commands import handle_send_text
        from cmdr_state import (
            apply_cmdr_to_survey,
            clear_commander_cache,
            get_commander,
        )
        from journal import SurveyState

        clear_commander_cache()
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            cmdr = get_commander(commander="Bookmarker", data_dir=data, reload=True)
            status = self._status(lat=1.0, lon=2.0, body="Alpha 1")

            msg = handle_send_text("+camp", cmdr=cmdr, status=status, persist=True)
            self.assertTrue(msg and msg.startswith("Bookmark"))
            self.assertIn("Alpha 1", cmdr.bookmarks)
            self.assertIn("camp", cmdr.bookmarks["Alpha 1"])

            handle_send_text(
                "+beacon",
                cmdr=cmdr,
                status=self._status(lat=5.0, lon=6.0, body="Alpha 1"),
                persist=True,
            )
            handle_send_text(
                "-camp",
                cmdr=cmdr,
                status=self._status(lat=1.0, lon=2.0, body="Alpha 1"),
                persist=True,
            )
            survey = apply_cmdr_to_survey(SurveyState(), cmdr)
            names = {bm.name for bm in survey.bookmarks if bm.body_name == "Alpha 1"}
            self.assertIn("beacon", names)
            self.assertNotIn("camp", names)

            clear_commander_cache()
            reloaded = get_commander(commander="Bookmarker", data_dir=data, reload=True)
            self.assertIn("beacon", (reloaded.bookmarks.get("Alpha 1") or {}))


class InaraAndRccParityTests(unittest.TestCase):
    def tearDown(self) -> None:
        import inara
        from raven_colonial import set_put_hook

        inara.clear_state()
        inara.set_post_hook(None)
        set_put_hook(None)
        for key in (
            "SRVSURVEY_NET_OFFLINE",
            "SRVSURVEY_INARA_OFFLINE",
            "SRVSURVEY_INARA_DRYRUN",
            "SRVSURVEY_DRY_RUN",
            "SRVSURVEY_RCC_OFFLINE",
            "SRVSURVEY_RCC_DRY_RUN",
        ):
            os.environ.pop(key, None)

    def test_inara_dry_run_maps_travel(self):
        import inara

        inara.clear_state()
        os.environ["SRVSURVEY_INARA_DRYRUN"] = "1"
        posted: list[tuple[str, str]] = []

        def hook(url: str, payload: str) -> tuple[int, str]:
            posted.append((url, payload))
            return 200, "ok"

        inara.set_post_hook(hook)
        events = [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "event": "LoadGame",
                "Commander": "Tester",
                "FID": "F123",
                "Ship": "Asp",
                "ShipID": 1,
                "gameversion": "4.0.0.0",
                "Odyssey": True,
            },
            {
                "timestamp": "2026-01-01T00:01:00Z",
                "event": "FSDJump",
                "StarSystem": "Sol",
                "StarPos": [0, 0, 0],
            },
            {
                "timestamp": "2026-01-01T00:02:00Z",
                "event": "Docked",
                "StarSystem": "Sol",
                "StationName": "Abraham Lincoln",
                "MarketID": 1,
            },
            {
                "timestamp": "2026-01-01T00:03:00Z",
                "event": "ScanOrganic",
                "StarSystem": "Sol",
                "Body": "Earth",
                "Species_Localised": "Bacterium Acies",
                "Latitude": 1.0,
                "Longitude": 2.0,
            },
        ]
        result = inara.process_journal_events(
            events,
            commander="Tester",
            frontier_id="F123",
            system_name="Sol",
            ship_type="Asp",
            ship_id=1,
            game_version="4.0.0.0",
            odyssey=True,
            api_key="test-key-not-real",
        )
        self.assertTrue(result.dry_run)
        self.assertTrue(result.ok)
        self.assertTrue(result.event_names)
        self.assertEqual(posted, [])
        self.assertIn("addCommanderTravelFSDJump", result.event_names)
        self.assertIn("addCommanderTravelDock", result.event_names)
        self.assertEqual(result.payload["header"]["appVersion"], "2.0.95.0")
        self.assertEqual(result.payload["header"]["appName"], "SrvSurvey")

    def test_inara_replace_key_keeps_latest(self):
        import inara

        inara.clear_state()
        first = inara.InaraEvent("setCommanderShip", "t1", {"shipGameID": 1}, "ship:1")
        second = inara.InaraEvent("setCommanderShip", "t2", {"shipGameID": 1, "shipName": "Bee"}, "ship:1")
        kept = inara._coalesce_replace_keys([first, second, inara.InaraEvent("addCommanderFriend", "t3", {})])
        self.assertEqual([ev.timestamp for ev in kept], ["t2", "t3"])

    def test_publish_current_ship_dry_run_shape(self):
        from raven_colonial import publish_current_ship

        os.environ["SRVSURVEY_RCC_DRY_RUN"] = "1"
        result = publish_current_ship(
            "F123",
            {
                "cmdr": "Tester",
                "name": "Bee",
                "type": "asp",
                "maxCargo": 64,
                "cargo": {"gold": 2},
            },
            api_key="rcc-test",
        )
        self.assertTrue(result.get("dry_run"))
        body = result.get("body") or ""
        self.assertIn("/api/cmdr/currentShip", body)
        self.assertIn("maxCargo", body)

    def test_inara_mapper_ranks_missions_combat_inventory(self):
        import inara

        inara.clear_state()
        ctx = inara.InaraContext(
            commander="Tester",
            frontier_id="F123",
            system_name="Sol",
            station_name="Abraham Lincoln",
            ship_type="Asp",
            ship_id=1,
        )
        names: list[str] = []
        for entry in (
            {"timestamp": "2026-01-01T00:00:00Z", "event": "Rank", "Combat": 3, "Trade": 2},
            {
                "timestamp": "2026-01-01T00:00:01Z",
                "event": "Progress",
                "Combat": 42,
                "Trade": 10,
            },
            {
                "timestamp": "2026-01-01T00:00:02Z",
                "event": "MissionAccepted",
                "MissionID": 7,
                "Name": "Mission_Courier",
                "Faction": "Sol Corp",
            },
            {
                "timestamp": "2026-01-01T00:00:03Z",
                "event": "MissionCompleted",
                "MissionID": 7,
                "Reward": 1000,
                "PermitsAwarded": ["Alioth"],
            },
            {
                "timestamp": "2026-01-01T00:00:04Z",
                "event": "PVPKill",
                "Victim": "BadGuy",
            },
            {
                "timestamp": "2026-01-01T00:00:05Z",
                "event": "Cargo",
                "Vessel": "Ship",
                "Inventory": [{"Name": "gold", "Count": 2}],
            },
            {
                "timestamp": "2026-01-01T00:00:06Z",
                "event": "StoredShips",
                "StarSystem": "Sol",
                "StationName": "Abraham Lincoln",
                "MarketID": 1,
                "ShipsHere": [{"ShipType": "SideWinder", "ShipID": 9, "Name": "Bug"}],
                "ShipsRemote": [],
            },
            {
                "timestamp": "2026-01-01T00:00:07Z",
                "event": "Friends",
                "Status": "Online",
                "Name": "Ally",
            },
        ):
            for ev in inara.map_journal_entry(entry, ctx):
                names.append(ev.name)
        self.assertIn("setCommanderRankPilot", names)
        self.assertIn("addCommanderMission", names)
        self.assertIn("setCommanderMissionCompleted", names)
        self.assertIn("addCommanderPermit", names)
        self.assertIn("addCommanderCombatKill", names)
        self.assertIn("setCommanderInventoryCargo", names)
        self.assertIn("setCommanderShip", names)
        self.assertIn("addCommanderFriend", names)

    def test_inara_offline_skips_post(self):
        import inara

        inara.clear_state()
        os.environ["SRVSURVEY_INARA_OFFLINE"] = "1"
        posted: list[tuple[str, str]] = []
        inara.set_post_hook(lambda u, p: posted.append((u, p)) or (200, "ok"))
        result = inara.process_journal_events(
            [
                {
                    "timestamp": "2026-01-01T00:00:00Z",
                    "event": "Location",
                    "StarSystem": "Sol",
                    "StarPos": [0, 0, 0],
                }
            ],
            commander="Tester",
            frontier_id="F123",
            api_key="test-key",
            odyssey=True,
            game_version="4.0.0.0",
        )
        self.assertTrue(result.skipped)
        self.assertEqual(result.reason, "offline")
        self.assertEqual(posted, [])

    def test_inara_full_mapper_ranks_rep_cargo_missions_credits(self):
        import inara

        inara.clear_state()
        os.environ["SRVSURVEY_INARA_DRYRUN"] = "1"
        events = [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "event": "LoadGame",
                "Commander": "Tester",
                "Credits": 1_000_000,
                "Loan": 0,
                "Ship": "Asp",
                "ShipID": 7,
            },
            {
                "timestamp": "2026-01-01T00:00:01Z",
                "event": "Rank",
                "Combat": 3,
                "Trade": 2,
                "Explore": 5,
            },
            {
                "timestamp": "2026-01-01T00:00:02Z",
                "event": "Progress",
                "Combat": 40,
                "Trade": 10,
                "Explore": 90,
            },
            {
                "timestamp": "2026-01-01T00:00:03Z",
                "event": "Promotion",
                "Combat": 4,
            },
            {
                "timestamp": "2026-01-01T00:00:04Z",
                "event": "Reputation",
                "Empire": 50,
                "Federation": -10,
            },
            {
                "timestamp": "2026-01-01T00:00:05Z",
                "event": "EngineerProgress",
                "Engineer": "Felicity Farseer",
                "Rank": 3,
                "Progress": "Unlocked",
            },
            {
                "timestamp": "2026-01-01T00:00:06Z",
                "event": "Cargo",
                "Vessel": "Ship",
                "Inventory": [{"Name": "hydrogen", "Count": 2}],
            },
            {
                "timestamp": "2026-01-01T00:00:07Z",
                "event": "Materials",
                "Raw": [{"Name": "iron", "Count": 5}],
                "Manufactured": [],
                "Encoded": [],
            },
            {
                "timestamp": "2026-01-01T00:00:08Z",
                "event": "MissionAccepted",
                "Name": "Mission_Courier",
                "MissionID": 42,
                "Faction": "Local",
            },
            {
                "timestamp": "2026-01-01T00:00:09Z",
                "event": "MissionCompleted",
                "MissionID": 42,
                "Reward": 5000,
            },
            {
                "timestamp": "2026-01-01T00:00:10Z",
                "event": "Statistics",
                "Bank_Account": {"Current_Wealth": 1_200_000},
                "Exploration": {"Systems_Visited": 10},
            },
            {
                "timestamp": "2026-01-01T00:00:11Z",
                "event": "StoredShips",
                "StarSystem": "Sol",
                "StationName": "Abraham Lincoln",
                "MarketID": 1,
                "ShipsHere": [{"ShipType": "SideWinder", "ShipID": 9, "Name": "Bug"}],
                "ShipsRemote": [],
            },
        ]
        result = inara.process_journal_events(
            events,
            commander="Tester",
            frontier_id="F123",
            system_name="Sol",
            station_name="Abraham Lincoln",
            ship_type="Asp",
            ship_id=7,
            api_key="test-key-not-real",
            odyssey=True,
            game_version="4.0.0.0",
        )
        self.assertTrue(result.ok)
        self.assertTrue(result.dry_run)
        names = result.event_names
        self.assertIn("setCommanderRankPilot", names)
        self.assertIn("setCommanderReputationMajorFaction", names)
        self.assertIn("setCommanderRankEngineer", names)
        self.assertIn("setCommanderInventoryCargo", names)
        self.assertIn("setCommanderInventoryMaterials", names)
        # Same mission id: Windows ReplaceKey drops the accept when complete is queued.
        self.assertNotIn("addCommanderMission", names)
        self.assertIn("setCommanderMissionCompleted", names)
        self.assertIn("setCommanderGameStatistics", names)
        self.assertIn("setCommanderCredits", names)
        self.assertIn("setCommanderShip", names)

    def test_inara_map_journal_entry_powerplay_and_combat(self):
        import inara

        inara.clear_state()
        ctx = inara.InaraContext(commander="Tester", system_name="Sol", ship_type="Asp", ship_id=1)
        mapped = inara.map_journal_entry(
            {
                "timestamp": "2026-01-01T01:00:00Z",
                "event": "Powerplay",
                "Power": "Aisling Duval",
                "Rank": 2,
                "Merits": 100,
            },
            ctx,
        )
        self.assertTrue(any(e.name == "setCommanderRankPower" for e in mapped))
        combat = inara.map_journal_entry(
            {
                "timestamp": "2026-01-01T01:01:00Z",
                "event": "PVPKill",
                "Victim": "OtherCmdr",
                "StarSystem": "Sol",
            },
            ctx,
        )
        self.assertTrue(any(e.name == "addCommanderCombatKill" for e in combat))

    def test_publish_fc_dry_without_key(self):
        from raven_colonial import publish_fc

        os.environ["SRVSURVEY_DRY_RUN"] = "1"
        result = publish_fc(12345, {"marketId": 12345, "name": "H0-ST", "cargo": {}})
        self.assertTrue(result.get("ok") or result.get("dry_run") or result.get("skipped"))

    def test_rcc_update_system_and_set_primary_offline(self):
        from raven_colonial import set_primary, set_put_hook, update_system

        posted: list[tuple[str, str]] = []
        set_put_hook(lambda u, b: posted.append((u, b)) or (200, "{}"))
        os.environ["SRVSURVEY_RCC_OFFLINE"] = "1"
        sys_result = update_system(
            "F1", "Sol", {"update": [], "delete": [], "architect": "Cmdr"}, api_key="k"
        )
        pri_result = set_primary("Cmdr", "build-1")
        self.assertTrue(sys_result.get("skipped"))
        self.assertTrue(pri_result.get("skipped"))
        self.assertEqual(posted, [])

    def test_rcc_sites_put_dry_run_payload(self):
        from raven_colonial import set_put_hook, update_system

        posted: list[tuple[str, str]] = []
        set_put_hook(lambda u, b: posted.append((u, b)) or (200, "{}"))
        os.environ["SRVSURVEY_RCC_DRY_RUN"] = "1"
        sites_put = {
            "update": [
                {
                    "id": "y1",
                    "name": "Outpost Alpha",
                    "bodyNum": 2,
                    "buildType": "outpost",
                    "status": "complete",
                }
            ],
            "delete": ["old-site"],
            "architect": "Cmdr",
        }
        result = update_system("F1", "Sol", sites_put, api_key="k")
        self.assertTrue(result.get("dry_run"))
        self.assertTrue(result.get("ok"))
        self.assertEqual(posted, [])
        body = result.get("body") or ""
        self.assertIn("Outpost Alpha", body)
        self.assertIn("old-site", body)

    def test_rcc_get_system_offline(self):
        from raven_colonial import get_system

        os.environ["SRVSURVEY_RCC_OFFLINE"] = "1"
        self.assertIsNone(get_system("Sol"))

    def test_rcc_set_primary_dry_run(self):
        from raven_colonial import set_primary, set_put_hook

        posted: list[tuple[str, str]] = []
        set_put_hook(lambda u, b: posted.append((u, b)) or (200, "{}"))
        os.environ["SRVSURVEY_RCC_DRY_RUN"] = "1"
        result = set_primary("Cmdr", "build-99")
        self.assertTrue(result.get("dry_run"))
        self.assertTrue(result.get("ok"))
        self.assertEqual(posted, [])

    def test_bio_predict_lines(self):
        from bio_predict import format_prediction_lines, predict, read_criteria
        from journal import SurveyState

        self.assertGreater(read_criteria(), 0)
        lines = format_prediction_lines(SurveyState(), limit=5)
        self.assertIsInstance(lines, list)

        props = {
            "PlanetClass": "Rocky body",
            "SurfaceGravity": 0.20,
            "SurfaceTemperature": 177.0,
            "SurfacePressure": 0.02,
            "Atmosphere": "Thin Carbon Dioxide",
            "AtmosphereType": "CarbonDioxide",
            "AtmosphereComposition": {"CarbonDioxide": 100.0},
            "DistanceFromArrivalLS": 100.0,
            "Volcanism": "None",
            "Materials": {"Iron": 20.0},
            "Region": "18",
            "Star": ["M"],
            "PrimaryStar": "M",
            "Nebulae": 99999.0,
            "Guardian": "False",
        }
        names = predict(props, body_name="Test A 1")
        self.assertTrue(any("Aleoida" in n for n in names))

    def test_msgcmd_kill_show_edit_survey(self):
        from chat_commands import handle_send_text
        from cmdr_state import clear_commander_cache, get_commander
        from journal import OrganicProgress, SurveyState

        clear_commander_cache()
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            os.environ["XDG_DATA_HOME"] = str(data)
            cmdr = get_commander(commander="MsgCmd", data_dir=data / "srvsurvey", reload=True)
            note = handle_send_text(".kill", cmdr=cmdr, persist=False)
            self.assertIsNotNone(note)
            self.assertIn("Quit", note or "")
            quit_path = Path(tmp) / "srvsurvey" / "request-quit"
            self.assertTrue(quit_path.is_file(), f"missing {quit_path}")

            handle_send_text(".edit", cmdr=cmdr, persist=True)
            self.assertTrue(cmdr.human_site_edit)
            handle_send_text(".start", cmdr=cmdr, persist=True)
            self.assertEqual(cmdr.human_site_survey, "active")
            handle_send_text(".stop", cmdr=cmdr, persist=True)
            self.assertEqual(cmdr.human_site_survey, "stopped")
            self.assertFalse(cmdr.human_site_edit)

            survey = SurveyState(
                organic_progress=(
                    OrganicProgress(
                        genus="Aleoida",
                        species="Aleoida Arcus - Emerald",
                        scan_type="Log",
                        body_name="Body A",
                    ),
                )
            )
            msg = handle_send_text(
                ".show", cmdr=cmdr, survey=survey, persist=False
            )
            self.assertIsNotNone(msg)
            self.assertIn("Aleoida", msg or "")

            msg_new = handle_send_text(".new", cmdr=cmdr, persist=False)
            self.assertIsNotNone(msg_new)
            self.assertIn(".add", msg_new or "")


class SpanshAndRegionTests(unittest.TestCase):
    def test_body_query_matches_windows_filter_shape(self) -> None:
        from spansh_search import build_bodies_query

        query = build_bodies_query(
            {
                "atmosphere": "Thin Carbon dioxide",
                "volcanism_type": "Water Magma",
                "landmarks": "Stratum/Stratum Tectonicas",
                "distance": "0~100",
            },
            reference_system="Sol",
        )
        self.assertEqual(query["filters"]["atmosphere"], {"value": ["Thin Carbon dioxide"]})
        self.assertEqual(query["filters"]["volcanism_type"], {"value": ["Water Magma"]})
        self.assertEqual(
            query["filters"]["landmarks"],
            [{"type": "Stratum", "subtype": ["Stratum Tectonicas"]}],
        )
        self.assertEqual(query["filters"]["distance"], {"min": 0, "max": 100})
        self.assertEqual(query["reference_system"], "Sol")

    def test_sol_region_and_nebula(self) -> None:
        from galactic_region import closest_nebula_ly, find_region

        found = find_region(0.0, 0.0, 0.0)
        self.assertIsNotNone(found)
        assert found is not None
        self.assertGreater(found[0], 0)
        self.assertTrue(found[1])
        dist = closest_nebula_ly((0.0, 0.0, 0.0))
        self.assertLess(dist, 99999.0)

    def test_threat_persists_on_cmdr(self) -> None:
        from chat_commands import handle_send_text
        from cmdr_state import CmdrState

        cmdr = CmdrState()
        handle_send_text(".threat 2", cmdr=cmdr, persist=False)
        self.assertEqual(cmdr.settlement_threat, 2)
        restored = CmdrState.from_dict(cmdr.to_dict())
        self.assertEqual(restored.settlement_threat, 2)


class PublishedDataAndShareTests(unittest.TestCase):
    def test_refresh_downloads_when_versions_are_newer(self) -> None:
        import io
        import zipfile

        from pub_data import refresh_published_data

        blob = io.BytesIO()
        with zipfile.ZipFile(blob, "w") as archive:
            archive.writestr("sample.json", "{}")
        payload = blob.getvalue()
        index = json.dumps(
            {
                "ghVer": "2.0.95.0",
                "msVer": "2.0.95.0",
                "bioCriteria": 1,
                "bioEngine": 4,
                "codexRef": 1,
                "settlementTemplate": 1,
                "guardian": 1,
                "settlements": 1,
                "nicknames": 1,
                "ggg": 1,
            }
        ).encode()

        def fetch(url: str) -> tuple[int, bytes]:
            if url.endswith("data.json"):
                return 200, index
            if url.endswith(".zip"):
                return 200, payload
            if url.endswith("nicknames"):
                return 200, b'[{"name":"Sol","nickname":"Home"}]'
            return 200, b"{}"

        with tempfile.TemporaryDirectory() as tmp:
            os.environ.pop("SRVSURVEY_NET_OFFLINE", None)
            os.environ.pop("SRVSURVEY_PUB_OFFLINE", None)
            os.environ.pop("SRVSURVEY_DRY_RUN", None)
            result = refresh_published_data(data_dir=Path(tmp), fetch=fetch)
            self.assertTrue(result["ok"])
            self.assertIn("codexRef", result["actions"])
            self.assertIn("guardian", result["actions"])
            self.assertTrue((Path(tmp) / "pub" / "ggg.json").is_file())
            self.assertTrue((Path(tmp) / "pub" / "nicknames.json").is_file())

    def test_share_package_includes_only_discoveries(self) -> None:
        from share_sites import build_share_package

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cmdr = root / "cmdr"
            cmdr.mkdir()
            (cmdr / "F1.json").write_text(
                json.dumps(
                    {
                        "fid": "F1",
                        "guardian_sites": {
                            "empty": {"site_key": "empty", "heading": -1, "relic_tower_heading": -1},
                            "found": {
                                "site_key": "found",
                                "heading": 12,
                                "extra_poi": [{"name": "relic"}],
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            result = build_share_package(data_dir=root)
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["sites"], ["found"])
            self.assertIn("surveys-F1-", str(result["zip"]))
            self.assertTrue(Path(str(result["zip"])).is_file())


class PortableWindowsBehaviorTests(unittest.TestCase):
    def test_quest_side_load_indexes_lua_without_running_it(self):
        from quests import (
            activate_first_chapter,
            apply_script_journal,
            journal_handlers,
            parse_message_markdown,
            side_load_quest,
        )

        self.assertEqual(journal_handlers("function on_FSDJump(entry)\nend\n"), ["FSDJump"])
        parsed = parse_message_markdown(
            "from: Ada\nsubject: Hello\naction: go: Depart\n\nBody line\n",
            "hello",
        )
        self.assertEqual(parsed["from"], "Ada")
        self.assertEqual(parsed["actions"]["go"], "Depart")
        self.assertIn("Body line", parsed["body"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "quest.json").write_text(
                json.dumps(
                    {
                        "id": "demo",
                        "ver": 1,
                        "publisher": "local",
                        "title": "Demo",
                        "firstChapter": "intro",
                        "objectives": {"land": "Land on the pad"},
                    }
                ),
                encoding="utf-8",
            )
            (root / "intro.lua").write_text(
                "function onStart()\nend\nfunction on_Docked(entry)\nend\n",
                encoding="utf-8",
            )
            (root / "hello.md").write_text(
                "from: Ada\nsubject: Hello\n\nWelcome.\n",
                encoding="utf-8",
            )
            state = side_load_quest(root, data_dir=root)
            self.assertEqual(state["chapters"][0]["handlers"], ["Start", "Docked"])
            self.assertTrue(state["chapters"][0]["active"])
            activate_first_chapter(state)
            fired = apply_script_journal(state, {"event": "Docked", "StationName": "Jameson"})
            self.assertEqual(fired, ["intro.on_Docked"])
            self.assertEqual(state["keptLasts"]["Docked"]["StationName"], "Jameson")
            self.assertEqual(state["messages"][0]["subject"], "Hello")
            from quests import _LIVE

            fresh = json.loads(json.dumps(state))
            fresh.pop("__runtime_id", None)
            _LIVE.clear()
            again = apply_script_journal(fresh, {"event": "Docked", "StationName": "Jameson"})
            self.assertEqual(again, ["intro.on_Docked"])

    def test_spansh_canonn_and_plotter_anchor_overrides(self) -> None:
        from canonn import import_canonn_challenge
        from plot_pos import plotter_anchors, reset_plotter_anchor, set_plotter_anchor
        from spansh_search import build_missing_variants_query, poll_route

        query = build_missing_variants_query(
            1.5,
            2.0,
            3.25,
            "bacterium",
            "bacterium informem",
            ["green", "red"],
        )
        landmark = query["filters"]["landmarks"][0]
        self.assertEqual(landmark["type"], "Bacterium")
        self.assertEqual(landmark["subtype"], ["Bacterium Informem"])
        self.assertEqual(landmark["variant"], ["Green", "Red"])
        self.assertEqual(query["reference_coords"]["z"], 3.25)

        calls = {"n": 0}

        def fetch(_route_id: str) -> dict:
            calls["n"] += 1
            if calls["n"] < 2:
                return {"ok": True, "skipped": False, "reason": "", "result": {"state": "queued", "status": "ok"}}
            return {"ok": True, "skipped": False, "reason": "", "result": {"state": "completed", "status": "ok"}}

        done = poll_route("abc", max_seconds=60, pause_seconds=5, fetch=fetch, sleep=lambda _seconds: None)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(done["result"]["state"], "completed")

        def challenge(_url: str) -> dict:
            return {
                "Biology": {
                    "hud_category": "Biology",
                    "types_found": ["Bacterium Informem"],
                }
            }

        imported = import_canonn_challenge(
            "grinning2001",
            codex_rows=[
                {"english_name": "Bacterium Informem", "hud_category": "Biology", "entryid": "42"},
                {"english_name": "Bacterium Informem", "hud_category": "Geology", "entryid": "7"},
            ],
            known_ids=[7],
            fetch=challenge,
        )
        self.assertEqual(imported["added"], [42])

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["XDG_CONFIG_HOME"] = tmp
            plotter_anchors.cache_clear()
            try:
                set_plotter_anchor("PlotSysStatus", "right", 12, "top", 4)
                self.assertEqual(plotter_anchors()["PlotSysStatus"], ("right", 12, "top", 4))
                reset_plotter_anchor("PlotSysStatus")
                plotter_anchors.cache_clear()
                self.assertNotEqual(plotter_anchors().get("PlotSysStatus"), ("right", 12, "top", 4))
            finally:
                os.environ.pop("XDG_CONFIG_HOME", None)
                plotter_anchors.cache_clear()

    def test_stripe_retry_queue_codex_and_screenshot_command(self) -> None:
        from codex_firsts import known_ids, save_challenge_firsts
        from eddn import clear_state, set_header_from_load_game, set_post_hook, upload
        from fss_pixel_watch import gnome_area_command
        from mutation_queue import drain, enqueue
        from plot_pos import plotter_opacity, scale_rgba_alpha, snapshot_user_anchors, restore_user_anchors
        from plot_vertical_stripe import render_vertical_stripe, select_stripe, stripe_opacity

        self.assertEqual(stripe_opacity(landed=True, mode="alpha", altitude=10, target=1200), 0.0)
        self.assertEqual(stripe_opacity(landed=False, mode="relictower", altitude=0, target=0), 0.8)
        self.assertIsNone(
            select_stripe(
                mode="aerial",
                site_type="Alpha",
                disable_ruins_grid=False,
                disable_aerial_grid=False,
                in_srv=True,
                on_foot=False,
                landed=False,
                aerial_alpha=1200,
                aerial_beta=1550,
                aerial_gamma=1600,
            )
        )
        chosen = select_stripe(
            mode="heading",
            site_type="Alpha",
            disable_ruins_grid=False,
            disable_aerial_grid=True,
            in_srv=False,
            on_foot=False,
            landed=False,
            aerial_alpha=1200,
            aerial_beta=1550,
            aerial_gamma=1600,
        )
        self.assertEqual(chosen, ("buttress", 20.0))
        bitmap = render_vertical_stripe(
            mode="heading",
            site_type="Alpha",
            game_width=200,
            game_height=120,
            altitude=20,
            heading=15,
            landed=False,
            in_srv=False,
            on_foot=False,
            disable_ruins_grid=False,
            disable_aerial_grid=False,
            aerial_alpha=1200,
            aerial_beta=1550,
            aerial_gamma=1600,
        )
        self.assertIsNotNone(bitmap)
        assert bitmap is not None
        self.assertEqual(bitmap[1], 200)
        self.assertGreater(bitmap[0].count(bytes([255])), 0)
        faded = scale_rgba_alpha(b"\xff\x00\x00\xff", 0.5)
        self.assertEqual(faded[3], 127)

        command = gnome_area_command("/usr/bin/busctl", "/tmp/shot.png", (1, 2, 32, 16))
        self.assertIn("ScreenshotArea", command)
        self.assertIn("iiiibs", command)
        self.assertEqual(command[-6:], ["1", "2", "32", "16", "false", "/tmp/shot.png"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os.environ["XDG_DATA_HOME"] = str(root)
            os.environ["XDG_CONFIG_HOME"] = str(root)
            from plot_pos import plotter_anchors, set_plotter_anchor

            plotter_anchors.cache_clear()
            previous_offline = os.environ.pop("SRVSURVEY_NET_OFFLINE", None)
            previous_dry = os.environ.pop("SRVSURVEY_EDDN_DRYRUN", None)
            try:
                shot = snapshot_user_anchors()
                set_plotter_anchor("PlotSysStatus", "left", 3, "top", 4, 0.4)
                self.assertEqual(plotter_opacity("PlotSysStatus"), 0.4)
                restore_user_anchors(shot)
                self.assertIsNone(plotter_opacity("PlotSysStatus"))

                self.assertTrue(enqueue("eddn", "https://eddn.edcd.io/upload/", "{}", data_dir=root))
                self.assertFalse(enqueue("eddn", "https://eddn.edcd.io/upload/", "{}", data_dir=root))
                self.assertEqual(drain("eddn", lambda _url, _body: (500, "down"), data_dir=root), 0)
                self.assertEqual(drain("eddn", lambda _url, _body: (400, "bad"), data_dir=root), 1)
                self.assertEqual(drain("eddn", lambda _url, _body: (200, "ok"), data_dir=root, blocked=True), 0)

                saved = save_challenge_firsts(
                    "F123",
                    "Tester",
                    codex_rows=[{"english_name": "Bacterium Informem", "hud_category": "Biology", "entryid": "42"}],
                    data_dir=root,
                    fetch=lambda _url: {"Biology": {"hud_category": "Biology", "types_found": ["Bacterium Informem"]}},
                )
                self.assertEqual(saved["written"], 1)
                self.assertEqual(known_ids("F123", root), {42})
                again = save_challenge_firsts(
                    "F123",
                    "Tester",
                    codex_rows=[{"english_name": "Bacterium Informem", "hud_category": "Biology", "entryid": "42"}],
                    data_dir=root,
                    fetch=lambda _url: {"Biology": {"hud_category": "Biology", "types_found": ["Bacterium Informem"]}},
                )
                self.assertEqual(again["added"], [])

                clear_state()
                set_header_from_load_game("Cmdr Test", "4.0.0.1904", "r1")
                calls = {"n": 0}

                def hook(_url: str, _body: str) -> tuple[int, str]:
                    calls["n"] += 1
                    if calls["n"] == 1:
                        return 500, "down"
                    return 200, "ok"

                set_post_hook(hook)
                message = {
                    "event": "FSDJump",
                    "timestamp": "2026-09-27T00:00:00Z",
                    "SystemAddress": 1,
                    "StarSystem": "Demo",
                    "StarPos": [1.0, 2.0, 3.0],
                }
                schema = "https://eddn.edcd.io/schemas/journal/1"
                held = upload(message, schema, eddn_upload=True, environment="dev")
                self.assertEqual(held.status_code, 500)
                retried = upload(message, schema, eddn_upload=True, environment="dev")
                self.assertEqual(retried.status_code, 200)
                from mutation_queue import queue_path

                queued = queue_path("eddn", root / "srvsurvey")
                if queued.is_file():
                    self.assertEqual(json.loads(queued.read_text(encoding="utf-8")), [])
            finally:
                set_post_hook(None)
                clear_state()
                os.environ.pop("XDG_DATA_HOME", None)
                os.environ.pop("XDG_CONFIG_HOME", None)
                plotter_anchors.cache_clear()
                if previous_offline is None:
                    os.environ.pop("SRVSURVEY_NET_OFFLINE", None)
                else:
                    os.environ["SRVSURVEY_NET_OFFLINE"] = previous_offline
                if previous_dry is None:
                    os.environ.pop("SRVSURVEY_EDDN_DRYRUN", None)
                else:
                    os.environ["SRVSURVEY_EDDN_DRYRUN"] = previous_dry

    def test_canonn_sheet_and_raven_phase_buckets(self) -> None:
        from canonn_sheets import import_catalog_xml, read_ruins_sheet, read_structures_sheet
        from raven_phases import site_in_phase

        self.assertTrue(site_in_phase("noBodyOrbitalPorts", -1, "no_truss"))
        self.assertFalse(site_in_phase("allSurfaceSites", 1, "no_truss"))
        self.assertTrue(site_in_phase("noBodyInstallation", -1, "installation?"))
        self.assertTrue(site_in_phase("allSurfaceSites", 2, ""))
        self.assertTrue(site_in_phase("allSurfaceSites", 2, "settlement"))
        ns = "urn:schemas-microsoft-com:office:spreadsheet"
        xml = (
            '<?xml version="1.0"?>'
            f'<Workbook xmlns="{ns}" xmlns:ss="{ns}">'
            '<Worksheet ss:Name="Ruins"><Table>'
            "<Row><Cell><Data>System</Data></Cell></Row>"
            "<Row>"
            "<Cell><Data>Synuefe</Data></Cell>"
            "<Cell><Data>skip</Data></Cell>"
            "<Cell><Data>1 b</Data></Cell>"
            "<Cell><Data>skip</Data></Cell>"
            "<Cell><Data>α β</Data></Cell>"
            '<Cell ss:Index="18"><Data>1.5</Data></Cell>'
            "<Cell><Data>2.5</Data></Cell>"
            "<Cell><Data>-3</Data></Cell>"
            "</Row></Table></Worksheet>"
            '<Worksheet ss:Name="Structures"><Table>'
            "<Row><Cell><Data>System</Data></Cell></Row>"
            "<Row>"
            "<Cell><Data>Synuefe</Data></Cell>"
            "<Cell><Data>skip</Data></Cell>"
            "<Cell><Data>2 a</Data></Cell>"
            "<Cell><Data>skip</Data></Cell>"
            "<Cell><Data>Bear</Data></Cell>"
            '<Cell ss:Index="18"><Data>4</Data></Cell>'
            "<Cell><Data>5</Data></Cell>"
            "<Cell><Data>6</Data></Cell>"
            "</Row></Table></Worksheet></Workbook>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sheet = root / "catalog.xml"
            sheet.write_text(xml, encoding="utf-8")
            ruins = read_ruins_sheet(sheet)
            self.assertEqual([row["siteType"] for row in ruins], ["Alpha", "Beta"])
            self.assertEqual(ruins[0]["starPos"], [1.5, 2.5, -3.0])
            self.assertEqual(ruins[1]["idx"], 2)
            structures = read_structures_sheet(sheet)
            self.assertEqual(structures[0]["siteType"], "Bear")
            counts = import_catalog_xml(sheet, root)
            self.assertEqual(counts, {"ruins": 2, "structures": 1})

    def test_quest_lua_error_and_offline_queue(self) -> None:
        from quests import apply_script_journal, publish_quest_stub, rcc_queue_path, side_load_quest

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "quest.json").write_text(
                json.dumps(
                    {
                        "id": "boom",
                        "ver": 1,
                        "publisher": "local",
                        "title": "Boom",
                        "firstChapter": "intro",
                        "objectives": {"land": "Land"},
                    }
                ),
                encoding="utf-8",
            )
            (root / "intro.lua").write_text(
                "function onStart()\n"
                "  quest.set('flag', true)\n"
                "  objective.show('land', 1, 2)\n"
                "  if cmdr.name ~= '' then quest.set('who', cmdr.name) end\n"
                "end\n"
                "function on_Docked(entry)\n"
                "  error('dock failed')\n"
                "end\n",
                encoding="utf-8",
            )
            previous = {name: os.environ.get(name) for name in ("DISPLAY", "WAYLAND_DISPLAY")}
            os.environ.pop("DISPLAY", None)
            os.environ.pop("WAYLAND_DISPLAY", None)
            try:
                state = side_load_quest(root, data_dir=root)
            finally:
                for name, value in previous.items():
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value
            self.assertTrue(state["luaExecuted"])
            self.assertTrue(state["vars"]["flag"])
            self.assertEqual(state["objectives"]["land"]["state"], "visible")
            self.assertEqual(state["objectives"]["land"]["current"], 1)
            os.environ.pop("DISPLAY", None)
            os.environ.pop("WAYLAND_DISPLAY", None)
            try:
                fired = apply_script_journal(state, {"event": "Docked", "StationName": "Jameson"})
            finally:
                for name, value in previous.items():
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value
            self.assertEqual(fired, ["intro.on_Docked"])
            home = root / "home"
            env_prev = os.environ.get("XDG_DATA_HOME")
            off_prev = os.environ.get("SRVSURVEY_NET_OFFLINE")
            os.environ["XDG_DATA_HOME"] = str(home)
            os.environ["SRVSURVEY_NET_OFFLINE"] = "1"
            try:
                queued = publish_quest_stub("F123", {"id": "q1"}, api_key="secret-key")
                self.assertTrue(queued["queued"])
                self.assertFalse(queued["ok"])
                rows = json.loads(rcc_queue_path().read_text(encoding="utf-8"))
                self.assertEqual(rows["items"][0]["reason"], "offline")
                self.assertNotIn("secret-key", rcc_queue_path().read_text(encoding="utf-8"))
            finally:
                if env_prev is None:
                    os.environ.pop("XDG_DATA_HOME", None)
                else:
                    os.environ["XDG_DATA_HOME"] = env_prev
                if off_prev is None:
                    os.environ.pop("SRVSURVEY_NET_OFFLINE", None)
                else:
                    os.environ["SRVSURVEY_NET_OFFLINE"] = off_prev

    def test_canonn_and_spansh_offline_skip_remaining_reads(self):
        from canonn import (
            find_nearest_system_with_bio,
            get_raw_ruins,
            get_stations,
            load_static_catalogs,
            submit_station,
            system_bio_stats,
        )
        from spansh_search import (
            atmosphere_clause_from_result,
            build_gas_clause,
            get_system_address,
            query_stations,
        )

        prev = {
            name: os.environ.get(name)
            for name in ("SRVSURVEY_NET_OFFLINE", "SRVSURVEY_DRY_RUN")
        }
        os.environ["SRVSURVEY_NET_OFFLINE"] = "1"
        os.environ["SRVSURVEY_DRY_RUN"] = "1"
        try:
            self.assertTrue(system_bio_stats(1)["skipped"])
            self.assertTrue(get_stations(1)["skipped"])
            self.assertTrue(get_raw_ruins()["skipped"])
            self.assertTrue(submit_station({"name": "X"})["skipped"])
            self.assertTrue(find_nearest_system_with_bio(0, 0, 0, "Brain Tree")["skipped"])
            self.assertEqual(get_system_address("Sol"), 0)
            self.assertTrue(query_stations({"size": 1})["skipped"])
        finally:
            for name, value in prev.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        catalogs = load_static_catalogs()
        self.assertGreater(catalogs["ruins"], 0)
        clause = build_gas_clause("Stratum", "Tectonicas", "Carbon dioxide")
        self.assertEqual(clause["filters"]["atmosphere"]["value"], ["Thin Carbon dioxide"])
        text = atmosphere_clause_from_result(
            "Carbon dioxide",
            {"atmosphere_composition": [{"name": "Carbon dioxide", "share": 100}]},
        )
        self.assertEqual(text, '"atmosComp [CarbonDioxide >= 100]"')

    def test_journal_dock_barycentre_and_materials(self):
        from journal import bump_materials, read_session

        snap = read_session(
            "\n".join(
                [
                    '{"event":"FSDJump","StarSystem":"Sol","SystemAddress":1}',
                    '{"event":"ScanBaryCentre","SystemAddress":1,"BodyID":7}',
                    '{"event":"Materials","Raw":[{"Name":"iron","Count":2}]}',
                    '{"event":"MaterialCollected","Category":"Raw","Name":"iron","Count":3}',
                    '{"event":"Docked","StationName":"Jameson Memorial","SystemAddress":1,"MarketID":1,"StationType":"Orbis"}',
                    '{"event":"Undocked","StationName":"Jameson Memorial"}',
                    '{"event":"Touchdown"}',
                    '{"event":"Liftoff"}',
                    '{"event":"Died"}',
                ]
            )
        )
        self.assertIn(7, snap.survey.barycentre_ids)
        self.assertEqual(snap.survey.materials.raw[0].count, 5)
        self.assertFalse(snap.survey.docked)
        self.assertIsNone(snap.survey.docked_station)
        self.assertEqual(snap.survey.last_docked_station, "Jameson Memorial")
        self.assertIsNone(snap.survey.last_construction_station)
        self.assertTrue(snap.survey.died)
        self.assertFalse(snap.survey.landed)
        bumped = bump_materials(None, "nickel", 1, "Raw")
        self.assertEqual(bumped.raw[0].name, "nickel")

    def test_post_process_star_cache_offsets_builder_and_scan(self):
        from post_process import journal_file_time, post_process_journals
        from raven_scan import next_phase, review_bucket, scan_instruction
        from ship_offsets import adjust_landing, load_windows_offsets, set_ship_offset
        from site_builder import add_point, commit_building, end_polygon, new_building
        from star_cache import backup_cache, download_star_cache, restore_cache

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "Journal.2024-06-01T120000.01.log"
            log.write_text(
                "\n".join(
                    [
                        '{"event":"FSDJump","JumpDist":12.5,"StarSystem":"Sol"}',
                        '{"event":"ApproachBody"}',
                        '{"event":"ScanOrganic","ScanType":"Analyse"}',
                        '{"event":"Docked"}',
                        '{"event":"Died"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            stamp = journal_file_time(log)
            self.assertIsNotNone(stamp)
            stats = post_process_journals(root, start=stamp)
            self.assertEqual(stats.jumps, 1)
            self.assertEqual(stats.distance_ly, 12.5)
            self.assertEqual(stats.organisms_analysed, 1)
            self.assertEqual(stats.died, 1)
            original = root / "VisitedStarsCache.dat"
            backup = root / "backup-VisitedStarsCache.dat"
            original.write_bytes(b"cache")
            self.assertEqual(backup_cache(original, backup), "backed-up")
            self.assertEqual(restore_cache(original, backup), "restored")
            os.environ["SRVSURVEY_NET_OFFLINE"] = "1"
            try:
                skipped = download_star_cache("Sol", root / "Sol.dat")
                self.assertTrue(skipped["skipped"])
            finally:
                os.environ.pop("SRVSURVEY_NET_OFFLINE", None)
            path = set_ship_offset("sidewinder", 1.0, -2.0, home=root, environ={})
            self.assertTrue(path.is_file())
        offsets = load_windows_offsets()
        self.assertIn("sidewinder", offsets)
        same = adjust_landing("foot", 1.0, 2.0, 0, 1000, offsets=offsets)
        self.assertEqual(same, (1.0, 2.0))
        moved = adjust_landing("type6", 0.0, 0.0, 0, 6_371_000, offsets=offsets)
        self.assertNotEqual(moved[0], 0.0)
        building = new_building()
        add_point(building, 0, 0)
        add_point(building, 4, 0)
        end_polygon(building)
        template = commit_building({}, building, "Pad")
        self.assertEqual(template["buildings"][0]["name"], "Pad")
        phase, message = scan_instruction(
            fss_progress=None,
            fss_complete=False,
            body_count=None,
            scanned_count=0,
            bodies_known=0,
        )
        self.assertEqual(phase, "scanning")
        self.assertIn("Discovery", message)
        sites = [
            {"name": "Inst", "buildType": "installation", "bodyNum": -1},
            {"name": "Port", "buildType": "orbis", "bodyNum": -1},
            {"name": "Town", "buildType": "settlement", "bodyNum": 3},
        ]
        self.assertEqual(len(review_bucket(sites, "noBodyInstallation")), 1)
        nxt, _msg = next_phase("scanning", sites, scan_done=True)
        self.assertEqual(nxt, "noBodyInstallation")


if __name__ == "__main__":
    unittest.main()
