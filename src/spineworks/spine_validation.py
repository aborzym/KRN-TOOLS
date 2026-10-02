import re
from dataclasses import dataclass
from enum import Enum

from spineworks.humdrum import HumdrumDocument


class RecordKind(Enum):
    GLOBAL = "global"
    EMPTY = "empty"
    BARLINE = "barline"
    INTERPRETATION = "interpretation"
    LOCAL_COMMENT = "local_comment"
    DATA = "data"


@dataclass(frozen=True)
class SpineRecord:
    line_number: int
    text: str
    kind: RecordKind
    fields: tuple[str, ...]

    @property
    def spine_count(self) -> int | None:
        if self.kind in {RecordKind.GLOBAL, RecordKind.EMPTY}:
            return None
        return len(self.fields)


def read_records(text: str) -> tuple[SpineRecord, ...]:
    """Read every line without modifying tokens or tab separators."""
    records: list[SpineRecord] = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            kind = RecordKind.EMPTY
        elif line.startswith("!!"):
            kind = RecordKind.GLOBAL
        elif line.startswith("="):
            kind = RecordKind.BARLINE
        elif line.startswith("*"):
            kind = RecordKind.INTERPRETATION
        elif line.startswith("!"):
            kind = RecordKind.LOCAL_COMMENT
        else:
            kind = RecordKind.DATA

        fields = () if kind in {RecordKind.GLOBAL, RecordKind.EMPTY} else tuple(line.split("\t"))
        records.append(
            SpineRecord(
                line_number=line_number,
                text=line,
                kind=kind,
                fields=fields,
            )
        )

    return tuple(records)

    return tuple(records)


@dataclass(frozen=True)
class SpineIdentity:
    root_column: int
    spine_type: str
    instrument: str
    part: str
    staff: str


@dataclass(frozen=True)
class SpineBranch:
    identity: SpineIdentity
    path: tuple[int, ...] = ()
    opening_lines: tuple[int, ...] = ()


@dataclass(frozen=True)
class TracedRecord:
    record: SpineRecord
    branches: tuple[SpineBranch, ...]


@dataclass(frozen=True)
class StructureIssue:
    line_number: int
    message: str


@dataclass(frozen=True)
class SpineTrace:
    records: tuple[TracedRecord, ...]
    issue: StructureIssue | None


def _merge_branch_group(
    branches: tuple[SpineBranch, ...],
) -> SpineBranch | None:
    """Merge a complete set of descendants back into their ancestor."""
    if len(branches) < 2:
        return None

    identity = branches[0].identity
    if any(branch.identity != identity for branch in branches):
        return None

    paths = [branch.path for branch in branches]
    if len(set(paths)) != len(paths):
        return None

    common = paths[0]
    for path in paths[1:]:
        while path[: len(common)] != common:
            common = common[:-1]

    relative_paths = {path[len(common) :] for path in paths}
    if () in relative_paths:
        return None

    # Reduce complete sibling pairs until only the common ancestor remains.
    while relative_paths != {()}:
        deepest = max(relative_paths, key=len)
        parent = deepest[:-1]
        left = parent + (0,)
        right = parent + (1,)
        if left not in relative_paths or right not in relative_paths:
            return None
        relative_paths.remove(left)
        relative_paths.remove(right)
        relative_paths.add(parent)

    return SpineBranch(
        identity=identity,
        path=common,
        opening_lines=branches[0].opening_lines[: len(common)],
    )


