from __future__ import annotations

import re
from pathlib import Path

from spineworks.humdrum import HumdrumDocument, HumdrumError

# Kolejność wierszy w szablonie.
# Klucz i tonacja nie są zapisywane.
# Przy nakładaniu szablonu ITr umieszczamy za kluczem i tonacją.
HEADER_ROWS = {
    "part": ("Part", "*part"),
    "staff": ("Staff", "*staff"),
    "name": ("Nazwa pełna", '*I"'),
    "modern_name": ("Nazwa modernowa", '*mI"'),
    "abbreviation": ("Nazwa skrócona", "*I'"),
    "modern_abbreviation": ("Skrót modernowy", "*mI'"),
    "group": ("Grupa instrumentu IG", "*IG"),
    "class": ("Klasa instrumentu IC", "*IC"),
    "code": ("Kod instrumentu", "*I"),
    "transposition": ("Transpozycja", "*ITr"),
}


def header_token_kind(token: str) -> str | None:
    """Rozpoznaj rodzaj interpretacji nagłówka."""
    # Szczegółowe prefiksy sprawdzamy przed ogólnym *I.
    for key in (
        "part",
        "staff",
        "name",
        "modern_name",
        "abbreviation",
        "modern_abbreviation",
        "group",
        "class",
        "transposition",
        "code",
    ):
        if token.startswith(HEADER_ROWS[key][1]):
            return key
    return None


def collect_header_template(
    document: HumdrumDocument,
    *,
    name: str,
    selected_rows: set[str] | None = None,
) -> dict[str, object]:
    """Zbierz istniejące wiersze nagłówka z kolejnych spinów kern."""
    name = name.strip()
    if not name:
        raise HumdrumError("Podaj nazwę szablonu.")

    selected = set(HEADER_ROWS) if selected_rows is None else set(selected_rows)
    if not selected:
        raise HumdrumError("Wybierz co najmniej jeden wiersz nagłówka.")
    if selected - HEADER_ROWS.keys():
        raise HumdrumError("Wybrano nieznany rodzaj wiersza nagłówka.")

    kern_columns = [
        column for column, spine_type in enumerate(document.spine_types) if spine_type == "**kern"
    ]
    if not kern_columns:
        raise HumdrumError("Dokument nie zawiera spinów **kern.")

    found_rows: dict[str, list[str]] = {}

    for line_number in range(
        document.header.exclusive_line + 1,
        len(document.lines),
    ):
        line = document.lines[line_number]

        if not line or line.startswith("!"):
            continue
        if not line.startswith("*") or line.startswith("**"):
            break

        fields = document.fields(line_number)
        if len(fields) != document.spine_count:
            raise HumdrumError(f"Nieprawidłowa liczba pól w linii {line_number + 1}.")
        if any(token in {"*^", "*v", "*x", "*+", "*-"} for token in fields):
            break

        values = [fields[column] for column in kern_columns]
        active = [token for token in values if token != "*"]
        kinds = {header_token_kind(token) for token in active}
        relevant = kinds & selected

        if not relevant:
            continue
        if len(kinds) != 1 or None in kinds:
            raise HumdrumError(
                f"Linia {line_number + 1}: różne rodzaje interpretacji "
                "w jednym wierszu — nie można zapisać go jako szablonu."
            )

        key = next(iter(relevant))
        if key in found_rows:
            raise HumdrumError(
                f"Linia {line_number + 1}: powtórzony wiersz "
                f"„{HEADER_ROWS[key][0]}” — wymaga osobnego rozpatrzenia."
            )

        found_rows[key] = values

    if not found_rows:
        raise HumdrumError("Wybrane wiersze nie występują w nagłówku dokumentu.")

    # Porządkujemy tylko znalezione wiersze, bez tworzenia brakujących.
    row_order = [key for key in HEADER_ROWS if key in found_rows]
    rows = {key: found_rows[key] for key in row_order}

    return {
        "format": "spineworks-header-template",
        "version": 1,
        "name": name,
        "kern_count": len(kern_columns),
        "row_order": row_order,
        "rows": rows,
    }


