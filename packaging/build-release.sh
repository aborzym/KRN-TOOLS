#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

test_python="$project_root/.venv/bin/python"
build_python="$project_root/.venv-build/bin/python"

for interpreter in "$test_python" "$build_python"; do
    if [[ ! -x "$interpreter" ]]; then
        echo "Brak środowiska: $interpreter"
        exit 1
    fi
done

case "$(uname -s)" in
    Darwin)
        if [[ "$(uname -m)" != "arm64" ]]; then
            echo "Obsługiwany macOS: Apple Silicon arm64."
            exit 1
        fi
        package_script="packaging/build-macos-dmg.sh"
        platform_name="macos-arm64"
        ;;
    Linux)
        if ! command -v dpkg-deb >/dev/null 2>&1; then
            echo "Brak dpkg-deb — potrzebny do przygotowania DEB."
            exit 1
        fi
        if [[ "$(dpkg --print-architecture)" != "amd64" ]]; then
            echo "Obsługiwany Linux: amd64."
            exit 1
        fi
        package_script="packaging/build-linux-deb.sh"
        platform_name="linux-x86_64"
        ;;
    *)
        echo "Ten system nie jest jeszcze obsługiwany."
        exit 1
        ;;
esac

"$build_python" -c "import PyInstaller, PySide6"

app_version="$(
    "$build_python" - <<'PY'
import runpy

print(runpy.run_path("src/spineworks/__init__.py")["__version__"])
PY
)"

mkdir -p dist
log_path="$project_root/dist/build-${app_version}-${platform_name}.log"

if [[ -n "$(git status --porcelain)" ]]; then
    echo "Najpierw zapisz wszystkie zmiany w commicie."
    exit 1
fi

build_commit="$(git rev-parse HEAD)"

{
    echo "Przygotowanie SPINEWORKS $app_version — $platform_name"

    git diff --check
    "$test_python" -m pytest -q

    "$build_python" -m pip install --no-deps --no-build-isolation -e .

    if [[ "$platform_name" == "macos-arm64" ]]; then
        bash packaging/build-macos-icon.sh
    fi

    "$build_python" -m PyInstaller --noconfirm --clean SPINEWORKS.spec
    bash "$package_script"

    "$build_python" - "$app_version" "$platform_name" "$build_commit" <<'PY'
import hashlib
import json
import subprocess
import sys
from pathlib import Path

version, platform_name, build_commit = sys.argv[1:]
extension = "dmg" if platform_name == "macos-arm64" else "deb"
asset = Path(f"dist/SPINEWORKS-{version}-{platform_name}.{extension}")

current_commit = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], text=True
).strip()
changes = subprocess.check_output(
    ["git", "status", "--porcelain"], text=True
).strip()

if current_commit != build_commit or changes:
    raise SystemExit("Źródła zmieniły się podczas budowania. Powtórz build.")

manifest = {
    "commit": build_commit,
    "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
}
Path(str(asset) + ".build.json").write_text(
    json.dumps(manifest, indent=2) + "\n",
    encoding="utf-8",
)
PY

    echo
    echo "Gotowe. Pakiet znajduje się w: $project_root/dist"
} 2>&1 | tee "$log_path"
