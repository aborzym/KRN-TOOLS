from dataclasses import dataclass
from fractions import Fraction

from spineworks.humdrum import HumdrumDocument, HumdrumError
from spineworks.kern_rhythm import advance_kern_row, hidden_rest_token
from spineworks.meter_rhythm import MeterSignature, parse_meter
from spineworks.spine_validation import (
    RecordKind,
    SpineBranch,
    StructureIssue,
    plan_merge_move,
    plan_split_move,
    prepare_merge_extension,
    prepare_split_move,
    trace_spines,
)


def remap_spine_remaining(
    before: tuple[SpineBranch, ...],
    remaining: tuple[Fraction, ...],
    after: tuple[SpineBranch, ...],
) -> tuple[Fraction, ...]:
    """Przenieś pozostałe długości przez rozdwojenia i scalenia."""
    if len(before) != len(remaining):
        raise HumdrumError("Liczba długości nie odpowiada liczbie spinów.")

    if any(value < 0 for value in remaining):
        raise HumdrumError("Pozostała długość nie może być ujemna.")

    def is_ancestor(
        ancestor: SpineBranch,
        descendant: SpineBranch,
    ) -> bool:
        depth = len(ancestor.path)
        return (
            ancestor.identity == descendant.identity
            and descendant.path[:depth] == ancestor.path
            and descendant.opening_lines[:depth] == ancestor.opening_lines
        )

    result: list[Fraction] = []

    for branch in after:
        if branch.identity.spine_type != "**kern":
            result.append(Fraction(0))
            continue

        ancestors = [
            (candidate, value)
            for candidate, value in zip(before, remaining, strict=True)
            if is_ancestor(candidate, branch)
        ]

        if ancestors:
            # Zachowany głos lub nowa gałąź po *^.
            _, value = max(
                ancestors,
                key=lambda item: len(item[0].path),
            )
            result.append(value)
            continue

        descendants = [
            value
            for candidate, value in zip(before, remaining, strict=True)
            if is_ancestor(branch, candidate)
        ]

        if not descendants:
            raise HumdrumError("Nie można ustalić poprzednika głosu **kern.")

        if len(set(descendants)) != 1:
            instrument = branch.identity.instrument or "**kern"
            raise HumdrumError(
                f"{instrument}: scalane głosy mają różne pozostałe długości rytmiczne."
            )

        result.append(descendants[0])

    return tuple(result)


@dataclass(frozen=True)
class TimedRecord:
    line_number: int
    onset: Fraction
    duration: Fraction
    remaining_before: tuple[Fraction, ...] = ()


@dataclass(frozen=True)
class RhythmTrace:
    records: tuple[TimedRecord, ...]
    issue: StructureIssue | None


def trace_rhythm(document: HumdrumDocument) -> RhythmTrace:
    """Odczytaj oś czasu bez zmieniania dokumentu."""
    structure = trace_spines(document)
    timed: list[TimedRecord] = []
    previous: tuple[SpineBranch, ...] = ()
    remaining: tuple[Fraction, ...] = ()
    current_time = Fraction(0)
    initialized = False

    for row in structure.records:
        record = row.record

        if structure.issue is not None and record.line_number >= structure.issue.line_number:
            return RhythmTrace(tuple(timed), structure.issue)

        if record.kind in {RecordKind.GLOBAL, RecordKind.EMPTY}:
            timed.append(TimedRecord(record.line_number, current_time, Fraction(0)))
            continue

        if not row.branches:
            timed.append(TimedRecord(record.line_number, current_time, Fraction(0)))
            continue

        try:
            if not initialized:
                remaining = tuple(Fraction(0) for _ in row.branches)
                initialized = True
            else:
                remaining = remap_spine_remaining(
                    previous,
                    remaining,
                    row.branches,
                )

            remaining_before = remaining
            elapsed = Fraction(0)

            if record.kind is RecordKind.DATA:
                kern_columns = [
                    column
                    for column, branch in enumerate(row.branches)
                    if branch.identity.spine_type == "**kern"
                ]
                tokens = tuple(record.fields[column] for column in kern_columns)

                if not tokens or all(token == "." for token in tokens):
                    raise HumdrumError(
                        "Nie można ustalić czasu wiersza: brak nowego tokenu rytmicznego **kern."
                    )

                elapsed, kern_remaining = advance_kern_row(
                    tokens,
                    tuple(remaining[column] for column in kern_columns),
                )

                updated = list(remaining)
                for column, value in zip(
                    kern_columns,
                    kern_remaining,
                    strict=True,
                ):
                    updated[column] = value
                remaining = tuple(updated)

        except HumdrumError as error:
            return RhythmTrace(
                records=tuple(timed),
                issue=StructureIssue(record.line_number, str(error)),
            )

        timed.append(
            TimedRecord(
                line_number=record.line_number,
                onset=current_time,
                duration=elapsed,
                remaining_before=remaining_before,
            )
        )
        current_time += elapsed
        previous = row.branches

    return RhythmTrace(tuple(timed), structure.issue)


@dataclass(frozen=True)
class TokenSuggestion:
    source_line: int
    source_column: int
    token: str