def validate_header_template(
    template: object,
) -> tuple[int, dict[str, list[str]]]:
    """Sprawdź zawartość JSON przed zastosowaniem szablonu."""
    if not isinstance(template, dict):
        raise HumdrumError("Szablon musi zawierać obiekt JSON.")

    if template.get("format") != "spineworks-header-template":
        raise HumdrumError("To nie jest szablon nagłówka SPINEWORKS.")
    if type(template.get("version")) is not int or template["version"] != 1:
        raise HumdrumError("Nieobsługiwana wersja szablonu.")

    name = template.get("name")
    if not isinstance(name, str) or not name.strip():
        raise HumdrumError("Szablon nie ma poprawnej nazwy.")

    kern_count = template.get("kern_count")
    if type(kern_count) is not int or kern_count < 1:
        raise HumdrumError("Nieprawidłowa liczba kernów w szablonie.")

    raw_rows = template.get("rows")
    if not isinstance(raw_rows, dict) or not raw_rows:
        raise HumdrumError("Szablon nie zawiera wierszy nagłówka.")

    rows: dict[str, list[str]] = {}

    for key, values in raw_rows.items():
        if key not in HEADER_ROWS:
            raise HumdrumError(f"Nieznany rodzaj wiersza w szablonie: {key}.")
        if not isinstance(values, list) or len(values) != kern_count:
            raise HumdrumError(f"Wiersz „{HEADER_ROWS[key][0]}” ma nieprawidłową liczbę pól.")

        for value in values:
            if (
                not isinstance(value, str)
                or not value
                or any(character in value for character in ("\t", "\n", "\r"))
            ):
                raise HumdrumError(f"Nieprawidłowe pole w wierszu „{HEADER_ROWS[key][0]}”.")

            if value == "*":
                continue
            if header_token_kind(value) != key:
                raise HumdrumError(
                    f"Token {value!r} nie pasuje do wiersza „{HEADER_ROWS[key][0]}”."
                )
            if key in {"part", "staff"}:
                number = value.removeprefix(HEADER_ROWS[key][1])
                if not number.isdigit():
                    raise HumdrumError(f"Nieprawidłowe przypisanie: {value!r}.")

        if all(value == "*" for value in values):
            raise HumdrumError(f"Wiersz „{HEADER_ROWS[key][0]}” zawiera wyłącznie puste pola.")

        rows[key] = values.copy()

    order = template.get("row_order")
    if (
        not isinstance(order, list)
        or any(not isinstance(key, str) for key in order)
        or len(order) != len(rows)
        or set(order) != set(rows)
    ):
        raise HumdrumError("Nieprawidłowa lista wierszy szablonu.")

    ordered_rows = {key: rows[key] for key in HEADER_ROWS if key in rows}
    return kern_count, ordered_rows


def _header_row_positions(
    document: HumdrumDocument,
) -> list[tuple[int, str]]:
    """Znajdź jednorodne wiersze nagłówka przed muzyką i manipulatorami."""
    positions: list[tuple[int, str]] = []

    for line_number in range(
        document.header.exclusive_line + 1,
        len(document.lines),
    ):
        line = document.lines[line_number]
        if not line or line.startswith("!"):
            continue
        if not line.startswith("*") or line.startswith("**"):
            break

        fields = document.fields(line_number)
        if len(fields) != document.spine_count:
            raise HumdrumError(f"Nieprawidłowa liczba pól w linii {line_number + 1}.")
        if any(token in {"*^", "*v", "*x", "*+", "*-"} for token in fields):
            break

        kinds: set[str | None] = set()
        for token in fields:
            if token == "*":
                continue
            if token.startswith("*clef"):
                kinds.add("clef")
            elif token.startswith("*k["):
                kinds.add("key_signature")
            else:
                kinds.add(header_token_kind(token))

        if not kinds or kinds == {None}:
            continue
        if None in kinds or len(kinds) != 1:
            raise HumdrumError(
                f"Linia {line_number + 1}: wymieszane rodzaje interpretacji "
                "— nie można bezpiecznie uporządkować wiersza."
            )

        kind = next(iter(kinds))
        if kind is not None:
            positions.append((line_number, kind))

    return positions


