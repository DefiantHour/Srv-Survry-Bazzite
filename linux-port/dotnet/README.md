# Avalonia / .NET Linux Path

The live overlay stays in the Python `linux-port/` HUD. Avalonia provides a
Main-window companion that mirrors Windows `Main` status lines and can open
the existing GTK settings UI.

## Prerequisites

```bash
curl -fsSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh
bash /tmp/dotnet-install.sh --channel 9.0
export DOTNET_ROOT="$HOME/.dotnet"
export PATH="$HOME/.dotnet:$PATH"
dotnet --version
```

## Build / Run

```bash
cd linux-port/dotnet
./bootstrap-avalonia.sh
# or:
dotnet build SrvSurveyLinuxUi/SrvSurveyLinuxUi.csproj -c Release
dotnet run --project SrvSurveyLinuxUi -c Release
```

Optional: `SRVSURVEY_LINUX_ROOT=/path/to/linux-port` if the binary is moved
away from the repo (Settings looks for `srvsurvey-linux`).

## What the Main Window Does

- Commander / system / body / vehicle / mode (journal + `Status.json`)
- Exploration jump/scan/DSS counters from the current journal
- Bio signal counts (system/body) and organic sale totals from the journal
- Present gate + overlay status from `~/.config/srvsurvey/config`
- **Temporarily Hide Overlays** writes `overlay_visible` and, when the Python
  presenter is running, sends `SIGUSR1` (host PID in `runtime-state.json`)
- **Settings** launches GTK `srvsurvey-linux --settings`
- Does **not** replace the overlay presenter or plotters

## Relation to the Windows SrvSurvey Tree

Upstream `SrvSurvey` is `net9.0-windows` + WinForms. Do **not** retarget that
csproj to linux-x64 without replacing WinForms/SharpDX. The intended merge is:

1. Keep Python (or later native) presenter for overlays.
2. Grow Avalonia for Main / settings / forms.
3. Port survey domain logic into a `net9.0` class library shared by Avalonia
   and (eventually) a non-WinForms headless service.

## AppImage

Python HUD packaging: `linux-port/build-appimage.sh`
