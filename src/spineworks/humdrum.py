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
    instrument_code_line: int | None
    instrument_class_line: int | None
    instrument_group_line: int | None

    @property
    def line_numbers(self) -> list[int]:
        candidates = [
            self.exclusive_line,
            self.part_line,
            self.staff_line,
            self.instrument_name_line,
            self.instrument_abbr_line,
            self.instrument_code_line,
            self.instrument_class_line,
            self.instrument_group_line,
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

    def instrument_codes(self) -> list[str]:
        if self.header.instrument_code_line is None:
            return ["*"] * self.spine_count
        return self.fields(self.header.instrument_code_line)

    def instrument_classes(self) -> list[str]:
        for line in self.lines[self.header.exclusive_line + 1 :]:
            if not line.startswith("*") or line.startswith("**"):
                break
            fields = line.split("\t")
            active = [value for value in fields if value != "*"]
            if active and all(value.startswith("*IC") for value in active):
                return fields
        return ["*"] * self.spine_count

    def instrument_groups(self) -> list[str]:
        if self.header.instrument_group_line is None:
            return ["*"] * self.spine_count
        return self.fields(self.header.instrument_group_line)

    def set_instrument_groups(self, values: list[str]) -> bool:
        self._validate_width(values, "*IG")
        normalized = [
            f"*IG{value.strip()}" if spine_type == "**kern" and value.strip() else "*"
            for spine_type, value in zip(self.spine_types, values, strict=True)
        ]
        if all(value == "*" for value in normalized):
            return False
        if self.header.instrument_group_line is not None:
            if self.fields(self.header.instrument_group_line) == normalized:
                return False
            self.replace_fields(self.header.instrument_group_line, normalized)
            return True

        insert_after = (
            self.header.instrument_class_line
            if self.header.instrument_class_line is not None
            else self.header.instrument_abbr_line
        )
        if insert_after is None:
            insert_after = self.header.exclusive_line
        self.lines.insert(insert_after + 1, "\t".join(normalized))
        for field_name in self.header.__dataclass_fields__:
            current = getattr(self.header, field_name)
            if isinstance(current, int) and current > insert_after:
                setattr(self.header, field_name, current + 1)
        self.header.instrument_group_line = insert_after + 1
        return True

    def set_instrument_names(self, values: list[str]) -> bool:
        return self._set_existing_prefixed_row(
            self.header.instrument_name_line, values, '*I"', "nazwy pełnej"
        )

    def set_instrument_abbreviations(self, values: list[str]) -> bool:
        return self._set_existing_prefixed_row(
            self.header.instrument_abbr_line, values, "*I'", "nazwy skróconej"
        )

    def _set_existing_prefixed_row(
        self, line_number: int | None, values: list[str], prefix: str, label: str
    ) -> bool:
        if line_number is None:
            raise HumdrumError(f"Brak wiersza {label} instrumentu.")
        self._validate_width(values, prefix)
        normalized = [
            prefix + value.strip() if spine_type == "**kern" and value.strip() else "*"
            for spine_type, value in zip(self.spine_types, values, strict=True)
        ]
        if self.fields(line_number) == normalized:
            return False
        self.replace_fields(line_number, normalized)
        return True

    def set_instrument_codes(self, values: list[str]) -> bool:
        self._validate_width(values, "*I")
        normalized: list[str] = []
        for spine_type, value in zip(self.spine_types, values, strict=True):
            if spine_type != "**kern":
                normalized.append("*")
                continue
            code = value.strip()
            if not code or code == "*":
                normalized.append("*")
            elif "\t" in code or "\n" in code or "\r" in code:
                raise HumdrumError("Kod instrumentu nie może zawierać tabulatora ani nowej linii.")
            elif code.startswith("*I"):
                normalized.append(code)
            elif code.startswith("I"):
                normalized.append(f"*{code}")
            else:
                normalized.append(f"*I{code.lstrip('*')}")

        current = self.instrument_codes()
        if current == normalized:
            return False

        if self.header.instrument_code_line is not None:
            self.replace_fields(self.header.instrument_code_line, normalized)
            return True

        anchors = [
            self.header.instrument_abbr_line,
            self.header.instrument_name_line,
            self.header.staff_line,
            self.header.part_line,
            self.header.exclusive_line,
        ]
        insert_after = next(line for line in anchors if line is not None)
        self.lines.insert(insert_after + 1, "\t".join(normalized))
        self.header.instrument_code_line = insert_after + 1
        return True

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
            "code": None,
            "class": None,
            "group": None,
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
            elif found["code"] is None and any(
                value.startswith("*I")
                and not value.startswith(('*I"', "*I'", "*IC", "*IG", "*ITr"))
                for value in fields
            ):
                found["code"] = index
            elif found["class"] is None:
                active = [value for value in fields if value != "*"]
                if active and all(value.startswith("*IC") for value in active):
                    found["class"] = index
            if found["group"] is None:
                active = [value for value in fields if value != "*"]
                if active and all(value.startswith("*IG") for value in active):
                    found["group"] = index

        return HeaderBlock(
            exclusive_line=exclusive_line,
            part_line=found["part"],
            staff_line=found["staff"],
            instrument_name_line=found["name"],
            instrument_abbr_line=found["abbr"],
            instrument_code_line=found["code"],
            instrument_class_line=found["class"],
            instrument_group_line=found["group"],
        )

    def _validate_width(self, fields: list[str], label: str) -> None:
        if len(fields) != self.spine_count:
            raise HumdrumError(
                f"Wiersz {label} ma {len(fields)} pól zamiast {self.spine_count}."
            )
