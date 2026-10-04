from __future__ import annotations

import re
from dataclasses import dataclass

from spineworks.humdrum import HumdrumDocument, HumdrumError
from spineworks.spine_validation import RecordKind, trace_spines


@dataclass(frozen=True)
class TieRepair:
    start_line: int
    end_line: int
    root_column: int
    start_notes: tuple[int, ...]
    end_notes: tuple[int, ...]


def _pitch(note: str) -> tuple[str, int] | None:
    match = re.search(r"([a-g]+|[A-G]+)([#n-]*)", note)
    if match is None:
        return None

    letters, accidental = match.groups()
    if len(set(letters)) != 1:
        return None

    if accidental in ("", "n"):
        alteration = 0
    elif set(accidental) == {"#"}:
        alteration = len(accidental)
    elif set(accidental) == {"-"}:
        alteration = -len(accidental)
    else:
        return None

    return letters, alteration


def _may_match(left: str, right: str) -> bool:
    first = _pitch(left)
    second = _pitch(right)
    if first is None or second is None:
        return True

    return first == second


def _remove_link(note: str, *, outgoing: bool) -> str:
    marker = "[" if outgoing else "]"
    if marker in note:
        return note.replace(marker, "", 1)

    # "_" łączy nutę zarówno z poprzednią, jak i następną.
    # Usuwamy tylko błędne połączenie przez badaną kreskę.
    replacement = "]" if outgoing else "["
    return note.replace("_", replacement, 1)


def repair_hidden_ties(
    document: HumdrumDocument,
) -> tuple[HumdrumDocument, tuple[TieRepair, ...], tuple[str, ...]]:
    trace = trace_spines(document)
    if trace.issue is not None:
        raise HumdrumError(
            f"Nie można bezpiecznie przeanalizować ligatur. "
            f"Linia {trace.issue.line_number}: {trace.issue.message}"
        )

    previous = {}
    bar = 0
    repairs = []
    warnings = []
    edits: dict[tuple[int, int, int], set[str]] = {}

    for row in trace.records:
        record = row.record
        if record.kind in {RecordKind.GLOBAL, RecordKind.EMPTY}:
            continue

        active = {
            (
                branch.identity.root_column,
                branch.path,
                branch.opening_lines,
            )
            for branch in row.branches
        }
        previous = {key: value for key, value in previous.items() if key in active}

        if record.kind is RecordKind.BARLINE:
            bar += 1
            continue

        if record.kind is not RecordKind.DATA:
            continue

        for column, (token, branch) in enumerate(zip(record.fields, row.branches, strict=True)):
            if branch.identity.spine_type != "**kern" or token == ".":
                continue

            key = (
                branch.identity.root_column,
                branch.path,
                branch.opening_lines,
            )
            notes = token.split()
            earlier = previous.get(key)

            if earlier is not None and earlier[2] != bar:
                old_line, old_column, _, old_notes = earlier

                starts = [
                    index for index, note in enumerate(old_notes) if "[" in note or "_" in note
                ]
                ends = [index for index, note in enumerate(notes) if "]" in note or "_" in note]

                # Chronimy każdy dźwięk, dla którego istnieje możliwe
                # poprawne połączenie, niezależnie od kolejności akordu.
                unmatched_starts = [
                    index
                    for index in starts
                    if not any(_may_match(old_notes[index], notes[end]) for end in ends)
                ]
                unmatched_ends = [
                    index
                    for index in ends
                    if not any(_may_match(old_notes[start], notes[index]) for start in starts)
                ]

                if unmatched_starts and unmatched_ends:
                    left_hidden = all("yy" in old_notes[index] for index in unmatched_starts)
                    right_hidden = all("yy" in notes[index] for index in unmatched_ends)
                    has_hidden = any("yy" in old_notes[index] for index in unmatched_starts) or any(
                        "yy" in notes[index] for index in unmatched_ends
                    )

                    unambiguous = len(unmatched_starts) == len(unmatched_ends) and (
                        left_hidden or right_hidden
                    )
                    simple_markers = all(
                        old_notes[index].count("[") + old_notes[index].count("_") == 1
                        for index in unmatched_starts
                    ) and all(
                        notes[index].count("]") + notes[index].count("_") == 1
                        for index in unmatched_ends
                    )

                    if has_hidden and unambiguous and simple_markers:
                        repairs.append(
                            TieRepair(
                                old_line,
                                record.line_number,
                                branch.identity.root_column,
                                tuple(unmatched_starts),
                                tuple(unmatched_ends),
                            )
                        )
                        for index in unmatched_starts:
                            edits.setdefault((old_line, old_column, index), set()).add("out")
                        for index in unmatched_ends:
                            edits.setdefault((record.line_number, column, index), set()).add("in")
                    elif has_hidden:
                        warnings.append(
                            f"Linie {old_line}–{record.line_number}, "
                            f"spine {branch.identity.root_column + 1}: "
                            "niejednoznaczne dopasowanie ligatur — bez zmian."
                        )

            previous[key] = (
                record.line_number,
                column,
                bar,
                notes,
            )

    result = HumdrumDocument.from_text(document.to_text())
    by_field: dict[tuple[int, int], dict[int, set[str]]] = {}
    for (line, column, index), directions in edits.items():
        by_field.setdefault((line, column), {})[index] = directions

    for (line, column), changes in by_field.items():
        fields = result.lines[line - 1].split("\t")
        index = 0

        def replace_note(
            match: re.Match[str],
            changes: dict[int, set[str]] = changes,
        ) -> str:
            nonlocal index
            note = match.group()
            directions = changes.get(index, set())
            index += 1

            if directions == {"in", "out"} and "_" in note:
                return note.replace("_", "", 1)
            if "out" in directions:
                note = _remove_link(note, outgoing=True)
            if "in" in directions:
                note = _remove_link(note, outgoing=False)
            return note

        fields[column] = re.sub(r"\S+", replace_note, fields[column])
        result.lines[line - 1] = "\t".join(fields)

    return result, tuple(repairs), tuple(dict.fromkeys(warnings))
