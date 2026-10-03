#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "${SHELL##*/}" in
    zsh) config_path="$HOME/.zshrc" ;;
    bash) config_path="$HOME/.bashrc" ;;
    *)
        echo "Obsługiwane powłoki: Bash i Zsh."
        exit 1
        ;;
esac

python3 - "$config_path" "$project_root" <<'PY'
import shlex
import sys
from pathlib import Path

config = Path(sys.argv[1])
root = Path(sys.argv[2])
text = config.read_text(encoding="utf-8") if config.exists() else ""

lines = [
    line
    for line in text.splitlines()
    if not line.lstrip().startswith(
        ("alias spine-release=", "alias spine-publish=")
    )
]

for alias, script in (
    ("spine-release", "build-release.sh"),
    ("spine-publish", "publish-release.sh"),
):
    command = "bash " + shlex.quote(str(root / "packaging" / script))
    lines.append(f"alias {alias}={shlex.quote(command)}")

config.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Aliasy zapisane w {config}.")
print(f"Aby je włączyć, wykonaj: source {shlex.quote(str(config))}")
PY
