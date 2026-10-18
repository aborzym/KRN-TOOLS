import re

from spineworks.humdrum import HumdrumDocument, HumdrumError
from spineworks.kern_rhythm import kern_duration
from spineworks.meter_rhythm import MeterSignature, parse_meter
from spineworks.spine_rhythm import TimedRecord, meter_at_line, trace_rhythm
from spineworks.spine_validation import RecordKind, TracedRecord, trace_spines

REST_LAYOUTS = {
    (3, 4): {"1.r": (2, "0"), "0.r": (4, "00")},
    (2, 4): {"1r": (2, "0"), "0r": (4, "00")},
    (3, 8): {"2.r": (2, "0"), "1.r": (4, "00")},
    (6, 8): {"1.r": (2, "0"), "0.r": (4, "00")},
    (12, 8): {"0.r": (2, "0"), "00.r": (4, "00")},
    (3, 2): {"0.r": (2, "0"), "00.r": (4, "00")},
    (2, 1): {"00r": (2, "0"), "0000r": (4, "00")},
    (3, 1): {"00.r": (2, "0"), "0000.r": (4, "00")},
}


def rest_layout_candidate(
    token: str,
    meter: MeterSignature,
) -> tuple[int, str] | None:
    """Znajdź widoczną pauzę z uzgodnionej tabeli."""
    if (meter.numerator, meter.denominator) in {(4, 4), (2, 2)}:
        return None
    if "yy" in token or len(token.split()) != 1:
        return None

    match = re.fullmatch(r"([0-9]+\.*r)[^a-gA-Grq]*", token)
    if match is None:
        return None

    options = REST_LAYOUTS.get((meter.numerator, meter.denominator), {})
    return options.get(match.group(1))


def rest_duration_matches(
    token: str,
    meter: MeterSignature,
    measure_count: int,
) -> bool:
    """Sprawdź długość pauzy według istniejącego parsera rytmu."""
    return kern_duration(token) == meter.duration * measure_count


def rest_span_matches(
    *,
    records: tuple[TracedRecord, ...],
    timed_by_line: dict[int, TimedRecord],
    record_index: int,
    column: int,
    meter: MeterSignature,
    measure_count: int,
) -> bool:
    """Sprawdź rzeczywiste granice taktów objętych pauzą."""
    row = records[record_index]
    timed = timed_by_line.get(row.record.line_number)
    if timed is None:
        return False

    branch = row.branches[column]
    start_time = timed.onset
    end_time = start_time + meter.duration * measure_count

    starts_at_barline = False

    for earlier in reversed(records[:record_index]):
        earlier_time = timed_by_line.get(earlier.record.line_number)
        if earlier_time is None:
            return False
        if earlier_time.onset != start_time:
            break
        if earlier.record.kind is RecordKind.BARLINE:
            starts_at_barline = True
            break

    if not starts_at_barline:
        return False

    boundaries = []

    for following in records[record_index + 1 :]:
        following_time = timed_by_line.get(following.record.line_number)
        if following_time is None:
            return False

        onset = following_time.onset
        if onset > end_time:
            break

        record = following.record

        if record.kind is RecordKind.INTERPRETATION:
            for token, active_branch in zip(
                record.fields,
                following.branches,
                strict=True,
            ):
                if active_branch.identity.root_column != branch.identity.root_column:
                    continue

                # Zmiana struktury lub metrum w trakcie pauzy
                # wymaga osobnego rozpatrzenia.
                if onset < end_time:
                    if token in {"*^", "*v", "*x", "*+", "*-"}:
                        return False
                    if token.startswith("*M"):
                        try:
                            changed_meter = parse_meter(token)
                        except HumdrumError:
                            return False
                        if changed_meter != meter:
                            return False

        if record.kind is RecordKind.BARLINE and onset > start_time:
            if not boundaries or boundaries[-1] != onset:
                boundaries.append(onset)

            if onset == end_time:
                expected = [
                    start_time + meter.duration * number for number in range(1, measure_count + 1)
                ]
                return boundaries == expected

    return False


