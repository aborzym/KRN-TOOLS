from dataclasses import dataclass
from enum import Enum


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
