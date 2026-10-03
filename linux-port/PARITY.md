# SrvSurvey Linux ↔ Windows Parity

Living checklist for 1-1 design and function. Inventory source:
[Inventory Windows Settings](56a51de3-5c8a-42fe-9b5c-b4fbefe4ed81).

## Architecture

| Layer | Windows | Linux now |
| --- | --- | --- |
| Journal / game state | `Game` + journal files | `journal.py` / `watcher.py` / `companion.py` |
| Plotters | `PlotBase2` bitmaps | Pillow panels + X11 presenter |
| Settings | `Settings.cs` / `FormSettings` | `game_settings.py` + GTK tabs (`gs.*`) |
| Colonisation FC data | RavenColonial HTTP | `raven_colonial.py` (wired) |
| Main window | WinForms `Main` | Avalonia Main (status + present/settings; Search/Guardian/Codex/Colonise/Travel/Help menus open real feature windows) |

## Settings (`Settings.cs` → `gs.*`)

- [x] All bool defaults mirrored in `game_settings.py`
- [x] GTK FormSettings tabs (Windows order: General, Bio Scanning, Guardians, Screenshots, Exploration, External Data, Settlements, Key Chords, More, About). Every `GameSettings` field editable; Linux AppSettings/HUD on General. Inara/RCC API-key dialogs → XDG secrets; VR Adjust + overlay-position controls; colonisation under External Data; notifications under More. Not pixel-perfect WinForms layout.
- [x] Persist `gs.<name>=…` in `~/.config/srvsurvey/config`
- [x] Numeric spinners (opacity, DSS thresholds, zooms, bio rings, sphere limits, …)
- [x] Key-chord editor (`keyActions_TEST` / `KeyChords.defaultKeys`)
- [x] Theme colour pickers (`defaultOrange`, cyan, banner, …)
- [x] Screenshot processing paths + processor (`screenshot.py` folder poll / banner)
- [x] Notifications sub-object (`allowNotifications.*`)
- [x] External: `useExternalData` / `useExternalBioData` / `eddnUpload` / `eddnEnvironment` / `uploadGGG` grouped
- [x] Inara / RavenColonial API keys in XDG secrets file (never in main config). Inara journal→API upload via `inara.py` (full Windows mapper; key presence = opt-in; offline / dry-run never POSTs). RCC key used for `publish_fc` / `update_system` / SitesPut / quest publish; Avalonia My Projects + Stations/Sites editor call `RavenColonialClient` HttpClient only (no Python Cli)
- [x] Overlay position (margin + panel_offset_x/y) + VR Adjust button

## Colonisation (`PlotBuildCommodities`)

- [x] Visual 1-1 (theme colours, gothic stand-in, layout)
- [x] `buildProjectsShowSumFC` / Delta / Collapse wired
- [x] `buildProjectsSuppressOtherOverlays`
- [x] RavenColonial linked FC cargo client (`raven_colonial.py`)
- [x] Assigned commodities / pending updates (pins + Updating… footer via pending_updates)
- [x] Alpha vs grouped by dock context
- [x] Untracked project / FC warnings (warning line on model)
- [x] Inline FC column / highlight-almost-FC

## Plotters (Windows → Linux)

