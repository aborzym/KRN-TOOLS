"""Workflow signatures; transformations never mutate the source document."""

import re
from dataclasses import dataclass
from datetime import date

from spineworks.humdrum import HumdrumDocument


@dataclass(frozen=True)
class Workflow:
    label: str
    author: str
    dated: str
    anchors: tuple[str, ...]


WORKFLOWS = {
    "xml": Workflow("XML review", "ENC-review", "END-review", ("END",)),
    "diplomatic": Workflow("Dyplomatyczna", "EED", "EEV", ("END-review", "END")),
    "diplomatic-review": Workflow("Dyplomatyczna — review", "EED-review", "EEV-review", ("EEV",)),
    "modern": Workflow("Modern", "ENC-modern", "END-modern", ("EEV-review", "EEV")),
}


@dataclass(frozen=True)
class ExistingSignature:
    author_line: int | None
    date_line: int | None

    @property
    def positions(self) -> tuple[int, ...]:
        return tuple(i for i in (self.author_line, self.date_line) if i is not None)

    def text(self, document: HumdrumDocument) -> str:
        return "\n".join(document.lines[i] for i in sorted(self.positions))


def existing_signatures(document: HumdrumDocument, workflow: str) -> list[ExistingSignature]:
    """Pair an author with its following date, never across another workflow record.

    Repeated authors and orphan dates remain separate, selectable partial signatures.
    Unrelated metadata between the two records is left untouched.
    """
    spec = WORKFLOWS[workflow]
    result = []
    pending = None
    keys = {key for item in WORKFLOWS.values() for key in (item.author, item.dated)}
    keys.update(("ENC", "END"))
    for i, line in enumerate(document.lines):
        key = line.partition(":")[0].removeprefix("!!!") if line.startswith("!!!") else ""
        if key not in keys:
            continue
        if pending is not None and key != spec.dated:
            result.append(ExistingSignature(pending, None))
            pending = None
        if key == spec.author:
            pending = i
        elif key == spec.dated:
            result.append(ExistingSignature(pending, i))
            pending = None
    if pending is not None:
        result.append(ExistingSignature(pending, None))
    return result


def signature_lines(workflow: str, name: str) -> list[str]:
    if not name.strip() or any(c in name for c in "\r\n\t"):
        raise ValueError("Wpisz imię i nazwisko w jednej linii.")
    spec = WORKFLOWS[workflow]
    return [f"!!!{spec.author}: {name}", f"!!!{spec.dated}: {date.today().isoformat()}"]  # noqa: DTZ011 — required local computer date


def add_signature(
    document: HumdrumDocument,
    workflow: str,
    name: str,
    *,
    selected: ExistingSignature | None = None,
    action: str = "add",
) -> HumdrumDocument:
    if action not in {"add", "replace"}:
        raise ValueError("Nieznana operacja podpisu.")
    existing = existing_signatures(document, workflow)
    if (existing and selected not in existing) or (
        selected is not None and selected not in existing
    ):
        raise ValueError("Wskaż istniejący podpis.")
    if action == "replace" and selected is None:
        raise ValueError("Wskaż podpis do zamiany.")
    pair = signature_lines(workflow, name)
    lines = document.lines.copy()
    if selected is not None:
        if action == "replace":
            if selected.author_line is not None:
                lines[selected.author_line] = pair[0]
            if selected.date_line is not None:
                lines[selected.date_line] = pair[1]
            if selected.author_line is None:
                lines.insert(selected.date_line, pair[0])
            elif selected.date_line is None:
                lines.insert(selected.author_line + 1, pair[1])
        else:
            index = max(selected.positions) + 1
            lines[index:index] = pair
    else:
        index = None
        for anchor in WORKFLOWS[workflow].anchors:
            matches = [i for i, line in enumerate(lines) if line.startswith(f"!!!{anchor}:")]
            if matches:
                index = matches[-1] + 1
                break
        if index is None:
            matches = [
                i for i, line in enumerate(lines) if re.match(r"^!!!(?:END|EEV)(?:-[\w-]+)?:", line)
            ]
            if not matches:
                matches = [
                    i for i, line in enumerate(lines) if line.startswith("!!!system-decoration:")
                ]
            index = matches[-1] + 1 if matches else len(lines)
        lines[index:index] = pair
    return HumdrumDocument(lines, trailing_newline=document.trailing_newline)