def trace_spines(document: HumdrumDocument) -> SpineTrace:
    """Track branches without modifying the document."""
    records = read_records(document.to_text())
    header = document.header
    types = document.spine_types

    def header_fields(line_number: int | None) -> list[str]:
        if line_number is None:
            return ["*"] * len(types)
        return document.fields(line_number)

    names = header_fields(header.instrument_name_line)
    parts = header_fields(header.part_line)
    staffs = header_fields(header.staff_line)

    active: tuple[SpineBranch, ...] = tuple(
        SpineBranch(
            SpineIdentity(
                root_column=column,
                spine_type=spine_type,
                instrument=names[column][3:] if names[column].startswith('*I"') else "",
                part=parts[column] if parts[column].startswith("*part") else "",
                staff=staffs[column] if staffs[column].startswith("*staff") else "",
            )
        )
        for column, spine_type in enumerate(types)
    )
    traced: list[TracedRecord] = []

    def stop(record: SpineRecord, message: str) -> SpineTrace:
        return SpineTrace(
            records=tuple(traced),
            issue=StructureIssue(record.line_number, message),
        )

    for record in records:
        if record.line_number <= header.exclusive_line:
            traced.append(TracedRecord(record, ()))
            continue

        traced.append(TracedRecord(record, active))

        if record.kind in {RecordKind.GLOBAL, RecordKind.EMPTY}:
            continue

        if record.spine_count != len(active):
            return stop(
                record,
                f"Nieprawidłowa liczba spinów: oczekiwano {len(active)}, "
                f"znaleziono {record.spine_count}.",
            )

        if any(field == "" for field in record.fields):
            return stop(record, "Puste pole w rekordzie spinów.")

        if record.kind is not RecordKind.INTERPRETATION:
            continue

        unsupported = next(
            (token for token in record.fields if token in {"*x", "*+"}),
            None,
        )
        if unsupported is not None:
            return stop(record, f"Nieobsługiwany token: {unsupported}.")

        if "*-" in record.fields:
            remaining = records[record.line_number :]
            has_following_record = any(
                candidate.kind not in {RecordKind.GLOBAL, RecordKind.EMPTY}
                for candidate in remaining
            )
            if not all(token == "*-" for token in record.fields) or has_following_record:
                return stop(record, "Nieobsługiwane zakończenie spinu przed końcem utworu.")
            active = ()
            continue

        following: list[SpineBranch] = []
        column = 0

        while column < len(active):
            token = record.fields[column]
            branch = active[column]

            if token == "*^":
                opening_lines = branch.opening_lines + (record.line_number,)
                following.extend(
                    (
                        SpineBranch(
                            identity=branch.identity,
                            path=branch.path + (0,),
                            opening_lines=opening_lines,
                        ),
                        SpineBranch(
                            identity=branch.identity,
                            path=branch.path + (1,),
                            opening_lines=opening_lines,
                        ),
                    )
                )
                column += 1
                continue

            if token == "*v":
                end = column + 1
                while end < len(active) and record.fields[end] == "*v":
                    end += 1

                merged = _merge_branch_group(active[column:end])
                if merged is None:
                    return stop(
                        record,
                        "Nieprawidłowe scalenie: tokeny *v muszą obejmować "
                        "komplet gałęzi jednego rozdwojenia.",
                    )
                following.append(merged)
                column = end
                continue

            following.append(branch)
            column += 1

        active = tuple(following)

    return SpineTrace(tuple(traced), None)

    return SpineTrace(tuple(traced), None)


@dataclass(frozen=True)
class SplitIssue:
    code: str
    line_number: int
    measure: str | None
    identities: tuple[SpineIdentity, ...]
    related_lines: tuple[int, ...]
    message: str


