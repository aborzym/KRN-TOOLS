from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from spineworks.humdrum import HumdrumDocument, HumdrumError


def run_addic(document: HumdrumDocument) -> HumdrumDocument:
    executable = shutil.which("addic")
    if executable is None:
        raise HumdrumError("Nie znaleziono programu addic w zmiennej PATH.")
    source_text = document.to_text()
    Path("addic-input.krn").write_text(source_text, encoding="utf-8")
    try:
        result = subprocess.run(
            [executable],
            input=source_text,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise HumdrumError("Filtr addic nie zakończył pracy w ciągu 30 sekund.") from error
    if result.returncode != 0:
        message = result.stderr.strip() or f"Kod zakończenia: {result.returncode}"
        raise HumdrumError(f"Filtr addic zakończył się błędem:\n{message}")
    if not result.stdout.strip():
        raise HumdrumError("Filtr addic nie zwrócił danych.")
    Path("addic-output.krn").write_text(result.stdout, encoding="utf-8")
    filtered = HumdrumDocument.from_text(result.stdout)
    if filtered.header.instrument_class_line is None:
        raise HumdrumError("Filtr addic nie utworzył wiersza *IC…")
    return filtered
