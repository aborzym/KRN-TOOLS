from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from spineworks.humdrum import HumdrumDocument, HumdrumError


def find_humdrum_tool(name: str) -> str:
    """Find a Humdrum executable in PATH or in common installation directories."""
    executable = shutil.which(name)
    if executable is not None:
        return executable

    home = Path.home()
    configured_paths = os.environ.get("SPINEWORKS_HUMDRUM_PATH", "").split(os.pathsep)
    search_directories = [
        *(Path(path).expanduser() for path in configured_paths if path),
        home / "humdrum-tools" / "humlib" / "bin",
        home / "humdrum-tools" / "humextra" / "bin",
        home / "humdrum-tools" / "humdrum" / "bin",
        home / "software" / "humdrum-tools" / "humlib" / "bin",
        home / "software" / "humdrum-tools" / "humextra" / "bin",
        home / "software" / "humdrum-tools" / "humdrum" / "bin",
        home / "humlib" / "bin",
        home / "humextra" / "bin",
        home / ".local" / "bin",
        Path("/opt/homebrew/bin"),
        Path("/opt/local/bin"),
        Path("/usr/local/bin"),
    ]
    for directory in search_directories:
        executable = shutil.which(name, path=str(directory))
        if executable is not None:
            return executable

    raise HumdrumError(
        f"Nie znaleziono programu {name}. Zainstaluj narzędzia Humdrum albo dodaj "
        "katalog z programami do PATH lub SPINEWORKS_HUMDRUM_PATH."
    )


def _tool_environment(executable: str) -> dict[str, str]:
    environment = os.environ.copy()
    tool_directory = str(Path(executable).resolve().parent)
    current_path = environment.get("PATH", "")
    environment["PATH"] = os.pathsep.join(
        part for part in (tool_directory, current_path) if part
    )
    return environment


def run_addic(document: HumdrumDocument) -> HumdrumDocument:
    executable = find_humdrum_tool("addic")
    source_text = document.to_text()
    try:
        result = subprocess.run(
            [executable, "-f"],
            input=source_text,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
            env=_tool_environment(executable),
        )
    except subprocess.TimeoutExpired as error:
        raise HumdrumError("Filtr addic nie zakończył pracy w ciągu 30 sekund.") from error
    if result.returncode != 0:
        message = result.stderr.strip() or f"Kod zakończenia: {result.returncode}"
        raise HumdrumError(f"Filtr addic zakończył się błędem:\n{message}")
    if not result.stdout.strip():
        raise HumdrumError("Filtr addic nie zwrócił danych.")
    filtered = HumdrumDocument.from_text(result.stdout)
    if filtered.header.instrument_class_line is None:
        raise HumdrumError("Filtr addic nie utworzył wiersza *IC…")
    return filtered


def run_barnum(document: HumdrumDocument) -> HumdrumDocument:
    executable = find_humdrum_tool("barnum")
    output = document.to_text()
    for mode in ("-r", "-a"):
        try:
            result = subprocess.run(
                [executable, mode],
                input=output,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
                env=_tool_environment(executable),
            )
        except subprocess.TimeoutExpired as error:
            raise HumdrumError(
                f"Filtr barnum {mode} nie zakończył pracy w ciągu 30 sekund."
            ) from error
        if result.returncode != 0:
            message = result.stderr.strip() or f"Kod zakończenia: {result.returncode}"
            raise HumdrumError(f"Filtr barnum {mode} zakończył się błędem:\n{message}")
        if not result.stdout.strip():
            raise HumdrumError(f"Filtr barnum {mode} nie zwrócił danych.")
        output = result.stdout
    return HumdrumDocument.from_text(output)


def remove_system_breaks(document: HumdrumDocument) -> HumdrumDocument:
    rid = find_humdrum_tool("rid")

    break_records = {"!!pagebreak:original", "!!linebreak:original"}
    source_lines = [
        line for line in document.to_text().splitlines() if line.strip() not in break_records
    ]
    source = "\n".join(source_lines)
    if document.trailing_newline:
        source += "\n"
    output = _run_filter([rid, "-glid"], source, "rid")
    return HumdrumDocument.from_text(output)


def insert_spine(
    document: HumdrumDocument,
    *,
    reference_column: int,
    after: bool,
    spine_type: str,
    hidden_rests: bool = False,
) -> HumdrumDocument:
    extract = find_humdrum_tool("extractx")
    if not 0 <= reference_column < document.spine_count:
        raise HumdrumError("Wybrany spine nie istnieje.")

    insertion_column = reference_column + (1 if after else 0)
    selection = list(range(1, document.spine_count + 1))
    selection.insert(insertion_column, 0)
    selector = ",".join(str(value) for value in selection)

    output = _run_filter(
        [extract, "-s", selector],
        document.to_text(),
        "extractx",
    )
    if spine_type == "**kern":
        restfill = find_humdrum_tool("restfill")
        arguments = [restfill, "-yi" if hidden_rests else "-i", "blank"]
        output = _run_filter(arguments, output, "restfill")
        filtered = HumdrumDocument.from_text(output)
    else:
        filtered = HumdrumDocument.from_text(output)
        types = filtered.spine_types
        if insertion_column >= len(types) or types[insertion_column] != "**blank":
            raise HumdrumError("Program extractx nie utworzył oczekiwanego spine’u **blank.")
        types[insertion_column] = spine_type
        filtered.replace_fields(filtered.header.exclusive_line, types)

    if filtered.spine_count != document.spine_count + 1:
        raise HumdrumError("Po dodaniu spine’u liczba spine’ów jest nieprawidłowa.")
    if filtered.spine_types[insertion_column] != spine_type:
        raise HumdrumError(f"Nowy spine nie ma oczekiwanego typu {spine_type}.")
    return filtered


def remove_spine(document: HumdrumDocument, *, column: int) -> HumdrumDocument:
    extract = find_humdrum_tool("extractx")
    if document.spine_count <= 1:
        raise HumdrumError("Nie można usunąć ostatniego spine’u.")
    if not 0 <= column < document.spine_count:
        raise HumdrumError("Wybrany spine nie istnieje.")

    selection = [
        str(index)
        for index in range(1, document.spine_count + 1)
        if index != column + 1
    ]
    output = _run_filter(
        [extract, "-s", ",".join(selection)],
        document.to_text(),
        "extractx",
    )
    filtered = HumdrumDocument.from_text(output)
    if filtered.spine_count != document.spine_count - 1:
        raise HumdrumError("Po usunięciu spine’u liczba spine’ów jest nieprawidłowa.")
    return filtered


def _run_filter(arguments: list[str], source: str, name: str) -> str:
    try:
        result = subprocess.run(
            arguments,
            input=source,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
            env=_tool_environment(arguments[0]),
        )
    except subprocess.TimeoutExpired as error:
        raise HumdrumError(f"Filtr {name} nie zakończył pracy w ciągu 30 sekund.") from error
    if result.returncode != 0:
        message = result.stderr.strip() or f"Kod zakończenia: {result.returncode}"
        raise HumdrumError(f"Filtr {name} zakończył się błędem:\n{message}")
    if not result.stdout.strip():
        raise HumdrumError(f"Filtr {name} nie zwrócił danych.")
    return result.stdout
