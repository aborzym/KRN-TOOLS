from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    notes: str
    release_url: str
    asset_name: str
    asset_url: str
    asset_size: int
    asset_sha256: str


def version_tuple(version: str) -> tuple[int, int, int]:
    normalized = version.strip().removeprefix("v")
    parts = normalized.split(".")

    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(f"Nieprawidłowy numer wersji: {version}")

    return tuple(int(part) for part in parts)


def is_newer_version(candidate: str, current: str) -> bool:
    return version_tuple(candidate) > version_tuple(current)


def expected_asset_name(
    version: str,
    *,
    platform_name: str,
    machine: str,
) -> str | None:
    normalized_machine = machine.lower()

    if platform_name.startswith("linux") and normalized_machine in {
        "x86_64",
        "amd64",
    }:
        return f"SPINEWORKS-{version}-linux-x86_64.deb"

    if platform_name == "darwin" and normalized_machine in {
        "arm64",
        "aarch64",
    }:
        return f"SPINEWORKS-{version}-macos-arm64.dmg"

    return None


def release_history_notes(
    releases: list[dict[str, Any]],
    *,
    current_version: str,
    latest_version: str,
) -> str:
    """Połącz opisy stabilnych wydań pomiędzy obecną a docelową wersją."""
    current = version_tuple(current_version)
    latest = version_tuple(latest_version)
    selected: dict[tuple[int, int, int], str] = {}

    for release in releases:
        if not isinstance(release, dict):
            continue
        if release.get("draft") or release.get("prerelease"):
            continue

        tag = release.get("tag_name")
        if not isinstance(tag, str):
            continue

        try:
            version = version_tuple(tag)
        except ValueError:
            continue

        if not current < version <= latest:
            continue

        body = release.get("body")
        notes = body.strip() if isinstance(body, str) else ""
        selected[version] = notes or "Autor nie dołączył opisu zmian do tego wydania."

    sections = [
        f"# SPINEWORKS {'.'.join(map(str, version))}\n\n{notes}"
        for version, notes in sorted(selected.items())
    ]
    return "\n\n---\n\n".join(sections)


def update_from_release(
    release: dict[str, Any],
    *,
    current_version: str,
    platform_name: str,
    machine: str,
    skipped_version: str = "",
) -> UpdateInfo | None:
    if release.get("draft") or release.get("prerelease"):
        return None

    tag_name = release.get("tag_name")
    if not isinstance(tag_name, str):
        return None

    version = tag_name.removeprefix("v")
    try:
        if not is_newer_version(version, current_version):
            return None
    except ValueError:
        return None

    if version == skipped_version:
        return None

    asset_name = expected_asset_name(
        version,
        platform_name=platform_name,
        machine=machine,
    )
    if asset_name is None:
        return None

    assets = release.get("assets")
    if not isinstance(assets, list):
        return None

    matching_asset = next(
        (
            asset
            for asset in assets
            if isinstance(asset, dict)
            and asset.get("name") == asset_name
            and asset.get("state") == "uploaded"
        ),
        None,
    )
    if matching_asset is None:
        return None

    asset_url = matching_asset.get("browser_download_url")
    digest = matching_asset.get("digest")
    size = matching_asset.get("size")

    if not isinstance(asset_url, str) or not asset_url.startswith("https://"):
        return None
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        return None
    if not isinstance(size, int) or size <= 0:
        return None

    sha256 = digest.removeprefix("sha256:")
    if len(sha256) != 64 or any(character not in "0123456789abcdefABCDEF" for character in sha256):
        return None

    notes = release.get("body")
    release_url = release.get("html_url")

    return UpdateInfo(
        version=version,
        notes=notes if isinstance(notes, str) else "",
        release_url=release_url if isinstance(release_url, str) else "",
        asset_name=asset_name,
        asset_url=asset_url,
        asset_size=size,
        asset_sha256=sha256.lower(),
    )
