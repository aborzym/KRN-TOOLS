from spineworks.humdrum import HumdrumDocument, HumdrumError
from spineworks.spine_validation import RecordKind, trace_spines


def repair_hairpin_layouts(
    document: HumdrumDocument,
) -> tuple[HumdrumDocument, int]:
    trace = trace_spines(document)
    if trace.issue is not None:
        raise HumdrumError(f"Linia {trace.issue.line_number}: {trace.issue.message}")

    result = HumdrumDocument.from_text(document.to_text())
    comment_lines: list[int] = []
    changes = 0

    for traced in trace.records:
        record = traced.record

        if record.kind == RecordKind.GLOBAL:
            continue

        if record.kind == RecordKind.LOCAL_COMMENT:
            comment_lines.append(record.line_number - 1)
            continue

        if record.kind != RecordKind.DATA:
            comment_lines.clear()
            continue

        for column, branch in enumerate(traced.branches):
            if branch.identity.spine_type != "**dynam":
                continue

            token = record.fields[column].lower()
            if not any(marker in token for marker in ("<", ">")):
                continue
            if any(marker in token for marker in ("p", "f", "s")):
                continue

            comments = [
                (line_number, result.lines[line_number].split("\t"))
                for line_number in comment_lines
            ]

            has_hairpin_layout = any(
                fields[column] == "!LO:HP" or fields[column].startswith("!LO:HP:")
                for _, fields in comments
            )

            for line_number, fields in comments:
                comment = fields[column]
                if comment == "!LO:DY" or comment.startswith("!LO:DY:"):
                    if has_hairpin_layout:
                        fields[column] = "!"
                    else:
                        fields[column] = comment.replace("!LO:DY", "!LO:HP", 1)
                        has_hairpin_layout = True

                    result.lines[line_number] = "\t".join(fields)
                    changes += 1

        comment_lines.clear()

    return result, changes
