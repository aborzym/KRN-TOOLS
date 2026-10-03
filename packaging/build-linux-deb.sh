#!/usr/bin/env bash
set -euo pipefail
umask 022

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

if [[ "$(dpkg --print-architecture)" != "amd64" ]]; then
    echo "Ten skrypt buduje paczkę dla Linuksa amd64."
    exit 1
fi

app_version="$(
    .venv-build/bin/python - <<'PY'
import runpy

print(runpy.run_path("src/spineworks/__init__.py")["__version__"])
PY
)"

if [[ ! -x dist/SPINEWORKS/SPINEWORKS ]]; then
    echo "Najpierw zbuduj aplikację za pomocą PyInstallera."
    exit 1
fi

package_root="$(mktemp -d /tmp/spineworks-deb-XXXXXX)"
trap 'rm -rf "$package_root"' EXIT
chmod 755 "$package_root"

mkdir -p \
    "$package_root/DEBIAN" \
    "$package_root/opt" \
    "$package_root/usr/bin" \
    "$package_root/usr/share/applications" \
    "$package_root/usr/share/icons/hicolor/1024x1024/apps"

cp -a dist/SPINEWORKS "$package_root/opt/spineworks"

cat > "$package_root/DEBIAN/control" <<EOF
Package: spineworks
Version: $app_version
Section: sound
Priority: optional
Architecture: amd64
Maintainer: Andrzej Borzym <borzym.a@gmail.com>
Description: SPINEWORKS - graficzny edytor plików Humdrum
 SPINEWORKS umożliwia korektę nagłówków oraz kontrolę i naprawę
 rozdwojeń spine’ów w plikach Humdrum.
EOF

cat > "$package_root/usr/bin/spineworks" <<'EOF'
#!/bin/sh
exec /opt/spineworks/SPINEWORKS "$@"
EOF
chmod 755 "$package_root/usr/bin/spineworks"

cat > "$package_root/usr/share/applications/spineworks.desktop" <<'EOF'
[Desktop Entry]
Name=SPINEWORKS
Comment=Graficzny edytor plików Humdrum
Exec=spineworks %F
Icon=spineworks
Terminal=false
Type=Application
Categories=AudioVideo;Audio;
MimeType=application/x-humdrum;
EOF

install -m 644 \
    src/spineworks/assets/spineworks.png \
    "$package_root/usr/share/icons/hicolor/1024x1024/apps/spineworks.png"

package_path="$project_root/dist/SPINEWORKS-${app_version}-linux-x86_64.deb"

dpkg-deb --root-owner-group --build "$package_root" "$package_path"
dpkg-deb --info "$package_path"
sha256sum "$package_path"