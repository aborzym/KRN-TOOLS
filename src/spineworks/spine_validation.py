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

    return SpineBranch(identity, common)


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
                following.extend(
                    (
                        SpineBranch(branch.identity, branch.path + (0,)),
                        SpineBranch(branch.identity, branch.path + (1,)),
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
