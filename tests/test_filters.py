from __future__ import annotations

import os
from pathlib import Path

import pytest

from spineworks.filters import find_humdrum_tool
from spineworks.humdrum import HumdrumError


def make_executable(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)


def test_finds_tool_in_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executable = tmp_path / "bin" / "rid"
    make_executable(executable)
    monkeypatch.setenv("PATH", str(executable.parent))

    assert find_humdrum_tool("rid") == str(executable)


def test_finds_tool_in_humdrum_tools_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "humdrum-tools" / "humlib" / "bin" / "extractx"
    make_executable(executable)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("SPINEWORKS_HUMDRUM_PATH", raising=False)

    assert find_humdrum_tool("extractx") == str(executable)


def test_finds_tool_in_configured_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "missing"
    second = tmp_path / "custom"
    executable = second / "barnum"
    make_executable(executable)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("SPINEWORKS_HUMDRUM_PATH", os.pathsep.join((str(first), str(second))))

    assert find_humdrum_tool("barnum") == str(executable)


def test_reports_missing_tool(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("SPINEWORKS_HUMDRUM_PATH", raising=False)

    with pytest.raises(HumdrumError, match="Nie znaleziono programu addic"):
        find_humdrum_tool("addic")
