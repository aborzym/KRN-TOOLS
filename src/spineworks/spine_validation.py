import re
from dataclasses import dataclass
from enum import Enum

from spineworks.humdrum import HumdrumDocument, HumdrumError


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


@dataclass(frozen=True)
class FragmentCell:
    source_column: int
    identity: SpineIdentity
    branch_path: tuple[int, ...]
    token: str
    editable: bool


@dataclass(frozen=True)
class FragmentRow:
    source_line: int
    kind: RecordKind
    spine_count: int | None
    cells: tuple[FragmentCell, ...]
    global_text: str | None


def build_fragment_rows(
    trace: SpineTrace,
    problem: ProblemRange,
    view: tuple[MeasureSlice, ...],
) -> tuple[FragmentRow, ...]:
    """Project selected spine groups while preserving complete source rows."""
    if not view:
        return ()

    first_line = view[0].start_line
    last_line = view[-1].end_line
    editable = set(problem.editable_identities)
    visible = editable | set(problem.helper_identities)
    result: list[FragmentRow] = []

    for row in trace.records:
        record = row.record
        if not first_line <= record.line_number <= last_line:
            continue

        if record.kind in {RecordKind.GLOBAL, RecordKind.EMPTY}:
            result.append(
                FragmentRow(
                    source_line=record.line_number,
                    kind=record.kind,
                    spine_count=None,
                    cells=(),
                    global_text=record.text,
                )
            )
            continue

        if trace.issue is not None and record.line_number >= trace.issue.line_number:
            raise ValueError("Nie można wydzielić tokenów z wiersza o niepewnej strukturze.")

        cells = tuple(
            FragmentCell(
                source_column=column,
                identity=branch.identity,
                branch_path=branch.path,
                token=token,
                editable=branch.identity in editable,
            )
            for column, (token, branch) in enumerate(zip(record.fields, row.branches, strict=True))
            if branch.identity in visible
        )

        result.append(
            FragmentRow(
                source_line=record.line_number,
                kind=record.kind,
                spine_count=record.spine_count,
                cells=cells,
                global_text=None,
            )
        )

    return tuple(result)


@dataclass(frozen=True)
class DraftLine:
    source_line: int | None
    text: str
    description: str = ""


class FragmentDraft:
    """Keep token edits separate from the application's document."""

    def __init__(
        self,
        document: HumdrumDocument,
        rows: tuple[FragmentRow, ...],
    ) -> None:
        self.original_text = document.to_text()
        self._source_lines = tuple(document.lines)
        self._trailing_newline = document.trailing_newline
        self._editable_cells = {
            (row.source_line, cell.source_column)
            for row in rows
            for cell in row.cells
            if cell.editable
        }
        self._changes: dict[tuple[int, int], str] = {}
        self._replacements: dict[int, tuple[DraftLine, ...]] = {}
        self._undo: list[
            tuple[
                dict[tuple[int, int], str],
                dict[int, tuple[DraftLine, ...]],
            ]
        ] = []

    @property
    def dirty(self) -> bool:
        return bool(self._changes or self._replacements)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    def token(self, source_line: int, source_column: int) -> str:
        key = (source_line, source_column)
        if key in self._changes:
            return self._changes[key]
        return self._source_lines[source_line - 1].split("\t")[source_column]

    def edit_token(
        self,
        source_line: int,
        source_column: int,
        token: str,
    ) -> bool:
        key = (source_line, source_column)
        if key not in self._editable_cells:
            raise ValueError("To pole nie jest edytowalne.")

        if source_line in self._replacements:
            raise ValueError("Ta linia została zastąpiona nowymi wierszami.")

        if any(character in token for character in ("\t", "\n", "\r")):
            raise ValueError("Jedno pole nie może zawierać tabulatora ani nowej linii.")

        if token == self.token(source_line, source_column):
            return False

        self._undo.append((self._changes.copy(), self._replacements.copy()))
        original = self._source_lines[source_line - 1].split("\t")[source_column]

        if token == original:
            self._changes.pop(key, None)
        else:
            self._changes[key] = token

        return True

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._changes, self._replacements = self._undo.pop()
        return True

    def separate_merges(self, source_line: int) -> bool:
        if source_line in self._replacements:
            return False

        # Overlay replacements do not change source coordinates of other rows.
        source_fields = self._source_lines[source_line - 1].split("\t")
        fields = source_fields.copy()

        for column in range(len(fields)):
            fields[column] = self.token(source_line, column)

        candidate_lines = list(self._source_lines)
        candidate_lines[source_line - 1] = "\t".join(fields)
        candidate = HumdrumDocument(
            candidate_lines,
            self._trailing_newline,
        )
        replacement = separate_merge_rows(candidate, source_line)

        if len(replacement.lines) < 2:
            return False

        groups = {identity.root_column for identity in replacement.identities}
        editable_roots = {
            column
            for line, column in self._editable_cells
            if line == source_line and fields[column] == "*v"
        }
        trace = trace_spines(candidate)
        row = next(item for item in trace.records if item.record.line_number == source_line)
        permitted_roots = {row.branches[column].identity.root_column for column in editable_roots}
        if not groups <= permitted_roots:
            raise ValueError("Scalenie obejmuje grupę tylko do odczytu.")

        self._undo.append((self._changes.copy(), self._replacements.copy()))
        self._replacements[source_line] = tuple(
            DraftLine(
                source_line=None,
                text=line,
                description=f"nowe: {identity.instrument or identity.spine_type}",
            )
            for identity, line in zip(
                replacement.identities,
                replacement.lines,
                strict=True,
            )
        )

        for key in list(self._changes):
            if key[0] == source_line:
                del self._changes[key]

        return True

    def rendered_lines(self) -> tuple[DraftLine, ...]:
        result: list[DraftLine] = []

        for source_line, text in enumerate(self._source_lines, start=1):
            replacement = self._replacements.get(source_line)
            if replacement is not None:
                result.extend(replacement)
                continue

            fields = text.split("\t")
            for column in range(len(fields)):
                key = (source_line, column)
                if key in self._changes:
                    fields[column] = self._changes[key]

            result.append(
                DraftLine(
                    source_line=source_line,
                    text="\t".join(fields),
                )
            )

        return tuple(result)

    def to_text(self) -> str:
        text = "\n".join(line.text for line in self.rendered_lines())
        return text + ("\n" if self._trailing_newline else "")


