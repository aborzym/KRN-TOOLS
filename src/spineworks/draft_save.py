import os
import stat
import tempfile
from pathlib import Path

from spineworks.humdrum import HumdrumDocument, HumdrumError
from spineworks.spine_validation import (
    FragmentDraft,
    ValidationState,
    trace_spines,
    validate_draft,
)


def compose_drafts(
    document: HumdrumDocument,
    drafts: tuple[FragmentDraft, ...],
) -> str:
    """Połącz zmiany szkiców bez zapisywania i zatwierdzania propozycji."""
    original_text = document.to_text()
    replacements: dict[int, tuple[str, ...]] = {}

    for draft in drafts:
        if draft.original_text != original_text:
            raise ValueError(
                "Szkic pochodzi z innej wersji pliku. Nie można bezpiecznie połączyć zmian."
            )

        for source_line, replacement in draft.source_replacements():
            if not 1 <= source_line <= len(document.lines):
                raise ValueError(f"Linia {source_line}: zmiana wykracza poza plik źródłowy.")

            texts = tuple(line.text for line in replacement)
            previous = replacements.get(source_line)

            if previous is not None and previous != texts:
                raise ValueError(
                    f"Linia {source_line}: różne szkice zawierają "
                    "sprzeczne zmiany tego samego wiersza."
                )

            replacements[source_line] = texts

    result: list[str] = []
    for source_line, text in enumerate(document.lines, start=1):
        replacement = replacements.get(source_line)
        if replacement is None:
            result.append(text)
        else:
            result.extend(replacement)

    composed = HumdrumDocument(result, document.trailing_newline)
    trace = trace_spines(composed)
    if trace.issue is not None:
        raise HumdrumError(
            f"Po połączeniu zmian — linia wynikowa {trace.issue.line_number}: {trace.issue.message}"
        )

    return composed.to_text()


def prepare_save_text(
    document: HumdrumDocument,
    ranges: tuple[tuple[FragmentDraft, int, int], ...],
) -> str:
    """Sprawdź zmienione zakresy i przygotuj tekst do zapisu."""
    selected: list[FragmentDraft] = []

    for draft, start_line, end_line in ranges:
        if not draft.dirty:
            continue

        result = validate_draft(
            draft,
            start_line=start_line,
            end_line=end_line,
        )
        if result.state is ValidationState.ERROR:
            raise ValueError(
                f"Nie można zapisać zmian w zakresie "
                f"linii {start_line}–{end_line}:\n" + "\n".join(result.messages)
            )

        selected.append(draft)

    return compose_drafts(document, tuple(selected))


def write_verified_text(
    path: Path,
    *,
    expected_text: str,
    new_text: str,
) -> None:
    """Zapisz cały wynik, jeśli plik nadal odpowiada wersji źródłowej."""
    destination = path.expanduser().resolve(strict=True)

    def check_source() -> None:
        current = destination.read_text(encoding="utf-8")
        if current != expected_text:
            raise ValueError(
                "Plik na dysku zmienił się od jego otwarcia. "
                "Zapis został przerwany, aby nie nadpisać cudzych zmian."
            )

    check_source()
    permissions = stat.S_IMODE(destination.stat().st_mode)
    temporary: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(new_text)
            stream.flush()
            os.fsync(stream.fileno())

        os.chmod(temporary, permissions)
        check_source()
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
