import re
from dataclasses import dataclass
from itertools import pairwise

from spineworks.humdrum import HumdrumDocument, HumdrumError
from spineworks.kern_rhythm import hidden_rest_token, kern_duration
from spineworks.meter_rhythm import MeterSignature
from spineworks.spine_rhythm import meter_at_line, trace_rhythm
from spineworks.spine_validation import RecordKind, trace_spines


@dataclass(frozen=True)
class FullMeasureRest:
    bar_index: int
    measure_number: int | None
    root_column: int
    line_number: int
    column: int
    token: str
    meter: MeterSignature
    break_before: bool
    break_after: bool


def find_full_measure_rests(
    document: HumdrumDocument,
    *,
    kern_columns: set[int],
    start_measure: int | None = None,
    end_measure: int | None = None,
) -> tuple[FullMeasureRest, ...]:
    if start_measure is not None and end_measure is not None and start_measure > end_measure:
        raise HumdrumError("Pierwszy takt nie może być późniejszy niż ostatni.")

    selected = {
        column
        for column in kern_columns
        if 0 <= column < document.spine_count and document.spine_types[column] == "**kern"
    }
    if not selected:
        raise HumdrumError("Nie wybrano żadnego spinu **kern.")

    structure = trace_spines(document)
    if structure.issue is not None:
        raise HumdrumError(f"Linia {structure.issue.line_number}: {structure.issue.message}")

    rhythm = trace_rhythm(
        document,
        structure=structure,
        allow_auxiliary_rows=True,
    )
    if rhythm.issue is not None:
        raise HumdrumError(f"Linia {rhythm.issue.line_number}: {rhythm.issue.message}")

    timed = {row.line_number: row for row in rhythm.records}
    records = structure.records
    barlines = [index for index, row in enumerate(records) if row.record.kind is RecordKind.BARLINE]

    found: list[FullMeasureRest] = []
    current_measure: int | None = None

    for bar_index, (left, right) in enumerate(pairwise(barlines)):
        opening = records[left]
        closing = records[right]
        number = next(
            (match for token in opening.record.fields if (match := re.match(r"^=+(\d+)", token))),
            None,
        )
        if number is not None:
            current_measure = int(number.group(1))

        if start_measure is not None or end_measure is not None:
            if current_measure is None:
                continue
            if start_measure is not None and current_measure < start_measure:
                continue
            if end_measure is not None and current_measure > end_measure:
                continue

        start_time = timed[opening.record.line_number].onset
        end_time = timed[closing.record.line_number].onset

        for root in sorted(selected):
            events = []
            changes = []
            opening_token = None
            closing_token = None
            supported = True

            for position in range(left, right + 1):
                row = records[position]
                record = row.record
                if record.kind in {RecordKind.GLOBAL, RecordKind.EMPTY}:
                    continue

                columns = [
                    column
                    for column, branch in enumerate(row.branches)
                    if branch.identity.root_column == root
                ]

                # Na początek kwalifikujemy tylko pojedynczą warstwę.
                if len(columns) != 1:
                    supported = False
                    break

                column = columns[0]
                token = record.fields[column]

                if position == left:
                    opening_token = token
                if position == right:
                    closing_token = token

                if record.kind is RecordKind.INTERPRETATION:
                    if token in {"*^", "*v", "*x", "*+", "*-"}:
                        supported = False
                        break
                    if token.startswith(("*clef", "*M")):
                        changes.append(record.line_number)

                if record.kind is RecordKind.DATA and token != ".":
                    events.append((record.line_number, column, token))

            if not supported or len(events) != 1:
                continue

            line_number, column, token = events[0]

            # Ukryte i dodatkowo oznaczone pauzy pozostawiamy bez zmian.
            if re.fullmatch(r"[0-9]+(?:%[0-9]+)?\.*r", token) is None:
                continue

            try:
                meter = meter_at_line(document, line_number, root)
            except HumdrumError:
                continue

            if timed[line_number].onset != start_time:
                continue
            if end_time - start_time != meter.duration:
                continue
            if kern_duration(token) != meter.duration:
                continue

            found.append(
                FullMeasureRest(
                    bar_index=bar_index,
                    measure_number=current_measure,
                    root_column=root,
                    line_number=line_number,
                    column=column,
                    token=token,
                    meter=meter,
                    break_before=(
                        "||" in (opening_token or "")
                        or (opening_token or "").startswith("==")
                        or any(line <= line_number for line in changes)
                    ),
                    break_after=(
                        "||" in (closing_token or "")
                        or (closing_token or "").startswith("==")
                        or any(line > line_number for line in changes)
                    ),
                )
            )

    return tuple(found)