| Plotter | Status |
| --- | --- |
| PlotBuildCommodities | Done — visual + FC + inline/highlight/alpha/warnings |
| PlotSysStatus | Done — `plot_sys_status.py` |
| PlotFSS | Done — `plot_fss.py` (journal last-scan). Pixel watch tries X11, grim, then a ScreenCast restore token. An ungranted capture stays journal-driven. |
| PlotFSSInfo | Done — `plot_fss_info.py` (shows in FSS / optional maps) |
| PlotBioStatus | Done — `plot_bio_status.py` (panel id `biostatus`) |
| PlotBioSystem | Done — `plot_bio_system.py` (panel id `biosystem`; Codex rewards via `codex_ref.py`; BioCriteria predictions via `bio_predict.py` when Scan props exist) |
| PlotJumpInfo | Done — `plot_jump_info.py` (route hops + NetSysData enrichment) |
| PlotBodyInfo | Done — `plot_body_info.py` (Scan/Status; Codex bio rewards / volume bars via `codex_ref.py`) |
| PlotGalMap | Done — `plot_gal_map.py` (NetSysData discovery lines) |
| PlotGuardians | Done for the live overlay — `plot_guardians.py`. Modes, survey header, compass, obelisk group names, and per-tower `.tower` headings match the Windows draw and score rules. The Avalonia editor writes `guardianSites` angle, distance, and `relic_headings`. It does not paint the WinForms background image. |
| PlotGuardianStatus | Done — `plot_guardian_status.py` |
| PlotGuardianSystem | Done — `plot_guardian_system.py` |
| PlotRamTah | Done — `plot_ram_tah.py` + `ram_tah_decode.py` + `cmdr_state` decode sets / Ram Tah mission Active (`Mission_TheDead` / `_002`) |
| PlotHumanSite | Done — approach + map; `.settlement` chat sets heading via `chat_commands` → `cmdr_state` (by marketId) |
| PlotPriorScans | Done — `plot_prior_scans.py` (panel `priorscans`; Canonn + offline stub) |
| PlotTrackers | Done — `plot_trackers.py` |
| PlotTrackTarget | Done — `plot_trackers.py` (`tracktarget`) |
| PlotStationInfo | Done — `plot_station_info.py` (journal Docked + Spansh dump) |
| PlotMassacre | Done — `plot_massacre.py` |
| PlotFloatie | Done — `plot_floatie.py` |
| PlotFootCombat | Done — `plot_foot_combat.py` |
| PlotMiniTrack | Done — `plot_trackers.py` (`minitrack`) |
| PlotGrounded | Done — `plot_grounded.py` (circular heading-up / N-up radar; bookmarks + bio dots) |
| PlotFlightWarning | Done — `plot_flight_warning.py` |
| PlotPulse | Done — `plot_pulse.py` (journal-write recency intensity via host `last_journal_write_monotonic`) |
| PlotQuestMini | Done — `plot_quest_mini.py` + `quests.py` (MissionAccepted/Completed/Abandoned → XDG `quests.json`) |
| PlotSphericalSearch | Done — `plot_spherical_search.py` (sphere distance + boxel lines; `COPY_NEXT_BOXEL` via `wl-copy`/`xclip`/GTK) |
| PlotAdjustVR / VR | Done — `plot_adjust_vr.py` opacity/scale via chords + GTK; OpenVR/headset inject N/A on Wayland |
| BigOverlay / PlotContainer | N/A — Linux uses X11 presenter (no DirectX PlotContainer) |

## External services

- [x] Inara full journal→API mapper (`inara.py` — Windows `InaraEventMapper` + `InaraCreditTracker` parity: travel, ranks/Progress/Promotion, Reputation, EngineerProgress, Powerplay, cargo/materials snapshots + deltas, credits/Statistics, shipyard/StoredShips/Loadout/StoredModules, missions, combat, suits/ShipLocker, CommunityGoal, Friends; plus Linux ScanOrganic location hint). API key from XDG secrets; `SRVSURVEY_NET_OFFLINE` / `SRVSURVEY_INARA_OFFLINE` / dry-run safe. Wired from `host.process_external_uploads` → `process_journal_events`
- [x] RavenColonial colonise writes (`publish_fc` / `update_system` SitesPut / `set_primary` / `update_sys_bodies` / `get_system`; RCC key from XDG secrets on mutating HTTP; Avalonia My Projects Publish FC / Update System / Set Primary / Fetch Active / Edit Sites via `RavenColonialClient` only; fail-soft offline / dry-run)
- [x] FormRavenUpdater / Update Stations/Sites — Avalonia `RavenSitesWindow` (Colonise → Update Stations / Sites…): load system, edit/add/remove sites, PUT SitesPut via `RavenColonialClient.UpdateSystemSitesAsync`. Not a pixel clone of the WinForms scanning wizard; same save API path
- [x] Canonn prior scans / POI (`canonn.py` + offline stub)
- [x] Spansh / EDSM (`net_sys_data.py` for jump/galmap/station)
- [x] EDDN upload (`eddn.py` — offline/dry-run safe; main journal schemas)
- [x] GGG upload (`ggg.py` + `raven_colonial.upload_ggg`; local `ggg.json` match)
- [x] Quests: Lua side-load and journal replay run in `quests.py`. RCC publish stays offline-safe and dry-run never sends.
- [x] Bio predictions (`bio_predict.py` BioCriteria rules engine + Avalonia Predictions via `BioPredictCli`; same `SrvSurvey/bio-criteria/*.json` as Windows BioPredictor; codexRef rewards; PlotBioSystem shows predicted genera when Scan props allow)