def suggest_merge_fill(
    document: HumdrumDocument,
    source_line: int,
    root_column: int,
) -> tuple[TokenSuggestion, ...]:
    """Zaproponuj wypełnienie dodatkowych głosów bez edycji dokumentu."""
    plan = plan_merge_move(document, source_line, root_column)
    extension = prepare_merge_extension(document, plan)
    data_rows = tuple(row for row in extension if row.proposed_columns)

    if plan.identity.spine_type != "**kern":
        return tuple(
            TokenSuggestion(row.source_line, column, ".")
            for row in data_rows
            for column in row.proposed_columns
        )

    rhythm = trace_rhythm(document)
    if rhythm.issue is not None and rhythm.issue.line_number <= plan.end_barline:
        raise HumdrumError(f"Linia {rhythm.issue.line_number}: {rhythm.issue.message}")

    times = {row.line_number: row for row in rhythm.records}
    structure = trace_spines(document)
    selected = next(row for row in structure.records if row.record.line_number == source_line)
    columns = [
        column
        for column, branch in enumerate(selected.branches)
        if branch.identity == plan.identity and selected.record.fields[column] == "*v"
    ]

    if len(columns) != plan.branch_count:
        raise HumdrumError("Nie można ustalić głosów przenoszonego scalenia.")

    merge_time = times[source_line]
    active_until = [
        merge_time.onset + merge_time.remaining_before[column] for column in columns[1:]
    ]
    measure_end = times[plan.end_barline].onset

    boundaries = sorted(
        {times[row.source_line].onset for row in data_rows} | {measure_end},
        reverse=True,
    )
    suggestions: list[TokenSuggestion] = []

    for row in data_rows:
        timed = times[row.source_line]

        for slot, column in enumerate(row.proposed_columns):
            if timed.duration == 0 or timed.onset < active_until[slot]:
                token = "."
            else:
                token = ""
                for boundary in boundaries:
                    if boundary <= timed.onset:
                        continue

                    try:
                        candidate = hidden_rest_token(boundary - timed.onset)
                    except HumdrumError:
                        continue

                    token = candidate
                    active_until[slot] = boundary
                    break

                if not token:
                    raise HumdrumError(
                        f"Linia {row.source_line}: nie można zaproponować "
                        "pauzy kończącej się na dostępnej granicy wiersza."
                    )

            suggestions.append(
                TokenSuggestion(
                    source_line=row.source_line,
                    source_column=column,
                    token=token,
                )
            )

    return tuple(suggestions)


def suggest_split_fill(
    document: HumdrumDocument,
    source_line: int,
    root_column: int,
) -> tuple[TokenSuggestion, ...]:
    """Zaproponuj wypełnienie głosu przed pierwotnym *^."""
    plan = plan_split_move(document, source_line, root_column)
    proposal = prepare_split_move(document, source_line, root_column)

    if not proposal.proposed_cells:
        return ()

    if plan.identity.spine_type != "**kern":
        return tuple(TokenSuggestion(line, column, ".") for line, column in proposal.proposed_cells)

    rhythm = trace_rhythm(document)
    if rhythm.issue is not None and rhythm.issue.line_number <= source_line:
        raise HumdrumError(f"Linia {rhythm.issue.line_number}: {rhythm.issue.message}")

    times = {row.line_number: row for row in rhythm.records}
    structure = trace_spines(document)
    target = next(row for row in structure.records if row.record.line_number == plan.target_line)
    column = target.branches.index(plan.branch)
    target_time = times[plan.target_line]
    active_until = target_time.onset + target_time.remaining_before[column]
    original_opening_time = times[source_line].onset

    boundaries = sorted(
        {times[line].onset for line, _ in proposal.proposed_cells} | {original_opening_time},
        reverse=True,
    )
    suggestions: list[TokenSuggestion] = []

    for line, column in proposal.proposed_cells:
        timed = times[line]

        if timed.duration == 0 or timed.onset < active_until:
            token = "."
        else:
            token = ""
            for boundary in boundaries:
                if boundary <= timed.onset:
                    continue

                try:
                    candidate = hidden_rest_token(boundary - timed.onset)
                except HumdrumError:
                    continue

                token = candidate
                active_until = boundary
                break

            if not token:
                raise HumdrumError(
                    f"Linia {line}: nie można zaproponować pauzy "
                    "przed pierwotnym otwarciem rozdwojenia."
                )

        suggestions.append(
            TokenSuggestion(
                source_line=line,
                source_column=column,
                token=token,
            )
        )

    return tuple(suggestions)


def meter_at_line(
    document: HumdrumDocument,
    source_line: int,
    root_column: int,
) -> MeterSignature:
    """Odczytaj metrum instrumentu obowiązujące we wskazanej linii."""
    if not 1 <= source_line <= len(document.lines):
        raise HumdrumError("Linia odczytu metrum wykracza poza dokument.")

    if not 0 <= root_column < document.spine_count:
        raise HumdrumError("Nieprawidłowy spine źródłowy.")

    trace = trace_spines(document)
    if trace.issue is not None and trace.issue.line_number <= source_line:
        raise HumdrumError(f"Linia {trace.issue.line_number}: {trace.issue.message}")

    meter: MeterSignature | None = None

    for row in trace.records:
        record = row.record
        if record.line_number > source_line:
            break
        if record.kind is not RecordKind.INTERPRETATION:
            continue

        found: set[MeterSignature] = set()

        for token, branch in zip(record.fields, row.branches):
            if branch.identity.root_column != root_column:
                continue
            if token.startswith("*M") and token[2:3].isdigit():
                found.add(parse_meter(token))

        if len(found) > 1:
            raise HumdrumError(
                f"Linia {record.line_number}: różne metra w gałęziach tego samego instrumentu."
            )
        if found:
            meter = next(iter(found))

    if meter is None:
        raise HumdrumError(f"Linia {source_line}: brak metrum dla wskazanego spinu.")

    return meter