def plan_rest_groups(
    rests: tuple[FullMeasureRest, ...],
) -> tuple[tuple[FullMeasureRest, ...], ...]:
    groups: list[tuple[FullMeasureRest, ...]] = []

    def add_run(run: list[FullMeasureRest]) -> None:
        position = 0

        while len(run) - position >= 4:
            groups.append(tuple(run[position : position + 4]))
            position += 4

        if len(run) - position >= 2:
            groups.append(tuple(run[position : position + 2]))

    roots = sorted({rest.root_column for rest in rests})

    for root in roots:
        ordered = sorted(
            (rest for rest in rests if rest.root_column == root),
            key=lambda rest: rest.bar_index,
        )
        run: list[FullMeasureRest] = []

        for rest in ordered:
            if run:
                previous = run[-1]
                interrupted = (
                    rest.bar_index != previous.bar_index + 1
                    or rest.meter != previous.meter
                    or previous.break_after
                    or rest.break_before
                )
                if interrupted:
                    add_run(run)
                    run = []

            run.append(rest)

            if rest.break_after:
                add_run(run)
                run = []

        add_run(run)

    return tuple(groups)


def create_multibar_rests(
    document: HumdrumDocument,
    *,
    kern_columns: set[int],
    start_measure: int | None = None,
    end_measure: int | None = None,
) -> tuple[HumdrumDocument, int]:
    rests = find_full_measure_rests(
        document,
        kern_columns=kern_columns,
        start_measure=start_measure,
        end_measure=end_measure,
    )
    groups = plan_rest_groups(rests)
    result = HumdrumDocument.from_text(document.to_text())
    updates: dict[int, list[str]] = {}

    for group in groups:
        first = group[0]
        duration = first.meter.duration * len(group)
        multibar_token = hidden_rest_token(duration).removesuffix("yy")

        if kern_duration(multibar_token) != duration:
            raise HumdrumError("Nieprawidłowa długość utworzonej pauzy wielotaktowej.")

        for index, rest in enumerate(group):
            line_index = rest.line_number - 1
            fields = updates.setdefault(
                line_index,
                result.lines[line_index].split("\t"),
            )
            fields[rest.column] = multibar_token if index == 0 else "."

    for line_index, fields in updates.items():
        result.lines[line_index] = "\t".join(fields)

    result = HumdrumDocument.from_text(result.to_text())
    return result, len(groups)


