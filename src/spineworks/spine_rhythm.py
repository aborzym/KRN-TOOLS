from dataclasses import dataclass
from fractions import Fraction

from spineworks.humdrum import HumdrumDocument, HumdrumError
from spineworks.kern_rhythm import advance_kern_row
from spineworks.spine_validation import (
    RecordKind,
    SpineBranch,
    StructureIssue,
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