class ValidationState(Enum):
    ERROR = "error"
    VALID = "valid"


@dataclass(frozen=True)
class DraftValidation:
    state: ValidationState
    messages: tuple[str, ...]


def validate_draft(
    draft: FragmentDraft,
    *,
    start_line: int,
    end_line: int,
) -> DraftValidation:
    """Validate the edited range without requiring unrelated measures to be fixed."""
    if start_line < 1 or end_line < start_line:
        raise ValueError("Nieprawidłowy zakres linii do kontroli.")

    try:
        document = HumdrumDocument.from_text(draft.to_text())
        trace = trace_spines(document)
    except HumdrumError as error:
        return DraftValidation(
            state=ValidationState.ERROR,
            messages=(str(error),),
        )

    messages: list[str] = []

    # A structural failure before the range also makes its identity uncertain.
    if trace.issue is not None and trace.issue.line_number <= end_line:
        messages.append(f"Linia {trace.issue.line_number}: {trace.issue.message}")

    for issue in find_split_issues(trace):
        if start_line <= issue.line_number <= end_line:
            messages.append(f"Linia {issue.line_number}: {issue.message}")

    if messages:
        return DraftValidation(
            state=ValidationState.ERROR,
            messages=tuple(messages),
        )

    return DraftValidation(
        state=ValidationState.VALID,
        messages=("Zakres poprawny według bieżącej kontroli.",),
    )


@dataclass(frozen=True)
class MergeReplacement:
    source_line: int
    lines: tuple[str, ...]
    identities: tuple[SpineIdentity, ...]


def separate_merge_rows(
    document: HumdrumDocument,
    source_line: int,
) -> MergeReplacement:
    """Prepare separate merge rows from right to left without changing the source."""
    if not 1 <= source_line <= len(document.lines):
        raise ValueError("Linia scalenia nie istnieje.")

    trace = trace_spines(document)
    if trace.issue is not None and trace.issue.line_number <= source_line:
        raise HumdrumError(
            f"Nie można rozdzielić scaleń: linia {trace.issue.line_number}: {trace.issue.message}"
        )

    row = next(item for item in trace.records if item.record.line_number == source_line)
    fields = row.record.fields

    if (
        row.record.kind is not RecordKind.INTERPRETATION
        or "*v" not in fields
        or any(token not in {"*", "*v"} for token in fields)
    ):
        raise HumdrumError("Wybrana linia musi zawierać wyłącznie scalenia *v i neutralne *.")

    groups: list[tuple[int, int]] = []
    column = 0

    while column < len(fields):
        if fields[column] != "*v":
            column += 1
            continue

        end = column + 1
        while end < len(fields) and fields[end] == "*v":
            end += 1

        groups.append((column, end))
        column = end

    width = len(fields)
    lines: list[str] = []
    identities: list[SpineIdentity] = []

    for start, end in reversed(groups):
        replacement = ["*"] * width
        replacement[start:end] = ["*v"] * (end - start)
        lines.append("\t".join(replacement))
        identities.append(row.branches[start].identity)
        width -= end - start - 1

    return MergeReplacement(
        source_line=source_line,
        lines=tuple(lines),
        identities=tuple(identities),
    )
