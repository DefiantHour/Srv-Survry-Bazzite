#!/usr/bin/env bash
# Build a portable AppImage for the Python linux-port HUD.
# Downloads appimagetool into linux-port/tools/ if missing (no sudo).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$ROOT/.." && pwd)"
TOOLS="$ROOT/tools"
APPDIR="$ROOT/build/SrvSurveyLinux.AppDir"
OUT="$ROOT/build/SrvSurvey-Linux-x86_64.AppImage"
ARCH="${ARCH:-x86_64}"

mkdir -p "$TOOLS" "$ROOT/build"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/share/srvsurvey"

if command -v rsync >/dev/null 2>&1; then
  rsync -a \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude 'build' \
    --exclude 'tools' \
    --exclude 'dotnet' \
    "$ROOT/" "$APPDIR/usr/share/srvsurvey/"
else
  cp -a "$ROOT/runtime" "$APPDIR/usr/share/srvsurvey/"
  cp -a "$ROOT/overlay-presenter" "$APPDIR/usr/share/srvsurvey/"
  cp "$ROOT/srvsurvey-linux" "$APPDIR/usr/share/srvsurvey/"
  cp "$ROOT/srvsurvey-linux.desktop" "$APPDIR/usr/share/srvsurvey/"
fi

cat > "$APPDIR/AppRun" << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$HERE/usr/share/srvsurvey/runtime:$HERE/usr/share/srvsurvey/overlay-presenter${PYTHONPATH:+:$PYTHONPATH}"
export SRVSURVEY_APPDIR="$HERE"
exec python3 "$HERE/usr/share/srvsurvey/srvsurvey-linux" "$@"
EOF
chmod +x "$APPDIR/AppRun"

cp "$ROOT/srvsurvey-linux.desktop" "$APPDIR/srvsurvey-linux.desktop"
sed -i 's|^Exec=.*|Exec=srvsurvey-linux|' "$APPDIR/srvsurvey-linux.desktop"
if grep -q '^Icon=' "$APPDIR/srvsurvey-linux.desktop"; then
  sed -i 's|^Icon=.*|Icon=srvsurvey-linux|' "$APPDIR/srvsurvey-linux.desktop"
else
  echo 'Icon=srvsurvey-linux' >> "$APPDIR/srvsurvey-linux.desktop"
fi

ICON_OUT="$APPDIR/srvsurvey-linux.png"
ICON_SRC=""
for candidate in \
  "$REPO/SrvSurvey/Resources/Logo.png" \
  "$ROOT/icon.png"
do
  if [[ -f "$candidate" ]]; then
    ICON_SRC="$candidate"
    break
  fi
done
if [[ -n "$ICON_SRC" ]]; then
  cp "$ICON_SRC" "$ICON_OUT"
else
  python3 - "$ICON_OUT" << 'PY'
import sys
from pathlib import Path
out = Path(sys.argv[1])
try:
    from PIL import Image, ImageDraw
except ImportError:
    out.write_bytes(b"")
    raise SystemExit(0)
img = Image.new("RGBA", (256, 256), (20, 24, 28, 255))
d = ImageDraw.Draw(img)
d.ellipse((40, 40, 216, 216), fill=(255, 140, 0, 255))
img.save(out)
PY
fi

APPIMAGETOOL="$TOOLS/appimagetool-$ARCH.AppImage"
if [[ ! -x "$APPIMAGETOOL" ]]; then
  echo "Downloading appimagetool..."
  url="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
  curl -fsSL -o "$APPIMAGETOOL" "$url"
  chmod +x "$APPIMAGETOOL"
fi

echo "Building AppImage → $OUT"
ARCH="$ARCH" "$APPIMAGETOOL" "$APPDIR" "$OUT"
echo "Done: $OUT"
echo "Run: \"$OUT\" --present"
echo "Note: needs host python3 + python-xlib + Pillow (+ GTK3 for --settings)."