def split_multibar_rests(
    document: HumdrumDocument,
    *,
    kern_columns: set[int],
    start_measure: int | None = None,
    end_measure: int | None = None,
) -> tuple[HumdrumDocument, int, tuple[str, ...]]:
    if start_measure is not None and end_measure is not None and start_measure > end_measure:
        raise HumdrumError("Pierwszy takt nie może być późniejszy niż ostatni.")

    selected = {
        column
        for column in kern_columns
        if 0 <= column < document.spine_count and document.spine_types[column] == "**kern"
    }
    if not selected:
        raise HumdrumError("Nie wybrano żadnego spinu **kern.")

    structure = trace_spines(document)
    if structure.issue is not None:
        raise HumdrumError(f"Linia {structure.issue.line_number}: {structure.issue.message}")

    rhythm = trace_rhythm(document, structure=structure, allow_auxiliary_rows=True)
    if rhythm.issue is not None:
        raise HumdrumError(f"Linia {rhythm.issue.line_number}: {rhythm.issue.message}")

    records = structure.records
    timed = {row.line_number: row for row in rhythm.records}
    barlines = [index for index, row in enumerate(records) if row.record.kind is RecordKind.BARLINE]

    measure_numbers: dict[int, int | None] = {}
    current_measure: int | None = None
    for position in barlines:
        match = next(
            (
                found
                for token in records[position].record.fields
                if (found := re.match(r"^=+(\d+)", token))
            ),
            None,
        )
        if match is not None:
            current_measure = int(match.group(1))
        measure_numbers[position] = current_measure

    result = HumdrumDocument.from_text(document.to_text())
    updates: dict[int, list[str]] = {}
    warnings: list[str] = []
    changed_count = 0

    def set_field(line_number: int, column: int, token: str) -> None:
        fields = updates.setdefault(
            line_number - 1,
            result.lines[line_number - 1].split("\t"),
        )
        fields[column] = token

    for record_index, row in enumerate(records):
        record = row.record
        if record.kind is not RecordKind.DATA:
            continue

        for column, branch in enumerate(row.branches):
            root = branch.identity.root_column
            if branch.identity.spine_type != "**kern" or root not in selected:
                continue

            token = record.fields[column]
            if re.fullmatch(r"[0-9]+(?:%[0-9]+)?\.*r", token) is None:
                continue

            meter = meter_at_line(document, record.line_number, root)
            duration = kern_duration(token)
            if duration is None:
                continue

            span = duration / meter.duration
            if span not in {2, 4}:
                continue
            measure_count = int(span)
            onset = timed[record.line_number].onset

            opening_index = next(
                (
                    index
                    for index in reversed(barlines)
                    if index < record_index
                    and timed[records[index].record.line_number].onset == onset
                ),
                None,
            )
            if opening_index is None:
                continue

            bar_position = barlines.index(opening_index)
            covered = barlines[bar_position : bar_position + measure_count + 1]
            if len(covered) != measure_count + 1:
                warnings.append(
                    f"Linia {record.line_number}: brak końcowej kreski pauzy — pominięto."
                )
                continue

            numbers = [measure_numbers[index] for index in covered[:-1]]
            if start_measure is not None or end_measure is not None:
                inside = [
                    number is not None
                    and (start_measure is None or number >= start_measure)
                    and (end_measure is None or number <= end_measure)
                    for number in numbers
                ]
                if not all(inside):
                    if any(inside):
                        warnings.append(
                            f"Linia {record.line_number}: pauza częściowo poza "
                            "wybranym zakresem — pominięto."
                        )
                    continue

            destinations: list[tuple[int, int]] = []
            safe = True

            for offset, (left, right) in enumerate(pairwise(covered)):
                expected_onset = onset + offset * meter.duration
                if (
                    timed[records[left].record.line_number].onset != expected_onset
                    or timed[records[right].record.line_number].onset
                    != expected_onset + meter.duration
                ):
                    safe = False
                    break

                destination = None

                for position in range(left, right):
                    active_row = records[position]
                    active_record = active_row.record
                    if active_record.kind in {RecordKind.GLOBAL, RecordKind.EMPTY}:
                        continue

                    columns = [
                        index
                        for index, active_branch in enumerate(active_row.branches)
                        if active_branch.identity.root_column == root
                    ]
                    if len(columns) != 1:
                        safe = False
                        break

                    active_column = columns[0]
                    active_token = active_record.fields[active_column]

                    if active_record.kind is RecordKind.INTERPRETATION and active_token in {
                        "*^",
                        "*v",
                        "*x",
                        "*+",
                        "*-",
                    }:
                        safe = False
                        break

                    if active_record.kind is not RecordKind.DATA:
                        continue

                    if active_record.line_number != record.line_number and active_token != ".":
                        safe = False
                        break

                    active_meter = meter_at_line(document, active_record.line_number, root)
                    if active_meter != meter:
                        safe = False
                        break

                    has_grace = any(
                        "q" in field
                        for field, active_branch in zip(
                            active_record.fields, active_row.branches, strict=True
                        )
                        if active_branch.identity.spine_type == "**kern"
                    )
                    if destination is None and not has_grace:
                        destination = (
                            active_record.line_number,
                            active_column,
                        )

                if not safe or destination is None:
                    safe = False
                    break

                if timed[destination[0]].onset != expected_onset:
                    safe = False
                    break

                destinations.append(destination)

            if not safe:
                warnings.append(
                    f"Linia {record.line_number}: nie można bezpiecznie rozbić "
                    "pauzy w istniejących wierszach danych — pominięto."
                )
                continue

            whole_rest = hidden_rest_token(meter.duration).removesuffix("yy")
            set_field(record.line_number, column, ".")
            for line_number, target_column in destinations:
                set_field(line_number, target_column, whole_rest)

            # Usuń całe LO:N:vis przypisane do rozbijanej pauzy.
            for earlier in reversed(records[:record_index]):
                if earlier.record.kind is RecordKind.GLOBAL:
                    continue
                if earlier.record.kind is not RecordKind.LOCAL_COMMENT:
                    break

                comment = earlier.record.fields[column]
                if comment.startswith("!LO:N:") and any(
                    parameter.startswith("vis=") for parameter in comment.split(":")[2:]
                ):
                    set_field(earlier.record.line_number, column, "!")

            changed_count += 1

    for line_index, fields in updates.items():
        result.lines[line_index] = "\t".join(fields)

    result = HumdrumDocument.from_text(result.to_text())
    return result, changed_count, tuple(dict.fromkeys(warnings))
