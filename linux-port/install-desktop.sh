#!/usr/bin/env bash
# Publish the Avalonia app and install a Show Apps entry. No sudo.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$ROOT/.." && pwd)"
DOTNET_ROOT="${DOTNET_ROOT:-$HOME/.dotnet}"
export DOTNET_ROOT
export PATH="$DOTNET_ROOT:${PATH:-}"
export NUGET_PACKAGES="${NUGET_PACKAGES:-$HOME/.nuget/packages}"
export AvaloniaTelemetryEnabled=false

APP_NAME="srvsurvey"
UI_PROJ="$ROOT/dotnet/SrvSurveyLinuxUi/SrvSurveyLinuxUi.csproj"
OUT="$ROOT/dist/ui"
ICON_TOOL="$ROOT/tools/write-app-icon.py"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
DESKTOP_SRC="$ROOT/srvsurvey-app.desktop"
DESKTOP_DST="$APPS/srvsurvey-linux.desktop"

if [[ ! -x "$DOTNET_ROOT/dotnet" && ! -x "$(command -v dotnet || true)" ]]; then
  echo "dotnet not found under $DOTNET_ROOT" >&2
  exit 1
fi

python3 "$ICON_TOOL" "$ROOT/dotnet/SrvSurveyLinuxUi/Assets/srvsurvey.png" 256
for size in 256 128 64 48; do
  dest="$ICONS/${size}x${size}/apps/${APP_NAME}.png"
  mkdir -p "$(dirname "$dest")"
  python3 "$ICON_TOOL" "$dest" "$size"
done

echo "Publishing Srv Survey…"
"$DOTNET_ROOT/dotnet" publish "$UI_PROJ" -c Release -o "$OUT" -p:AvaloniaTelemetryEnabled=false
chmod +x "$OUT/SrvSurveyLinuxUi"

mkdir -p "$APPS"
python3 - "$DESKTOP_SRC" "$DESKTOP_DST" "$ROOT" "$APP_NAME" << 'PY'
from pathlib import Path
import sys
src, dst, root, icon = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
text = Path(src).read_text(encoding="utf-8")
old = "/home/Matthew/SrvSurvey for Linux Bazzite/linux-port"
text = text.replace(f'Exec="{old}/srvsurvey-app"', f'Exec="{root}/srvsurvey-app"')
text = text.replace(f'Exec="{old}/srvsurvey-linux"', f'Exec="{root}/srvsurvey-linux"')
icon_path = Path.home() / ".local/share/icons/hicolor/256x256/apps" / f"{icon}.png"
text = text.replace(f"Path={old}", f"Path={root}")
text = text.replace(
    "Icon=/home/Matthew/.local/share/icons/hicolor/256x256/apps/srvsurvey.png",
    f"Icon={icon_path}",
)
text = text.replace("Icon=srvsurvey", f"Icon={icon_path}")
Path(dst).write_text(text, encoding="utf-8")
PY
chmod +x "$ROOT/srvsurvey-app"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS" 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || true
fi

echo "Installed Show Apps entry: $DESKTOP_DST"
echo "Launch: \"$ROOT/srvsurvey-app\""
echo "Leave ~/.local/share/applications/srvsurvey.desktop (Wine) unchanged."
