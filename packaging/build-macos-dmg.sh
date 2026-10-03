#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

if [[ "$(uname -m)" != "arm64" ]]; then
    echo "Ten skrypt buduje DMG dla macOS Apple Silicon."
    exit 1
fi

app_version="$(
    .venv-build/bin/python - <<'PY'
import runpy

print(runpy.run_path("src/spineworks/__init__.py")["__version__"])
PY
)"

app_path="$project_root/dist/SPINEWORKS.app"
plist_path="$app_path/Contents/Info.plist"

if [[ ! -d "$app_path" ]]; then
    echo "Najpierw zbuduj SPINEWORKS.app za pomocą PyInstallera."
    exit 1
fi

bundle_version="$(
    /usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$plist_path"
)"

if [[ "$bundle_version" != "$app_version" ]]; then
    echo "Wersja aplikacji ($bundle_version) różni się od źródeł ($app_version)."
    exit 1
fi

dmg_root="$(mktemp -d /tmp/spineworks-dmg-XXXXXX)"
trap 'rm -rf "$dmg_root"' EXIT

ditto "$app_path" "$dmg_root/SPINEWORKS.app"
ln -s /Applications "$dmg_root/Applications"

dmg_path="$project_root/dist/SPINEWORKS-${app_version}-macos-arm64.dmg"

hdiutil create \
    -volname "SPINEWORKS $app_version" \
    -srcfolder "$dmg_root" \
    -format UDZO \
    -ov \
    "$dmg_path"

hdiutil verify "$dmg_path"
shasum -a 256 "$dmg_path"