def sort_template_header(document: HumdrumDocument) -> HumdrumDocument:
    """Uporządkuj nagłówek, zachowując treść kluczy i oznaczeń tonacji."""
    order = (
        "part",
        "staff",
        "name",
        "modern_name",
        "abbreviation",
        "modern_abbreviation",
        "group",
        "class",
        "code",
        "clef",
        "key_signature",
        "transposition",
    )
    ranks = {key: index for index, key in enumerate(order)}
    positions = _header_row_positions(document)
    ordered = sorted(positions, key=lambda entry: ranks[entry[1]])
    lines = document.lines.copy()

    for (destination, _), (source, _) in zip(positions, ordered, strict=True):
        lines[destination] = document.lines[source]

    return HumdrumDocument(lines, document.trailing_newline)


def apply_header_template(
    document: HumdrumDocument,
    template: object,
    *,
    selected_rows: set[str] | None = None,
) -> HumdrumDocument:
    """Nałóż szablon bez zmiany źródłowego obiektu dokumentu."""
    expected_count, template_rows = validate_header_template(template)
    selected = set(template_rows) if selected_rows is None else set(selected_rows)
    if not selected:
        raise HumdrumError("Wybierz co najmniej jeden wiersz do wczytania.")
    if selected - template_rows.keys():
        raise HumdrumError("Wybrano wiersz, którego nie ma w szablonie.")

    kern_columns = [
        column for column, spine_type in enumerate(document.spine_types) if spine_type == "**kern"
    ]
    if len(kern_columns) != expected_count:
        raise HumdrumError(
            f"Szablon zawiera {expected_count} kernów, "
            f"a bieżący plik {len(kern_columns)}. Nie wprowadzono zmian."
        )

    existing: dict[str, int] = {}
    for line_number, kind in _header_row_positions(document):
        if kind not in selected:
            continue
        if kind in existing:
            raise HumdrumError(
                f"Powtórzony wiersz „{HEADER_ROWS[kind][0]}” "
                "w pliku docelowym — wymaga osobnego rozpatrzenia."
            )
        existing[kind] = line_number

    lines = document.lines.copy()
    additions: list[str] = []

    for key, values in template_rows.items():
        if key not in selected:
            continue

        line_number = existing.get(key)
        fields = (
            document.fields(line_number).copy()
            if line_number is not None
            else ["*"] * document.spine_count
        )

        for column, value in zip(kern_columns, values, strict=True):
            fields[column] = value

        if key in {"part", "staff"}:
            owner_value: str | None = None
            for column, spine_type in enumerate(document.spine_types):
                if spine_type == "**kern":
                    owner_value = fields[column]
                elif owner_value is not None:
                    fields[column] = owner_value

        text = "\t".join(fields)
        if line_number is None:
            additions.append(text)
        else:
            lines[line_number] = text

    insert_at = document.header.exclusive_line + 1
    lines[insert_at:insert_at] = additions

    result = HumdrumDocument(lines, document.trailing_newline)
    return sort_template_header(result)


def suggest_header_template_name(
    document: HumdrumDocument,
    filename: str = "",
) -> str:
    """Zaproponuj nazwę na podstawie metadanych, z nazwą pliku jako fallback."""
    metadata: dict[str, str] = {}

    for line in document.lines[: document.header.exclusive_line]:
        if not line.startswith("!!!"):
            continue
        key, separator, value = line[3:].partition(":")
        if separator and value.strip():
            metadata.setdefault(key, value.strip())

    def normalize(value: str, *, separator: str = " ") -> str:
        value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value)
        value = re.sub(r"\s+", separator, value.strip())
        return value.strip(" .-")

    fallback = normalize(Path(filename).stem)
    composer = normalize(metadata.get("COM", "").split(",", 1)[0])
    title = normalize(metadata.get("OPR") or metadata.get("OTL", ""))

    source = normalize(
        " ".join(
            value
            for value in (
                metadata.get("SMS-siglum", ""),
                metadata.get("SMS-shelfmark", ""),
            )
            if value
        ),
        separator="-",
    )

    if not title:
        return fallback or "naglowek"

    return " - ".join(part for part in (composer, title, source) if part)
