# SrvSurvey Linux Port Slice

Native journal discovery and session-X11 HUD overlays for Elite Dangerous on
Bazzite / Proton. This is not the full Avalonia AppImage yet.

## What Works

- Find Elite journals inside the Proton prefix via Steam `libraryfolders.vdf`
- XDG data dir at `$XDG_DATA_HOME/srvsurvey` (writes `runtime-state.json`)
- Journal tail watcher + `Status.json` / `Cargo.json` / `ShipLocker.json` /
  `NavRoute.json` polling
- Session-X11 override-redirect click-through HUD panels (gated)
- Stacked top-right panels (enable/disable in settings): location, survey,
  bio (genus / ScanOrganic / sales), signals, guardian, human sites,
  colonisation, route (dest / NavRoute / carrier jump), ship, materials by
  category, ship locker
- Hotkey toggle (default **Pause**) plus main-monitor **HUD ON/OFF** chip and
  `SIGUSR1` fallback; right-click chip opens settings; optional tray
- Remembers last overlay on/off in config (`overlay_visible`)
- Chip click arm-delay so mapping under the cursor does not auto-hide
- GTK3 settings UI (`--settings`)
- AppImage builder: `linux-port/build-appimage.sh`
- Avalonia Main under `linux-port/dotnet/SrvSurveyLinuxUi/` (needs `~/.dotnet` on PATH; status + present/settings)

## Present Gate (Opt-In)

Overlays never open unless you opt in. Any one of these is enough:

```bash
# One-shot CLI flag
linux-port/srvsurvey-linux --allow-present

# Environment (still supported)
export SRVSURVEY_ALLOW_PRESENT=1

# Persistent user config (recommended for daily use)
mkdir -p ~/.config/srvsurvey
echo 'allow_present=true' > ~/.config/srvsurvey/config
```

## Daily Launcher

```bash
cp linux-port/srvsurvey-linux.desktop ~/.local/share/applications/
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true
```

Then start **SrvSurvey Linux** from the app menu, or:

```bash
linux-port/srvsurvey-linux
```

With `allow_present=true` in config, that presents and holds until Ctrl-C.

## Settings

```bash
linux-port/srvsurvey-linux --settings
# or right-click the desktop entry → Settings
```

Persists to `~/.config/srvsurvey/config` (key=value). Keys include:

| Key | Default | Meaning |
| --- | --- | --- |
| `allow_present` | false | Opt in to mapping overlays |
| `hotkey` | `Pause` | Best-effort X11 chord (`F9` / `Super+Shift+S` also fine) |
| `font_size` | 28 | TrueType HUD size |
| `poll_seconds` | 0.75 | Present-loop poll interval |
| `hold_seconds` | 0 | 0 = until Ctrl-C |
| `margin` | 40 | Top-right inset (px) |
| `panel_scale` | 1 | Integer nearest-neighbor scale |
| `stack_gap` | 12 | Gap between stacked panels |
| `max_stack_fraction` | 0.82 | Cap stack height vs game window |
| `panel.<id>` | true | `location` `survey` `bio` `signals` `route` `ship` `materials` `locker` |

## Hotkeys / Toggle

While presenting:

1. **Side-monitor chip (recommended)** — small **HUD ON** / **HUD OFF** button
   just left (or right) of the Elite window. Click it with the mouse while the
   game stays focused. This is the reliable path on GNOME Wayland + Proton.
2. **Pause** (configurable) — X11 `GrabKey` on the session display. Often fails
   to deliver while Elite has focus; kept as a best-effort chord.
3. `kill -USR1 $(pgrep -f 'srvsurvey-linux|host.py')` — always works in-process

Hide unmaps panels; journal / Status polling keeps running. Show remounts
them with the latest bitmaps. The chip stays mapped while the HUD is hidden.

### Wayland limitation (honest)

Elite under Proton is XWayland on `:0`. Passive X11 `GrabKey` commonly reports
success but never receives KeyPress while another XWayland client has focus
(Mutter delivers keys to the focused surface first). Pure Wayland clients also
miss X11 grabs. Use the main-monitor chip or `SIGUSR1` in those cases. The
GlobalShortcuts portal is available on GNOME but needs an interactive bind
with a parent window; it is not required for the daily present path.

`/dev/input` evdev polling was considered but needs membership in group
`input` (not available without sudo on this desktop).

## Longer Hold

`--hold` defaults to **0** (until Ctrl-C), or the config `hold_seconds` value.

```bash
linux-port/srvsurvey-linux --hold 0
linux-port/srvsurvey-linux --present --allow-present --hold 15
```

## Multi-Panel Layout

Panels stack under the top-right inset. Bitmaps render at the configured
TrueType size (default ~28pt). Stack height is capped by
`max_stack_fraction` so the ultrawide playfield stays clear; lower-priority
panels are dropped when the cap would be exceeded.

## Watch Without Overlay

```bash
python3 linux-port/runtime/host.py --watch --hold 30
```

## Tests

```bash
cd linux-port/runtime && python3 test-runtime.py
cd ../overlay-presenter && python3 test-layout.py
```

## Remaining Gaps

- Full BigOverlay plotter parity (bio routes, guardians, human sites, etc.)
- Avalonia Main status UI (GTK settings still cover the full settings surface)
- AppImage packaging and .NET host
- Reliable X11 GrabKey while Elite (XWayland) has focus — use the HUD chip
- Reliable hotkeys while a pure Wayland app has focus (portal bind UX)
- VR / OpenXR
- gamescope `GAMESCOPE_EXTERNAL_OVERLAY` path still needs a live gamescope proof
