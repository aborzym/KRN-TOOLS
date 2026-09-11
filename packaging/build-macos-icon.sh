#!/bin/sh
set -eu

project_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
source_icon="$project_root/src/spineworks/assets/spineworks.png"
iconset="$project_root/build/spineworks.iconset"
output_icon="$project_root/packaging/spineworks.icns"

mkdir -p "$iconset"
for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$source_icon" \
        --out "$iconset/icon_${size}x${size}.png" >/dev/null
    double_size=$((size * 2))
    sips -z "$double_size" "$double_size" "$source_icon" \
        --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done

iconutil -c icns "$iconset" -o "$output_icon"
printf 'Utworzono %s\n' "$output_icon"
