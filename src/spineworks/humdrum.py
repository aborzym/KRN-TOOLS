from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class HumdrumError(ValueError):
    """Raised when the requested Humdrum header cannot be interpreted safely."""


@dataclass
class HeaderBlock:
    exclusive_line: int
    part_line: int | None
    staff_line: int | None
    instrument_name_line: int | None
    instrument_abbr_line: int | None

    @property
    def line_numbers(self) -> list[int]:
        candidates = [
            self.exclusive_line,
            self.part_line,
            self.staff_line,
            self.instrument_name_line,
            self.instrument_abbr_line,
        ]
        return [line for line in candidates if line is not None]


class HumdrumDocument:
    def __init__(self, lines: list[str], trailing_newline: bool = True) -> None:
        self.lines = lines
        self.trailing_newline = trailing_newline
        self.header = self._find_header()

    @classmethod
    def from_text(cls, text: str) -> HumdrumDocument:
        return cls(text.splitlines(), text.endswith(("\n", "\r")))

    @classmethod
    def from_path(cls, path: Path) -> HumdrumDocument:
        return cls.from_text(path.read_text(encoding="utf-8"))

    @property
    def spine_types(self) -> list[str]:
        return self.fields(self.header.exclusive_line)

    @property
    def spine_count(self) -> int:
        return len(self.spine_types)

    def fields(self, line_number: int) -> list[str]:
        return self.lines[line_number].split("\t")

    def replace_fields(self, line_number: int, fields: list[str]) -> None:
        if len(fields) != self.spine_count:
            raise HumdrumError(
                f"Rekord ma {len(fields)} pól zamiast wymaganych {self.spine_count}."
            )
        self.lines[line_number] = "\t".join(fields)

    def propagate_kern_assignments(self) -> bool:
        if self.header.part_line is None or self.header.staff_line is None:
            raise HumdrumError("Brak wiersza *part… albo *staff… w nagłówku pliku.")

        parts = self.fields(self.header.part_line)
        staffs = self.fields(self.header.staff_line)
        self._validate_width(parts, "*part")
        self._validate_width(staffs, "*staff")

        changed = False
        current_part: str | None = None
        current_staff: str | None = None

        for column, spine_type in enumerate(self.spine_types):
            if spine_type == "**kern":
                current_part = parts[column]
                current_staff = staffs[column]
                continue

            if current_part is None or current_staff is None:
                continue

            if parts[column] != current_part:
                parts[column] = current_part
                changed = True
            if staffs[column] != current_staff:
                staffs[column] = current_staff
                changed = True

        if changed:
            self.replace_fields(self.header.part_line, parts)
            self.replace_fields(self.header.staff_line, staffs)
        return changed

    def to_text(self) -> str:
        text = "\n".join(self.lines)
        return text + ("\n" if self.trailing_newline else "")

    def _find_header(self) -> HeaderBlock:
        exclusive_line = next(
            (index for index, line in enumerate(self.lines) if line.startswith("**")), None
        )
        if exclusive_line is None:
            raise HumdrumError("Nie znaleziono rekordu interpretacji wyłącznych **…")

        width = len(self.lines[exclusive_line].split("\t"))
        if width == 0:
            raise HumdrumError("Pusty rekord interpretacji wyłącznych.")

        found: dict[str, int | None] = {
            "part": None,
            "staff": None,
            "name": None,
            "abbr": None,
        }
        for index in range(exclusive_line + 1, len(self.lines)):
            line = self.lines[index]
            if not line.startswith("*") or line.startswith("**"):
                break
            fields = line.split("\t")
            if len(fields) != width:
                raise HumdrumError(
                    f"Wiersz {index + 1} ma {len(fields)} pól, a powinien mieć {width}."
                )
            if found["part"] is None and any(value.startswith("*part") for value in fields):
                found["part"] = index
            elif found["staff"] is None and any(value.startswith("*staff") for value in fields):
                found["staff"] = index
            elif found["name"] is None and any(value.startswith('*I"') for value in fields):
                found["name"] = index
            elif found["abbr"] is None and any(value.startswith("*I'") for value in fields):
                found["abbr"] = index

        return HeaderBlock(
            exclusive_line=exclusive_line,
            part_line=found["part"],
            staff_line=found["staff"],
            instrument_name_line=found["name"],
            instrument_abbr_line=found["abbr"],
        )

    def _validate_width(self, fields: list[str], label: str) -> None:
        if len(fields) != self.spine_count:
            raise HumdrumError(
                f"Wiersz {label} ma {len(fields)} pól zamiast {self.spine_count}."
            )