def find_split_issues(trace: SpineTrace) -> tuple[SplitIssue, ...]:
    """Check project placement rules within the safely traced range."""
    issues: list[SplitIssue] = []
    measure: str | None = None
    measure_rows: list[TracedRecord] = []

    def check_measure(rows: list[TracedRecord], label: str | None) -> None:
        data_lines: list[int] = []
        previous_merge_column: int | None = None
        previous_merge_line: int | None = None

        for position, row in enumerate(rows):
            record = row.record
            if record.kind is RecordKind.DATA:
                data_lines.append(record.line_number)
                previous_merge_column = None
                previous_merge_line = None
                continue

            if record.kind is not RecordKind.INTERPRETATION:
                continue

            openings = tuple(
                branch.identity
                for token, branch in zip(record.fields, row.branches, strict=True)
                if token == "*^"
            )
            if openings and data_lines:
                issues.append(
                    SplitIssue(
                        code="late_split",
                        line_number=record.line_number,
                        measure=label,
                        identities=tuple(dict.fromkeys(openings)),
                        related_lines=tuple(data_lines),
                        message="Rozdwojenie po rekordach danych w tym takcie.",
                    )
                )

            closing_groups: list[SpineIdentity] = []
            for column, token in enumerate(record.fields):
                if token == "*v" and (column == 0 or record.fields[column - 1] != "*v"):
                    closing_groups.append(row.branches[column].identity)

            if not closing_groups:
                continue

            identities = tuple(dict.fromkeys(closing_groups))

            if len(closing_groups) == 1:
                current_column = closing_groups[0].root_column

                if previous_merge_column is not None and current_column > previous_merge_column:
                    issues.append(
                        SplitIssue(
                            code="merge_order",
                            line_number=record.line_number,
                            measure=label,
                            identities=identities,
                            related_lines=(
                                (previous_merge_line,) if previous_merge_line is not None else ()
                            ),
                            message="Scalenia powinny następować od prawej do lewej.",
                        )
                    )

                previous_merge_column = current_column
                previous_merge_line = record.line_number
            else:
                # First separate ambiguous multi-group closing rows.
                previous_merge_column = None
                previous_merge_line = None

            if len(closing_groups) > 1:
                issues.append(
                    SplitIssue(
                        code="multiple_merges",
                        line_number=record.line_number,
                        measure=label,
                        identities=identities,
                        related_lines=(),
                        message="Niezależne scalenia wymagają osobnych linii.",
                    )
                )

            following_data: list[int] = []
            following_interpretations: list[int] = []

            for following in rows[position + 1 :]:
                candidate = following.record

                if candidate.kind is RecordKind.DATA:
                    following_data.append(candidate.line_number)
                elif candidate.kind is RecordKind.INTERPRETATION:
                    # Further merges belong to the final closing block.
                    is_merge_row = "*v" in candidate.fields and all(
                        token in {"*", "*v"} for token in candidate.fields
                    )
                    is_final_termination = all(token == "*-" for token in candidate.fields)
                    if not is_merge_row and not is_final_termination:
                        following_interpretations.append(candidate.line_number)

            if following_data:
                issues.append(
                    SplitIssue(
                        code="early_merge",
                        line_number=record.line_number,
                        measure=label,
                        identities=identities,
                        related_lines=tuple(following_data),
                        message="Scalenie przed końcem taktu: po *v występują dane.",
                    )
                )

            if following_interpretations:
                issues.append(
                    SplitIssue(
                        code="interpretation_after_merge",
                        line_number=record.line_number,
                        measure=label,
                        identities=identities,
                        related_lines=tuple(following_interpretations),
                        message="Po scaleniu występują interpretacje poza blokiem zamknięć.",
                    )
                )

    for row in trace.records:
        # The record where tracing failed must not be interpreted further.
        if trace.issue is not None and row.record.line_number >= trace.issue.line_number:
            break

        if row.record.kind is RecordKind.BARLINE:
            check_measure(measure_rows, measure)
            measure_rows = []
            match = next(
                (match for token in row.record.fields if (match := re.match(r"^=+(\d+)", token))),
                None,
            )
            measure = match.group(1) if match is not None else None
        else:
            measure_rows.append(row)

    check_measure(measure_rows, measure)
    return tuple(issues)


@dataclass(frozen=True)
class ProblemRange:
    measure: str | None
    start_line: int
    end_line: int
    issues: tuple[SplitIssue, ...]
    editable_identities: tuple[SpineIdentity, ...]
    helper_identities: tuple[SpineIdentity, ...]


