from __future__ import annotations

import pytest

from spineworks.updates import (
    expected_asset_name,
    is_newer_version,
    update_from_release,
    version_tuple,
)

SHA256 = "a" * 64


def make_release(
    *,
    version: str = "2.3.0",
    asset_name: str = "SPINEWORKS-2.3.0-linux-x86_64.deb",
    digest: str | None = f"sha256:{SHA256}",
) -> dict:
    return {
        "tag_name": f"v{version}",
        "name": f"SPINEWORKS {version}",
        "body": "- Nowa funkcja\n- Poprawka",
        "html_url": f"https://github.com/aborzym/KRN-TOOLS/releases/tag/v{version}",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": asset_name,
                "state": "uploaded",
                "browser_download_url": (
                    "https://github.com/aborzym/KRN-TOOLS/releases/download/"
                    f"v{version}/{asset_name}"
                ),
                "size": 52_000_000,
                "digest": digest,
            }
        ],
    }


def test_parses_and_compares_versions() -> None:
    assert version_tuple("v2.3.0") == (2, 3, 0)
    assert is_newer_version("2.3.0", "2.2.0") is True
    assert is_newer_version("2.2.0", "2.2.0") is False
    assert is_newer_version("2.1.9", "2.2.0") is False


def test_rejects_invalid_version() -> None:
    with pytest.raises(ValueError, match="Nieprawidłowy numer wersji"):
        version_tuple("2.3")


def test_selects_linux_update() -> None:
    update = update_from_release(
        make_release(),
        current_version="2.2.0",
        platform_name="linux",
        machine="x86_64",
    )

    assert update is not None
    assert update.version == "2.3.0"
    assert update.asset_name == "SPINEWORKS-2.3.0-linux-x86_64.deb"
    assert update.asset_sha256 == SHA256
    assert update.notes == "- Nowa funkcja\n- Poprawka"


def test_selects_macos_arm_update() -> None:
    asset_name = "SPINEWORKS-2.3.0-macos-arm64.dmg"

    update = update_from_release(
        make_release(asset_name=asset_name),
        current_version="2.2.0",
        platform_name="darwin",
        machine="arm64",
    )

    assert update is not None
    assert update.asset_name == asset_name


def test_ignores_update_without_asset_for_current_platform() -> None:
    update = update_from_release(
        make_release(asset_name="SPINEWORKS-2.3.0-macos-arm64.dmg"),
        current_version="2.2.0",
        platform_name="linux",
        machine="x86_64",
    )

    assert update is None


def test_ignores_current_older_and_skipped_versions() -> None:
    assert (
        update_from_release(
            make_release(version="2.2.0", asset_name="SPINEWORKS-2.2.0-linux-x86_64.deb"),
            current_version="2.2.0",
            platform_name="linux",
            machine="x86_64",
        )
        is None
    )
    assert (
        update_from_release(
            make_release(),
            current_version="2.2.0",
            platform_name="linux",
            machine="x86_64",
            skipped_version="2.3.0",
        )
        is None
    )


def test_requires_sha256_digest() -> None:
    update = update_from_release(
        make_release(digest=None),
        current_version="2.2.0",
        platform_name="linux",
        machine="x86_64",
    )

    assert update is None


def test_returns_expected_asset_names() -> None:
    assert (
        expected_asset_name(
            "2.3.0",
            platform_name="linux",
            machine="amd64",
        )
        == "SPINEWORKS-2.3.0-linux-x86_64.deb"
    )
    assert (
        expected_asset_name(
            "2.3.0",
            platform_name="darwin",
            machine="aarch64",
        )
        == "SPINEWORKS-2.3.0-macos-arm64.dmg"
    )
    assert (
        expected_asset_name(
            "2.3.0",
            platform_name="win32",
            machine="AMD64",
        )
        is None
    )
