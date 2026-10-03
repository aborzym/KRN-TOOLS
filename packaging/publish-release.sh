#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

repository="aborzym/KRN-TOOLS"
build_python="$project_root/.venv-build/bin/python"

if [[ "$(git branch --show-current)" != "main" ]]; then
    echo "Publikuj z gałęzi main, po połączeniu zmian."
    exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
    echo "Najpierw zapisz wszystkie zmiany w commicie."
    exit 1
fi

gh auth status >/dev/null 2>&1

app_version="$(
    "$build_python" - <<'PY'
import runpy

print(runpy.run_path("src/spineworks/__init__.py")["__version__"])
PY
)"
tag="v$app_version"
notes="packaging/release-notes-${app_version}.md"

case "$(uname -s)" in
    Darwin) platform_name="macos-arm64"; extension="dmg" ;;
    Linux) platform_name="linux-x86_64"; extension="deb" ;;
    *) echo "Nieobsługiwany system."; exit 1 ;;
esac

asset="dist/SPINEWORKS-${app_version}-${platform_name}.${extension}"
manifest="${asset}.build.json"

if [[ ! -f "$asset" || ! -f "$manifest" || ! -f "$notes" ]]; then
    echo "Brak pakietu, informacji o buildzie lub opisu zmian."
    echo "Najpierw uruchom spine-release."
    exit 1
fi

"$build_python" - "$asset" "$manifest" <<'PY'
import hashlib
import json
import subprocess
import sys
from pathlib import Path

asset = Path(sys.argv[1])
manifest = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
commit = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], text=True
).strip()
digest = hashlib.sha256(asset.read_bytes()).hexdigest()

if manifest["commit"] != commit or manifest["sha256"] != digest:
    raise SystemExit("Pakiet nie odpowiada bieżącemu commitowi. Uruchom spine-release.")
PY

git fetch --no-tags origin main

remote_tag="$(git ls-remote --tags origin "refs/tags/$tag")"
if [[ -n "$remote_tag" ]]; then
    git fetch --no-tags origin "refs/tags/$tag:refs/tags/$tag"
fi
head_commit="$(git rev-parse HEAD)"
remote_commit="$(git rev-parse origin/main)"

if [[ "$head_commit" != "$remote_commit" ]]; then
    if ! git merge-base --is-ancestor origin/main HEAD; then
        echo "Main na GitHub zawiera inne zmiany. Najpierw zaktualizuj repozytorium."
        exit 1
    fi
    git push origin main
fi

if git show-ref --verify --quiet "refs/tags/$tag"; then
    if [[ "$(git rev-parse "$tag^{commit}")" != "$head_commit" ]]; then
        echo "Tag $tag wskazuje inny commit. Nie zostanie zmieniony."
        exit 1
    fi
else
    git tag "$tag"
fi
git push origin "$tag"

if gh release view "$tag" --repo "$repository" >/dev/null 2>&1; then
    gh release upload "$tag" "$asset" --repo "$repository"
else
    gh release create "$tag" "$asset" \
        --repo "$repository" \
        --verify-tag \
        --title "SPINEWORKS $app_version" \
        --notes-file "$notes" \
        --latest
fi

gh release view "$tag" --repo "$repository" --json url,assets


"$build_python" - "$repository" "$tag" "$asset" "$manifest" <<'PY'
import hashlib
import json
import subprocess
import sys
from pathlib import Path

repository, tag, asset_path, manifest_path = sys.argv[1:]
asset = Path(asset_path)
manifest = Path(manifest_path)

release = json.loads(
    subprocess.check_output(
        ["gh", "api", f"repos/{repository}/releases/tags/{tag}"],
        text=True,
    )
)

if release.get("draft"):
    raise SystemExit("Wydanie jest szkicem — lokalny pakiet zostaje.")

remote = next(
    (
        item
        for item in release.get("assets", [])
        if item.get("name") == asset.name
    ),
    None,
)
digest = "sha256:" + hashlib.sha256(asset.read_bytes()).hexdigest()

if (
    remote is None
    or remote.get("state") != "uploaded"
    or remote.get("size") != asset.stat().st_size
    or remote.get("digest") != digest
):
    raise SystemExit(
        "Nie potwierdzono zgodności pakietu na GitHub — lokalne pliki zostają."
    )

asset.unlink()
manifest.unlink()
print(f"Publikacja zweryfikowana. Usunięto lokalny instalator: {asset.name}")
PY