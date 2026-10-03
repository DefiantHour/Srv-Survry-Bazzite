#!/usr/bin/env bash
# Create a minimal Avalonia MVVM app that can edit SrvSurvey Linux settings.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
if ! command -v dotnet >/dev/null 2>&1; then
  echo "dotnet not on PATH. Install with:"
  echo "  curl -fsSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel 9.0"
  echo "  export PATH=\"\$HOME/.dotnet:\$PATH\""
  exit 1
fi
cd "$ROOT"
if [[ ! -d SrvSurveyLinuxUi ]]; then
  dotnet new install Avalonia.Templates >/dev/null
  dotnet new avalonia.mvvm -n SrvSurveyLinuxUi -o SrvSurveyLinuxUi --force
fi
dotnet build SrvSurveyLinuxUi/SrvSurveyLinuxUi.csproj -c Release
echo "Built Avalonia Main UI. Run:"
echo "  dotnet run --project SrvSurveyLinuxUi -c Release"
echo "Shows commander/system/body, present/overlay status, and launches GTK settings."