def group_split_issues(
    trace: SpineTrace,
    issues: tuple[SplitIssue, ...],
) -> tuple[ProblemRange, ...]:
    """Group issues by physical measure boundaries, not measure labels."""
    grouped: dict[tuple[int, int], list[SplitIssue]] = {}
    rows = trace.records

    for issue in issues:
        start_line = next(
            (
                row.record.line_number
                for row in reversed(rows)
                if row.record.kind is RecordKind.BARLINE
                and row.record.line_number <= issue.line_number
            ),
            1,
        )
        end_line = next(
            (
                row.record.line_number
                for row in rows
                if row.record.kind is RecordKind.BARLINE
                and row.record.line_number > issue.line_number
            ),
            rows[-1].record.line_number if rows else issue.line_number,
        )
        grouped.setdefault((start_line, end_line), []).append(issue)

    ranges: list[ProblemRange] = []

    for (start_line, end_line), range_issues in sorted(grouped.items()):
        editable = {identity for issue in range_issues for identity in issue.identities}
        involved = set(editable)

        for row in rows:
            # The final barline is context; the next measure starts there.
            if not start_line <= row.record.line_number < end_line:
                continue

            if row.record.kind is RecordKind.INTERPRETATION:
                for token, branch in zip(
                    row.record.fields,
                    row.branches,
                    strict=True,
                ):
                    if token in {"*^", "*v"}:
                        involved.add(branch.identity)

        ranges.append(
            ProblemRange(
                measure=range_issues[0].measure,
                start_line=start_line,
                end_line=end_line,
                issues=tuple(range_issues),
                editable_identities=tuple(
                    sorted(editable, key=lambda identity: identity.root_column)
                ),
                helper_identities=tuple(
                    sorted(
                        involved - editable,
                        key=lambda identity: identity.root_column,
                    )
                ),
            )
        )

    return tuple(ranges)


@dataclass(frozen=True)
class MeasureSlice:
    measure: str | None
    start_line: int
    end_line: int
    collapsed: bool


def build_measure_view(
    trace: SpineTrace,
    problem: ProblemRange,
    all_issues: tuple[SplitIssue, ...],
) -> tuple[MeasureSlice, ...]:
    """Plan visible measures and foldable intermediate measures."""
    rows = trace.records
    rows_by_line = {row.record.line_number: row for row in rows}
    opening_lines: set[int] = set()

    for issue in problem.issues:
        # Ordering and separating closing rows require only the problem measure.
        if issue.code not in {"late_split", "early_merge"}:
            continue

        row = rows_by_line[issue.line_number]
        affected = set(issue.identities)

        for token, branch in zip(
            row.record.fields,
            row.branches,
            strict=True,
        ):
            if token == "*v" and branch.identity in affected:
                opening_lines.update(branch.opening_lines)
            elif token == "*^" and branch.identity in affected:
                opening_lines.add(row.record.line_number)
                opening_lines.update(branch.opening_lines)

    barlines = [row for row in rows if row.record.kind is RecordKind.BARLINE]

    def measure_start(line_number: int) -> int:
        return next(
            (
                row.record.line_number
                for row in reversed(barlines)
                if row.record.line_number <= line_number
            ),
            1,
        )

    opening_starts = {measure_start(line) for line in opening_lines}
    first_line = min(opening_starts | {problem.start_line})
    issue_lines = {issue.line_number for issue in all_issues}

    starts = [
        row.record.line_number
        for row in barlines
        if first_line <= row.record.line_number < problem.end_line
    ]
    if first_line not in starts:
        starts.insert(0, first_line)

    slices: list[MeasureSlice] = []

    for position, start_line in enumerate(starts):
        end_line = starts[position + 1] if position + 1 < len(starts) else problem.end_line
        start_row = rows_by_line.get(start_line)
        match = (
            re.match(r"^=+(\d+)", start_row.record.fields[0])
            if start_row is not None and start_row.record.kind is RecordKind.BARLINE
            else None
        )
        has_issue = any(start_line <= line < end_line for line in issue_lines)
        must_show = start_line in opening_starts or start_line == problem.start_line or has_issue

        slices.append(
            MeasureSlice(
                measure=match.group(1) if match is not None else None,
                start_line=start_line,
                end_line=end_line,
                collapsed=not must_show,
            )
        )

    return tuple(slices)
