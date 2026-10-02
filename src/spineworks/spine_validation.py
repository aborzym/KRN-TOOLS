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
    anchor_line: int | None = None


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
        self._editable_roots = {
            cell.identity.root_column for row in rows for cell in row.cells if cell.editable
        }
        self._changes: dict[tuple[int, int], str] = {}
        self._replacements: dict[int, tuple[DraftLine, ...]] = {}
        self._pending_suggestions: set[tuple[int, int]] = set()
        self._undo: list[
            tuple[
                dict[tuple[int, int], str],
                dict[int, tuple[DraftLine, ...]],
                set[tuple[int, int]],
            ]
        ] = []

    @property
    def dirty(self) -> bool:
        return bool(self._changes or self._replacements)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def pending_suggestions(self) -> tuple[tuple[int, int], ...]:
        return tuple(sorted(self._pending_suggestions))

    def _remember(self) -> None:
        self._undo.append(
            (
                self._changes.copy(),
                self._replacements.copy(),
                self._pending_suggestions.copy(),
            )
        )

    @property
    def missing_data_cells(self) -> tuple[tuple[int, int], ...]:
        missing: list[tuple[int, int]] = []

        for row_index, line in enumerate(self.rendered_lines()):
            record = read_records(line.text)[0]
            if record.kind is not RecordKind.DATA:
                continue

            for column, token in enumerate(record.fields):
                if token == "":
                    missing.append((row_index, column))

        return tuple(missing)

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

        self._remember()
        original = self._source_lines[source_line - 1].split("\t")[source_column]

        if token == original:
            self._changes.pop(key, None)
        else:
            self._changes[key] = token

        return True

    def undo(self) -> bool:
        if not self._undo:
            return False

        (
            self._changes,
            self._replacements,
            self._pending_suggestions,
        ) = self._undo.pop()
        return True

    def separate_merges(self, source_line: int) -> bool:
        if not any(line == source_line for line, _ in self._editable_cells):
            raise ValueError("Ta linia nie zawiera edytowalnych pól.")

        try:
            current_line = self.rendered_index(source_line) + 1
        except ValueError:
            if source_line in self._replacements:
                return False
            raise

        candidate = HumdrumDocument.from_text(self.to_text())
        replacement = separate_merge_rows(candidate, current_line)

        if len(replacement.lines) < 2:
            return False

        groups = {identity.root_column for identity in replacement.identities}
        if not groups <= self._editable_roots:
            raise ValueError("Scalenie obejmuje grupę tylko do odczytu.")

        new_rows = tuple(
            DraftLine(
                source_line=None,
                text=line,
                description=f"nowe: {identity.instrument or identity.spine_type}",
                anchor_line=current_line,
            )
            for identity, line in zip(
                replacement.identities,
                replacement.lines,
                strict=True,
            )
        )

        return self._apply_candidate_replacements(((current_line, new_rows),))

    def _apply_candidate_replacements(
        self,
        replacements: tuple[tuple[int, tuple[DraftLine, ...]], ...],
    ) -> bool:
        if not replacements:
            return False

        rendered = self.rendered_lines()
        composed, included = self._compose_replacements(replacements)
        updates = dict(replacements)
        preview: list[DraftLine] = []

        for number, line in enumerate(rendered, start=1):
            if number in updates:
                preview.extend(
                    self._map_candidate_line(candidate, rendered) for candidate in updates[number]
                )
            else:
                preview.append(line)

        preview_lines = tuple(preview)
        pending = self._remap_pending_suggestions(preview_lines)

        if preview_lines == rendered and pending == self._pending_suggestions:
            return False

        changes = {key: token for key, token in self._changes.items() if key[0] not in included}

        self._remember()
        self._changes = changes
        self._replacements = composed
        self._pending_suggestions = pending
        return True

    def _remap_pending_suggestions(
        self,
        rendered: tuple[DraftLine, ...],
    ) -> set[tuple[int, int]]:
        if not self._pending_suggestions:
            return set()

        def traced_rows(
            lines: tuple[DraftLine, ...],
        ) -> dict[int, TracedRecord]:
            texts: list[str] = []
            for line in lines:
                record = read_records(line.text)[0]
                if record.kind is RecordKind.DATA:
                    texts.append("\t".join(token or "." for token in record.fields))
                else:
                    texts.append(line.text)

            trace = trace_spines(HumdrumDocument(texts, self._trailing_newline))
            records = {row.record.line_number: row for row in trace.records}
            result: dict[int, TracedRecord] = {}

            for number, line in enumerate(lines, start=1):
                if line.source_line is None:
                    continue
                if trace.issue is not None and number >= trace.issue.line_number:
                    break
                if number in records:
                    result[line.source_line] = records[number]

            return result

        before = traced_rows(self.rendered_lines())
        after = traced_rows(rendered)
        mapped: set[tuple[int, int]] = set()

        for source_line, column in self._pending_suggestions:
            previous = before.get(source_line)
            current = after.get(source_line)
            if previous is None or current is None:
                raise HumdrumError(
                    f"Linia {source_line}: nie można zachować "
                    "powiązania niezatwierdzonej propozycji."
                )

            branch = previous.branches[column]
            token = previous.record.fields[column]
            candidates = [
                index
                for index, candidate in enumerate(current.branches)
                if candidate.identity == branch.identity
                and (
                    candidate.path[: len(branch.path)] == branch.path
                    or branch.path[: len(candidate.path)] == candidate.path
                )
                and current.record.fields[index] == token
            ]
            if not candidates:
                raise HumdrumError(
                    f"Linia {source_line}: propozycja utraciłaby powiązanie z właściwym głosem."
                )

            destination = min(
                candidates,
                key=lambda index: (
                    abs(len(current.branches[index].path) - len(branch.path)),
                    index,
                ),
            )
            mapped.add((source_line, destination))

        return mapped

    def _compose_replacements(
        self,
        replacements: tuple[tuple[int, tuple[DraftLine, ...]], ...],
    ) -> tuple[dict[int, tuple[DraftLine, ...]], set[int]]:
        rendered = self.rendered_lines()
        updates = dict(replacements)

        if len(updates) != len(replacements):
            raise ValueError("Operacja powtarza numer zastępowanego wiersza.")

        if any(not 1 <= number <= len(rendered) for number in updates):
            raise ValueError("Zastępowany wiersz wykracza poza bieżący szkic.")

        composed = self._replacements.copy()
        included_source_lines: set[int] = set()
        position = 0

        for source_line, original in enumerate(self._source_lines, start=1):
            previous = self._replacements.get(source_line)
            count = len(previous) if previous is not None else 1
            current = rendered[position : position + count]
            physical_numbers = range(position + 1, position + count + 1)

            if not any(number in updates for number in physical_numbers):
                position += count
                continue

            combined: list[DraftLine] = []

            for number, line in zip(
                physical_numbers,
                current,
                strict=True,
            ):
                if line.source_line is not None:
                    included_source_lines.add(line.source_line)

                replacement = updates.get(number)
                if replacement is None:
                    combined.append(line)
                    continue

                for candidate_line in replacement:
                    mapped = self._map_candidate_line(candidate_line, rendered)
                    combined.append(mapped)
                    if mapped.source_line is not None:
                        included_source_lines.add(mapped.source_line)

            baseline = (DraftLine(source_line=source_line, text=original),)
            result = tuple(combined)

            if result == baseline:
                composed.pop(source_line, None)
            else:
                composed[source_line] = result

            position += count

        return composed, included_source_lines

    def _map_candidate_line(
        self,
        line: DraftLine,
        rendered: tuple[DraftLine, ...],
    ) -> DraftLine:
        def original_line(number: int) -> DraftLine:
            if not 1 <= number <= len(rendered):
                raise ValueError("Numer linii wykracza poza bieżący szkic.")
            return rendered[number - 1]

        source_line = None
        anchor_line = None
        description = line.description

        if line.source_line is not None:
            previous = original_line(line.source_line)
            source_line = previous.source_line
            anchor_line = previous.anchor_line
            if not description:
                description = previous.description

        if line.anchor_line is not None:
            previous_anchor = original_line(line.anchor_line)
            anchor_line = (
                previous_anchor.source_line
                if previous_anchor.source_line is not None
                else previous_anchor.anchor_line
            )

        return DraftLine(
            source_line=source_line,
            text=line.text,
            description=description,
            anchor_line=anchor_line,
        )

    def rendered_index(self, source_line: int) -> int:
        matching = [
            index
            for index, line in enumerate(self.rendered_lines())
            if line.source_line == source_line
        ]

        if not matching:
            raise ValueError(
                f"Linia źródłowa {source_line} została usunięta lub zastąpiona nowymi wierszami."
            )

        if len(matching) != 1:
            raise ValueError(f"Linia źródłowa {source_line} występuje w szkicu więcej niż raz.")

        return matching[0]

    def move_merge(
        self,
        source_line: int,
        root_column: int,
    ) -> "MergeMoveProposal | None":
        if root_column not in self._editable_roots or not any(
            line == source_line for line, _ in self._editable_cells
        ):
            raise ValueError("Scalenie należy do grupy tylko do odczytu.")

        rendered = self.rendered_lines()
        current_line = self.rendered_index(source_line) + 1
        candidate = HumdrumDocument.from_text(self.to_text())
        proposal = prepare_merge_move(
            candidate,
            current_line,
            root_column,
        )

        proposed_cells: list[tuple[int, int]] = []
        for number, column in proposal.proposed_cells:
            original_number = rendered[number - 1].source_line
            if original_number is None:
                raise HumdrumError("Pole do uzupełnienia nie ma numeru źródłowego.")
            proposed_cells.append((original_number, column))

        if not self._apply_candidate_replacements(proposal.replacements):
            return None

        return MergeMoveProposal(
            replacements=proposal.replacements,
            proposed_cells=tuple(proposed_cells),
        )

    def join_reopenings(
        self,
        source_line: int,
        root_column: int,
    ) -> "MergeReopeningProposal | None":
        if root_column not in self._editable_roots or not any(
            line == source_line for line, _ in self._editable_cells
        ):
            raise ValueError("Scalenie należy do grupy tylko do odczytu.")

        rendered = self.rendered_lines()
        current_line = self.rendered_index(source_line) + 1
        candidate = HumdrumDocument.from_text(self.to_text())
        proposal = prepare_merge_reopenings(
            candidate,
            current_line,
            root_column,
        )

        proposed_cells: list[tuple[int, int]] = []
        for number, column in proposal.proposed_cells:
            original_number = rendered[number - 1].source_line
            if original_number is None:
                raise HumdrumError("Pole do uzupełnienia nie ma numeru źródłowego.")
            proposed_cells.append((original_number, column))

        if not self._apply_candidate_replacements(proposal.replacements):
            return None

        return MergeReopeningProposal(
            replacements=proposal.replacements,
            proposed_cells=tuple(proposed_cells),
        )

    def move_split(
        self,
        source_line: int,
        root_column: int,
    ) -> "SplitMoveProposal | None":
        if root_column not in self._editable_roots or not any(
            line == source_line for line, _ in self._editable_cells
        ):
            raise ValueError("Otwarcie należy do grupy tylko do odczytu.")

        rendered = self.rendered_lines()
        current_line = self.rendered_index(source_line) + 1
        candidate = HumdrumDocument.from_text(self.to_text())
        proposal = prepare_split_move(
            candidate,
            current_line,
            root_column,
        )

        if not proposal.replacements:
            return None

        proposed_cells: list[tuple[int, int]] = []
        for number, column in proposal.proposed_cells:
            original_number = rendered[number - 1].source_line
            if original_number is None:
                raise HumdrumError("Pole do uzupełnienia nie ma numeru źródłowego.")
            proposed_cells.append((original_number, column))

        if not self._apply_candidate_replacements(proposal.replacements):
            return None

        return SplitMoveProposal(
            replacements=proposal.replacements,
            proposed_cells=tuple(proposed_cells),
        )

    def edit_rendered_token(
        self,
        row_index: int,
        column: int,
        token: str,
    ) -> bool:
        rendered = self.rendered_lines()
        if not 0 <= row_index < len(rendered):
            raise ValueError("Wiersz szkicu nie istnieje.")

        if any(character in token for character in ("\t", "\n", "\r")):
            raise ValueError("Jedno pole nie może zawierać tabulatora ani nowej linii.")

        line = rendered[row_index]
        record = read_records(line.text)[0]
        if record.kind in {RecordKind.GLOBAL, RecordKind.EMPTY}:
            raise ValueError("Ten wiersz nie zawiera edytowalnych pól spinów.")

        fields = list(record.fields)
        if not 0 <= column < len(fields):
            raise ValueError("Kolumna szkicu nie istnieje.")

        # Empty data cells are temporarily represented by dots solely
        # to trace column identities. The actual draft remains unchanged.
        tracing_lines: list[str] = []
        for current in rendered:
            current_record = read_records(current.text)[0]
            if current_record.kind is RecordKind.DATA:
                tracing_lines.append("\t".join(value or "." for value in current_record.fields))
            else:
                tracing_lines.append(current.text)

        tracing_document = HumdrumDocument(
            tracing_lines,
            self._trailing_newline,
        )
        trace = trace_spines(tracing_document)
        current_line = row_index + 1

        if trace.issue is not None and trace.issue.line_number <= current_line:
            raise HumdrumError(
                f"Nie można bezpiecznie ustalić instrumentu tego pola: {trace.issue.message}"
            )

        traced_row = next(row for row in trace.records if row.record.line_number == current_line)
        root = traced_row.branches[column].identity.root_column
        if root not in self._editable_roots:
            raise ValueError("To pole należy do grupy tylko do odczytu.")

        if fields[column] == token:
            return False

        # Locate the replacement by its position, not by matching its text.
        position = 0
        for source_line in range(1, len(self._source_lines) + 1):
            replacement = self._replacements.get(source_line)

            if replacement is None:
                if position == row_index:
                    return self.edit_token(source_line, column, token)
                position += 1
                continue

            if position <= row_index < position + len(replacement):
                replacement_index = row_index - position
                fields[column] = token

                updated = list(replacement)
                updated[replacement_index] = DraftLine(
                    source_line=line.source_line,
                    text="\t".join(fields),
                    description=line.description,
                    anchor_line=line.anchor_line,
                )

                self._remember()
                self._replacements[source_line] = tuple(updated)
                return True

            position += len(replacement)

        raise ValueError("Nie odnaleziono wiersza szkicu.")

    def propose_token(
        self,
        source_line: int,
        source_column: int,
        token: str,
    ) -> bool:
        if (
            not token.strip()
            or any(character in token for character in ("\t", "\n", "\r"))
            or read_records(token)[0].kind is not RecordKind.DATA
        ):
            raise ValueError("Propozycja musi być jednym tokenem danych.")

        rendered = self.rendered_lines()
        matching = [index for index, line in enumerate(rendered) if line.source_line == source_line]
        if len(matching) != 1:
            raise ValueError("Nie można jednoznacznie odnaleźć linii propozycji.")

        row_index = matching[0]
        record = read_records(rendered[row_index].text)[0]
        if record.kind is not RecordKind.DATA:
            raise ValueError("Propozycje wypełnienia dotyczą tylko danych.")

        if not 0 <= source_column < len(record.fields):
            raise ValueError("Kolumna propozycji nie istnieje.")

        current = record.fields[source_column]
        if current not in {"", token}:
            return False

        key = (source_line, source_column)
        changed = self.edit_rendered_token(row_index, source_column, token)

        if not changed:
            if key in self._pending_suggestions:
                return False
            self._remember()

        self._pending_suggestions.add(key)
        return True

    def propose_tokens(
        self,
        tokens: tuple[tuple[int, int, str], ...],
    ) -> bool:
        keys = [(line, column) for line, column, _ in tokens]
        if len(set(keys)) != len(keys):
            raise ValueError("Grupa propozycji powtarza to samo pole.")

        if not tokens:
            return False

        history_start = len(self._undo)
        self._remember()
        changed = False

        try:
            for source_line, source_column, token in tokens:
                if self.propose_token(source_line, source_column, token):
                    changed = True
        except (ValueError, HumdrumError):
            (
                self._changes,
                self._replacements,
                self._pending_suggestions,
            ) = self._undo[history_start]
            del self._undo[history_start:]
            raise

        if not changed:
            del self._undo[history_start:]
            return False

        # Cała grupa ma jeden wspólny stan sprzed operacji.
        del self._undo[history_start + 1 :]
        return True

    def approve_suggestions(self) -> bool:
        if not self._pending_suggestions:
            return False

        self._remember()
        self._pending_suggestions.clear()
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
    PENDING = "pending"
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
    """Validate a source range after mapping it to the current draft."""
    from spineworks.spine_rhythm import trace_rhythm

    if start_line < 1 or end_line < start_line:
        raise ValueError("Nieprawidłowy zakres linii do kontroli.")

    rendered = draft.rendered_lines()
    positions: list[int] = []

    for position, line in enumerate(rendered, start=1):
        origin = line.source_line if line.source_line is not None else line.anchor_line
        if origin is not None and start_line <= origin <= end_line:
            positions.append(position)

    if not positions:
        raise ValueError("Zakres źródłowy nie ma wierszy w bieżącym szkicu.")

    current_start = min(positions)
    current_end = max(positions)

    def location(current_line: int) -> str:
        line = rendered[current_line - 1]
        if line.source_line is not None:
            return f"Linia {line.source_line}"
        return line.description or "Nowy wiersz"

    missing_messages = tuple(
        f"{location(row_index + 1)}: Puste pole danych "
        f"w kolumnie {column + 1} — wymaga uzupełnienia."
        for row_index, column in draft.missing_data_cells
        if current_start <= row_index + 1 <= current_end
    )

    if missing_messages:
        return DraftValidation(
            state=ValidationState.ERROR,
            messages=missing_messages,
        )

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
    if trace.issue is not None and trace.issue.line_number <= current_end:
        messages.append(f"{location(trace.issue.line_number)}: {trace.issue.message}")

    for issue in find_split_issues(trace):
        if current_start <= issue.line_number <= current_end:
            messages.append(f"{location(issue.line_number)}: {issue.message}")

    if not messages:
        rhythm = trace_rhythm(document)
        if rhythm.issue is not None and rhythm.issue.line_number <= current_end:
            messages.append(f"{location(rhythm.issue.line_number)}: {rhythm.issue.message}")

    if messages:
        return DraftValidation(
            state=ValidationState.ERROR,
            messages=tuple(messages),
        )

    pending_messages = tuple(
        f"Linia {source_line} | kolumna {column + 1}: propozycja oczekuje na zatwierdzenie."
        for source_line, column in draft.pending_suggestions
        if start_line <= source_line <= end_line
    )

    if pending_messages:
        return DraftValidation(
            state=ValidationState.PENDING,
            messages=pending_messages,
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


@dataclass(frozen=True)
class MergeMovePlan:
    source_line: int
    identity: SpineIdentity
    branch_count: int
    end_barline: int
    closing_block_start: int


def plan_merge_move(
    document: HumdrumDocument,
    source_line: int,
    root_column: int,
) -> MergeMovePlan:
    """Locate a selected merge and the measure's final closing block."""
    trace = trace_spines(document)
    if trace.issue is not None:
        raise HumdrumError(
            f"Nie można zaplanować przeniesienia: linia "
            f"{trace.issue.line_number}: {trace.issue.message}"
        )

    selected = next(
        (row for row in trace.records if row.record.line_number == source_line),
        None,
    )
    if selected is None:
        raise ValueError("Linia scalenia nie istnieje.")

    fields = selected.record.fields
    if selected.record.kind is not RecordKind.INTERPRETATION or any(
        token not in {"*", "*v"} for token in fields
    ):
        raise HumdrumError("Linia przenoszonego scalenia musi zawierać tylko *v i neutralne *.")

    groups: list[tuple[int, int]] = []
    column = 0
    while column < len(fields):
        if fields[column] != "*v":
            column += 1
            continue

        end = column + 1
        while end < len(fields) and fields[end] == "*v":
            end += 1

        if selected.branches[column].identity.root_column == root_column:
            groups.append((column, end))
        column = end

    if len(groups) != 1:
        raise HumdrumError("Wskaż jedno scalenie wybranego spinu w tej linii.")

    start, end = groups[0]
    boundary = next(
        (
            row
            for row in trace.records
            if row.record.line_number > source_line and row.record.kind is RecordKind.BARLINE
        ),
        None,
    )
    if boundary is None:
        raise HumdrumError("Brak końcowej kreski taktu; ten przypadek wymaga osobnej obsługi.")

    closing_start = boundary.record.line_number
    between = [
        row
        for row in trace.records
        if source_line < row.record.line_number < boundary.record.line_number
    ]

    for row in reversed(between):
        record = row.record

        if record.kind in {
            RecordKind.GLOBAL,
            RecordKind.LOCAL_COMMENT,
            RecordKind.EMPTY,
        }:
            continue

        is_merge_row = (
            record.kind is RecordKind.INTERPRETATION
            and "*v" in record.fields
            and all(token in {"*", "*v"} for token in record.fields)
        )
        if is_merge_row:
            closing_start = record.line_number
            continue

        break

    return MergeMovePlan(
        source_line=source_line,
        identity=selected.branches[start].identity,
        branch_count=end - start,
        end_barline=boundary.record.line_number,
        closing_block_start=closing_start,
    )


@dataclass(frozen=True)
class ExtendedRow:
    source_line: int
    fields: tuple[str, ...]
    proposed_columns: tuple[int, ...]


def prepare_merge_extension(
    document: HumdrumDocument,
    plan: MergeMovePlan,
) -> tuple[ExtendedRow, ...]:
    """Propose extra branch fields before the final closing block."""
    trace = trace_spines(document)
    if trace.issue is not None:
        raise HumdrumError(
            f"Nie można rozszerzyć gałęzi: linia {trace.issue.line_number}: {trace.issue.message}"
        )

    opening_row = next(row for row in trace.records if row.record.line_number == plan.source_line)
    fields = opening_row.record.fields
    groups: list[tuple[int, int]] = []
    column = 0

    while column < len(fields):
        if fields[column] != "*v":
            column += 1
            continue

        end = column + 1
        while end < len(fields) and fields[end] == "*v":
            end += 1

        if opening_row.branches[column].identity == plan.identity:
            groups.append((column, end))
        column = end

    if len(groups) != 1:
        raise HumdrumError("Plan nie wskazuje jednoznacznego scalenia.")

    start, end = groups[0]
    merged = _merge_branch_group(opening_row.branches[start:end])
    if merged is None or end - start != plan.branch_count:
        raise HumdrumError("Struktura scalenia nie odpowiada planowi.")

    additions = plan.branch_count - 1
    extended: list[ExtendedRow] = []

    for row in trace.records:
        record = row.record
        if not plan.source_line < record.line_number < plan.closing_block_start:
            continue

        if record.kind in {RecordKind.GLOBAL, RecordKind.EMPTY}:
            continue

        matching = [index for index, branch in enumerate(row.branches) if branch == merged]
        if len(matching) != 1:
            raise HumdrumError(
                f"Linia {record.line_number}: gałąź zmieniła strukturę przed miejscem docelowym."
            )
        column = matching[0]
        token = record.fields[column]

        if record.kind is RecordKind.DATA:
            fill = "" if plan.identity.spine_type == "**kern" else "."
            proposed = tuple(range(column + 1, column + 1 + additions))
        elif record.kind is RecordKind.LOCAL_COMMENT:
            fill = "!"
            proposed = ()
        elif record.kind is RecordKind.INTERPRETATION:
            if token in {"*^", "*v", "*x", "*+", "*-"}:
                raise HumdrumError(
                    f"Linia {record.line_number}: kolejna operacja "
                    "strukturalna w rozszerzanej gałęzi."
                )
            # Preserve common musical settings in every extended branch.
            fill = token
            proposed = ()
        else:
            raise HumdrumError(f"Nieoczekiwany rekord w rozszerzeniu — linia {record.line_number}.")

        new_fields = list(record.fields)
        new_fields[column + 1 : column + 1] = [fill] * additions
        extended.append(
            ExtendedRow(
                source_line=record.line_number,
                fields=tuple(new_fields),
                proposed_columns=proposed,
            )
        )

    return tuple(extended)


@dataclass(frozen=True)
class ClosingRow:
    identity: SpineIdentity
    fields: tuple[str, ...]


def prepare_closing_block(
    document: HumdrumDocument,
    plan: MergeMovePlan,
) -> tuple[ClosingRow, ...]:
    """Combine the moved merge with existing final merges, right to left."""
    trace = trace_spines(document)
    if trace.issue is not None:
        raise HumdrumError(
            f"Nie można przygotować zamknięć: linia "
            f"{trace.issue.line_number}: {trace.issue.message}"
        )

    rows = {row.record.line_number: row for row in trace.records}
    selected = rows[plan.source_line]

    selected_groups: list[tuple[SpineBranch, ...]] = []
    column = 0

    while column < len(selected.record.fields):
        if selected.record.fields[column] != "*v":
            column += 1
            continue

        end = column + 1
        while end < len(selected.record.fields) and selected.record.fields[end] == "*v":
            end += 1

        group = selected.branches[column:end]
        if group[0].identity == plan.identity:
            selected_groups.append(group)
        column = end

    if len(selected_groups) != 1:
        raise HumdrumError("Nie można jednoznacznie odnaleźć przenoszonego scalenia.")

    moved_group = selected_groups[0]
    merged = _merge_branch_group(moved_group)
    if merged is None or len(moved_group) != plan.branch_count:
        raise HumdrumError("Przenoszone scalenie nie odpowiada planowi.")

    active = list(rows[plan.closing_block_start].branches)
    matches = [index for index, branch in enumerate(active) if branch == merged]
    if len(matches) != 1:
        raise HumdrumError("Przenoszona gałąź zmieniła strukturę przed końcowym blokiem.")

    insertion = matches[0]
    active[insertion : insertion + 1] = moved_group
    pending: list[tuple[SpineBranch, ...]] = [moved_group]

    for line_number in range(plan.closing_block_start, plan.end_barline):
        row = rows[line_number]
        record = row.record

        if record.kind in {
            RecordKind.GLOBAL,
            RecordKind.LOCAL_COMMENT,
            RecordKind.EMPTY,
        }:
            continue

        if record.kind is not RecordKind.INTERPRETATION or any(
            token not in {"*", "*v"} for token in record.fields
        ):
            raise HumdrumError(f"Linia {line_number}: rekord spoza końcowego bloku scaleń.")

        column = 0
        while column < len(record.fields):
            if record.fields[column] != "*v":
                column += 1
                continue

            end = column + 1
            while end < len(record.fields) and record.fields[end] == "*v":
                end += 1

            pending.append(row.branches[column:end])
            column = end

    result: list[ClosingRow] = []

    while pending:
        available: list[tuple[int, int, tuple[SpineBranch, ...]]] = []

        for operation, group in enumerate(pending):
            for start in range(len(active) - len(group) + 1):
                if tuple(active[start : start + len(group)]) == group:
                    available.append((start, operation, group))

        if not available:
            raise HumdrumError("Nie można ułożyć zamknięć bez zmiany tożsamości gałęzi.")

        start, operation, group = max(
            available,
            key=lambda candidate: candidate[0],
        )
        merged_group = _merge_branch_group(group)
        if merged_group is None:
            raise HumdrumError("Nieprawidłowa grupa w końcowym bloku scaleń.")

        fields = ["*"] * len(active)
        fields[start : start + len(group)] = ["*v"] * len(group)
        result.append(
            ClosingRow(
                identity=group[0].identity,
                fields=tuple(fields),
            )
        )

        active[start : start + len(group)] = [merged_group]
        pending.pop(operation)

    return tuple(result)


@dataclass(frozen=True)
class MergeMoveProposal:
    replacements: tuple[tuple[int, tuple[DraftLine, ...]], ...]
    proposed_cells: tuple[tuple[int, int], ...]


def prepare_merge_move(
    document: HumdrumDocument,
    source_line: int,
    root_column: int,
) -> MergeMoveProposal:
    """Prepare source-mapped replacements without modifying the document."""
    plan = plan_merge_move(document, source_line, root_column)
    extension = prepare_merge_extension(document, plan)
    closing = prepare_closing_block(document, plan)
    trace = trace_spines(document)
    rows = {row.record.line_number: row for row in trace.records}

    replacements: dict[int, tuple[DraftLine, ...]] = {}
    proposed_cells: list[tuple[int, int]] = []

    selected = rows[source_line]
    selected_fields = list(selected.record.fields)

    for column, branch in enumerate(selected.branches):
        if branch.identity.root_column == root_column and selected_fields[column] == "*v":
            selected_fields[column] = "*"

    if all(token == "*" for token in selected_fields):
        replacements[source_line] = ()
    else:
        replacements[source_line] = (
            DraftLine(
                source_line=source_line,
                text="\t".join(selected_fields),
            ),
        )

    for row in extension:
        replacements[row.source_line] = (
            DraftLine(
                source_line=row.source_line,
                text="\t".join(row.fields),
            ),
        )
        proposed_cells.extend((row.source_line, column) for column in row.proposed_columns)

    block_lines = [
        DraftLine(
            source_line=None,
            text="\t".join(row.fields),
            description=f"nowe: {row.identity.instrument or row.identity.spine_type}",
            anchor_line=plan.closing_block_start,
        )
        for row in closing
    ]

    # After all closing operations, the spine structure matches the source barline.
    final_branches = rows[plan.end_barline].branches
    comments: list[DraftLine] = []

    for line_number in range(plan.closing_block_start, plan.end_barline):
        row = rows[line_number]
        record = row.record

        if record.kind in {RecordKind.GLOBAL, RecordKind.EMPTY}:
            comments.append(
                DraftLine(
                    source_line=line_number,
                    text=record.text,
                )
            )
        elif record.kind is RecordKind.LOCAL_COMMENT:
            fields = ["!"] * len(final_branches)

            for token, branch in zip(
                record.fields,
                row.branches,
                strict=True,
            ):
                if token == "!":
                    continue

                destinations = [
                    column
                    for column, final in enumerate(final_branches)
                    if final.identity == branch.identity
                    and branch.path[: len(final.path)] == final.path
                ]
                if len(destinations) != 1:
                    raise HumdrumError(
                        f"Linia {line_number}: nie można bezpiecznie "
                        "przypisać komentarza po scaleniu."
                    )

                destination = destinations[0]
                if fields[destination] not in {"!", token}:
                    raise HumdrumError(
                        f"Linia {line_number}: różne komentarze gałęzi trafiłyby do jednego pola."
                    )
                fields[destination] = token

            comments.append(
                DraftLine(
                    source_line=line_number,
                    text="\t".join(fields),
                )
            )

        replacements[line_number] = ()

    block_lines.extend(comments)

    if plan.closing_block_start == plan.end_barline:
        block_lines.append(
            DraftLine(
                source_line=plan.end_barline,
                text=document.lines[plan.end_barline - 1],
            )
        )

    replacements[plan.closing_block_start] = tuple(block_lines)

    return MergeMoveProposal(
        replacements=tuple(sorted(replacements.items())),
        proposed_cells=tuple(proposed_cells),
    )


@dataclass(frozen=True)
class SplitMovePlan:
    source_line: int
    identity: SpineIdentity
    branch: SpineBranch
    target_line: int
    start_barline: int | None


def plan_split_move(
    document: HumdrumDocument,
    source_line: int,
    root_column: int,
) -> SplitMovePlan:
    """Znajdź miejsce otwarcia przed pierwszymi danymi taktu."""
    trace = trace_spines(document)
    if trace.issue is not None:
        raise HumdrumError(f"Linia {trace.issue.line_number}: {trace.issue.message}")

    selected = next(
        (row for row in trace.records if row.record.line_number == source_line),
        None,
    )
    if selected is None:
        raise ValueError("Linia rozdwojenia nie istnieje.")

    branches = [
        branch
        for token, branch in zip(
            selected.record.fields,
            selected.branches,
            strict=True,
        )
        if token == "*^" and branch.identity.root_column == root_column
    ]
    if len(branches) != 1:
        raise HumdrumError("Wybór nie wskazuje jednoznacznie jednego otwarcia rozdwojenia.")

    branch = branches[0]
    barlines = [
        row.record.line_number
        for row in trace.records
        if row.record.line_number < source_line and row.record.kind is RecordKind.BARLINE
    ]
    start_barline = max(barlines) if barlines else None

    candidates = [
        row
        for row in trace.records
        if (start_barline or 0) < row.record.line_number <= source_line
        and row.record.kind not in {RecordKind.GLOBAL, RecordKind.EMPTY}
    ]

    first_data = next(
        (row.record.line_number for row in candidates if row.record.kind is RecordKind.DATA),
        source_line,
    )

    # Bez poprzedniej kreski zachowujemy interpretacje nagłówka.
    lower_bound = first_data if start_barline is None else start_barline + 1

    target = next(
        (
            row.record.line_number
            for row in candidates
            if lower_bound <= row.record.line_number <= first_data and branch in row.branches
        ),
        None,
    )
    if target is None:
        raise HumdrumError(
            "Nie można przenieść otwarcia przed dane: "
            "jego gałąź powstaje dopiero po rozpoczęciu taktu."
        )

    return SplitMovePlan(
        source_line=source_line,
        identity=branch.identity,
        branch=branch,
        target_line=target,
        start_barline=start_barline,
    )


@dataclass(frozen=True)
class SplitMoveProposal:
    replacements: tuple[tuple[int, tuple[DraftLine, ...]], ...]
    proposed_cells: tuple[tuple[int, int], ...]


def prepare_split_move(
    document: HumdrumDocument,
    source_line: int,
    root_column: int,
) -> SplitMoveProposal:
    """Przygotuj przeniesienie *^ bez zmieniania dokumentu."""
    plan = plan_split_move(document, source_line, root_column)

    if plan.target_line == plan.source_line:
        return SplitMoveProposal((), ())

    trace = trace_spines(document)
    rows = {row.record.line_number: row for row in trace.records}
    replacements: dict[int, tuple[DraftLine, ...]] = {}
    proposed_cells: list[tuple[int, int]] = []

    target = rows[plan.target_line]
    target_column = target.branches.index(plan.branch)
    opening_fields = ["*"] * len(target.branches)
    opening_fields[target_column] = "*^"
    opening = DraftLine(
        source_line=None,
        text="\t".join(opening_fields),
        description=(f"nowe: otwarcie {plan.identity.instrument or plan.identity.spine_type}"),
        anchor_line=plan.target_line,
    )

    for line_number in range(plan.target_line, plan.source_line):
        row = rows[line_number]
        record = row.record

        if record.kind in {RecordKind.GLOBAL, RecordKind.EMPTY}:
            continue

        matching = [column for column, branch in enumerate(row.branches) if branch == plan.branch]
        if len(matching) != 1:
            raise HumdrumError(
                f"Linia {line_number}: gałąź zmieniła strukturę przed pierwotnym otwarciem."
            )

        column = matching[0]
        fields = list(record.fields)

        if record.kind is RecordKind.DATA:
            fill = "" if plan.identity.spine_type == "**kern" else "."
            proposed_cells.append((line_number, column + 1))
        elif record.kind is RecordKind.LOCAL_COMMENT:
            fill = "!"
        elif record.kind is RecordKind.INTERPRETATION:
            fill = fields[column]
            if fill in {"*^", "*v", "*x", "*+", "*-"}:
                raise HumdrumError(
                    f"Linia {line_number}: operacja strukturalna w przenoszonej gałęzi."
                )
        else:
            raise HumdrumError(
                f"Linia {line_number}: nieoczekiwany rekord przed otwarciem rozdwojenia."
            )

        fields.insert(column + 1, fill)
        extended = DraftLine(
            source_line=line_number,
            text="\t".join(fields),
        )
        replacements[line_number] = (
            (opening, extended) if line_number == plan.target_line else (extended,)
        )

    selected = rows[plan.source_line]
    column = selected.branches.index(plan.branch)
    fields = list(selected.record.fields)
    fields[column] = "*"
    fields.insert(column + 1, "*")

    replacements[plan.source_line] = (
        ()
        if all(token == "*" for token in fields)
        else (
            DraftLine(
                source_line=plan.source_line,
                text="\t".join(fields),
            ),
        )
    )

    return SplitMoveProposal(
        replacements=tuple(sorted(replacements.items())),
        proposed_cells=tuple(proposed_cells),
    )


@dataclass(frozen=True)
class MergeReopeningPlan:
    source_line: int
    reopening_line: int
    identity: SpineIdentity
    branches: tuple[SpineBranch, ...]
    parent: SpineBranch


def plan_merge_reopening(
    document: HumdrumDocument,
    source_line: int,
    root_column: int,
) -> MergeReopeningPlan:
    """Znajdź ponowne otwarcie po scaleniu w tym samym takcie."""
    trace = trace_spines(document)
    if trace.issue is not None:
        raise HumdrumError(f"Linia {trace.issue.line_number}: {trace.issue.message}")

    selected = next(
        (row for row in trace.records if row.record.line_number == source_line),
        None,
    )
    if selected is None:
        raise ValueError("Linia scalenia nie istnieje.")

    columns = [
        column
        for column, branch in enumerate(selected.branches)
        if branch.identity.root_column == root_column and selected.record.fields[column] == "*v"
    ]
    if not columns:
        raise HumdrumError("Wybrany spine nie ma scalenia w tej linii.")

    start = columns[0]
    end = columns[-1] + 1
    if columns != list(range(start, end)):
        raise HumdrumError("Wybór obejmuje więcej niż jedną grupę scaleń.")

    branches = selected.branches[start:end]
    parent = _merge_branch_group(branches)
    if parent is None:
        raise HumdrumError("Nieprawidłowa grupa scalanych gałęzi.")

    # Pierwsza wersja łączy parę gałęzi bez zagnieżdżeń.
    if tuple(branch.path for branch in branches) != (
        parent.path + (0,),
        parent.path + (1,),
    ):
        raise HumdrumError(
            "Łączenie ponownych otwarć zagnieżdżonych gałęzi nie jest jeszcze obsługiwane."
        )

    for row in trace.records:
        record = row.record
        if record.line_number <= source_line:
            continue
        if record.kind is RecordKind.BARLINE:
            break
        if record.kind in {RecordKind.GLOBAL, RecordKind.EMPTY}:
            continue

        matching = [column for column, branch in enumerate(row.branches) if branch == parent]
        if len(matching) != 1:
            raise HumdrumError("Scalony głos zmienił strukturę przed ponownym otwarciem.")

        token = record.fields[matching[0]]
        if record.kind is RecordKind.INTERPRETATION:
            if token == "*^":
                return MergeReopeningPlan(
                    source_line=source_line,
                    reopening_line=record.line_number,
                    identity=parent.identity,
                    branches=branches,
                    parent=parent,
                )
            if token in {"*v", "*x", "*+", "*-"}:
                break

    raise HumdrumError("Nie znaleziono ponownego otwarcia tego głosu w tym samym takcie.")


@dataclass(frozen=True)
class MergeReopeningProposal:
    replacements: tuple[tuple[int, tuple[DraftLine, ...]], ...]
    proposed_cells: tuple[tuple[int, int], ...]


def prepare_merge_reopening(
    document: HumdrumDocument,
    source_line: int,
    root_column: int,
) -> MergeReopeningProposal:
    """Połącz rozdwojenia rozdzielone scaleniem i ponownym *^."""
    plan = plan_merge_reopening(document, source_line, root_column)
    trace = trace_spines(document)
    rows = {row.record.line_number: row for row in trace.records}
    replacements: dict[int, tuple[DraftLine, ...]] = {}
    proposed_cells: list[tuple[int, int]] = []

    closing = rows[source_line]
    fields = list(closing.record.fields)
    for column, branch in enumerate(closing.branches):
        if branch in plan.branches and fields[column] == "*v":
            fields[column] = "*"

    replacements[source_line] = (
        ()
        if all(token == "*" for token in fields)
        else (DraftLine(source_line=source_line, text="\t".join(fields)),)
    )

    for line_number in range(source_line + 1, plan.reopening_line):
        row = rows[line_number]
        record = row.record
        if record.kind in {RecordKind.GLOBAL, RecordKind.EMPTY}:
            continue

        column = row.branches.index(plan.parent)
        fields = list(record.fields)

        if record.kind is RecordKind.DATA:
            fill = "" if plan.identity.spine_type == "**kern" else "."
            proposed_cells.append((line_number, column + 1))
        elif record.kind is RecordKind.LOCAL_COMMENT:
            fill = "!"
        elif record.kind is RecordKind.INTERPRETATION:
            fill = fields[column]
            if fill in {"*^", "*v", "*x", "*+", "*-"}:
                raise HumdrumError(
                    f"Linia {line_number}: nieoczekiwana operacja "
                    "strukturalna pomiędzy rozdwojeniami."
                )
        else:
            raise HumdrumError(f"Linia {line_number}: nieoczekiwany rekord pomiędzy rozdwojeniami.")

        fields.insert(column + 1, fill)
        replacements[line_number] = (
            DraftLine(
                source_line=line_number,
                text="\t".join(fields),
            ),
        )

    reopening = rows[plan.reopening_line]
    column = reopening.branches.index(plan.parent)
    fields = list(reopening.record.fields)
    fields[column] = "*"
    fields.insert(column + 1, "*")

    replacements[plan.reopening_line] = (
        ()
        if all(token == "*" for token in fields)
        else (
            DraftLine(
                source_line=plan.reopening_line,
                text="\t".join(fields),
            ),
        )
    )

    return MergeReopeningProposal(
        replacements=tuple(sorted(replacements.items())),
        proposed_cells=tuple(proposed_cells),
    )


def prepare_merge_reopenings(
    document: HumdrumDocument,
    source_line: int,
    root_column: int,
) -> MergeReopeningProposal:
    """Połącz kolejne pary *v–*^ do końca bieżącego taktu."""
    first_plan = plan_merge_reopening(
        document,
        source_line,
        root_column,
    )
    trace = trace_spines(document)
    end_line = next(
        (
            row.record.line_number
            for row in trace.records
            if row.record.line_number > source_line and row.record.kind is RecordKind.BARLINE
        ),
        len(document.lines) + 1,
    )

    merged: dict[int, tuple[DraftLine, ...]] = {}
    proposed_cells: list[tuple[int, int]] = []
    next_allowed_line = source_line

    for row in trace.records:
        number = row.record.line_number
        if not next_allowed_line <= number < end_line:
            continue

        has_merge = any(
            token == "*v" and branch.identity.root_column == root_column
            for token, branch in zip(
                row.record.fields,
                row.branches,
                strict=True,
            )
        )
        if not has_merge:
            continue

        has_later_opening = any(
            number < later.record.line_number < end_line
            and any(
                token == "*^" and branch.identity.root_column == root_column
                for token, branch in zip(
                    later.record.fields,
                    later.branches,
                    strict=True,
                )
            )
            for later in trace.records
        )
        if not has_later_opening:
            break

        plan = plan_merge_reopening(document, number, root_column)
        if plan.identity != first_plan.identity or plan.parent.path != first_plan.parent.path:
            raise HumdrumError("Kolejna para dotyczy innego poziomu rozdwojenia.")

        proposal = prepare_merge_reopening(
            document,
            number,
            root_column,
        )
        for replaced_line, replacement in proposal.replacements:
            if replaced_line in merged:
                raise HumdrumError("Zakresy łączonych rozdwojeń nakładają się.")
            merged[replaced_line] = replacement

        proposed_cells.extend(proposal.proposed_cells)
        next_allowed_line = plan.reopening_line + 1

    return MergeReopeningProposal(
        replacements=tuple(sorted(merged.items())),
        proposed_cells=tuple(proposed_cells),
    )