## UX

- [x] Each plotter is its own window, placed from `SrvSurvey/plotters.json`. The build list is its own panel.
- [x] Present gate, chip toggle, tray. GlobalShortcuts is wired for keys while Elite is focused. The chip remains if that dialog is cancelled.
- [x] Avalonia Main covers the Windows menu surface for the Linux-capable windows. This is not a line-for-line port of every WinForms paint method.
- [x] FormSettings layout parity (Windows tab names/order + field coverage; API key + VR Adjust + overlay position; not pixel-perfect WinForms)
- [x] Key chords (ALT S colony, ALT F FSS, ALT B body, CTRL C copyNextBoxel, ALT CTRL I toggleImageEmbed, ALT V VR adjust, …)
- [x] Screenshot convert + banner embed (`screenshot.py`; present/watch mtime poll)

## Chat MsgCmd (`MsgCmd.cs` / Main handlers)

- [x] Guardian / human site cmds already ported (`.aerial` / `.map` / `.heading` / `.site` / `.to` / `.os` / `.empty` / `.add` / `.remove` / `.note` / `.settlement` / `z` / `.threat` stub)
- [x] `.target here` / `.target on` / `.target off` → `gs.targetLat` / `gs.targetLong` / `gs.targetLatLongActive` via `config.set_ground_target*` (PlotTrackTarget reads these)
- [x] `+name` / `-name` / `=name` / `--name` / `---` body bookmarks → `cmdr_state.bookmarks` (Windows name→positions map); merged into `SurveyState.bookmarks` for PlotTrackers / PlotGrounded
- [x] `.visited` / `.firstFoot` / `.ff` → `cmdr_state.body_flags` (best-effort; Windows `.visited` was MsgCmd-only / rarely wired)
- [x] `.show` (xdg-open codex `image_url` for active organic / named species), `.imgs`, `.kill` → XDG `request-quit` (host watches; does not kill Avalonia blindly), `.tower`, `.new` (aliases `.add` with guidance), `.edit` / `.start` / `.stop` → `cmdr_state.human_site_edit` / `human_site_survey` (persisted)

## Avalonia FormPredictions

- [x] Codex → Predictions… lists journal bio signals + BioCriteria species/variant predictions with codexRef rewards (`BioPredictCli` → `bio_predict.py`)
- Windows-equivalent path: rules-based BioCriteria JSON (not ML). Nebula distance / galactic region ID are best-effort when journal lacks them (nebulae default far; region clauses skipped when unknown)

## Platform N/A (honest — do not fake)

| Windows | Linux | Why |
| --- | --- | --- |
| OpenVR headset inject | N/A | Wayland / no OpenVR headset path; VR Adjust opacity/scale chords still work |
| FormEditMap background image | Thinner | Avalonia Edit Guardian Map edits extra POI angle, distance, heading, and status on `guardianSites`. It does not load the WinForms site background image. |
| BigOverlay / PlotContainer (DirectX) | N/A | Linux uses X11 presenter panels instead |
| WinForms window and Windows font | N/A | Settings are GTK. Other windows are Avalonia. The HUD font is URW Gothic. |
