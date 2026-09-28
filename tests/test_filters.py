from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from spineworks import filters
from spineworks.filters import find_humdrum_tool
from spineworks.humdrum import HumdrumDocument


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


def test_finds_tool_in_software_humdrum_tools_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "software" / "humdrum-tools" / "humextra" / "bin" / "barnum"
    make_executable(executable)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("SPINEWORKS_HUMDRUM_PATH", raising=False)

    assert find_humdrum_tool("barnum") == str(executable)


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


def test_finds_tool_in_standard_usr_local_humlib_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = "/usr/local/humlib/bin/addic"

    def fake_which(name: str, path: str | None = None) -> str | None:
        if name == "addic" and path == "/usr/local/humlib/bin":
            return executable
        return None

    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("SPINEWORKS_HUMDRUM_PATH", raising=False)
    monkeypatch.setattr(filters.shutil, "which", fake_which)

    assert find_humdrum_tool("addic") == executable


def test_reports_missing_tool(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("SPINEWORKS_HUMDRUM_PATH", raising=False)
    monkeypatch.setattr(filters.shutil, "which", lambda *args, **kwargs: None)

    with pytest.raises(filters.HumdrumToolError) as caught:
        find_humdrum_tool("addic")

    assert "Nie znaleziono programu addic" in str(caught.value)
    assert "SPINEWORKS — raport diagnostyczny" in caught.value.diagnostic_report
    assert "Narzędzie: addic" in caught.value.diagnostic_report
    assert "Treść dokumentu .krn nie została dołączona." in (caught.value.diagnostic_report)


def test_addic_does_not_write_diagnostic_files(monkeypatch: pytest.MonkeyPatch) -> None:
    source = "**kern\n*Ivioln\n*-\n"
    output = "**kern\n*ICstr\n*Ivioln\n*-\n"
    monkeypatch.setattr(filters, "find_humdrum_tool", lambda name: "/bin/addic")
    monkeypatch.setattr(
        filters.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=output, stderr=""),
    )

    def reject_write(*args, **kwargs):
        raise AssertionError("run_addic nie powinien zapisywać plików diagnostycznych")

    monkeypatch.setattr(Path, "write_text", reject_write)

    filtered = filters.run_addic(HumdrumDocument.from_text(source))

    assert filtered.instrument_classes() == ["*ICstr"]


def test_addic_error_contains_diagnostic_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "**kern\n*Ivioln\n*-\n"
    monkeypatch.setattr(
        filters,
        "find_humdrum_tool",
        lambda name: "/usr/local/humlib/bin/addic",
    )
    monkeypatch.setattr(
        filters.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=2,
            stdout="",
            stderr="Nieprawidłowe dane testowe",
        ),
    )

    with pytest.raises(filters.HumdrumToolError) as caught:
        filters.run_addic(HumdrumDocument.from_text(source))

    report = caught.value.diagnostic_report
    assert "Narzędzie: addic" in report
    assert "Kod zakończenia: 2" in report
    assert "Nieprawidłowe dane testowe" in report
    assert source not in report


def test_filter_adds_tool_directory_to_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool_directory = tmp_path / "humdrum" / "bin"
    rid = tool_directory / "rid"
    rid_helper = tool_directory / "rid_"
    make_executable(rid)
    make_executable(rid_helper)
    rid.write_text('#!/bin/sh\nexec rid_ "$@"\n', encoding="utf-8")
    rid_helper.write_text("#!/bin/sh\ncat\n", encoding="utf-8")
    monkeypatch.setattr(filters, "find_humdrum_tool", lambda name: str(rid))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    document = HumdrumDocument.from_text("**kern\n!!linebreak:original\n\n4c\n*-\n")

    filtered = filters.remove_system_breaks(document)

    assert "!!linebreak:original" not in filtered.to_text()
