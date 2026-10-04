import re
from dataclasses import dataclass
from fractions import Fraction

from spineworks.humdrum import HumdrumDocument, HumdrumError
from spineworks.kern_rhythm import advance_kern_row, hidden_rest_token, kern_duration
from spineworks.meter_rhythm import (
    MeterRestOption,
    MeterSignature,
    parse_meter,
    plan_meter_rests,
)
from spineworks.spine_validation import (
    RecordKind,
    SpineBranch,
    SpineTrace,
    StructureIssue,
    TracedRecord,
    plan_merge_move,
    plan_merge_reopening,
    plan_split_move,
    prepare_merge_extension,
    prepare_merge_reopenings,
    prepare_split_move,
    read_records,
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

    if before == after:
        return tuple(
            value if branch.identity.spine_type == "**kern" else Fraction(0)
            for branch, value in zip(after, remaining, strict=True)
        )

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


@dataclass(frozen=True)
class RhythmCheckpoint:
    previous: tuple[SpineBranch, ...]
    remaining: tuple[Fraction, ...]
    current_time: Fraction
    initialized: bool


@dataclass
class RhythmCache:
    source_records: tuple[TracedRecord, ...] = ()
    timed_records: tuple[TimedRecord, ...] = ()
    checkpoints: tuple[RhythmCheckpoint, ...] = ()


def trace_rhythm(
    document: HumdrumDocument,
    *,
    structure: SpineTrace | None = None,
    cache: RhythmCache | None = None,
) -> RhythmTrace:
    """Odczytaj rytm, wykorzystując stan niezmienionego początku."""
    if structure is None:
        structure = trace_spines(document)

    prefix = 0
    if cache is not None:
        limit = min(
            len(structure.records),
            len(cache.source_records),
            len(cache.timed_records),
            len(cache.checkpoints),
        )
        if structure.issue is not None:
            limit = min(limit, structure.issue.line_number - 1)

        while prefix < limit and structure.records[prefix] == cache.source_records[prefix]:
            prefix += 1

    timed = list(cache.timed_records[:prefix]) if cache is not None else []
    checkpoints = list(cache.checkpoints[:prefix]) if cache is not None else []

    previous: tuple[SpineBranch, ...] = ()
    remaining: tuple[Fraction, ...] = ()
    current_time = Fraction(0)
    initialized = False

    if prefix:
        checkpoint = checkpoints[-1]
        previous = checkpoint.previous
        remaining = checkpoint.remaining
        current_time = checkpoint.current_time
        initialized = checkpoint.initialized

    def remember_state() -> None:
        if cache is not None:
            checkpoints.append(
                RhythmCheckpoint(
                    previous=previous,
                    remaining=remaining,
                    current_time=current_time,
                    initialized=initialized,
                )
            )

    def finish(issue: StructureIssue | None) -> RhythmTrace:
        result = RhythmTrace(tuple(timed), issue)
        if cache is not None:
            cache.source_records = structure.records[: len(timed)]
            cache.timed_records = result.records
            cache.checkpoints = tuple(checkpoints)
        return result

    for row in structure.records[prefix:]:
        record = row.record

        if structure.issue is not None and record.line_number >= structure.issue.line_number:
            return finish(structure.issue)

        if record.kind in {RecordKind.GLOBAL, RecordKind.EMPTY}:
            timed.append(TimedRecord(record.line_number, current_time, Fraction(0)))
            remember_state()
            continue

        if not row.branches:
            timed.append(TimedRecord(record.line_number, current_time, Fraction(0)))
            remember_state()
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
            return finish(StructureIssue(record.line_number, str(error)))

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
        remember_state()

    return finish(structure.issue)


@dataclass(frozen=True)
class TokenSuggestion:
    source_line: int
    source_column: int
    token: str


def suggest_merge_fill(
    document: HumdrumDocument,
    source_line: int,
    root_column: int,
    *,
    rest_option: MeterRestOption | None = None,
) -> tuple[TokenSuggestion, ...]:
    """Zaproponuj wypełnienie dodatkowych głosów bez edycji dokumentu."""
    plan = plan_merge_move(document, source_line, root_column)

    document = HumdrumDocument(
        document.lines[: plan.end_barline],
        False,
    )

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

    if rest_option is not None:
        meter = meter_at_line(document, source_line, root_column)
        if rest_option.meter != meter:
            raise HumdrumError("Wybrany podział pauz nie odpowiada metrum instrumentu.")

        preceding_barlines = [
            row.record.line_number
            for row in structure.records
            if row.record.kind is RecordKind.BARLINE and row.record.line_number < source_line
        ]
        measure_start = times[preceding_barlines[-1]].onset if preceding_barlines else Fraction(0)
        timed_rows = tuple(times[row.source_line] for row in data_rows)
        suggestions: list[TokenSuggestion] = []

        for slot in range(len(active_until)):
            tokens = _meter_fill_tokens(
                timed_rows,
                option=rest_option,
                measure_start=measure_start,
                active_until=active_until[slot],
                end_time=measure_end,
            )

            for row in data_rows:
                suggestions.append(
                    TokenSuggestion(
                        source_line=row.source_line,
                        source_column=row.proposed_columns[slot],
                        token=tokens[row.source_line],
                    )
                )

        return tuple(
            sorted(
                suggestions,
                key=lambda item: (item.source_line, item.source_column),
            )
        )

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
    *,
    rest_option: MeterRestOption | None = None,
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

    if rest_option is not None:
        meter = meter_at_line(document, plan.target_line, root_column)
        if rest_option.meter != meter:
            raise HumdrumError("Wybrany podział pauz nie odpowiada metrum instrumentu.")

        preceding_barlines = [
            row.record.line_number
            for row in structure.records
            if row.record.kind is RecordKind.BARLINE and row.record.line_number <= plan.target_line
        ]
        measure_start = times[preceding_barlines[-1]].onset if preceding_barlines else Fraction(0)
        timed_rows = tuple(
            times[line] for line in dict.fromkeys(line for line, _ in proposal.proposed_cells)
        )
        tokens = _meter_fill_tokens(
            timed_rows,
            option=rest_option,
            measure_start=measure_start,
            active_until=active_until,
            end_time=original_opening_time,
        )

        return tuple(
            TokenSuggestion(
                source_line=line,
                source_column=column,
                token=tokens[line],
            )
            for line, column in proposal.proposed_cells
        )

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


def _meter_fill_tokens(
    rows: tuple[TimedRecord, ...],
    *,
    option: MeterRestOption,
    measure_start: Fraction,
    active_until: Fraction,
    end_time: Fraction,
) -> dict[int, str]:
    """Przypisz pauzy i kropki do istniejących wierszy danych."""
    tokens = {row.line_number: "." for row in rows}
    available = tuple(
        row for row in rows if row.duration > 0 and active_until <= row.onset < end_time
    )

    if not available:
        if active_until < end_time:
            raise HumdrumError("Brak wiersza danych, w którym można rozpocząć pauzę.")
        return tokens

    silence_start = available[0].onset
    if silence_start != active_until:
        raise HumdrumError(
            "Początek ciszy wypada między wierszami danych — wymaga ręcznego uzupełnienia."
        )

    rests = plan_meter_rests(
        option,
        silence_start - measure_start,
        end_time - measure_start,
    )

    rows_at_time: dict[Fraction, TimedRecord] = {}
    for row in available:
        rows_at_time.setdefault(row.onset, row)

    for rest in rests:
        onset = measure_start + rest.onset
        row = rows_at_time.get(onset)
        if row is None:
            raise HumdrumError(
                "Brak wiersza danych na granicy wymaganej przez "
                "podział metrum — wymaga ręcznego uzupełnienia."
            )
        tokens[row.line_number] = rest.token

    return tokens


def suggest_hidden_rest_span(
    rows: tuple[TimedRecord, ...],
    tokens: tuple[str, ...],
    *,
    source_column: int,
    option: MeterRestOption,
    measure_start: Fraction,
    end_time: Fraction,
) -> tuple[TokenSuggestion, ...]:
    """Zaproponuj podział potwierdzonego odcinka ciszy w jednej warstwie."""
    if len(rows) != len(tokens):
        raise HumdrumError("Liczba tokenów nie odpowiada liczbie wierszy.")

    if not rows:
        return ()

    for row, token in zip(rows, tokens, strict=True):
        is_hidden_rest = (
            re.fullmatch(
                r"\d+(?:%\d+)?\.*ryy",
                token,
            )
            is not None
        )

        if token not in {"", "."} and not is_hidden_rest:
            raise HumdrumError(
                f"Linia {row.line_number}: odcinek zawiera nutę, "
                "zwykłą pauzę lub token wymagający ręcznej kontroli."
            )

    if tokens[0] == ".":
        raise HumdrumError(
            "Odcinek zaczyna się kontynuacją — trzeba ustalić "
            "wcześniejszy token przed proponowaniem pauz."
        )

    proposed = _meter_fill_tokens(
        rows,
        option=option,
        measure_start=measure_start,
        active_until=rows[0].onset,
        end_time=end_time,
    )

    return tuple(
        TokenSuggestion(
            source_line=row.line_number,
            source_column=source_column,
            token=proposed[row.line_number],
        )
        for row in rows
    )


def suggest_reopening_fill(
    document: HumdrumDocument,
    source_line: int,
    root_column: int,
    *,
    rest_option: MeterRestOption,
) -> tuple[TokenSuggestion, ...]:
    """Zaproponuj pauzy po połączeniu zamknięć i ponownych otwarć."""
    plan = plan_merge_reopening(document, source_line, root_column)
    structure = trace_spines(document)

    start_line = max(
        (
            row.record.line_number
            for row in structure.records
            if row.record.kind is RecordKind.BARLINE and row.record.line_number < source_line
        ),
        default=1,
    )
    end_line = next(
        (
            row.record.line_number
            for row in structure.records
            if row.record.kind is RecordKind.BARLINE and row.record.line_number > source_line
        ),
        None,
    )
    if end_line is None:
        raise HumdrumError("Brak końcowej kreski taktu.")

    document = HumdrumDocument(document.lines[:end_line], False)
    if meter_at_line(document, source_line, root_column) != rest_option.meter:
        raise HumdrumError("Wybrany podział pauz nie odpowiada metrum.")

    rhythm = trace_rhythm(document)
    if rhythm.issue is not None:
        raise HumdrumError(f"Linia {rhythm.issue.line_number}: {rhythm.issue.message}")

    times = {row.line_number: row for row in rhythm.records}
    measure_start = times[start_line].onset
    measure_end = times[end_line].onset
    proposal = prepare_merge_reopenings(document, source_line, root_column)
    replacements = dict(proposal.replacements)

    mapped_lines: list[tuple[int, str]] = []
    for number, text in enumerate(document.lines, start=1):
        if number not in replacements:
            mapped_lines.append((number, text))
            continue

        for line in replacements[number]:
            if line.source_line is None:
                raise HumdrumError("Wiersz połączenia nie ma numeru źródłowego.")
            mapped_lines.append((line.source_line, line.text))

    records = read_records("\n".join(text for _, text in mapped_lines))
    tracing_lines = [
        "\t".join(token or "." for token in record.fields)
        if record.kind is RecordKind.DATA
        else record.text
        for record in records
    ]
    joined = trace_spines(HumdrumDocument(tracing_lines, False))
    if joined.issue is not None:
        raise HumdrumError(joined.issue.message)

    path = plan.branches[1].path
    suggestions: list[TokenSuggestion] = []
    span_rows: list[TimedRecord] = []
    span_tokens: list[str] = []
    span_columns: list[int] = []
    blocked_until = measure_start

    original_start = next(row for row in structure.records if row.record.line_number == start_line)
    for column, branch in enumerate(original_start.branches):
        if branch.identity == plan.identity and branch.path == path:
            blocked_until += times[start_line].remaining_before[column]
            break

    def finish_span(end_time: Fraction) -> None:
        if not span_rows:
            return

        proposed = suggest_hidden_rest_span(
            tuple(span_rows),
            tuple(span_tokens),
            source_column=0,
            option=rest_option,
            measure_start=measure_start,
            end_time=end_time,
        )
        for item, column in zip(proposed, span_columns, strict=True):
            suggestions.append(TokenSuggestion(item.source_line, column, item.token))

        span_rows.clear()
        span_tokens.clear()
        span_columns.clear()

    for index, row in enumerate(joined.records):
        number = mapped_lines[index][0]
        record = records[index]
        if not start_line <= number < end_line:
            continue
        if record.kind is not RecordKind.DATA:
            continue

        columns = [
            column
            for column, branch in enumerate(row.branches)
            if branch.identity == plan.identity and branch.path == path
        ]
        if not columns:
            finish_span(times[number].onset)
            continue
        if len(columns) != 1:
            raise HumdrumError("Nie można jednoznacznie ustalić dodatkowej warstwy.")

        column = columns[0]
        token = record.fields[column]
        timed = times[number]
        is_hidden_rest = re.fullmatch(r"\d+(?:%\d+)?\.*ryy", token) is not None

        if token in {"", "."} and timed.onset < blocked_until:
            if token == "":
                suggestions.append(TokenSuggestion(number, column, "."))
            continue

        if is_hidden_rest or token == "" or (token == "." and span_rows):
            if is_hidden_rest:
                duration = kern_duration(token)
                if duration is None or timed.onset + duration > measure_end:
                    raise HumdrumError(f"Linia {number}: ukryta pauza wykracza poza takt.")

            span_rows.append(timed)
            span_tokens.append(token)
            span_columns.append(column)
            continue

        finish_span(timed.onset)

        if token != ".":
            duration = kern_duration(token)
            if duration is None:
                raise HumdrumError(f"Linia {number}: nie można ustalić długości tokenu.")
            blocked_until = timed.onset + duration

    finish_span(measure_end)
    return tuple(suggestions)