def annotate_multibar_rests(
    document: HumdrumDocument,
) -> tuple[HumdrumDocument, int, tuple[str, ...]]:
    structure = trace_spines(document)
    if structure.issue is not None:
        raise HumdrumError(f"Linia {structure.issue.line_number}: {structure.issue.message}")

    rhythm = trace_rhythm(document, structure=structure)
    if rhythm.issue is not None:
        raise HumdrumError(f"Linia {rhythm.issue.line_number}: {rhythm.issue.message}")

    timed_by_line = {record.line_number: record for record in rhythm.records}
    result = HumdrumDocument.from_text(document.to_text())
    insertions: dict[int, list[list[str]]] = {}
    comment_lines: list[int] = []
    warnings: list[str] = []
    changed_count = 0
    rest_tokens = {token for options in REST_LAYOUTS.values() for token in options}

    for record_index, row in enumerate(structure.records):
        record = row.record

        if record.kind is RecordKind.GLOBAL:
            continue

        if record.kind is RecordKind.LOCAL_COMMENT:
            comment_lines.append(record.line_number - 1)
            continue

        if record.kind is not RecordKind.DATA:
            comment_lines.clear()
            continue

        for column, branch in enumerate(row.branches):
            if branch.identity.spine_type != "**kern":
                continue

            token = record.fields[column]
            if "yy" in token:
                continue

            match = re.fullmatch(r"([0-9]+\.*r)[^a-gA-Grq]*", token)
            if match is None or match.group(1) not in rest_tokens:
                continue

            comments = [
                (line_number, result.lines[line_number].split("\t"))
                for line_number in comment_lines
            ]

            has_visual = any(
                (fields[column] == "!LO:N" or fields[column].startswith("!LO:N:"))
                and any(parameter.startswith("vis=") for parameter in fields[column].split(":")[2:])
                for _, fields in comments
            )
            if has_visual:
                continue

            try:
                meter = meter_at_line(
                    document,
                    record.line_number,
                    branch.identity.root_column,
                )
            except HumdrumError as error:
                warnings.append(f"Linia {record.line_number}, kolumna {column + 1}: {error}")
                continue

            candidate = rest_layout_candidate(token, meter)
            if candidate is None:
                continue

            measure_count, visual = candidate

            if not rest_duration_matches(token, meter, measure_count):
                warnings.append(
                    f"Linia {record.line_number}, kolumna {column + 1}: "
                    f"{token} nie ma długości {measure_count} pełnych taktów — pominięto."
                )
                continue

            if not rest_span_matches(
                records=structure.records,
                timed_by_line=timed_by_line,
                record_index=record_index,
                column=column,
                meter=meter,
                measure_count=measure_count,
            ):
                warnings.append(
                    f"Linia {record.line_number}, kolumna {column + 1}: "
                    f"nie potwierdzono granic {measure_count} pełnych taktów — pominięto."
                )
                continue

            layout_token = f"!LO:N:vis={visual}"
            empty_line = next(
                (
                    line_number
                    for line_number, fields in reversed(comments)
                    if fields[column] == "!"
                ),
                None,
            )

            if empty_line is not None:
                fields = result.lines[empty_line].split("\t")
                fields[column] = layout_token
                result.lines[empty_line] = "\t".join(fields)
            else:
                has_modern_layout = any(
                    field == "!LO:MO" or field.startswith("!LO:MO:")
                    for _, fields in comments
                    for field in fields
                )

                insertion_line = record.line_number - 1
                if has_modern_layout:
                    insertion_line = next(
                        (line_number for line_number, fields in comments if fields[column] != "!"),
                        insertion_line,
                    )

                insertion_rows = insertions.setdefault(insertion_line, [])
                insertion_row = next(
                    (
                        fields
                        for fields in insertion_rows
                        if len(fields) == len(record.fields) and fields[column] == "!"
                    ),
                    None,
                )

                if insertion_row is None:
                    insertion_row = ["!"] * len(record.fields)
                    insertion_rows.append(insertion_row)

                insertion_row[column] = layout_token

            changed_count += 1

        comment_lines.clear()

    for line_number, rows in sorted(insertions.items(), reverse=True):
        for fields in reversed(rows):
            result.lines.insert(line_number, "\t".join(fields))

    # Ponowne odczytanie odświeża również numery linii nagłówka.
    result = HumdrumDocument.from_text(result.to_text())
    return result, changed_count, tuple(dict.fromkeys(warnings))
