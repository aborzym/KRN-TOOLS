import pytest

from spineworks.humdrum import HumdrumDocument
from spineworks.spine_validation import (
    FragmentDraft,
    build_fragment_rows,
    build_measure_view,
    find_split_issues,
    group_split_issues,
    trace_spines,
)


def make_export_draft(
    *,
    trailing_newline: bool = True,
) -> tuple[HumdrumDocument, FragmentDraft]:
    text = "**kern\n=1\n4c\n*^\n4d\t4ryy\n2e\t2ryy\n*v\t*v\n=2\n*-"
    if trailing_newline:
        text += "\n"

    document = HumdrumDocument.from_text(text)
    trace = trace_spines(document)
    issues = find_split_issues(trace)
    problem = group_split_issues(trace, issues)[0]
    rows = build_fragment_rows(
        trace,
        problem,
        build_measure_view(trace, problem, issues),
    )
    return document, FragmentDraft(document, rows)


def test_unchanged_draft_exports_no_replacements() -> None:
    _, draft = make_export_draft()

    assert draft.source_replacements() == ()


def test_export_keeps_source_number_and_disappears_after_undo() -> None:
    document, draft = make_export_draft()
    draft.edit_token(3, 0, "4g")

    exported = draft.source_replacements()

    assert len(exported) == 1
    source_line, replacement = exported[0]
    assert source_line == 3
    assert len(replacement) == 1
    assert replacement[0].source_line == 3
    assert replacement[0].text == "4g"
    assert document.lines[2] == "4c"

    assert draft.undo() is True
    assert draft.source_replacements() == ()


@pytest.mark.parametrize("trailing_newline", [False, True])
def test_export_reconstructs_structural_edit_without_losing_prior_edit(
    trailing_newline: bool,
) -> None:
    document, draft = make_export_draft(trailing_newline=trailing_newline)
    original = document.to_text()
    draft.edit_token(3, 0, "4g")

    with draft.group_changes():
        proposal = draft.move_split(4, 0)
        assert proposal is not None
        draft.propose_tokens(((3, 1, "4ryy"),))

    before_export = draft.to_text()
    pending = draft.pending_suggestions
    exported = dict(draft.source_replacements())

    rebuilt: list[str] = []
    for source_line, text in enumerate(document.lines, start=1):
        if source_line in exported:
            rebuilt.extend(line.text for line in exported[source_line])
        else:
            rebuilt.append(text)

    reconstructed = "\n".join(rebuilt)
    if document.trailing_newline:
        reconstructed += "\n"

    assert reconstructed == before_export
    assert "4g\t4ryy" in reconstructed
    assert document.to_text() == original
    assert draft.to_text() == before_export
    assert draft.pending_suggestions == pending
    assert pending == ((3, 1),)

    assert draft.undo() is True
    assert draft.token(3, 0) == "4g"
    assert draft.pending_suggestions == ()

    assert draft.undo() is True
    assert draft.source_replacements() == ()
