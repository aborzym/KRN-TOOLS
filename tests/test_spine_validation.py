import pytest

from spineworks.humdrum import HumdrumDocument, HumdrumError
from spineworks.spine_rhythm import (
    suggest_merge_fill,
    suggest_split_fill,
)
from spineworks.spine_validation import (
    DraftLine,
    FragmentDraft,
    RecordKind,
    ValidationState,
    build_fragment_rows,
    build_measure_view,
    find_split_issues,
    group_split_issues,
    plan_merge_move,
    plan_merge_reopening,
    plan_split_move,
    prepare_closing_block,
    prepare_merge_extension,
    prepare_merge_move,
    prepare_merge_reopening,
    prepare_merge_reopenings,
    prepare_split_move,
    read_records,
    separate_merge_rows,
    trace_spines,
    validate_draft,
)


def test_spaces_do_not_create_spines() -> None:
    record = read_records("4e\\ 4cc 4aa\t2ryy\n")[0]

    assert record.kind is RecordKind.DATA
    assert record.spine_count == 2
    assert record.fields == ("4e\\ 4cc 4aa", "2ryy")


def test_global_records_have_no_spine_count() -> None:
    records = read_records("!!Komentarz\n!!!OMD: Allegro\n")

    assert len(records) == 2
    assert all(record.kind is RecordKind.GLOBAL for record in records)
    assert all(record.spine_count is None for record in records)


def test_preserves_every_line_and_its_number() -> None:
    records = read_records(
        "**kern\n=45\n!!Komentarz globalny\n\n*^\n!\t!\n2c\t2ryy\n.\t.\n*v\t*v\n=46\n*-\n"
    )

    assert [record.line_number for record in records] == list(range(1, 12))
    assert [record.kind for record in records] == [
        RecordKind.INTERPRETATION,
        RecordKind.BARLINE,
        RecordKind.GLOBAL,
        RecordKind.EMPTY,
        RecordKind.INTERPRETATION,
        RecordKind.LOCAL_COMMENT,
        RecordKind.DATA,
        RecordKind.DATA,
        RecordKind.INTERPRETATION,
        RecordKind.BARLINE,
        RecordKind.INTERPRETATION,
    ]
    assert records[7].fields == (".", ".")
    assert records[7].spine_count == 2


def test_empty_field_is_preserved_for_later_validation() -> None:
    record = read_records("4c\t\t4e\t\n")[0]

    assert record.spine_count == 4
    assert record.fields == ("4c", "", "4e", "")


def test_tracks_identity_and_width_before_each_operation() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\n"
        '*I"Violin 2\t*\n'
        "*part14\t*part14\n"
        "*staff14\t*staff14\n"
        "=45\t=45\n"
        "*^\t*\n"
        "2c\t2ryy\tp\n"
        "*v\t*v\t*\n"
        "=46\t=46\n"
        "*-\t*-\n"
    )

    trace = trace_spines(document)

    assert trace.issue is None
    opening = trace.records[5]
    data = trace.records[6]
    closing = trace.records[7]
    next_barline = trace.records[8]

    assert len(opening.branches) == 2
    assert len(data.branches) == 3
    assert len(closing.branches) == 3
    assert len(next_barline.branches) == 2

    left, right = data.branches[:2]
    assert left.identity == right.identity
    assert left.identity.instrument == "Violin 2"
    assert left.identity.spine_type == "**kern"
    assert left.identity.part == "*part14"
    assert left.identity.staff == "*staff14"
    assert left.path == (0,)
    assert right.path == (1,)
    assert next_barline.branches[0].path == ()


def test_tracks_nested_split_and_partial_then_full_merge() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n=1\n*^\n*^\t*\n4c\t4e\t4g\n*v\t*v\t*\n*v\t*v\n=2\n*-\n"
    )

    trace = trace_spines(document)

    assert trace.issue is None
    assert [branch.path for branch in trace.records[4].branches] == [
        (0, 0),
        (0, 1),
        (1,),
    ]
    assert [branch.path for branch in trace.records[6].branches] == [(0,), (1,)]
    assert trace.records[7].branches[0].path == ()


def test_allows_final_termination_of_unmerged_branches() -> None:
    document = HumdrumDocument.from_text("**kern\n=1\n*^\n2c\t2e\n*-\t*-\n!!!END: Test\n")

    assert trace_spines(document).issue is None


def test_stops_at_wrong_width_without_guessing_later_identity() -> None:
    document = HumdrumDocument.from_text("**kern\n=1\n*^\n4c\n=2\t=2\n")

    trace = trace_spines(document)

    assert trace.issue is not None
    assert trace.issue.line_number == 4
    assert "oczekiwano 2, znaleziono 1" in trace.issue.message
    assert len(trace.records) == 4


def test_rejects_merge_of_independent_root_spines() -> None:
    document = HumdrumDocument.from_text("**kern\t**kern\n=1\t=1\n2c\t2e\n*v\t*v\n")

    trace = trace_spines(document)

    assert trace.issue is not None
    assert trace.issue.line_number == 4
    assert "Nieprawidłowe scalenie" in trace.issue.message


def test_reports_unsupported_manipulators() -> None:
    for token in ("*x", "*+"):
        document = HumdrumDocument.from_text(f"**kern\t**kern\n=1\t=1\n{token}\t*\n")

        trace = trace_spines(document)

        assert trace.issue is not None
        assert trace.issue.line_number == 3
        assert token in trace.issue.message


def test_rejects_early_termination() -> None:
    document = HumdrumDocument.from_text("**kern\t**kern\n=1\t=1\n*-\t*\n4c\n")

    trace = trace_spines(document)

    assert trace.issue is not None
    assert trace.issue.line_number == 3
    assert "przed końcem utworu" in trace.issue.message


def test_detects_late_split_after_data_in_other_spine() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n=45\t=45\n.\t4c\n*^\t*\n4e\t4g\t4d\n*-\t*-\t*-\n"
    )

    issues = find_split_issues(trace_spines(document))

    assert len(issues) == 1
    assert issues[0].code == "late_split"
    assert issues[0].line_number == 4
    assert issues[0].measure == "45"
    assert issues[0].related_lines == (3,)


def test_detects_early_merge_even_when_following_token_is_dot() -> None:
    document = HumdrumDocument.from_text("**kern\n=45\n*^\n2c\t2ryy\n*v\t*v\n.\n=46\n*-\n")

    issues = find_split_issues(trace_spines(document))

    assert len(issues) == 1
    assert issues[0].code == "early_merge"
    assert issues[0].line_number == 5
    assert issues[0].related_lines == (6,)


def test_allows_multimeasure_split_and_comments_after_merge() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n"
        "=45\n"
        "!!!OMD: Allegro\n"
        "*^\n"
        "!\t!\n"
        "1c\t1ryy\n"
        "=46\t=46\n"
        "1d\t1ryy\n"
        "*v\t*v\n"
        "!Komentarz\n"
        "!!Komentarz globalny\n"
        "=47\n"
        "*-\n"
    )

    assert find_split_issues(trace_spines(document)) == ()


def test_detects_ordinary_interpretation_after_merge() -> None:
    document = HumdrumDocument.from_text("**kern\n=1\n*^\n1c\t1e\n*v\t*v\n*clefG2\n=2\n*-\n")

    issues = find_split_issues(trace_spines(document))

    assert len(issues) == 1
    assert issues[0].code == "interpretation_after_merge"
    assert issues[0].related_lines == (6,)


def test_detects_two_independent_merges_in_one_line() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n=1\t=1\n*^\t*^\n1c\t1e\t1g\t1b\n*v\t*v\t*v\t*v\n=2\t=2\n*-\t*-\n"
    )

    trace = trace_spines(document)

    # Adjacent *v tokens form one group, so this is structurally ambiguous.
    assert trace.issue is not None


def test_reports_separated_merge_groups() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\t**kern\n"
        "=1\t=1\t=1\n"
        "*^\t*\t*^\n"
        "1c\t1e\tp\t1g\t1b\n"
        "*v\t*v\t*\t*v\t*v\n"
        "=2\t=2\t=2\n"
        "*-\t*-\t*-\n"
    )

    trace = trace_spines(document)
    issues = find_split_issues(trace)

    assert trace.issue is None
    assert len(issues) == 1
    assert issues[0].code == "multiple_merges"
    assert len(issues[0].identities) == 2


def test_allows_separate_closing_rows_and_final_termination() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n=1\t=1\n*^\t*^\n1c\t1e\t1g\t1b\n*\t*\t*v\t*v\n*v\t*v\t*\n*-\t*-\n"
    )

    trace = trace_spines(document)

    assert trace.issue is None
    assert find_split_issues(trace) == ()


def test_detects_closing_left_instrument_before_right_instrument() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n=1\t=1\n*^\t*^\n1c\t1e\t1g\t1b\n*v\t*v\t*\t*\n*\t*v\t*v\n=2\t=2\n*-\t*-\n"
    )

    trace = trace_spines(document)
    issues = find_split_issues(trace)

    assert trace.issue is None
    assert len(issues) == 1
    assert issues[0].code == "merge_order"
    assert issues[0].line_number == 6
    assert issues[0].related_lines == (5,)


def test_allows_nested_closings_of_same_root_spine() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n=1\n*^\n*\t*^\n1c\t1e\t1g\n*\t*v\t*v\n*v\t*v\n=2\n*-\n"
    )

    trace = trace_spines(document)

    assert trace.issue is None
    assert find_split_issues(trace) == ()


def test_groups_problems_and_includes_helper_spines() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\t**kern\n"
        '*I"Violin 2\t*\t*I"Trumpet\n'
        "=45\t=45\t=45\n"
        "*^\t*\t*^\n"
        "2c\t2ryy\tp\t2e\t2ryy\n"
        "*v\t*v\t*\t*\t*\n"
        "2d\t.\t2f\t2ryy\n"
        "*clefG2\t*\t*\t*\n"
        "=46\t=46\t=46\t=46\n"
        "*-\t*-\t*-\t*-\n"
    )

    trace = trace_spines(document)
    ranges = group_split_issues(trace, find_split_issues(trace))

    assert trace.issue is None
    assert len(ranges) == 1
    problem = ranges[0]
    assert problem.measure == "45"
    assert problem.start_line == 3
    assert problem.end_line == 9
    assert {issue.code for issue in problem.issues} == {
        "early_merge",
        "interpretation_after_merge",
    }
    assert [identity.instrument for identity in problem.editable_identities] == [
        "Violin 2",
    ]
    assert [identity.instrument for identity in problem.helper_identities] == [
        "Trumpet",
    ]


def test_repeated_measure_numbers_do_not_combine_different_places() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n=1\n4c\n*^\n2d\t2e\n*v\t*v\n=1\n4f\n*^\n2g\t2a\n*-\t*-\n"
    )

    trace = trace_spines(document)
    ranges = group_split_issues(trace, find_split_issues(trace))

    assert trace.issue is None
    assert len(ranges) == 2
    assert [problem.measure for problem in ranges] == ["1", "1"]
    assert [problem.start_line for problem in ranges] == [2, 7]


def test_omits_helper_split_unchanged_through_problem_measure() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n"
        '*I"Violin 2\t*I"Bassoon\n'
        "=44\t=44\n"
        "*\t*^\n"
        "1c\t1e\t1ryy\n"
        "=45\t=45\t=45\n"
        "*^\t*\t*\n"
        "2c\t2ryy\t2e\t2ryy\n"
        "*v\t*v\t*\t*\n"
        "2d\t2f\t2ryy\n"
        "=46\t=46\t=46\n"
        "*-\t*-\t*-\n"
    )

    trace = trace_spines(document)
    ranges = group_split_issues(trace, find_split_issues(trace))

    assert trace.issue is None
    assert len(ranges) == 1
    assert ranges[0].measure == "45"
    assert [identity.instrument for identity in ranges[0].editable_identities] == ["Violin 2"]
    assert ranges[0].helper_identities == ()

    # Bassoon still contributes two fields to the complete source record.
    assert trace.records[7].record.spine_count == 4


def test_preserves_opening_lines_through_nested_merges() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n=44\n*^\n1c\t1e\n=45\t=45\n*^\t*\n1d\t1f\t1a\n*v\t*v\t*\n*v\t*v\n=46\n*-\n"
    )

    trace = trace_spines(document)

    assert trace.issue is None
    assert [branch.opening_lines for branch in trace.records[6].branches] == [(3, 6), (3, 6), (3,)]
    assert [branch.opening_lines for branch in trace.records[8].branches] == [(3,), (3,)]
    assert trace.records[9].branches[0].opening_lines == ()


def test_shows_opening_and_problem_measures_and_folds_middle() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n=43\n*^\n1c\t1ryy\n=44\t=44\n1d\t1ryy\n=45\t=45\n2e\t2ryy\n*v\t*v\n2f\n=46\n*-\n"
    )

    trace = trace_spines(document)
    issues = find_split_issues(trace)
    problem = group_split_issues(trace, issues)[0]
    view = build_measure_view(trace, problem, issues)

    assert trace.issue is None
    assert [item.measure for item in view] == ["43", "44", "45"]
    assert [item.collapsed for item in view] == [False, True, False]
    assert [(item.start_line, item.end_line) for item in view] == [
        (2, 5),
        (5, 7),
        (7, 11),
    ]


def test_does_not_fold_intermediate_measure_containing_an_issue() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n"
        "=43\n"
        "*^\n"
        "1c\t1ryy\n"
        "=44\t=44\n"
        "2d\t2ryy\n"
        "*^\t*\n"
        "2e\t2ryy\t.\n"
        "=45\t=45\t=45\n"
        "2f\t2ryy\t2ryy\n"
        "*v\t*v\t*v\n"
        "2g\n"
        "=46\n"
        "*-\n"
    )

    trace = trace_spines(document)
    issues = find_split_issues(trace)
    problems = group_split_issues(trace, issues)
    problem = next(item for item in problems if item.measure == "45")
    view = build_measure_view(trace, problem, issues)

    assert trace.issue is None
    assert [item.measure for item in view] == ["43", "44", "45"]
    assert all(not item.collapsed for item in view)


def test_multiple_merges_do_not_pull_in_earlier_opening_measures() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\t**kern\n"
        "=44\t=44\t=44\n"
        "*^\t*\t*^\n"
        "1c\t1ryy\tp\t1e\t1ryy\n"
        "=45\t=45\t=45\t=45\t=45\n"
        "1d\t1ryy\t.\t1f\t1ryy\n"
        "*v\t*v\t*\t*v\t*v\n"
        "=46\t=46\t=46\n"
        "*-\t*-\t*-\n"
    )

    trace = trace_spines(document)
    issues = find_split_issues(trace)
    problem = group_split_issues(trace, issues)[0]
    view = build_measure_view(trace, problem, issues)

    assert trace.issue is None
    assert [issue.code for issue in issues] == ["multiple_merges"]
    assert len(view) == 1
    assert view[0].measure == "45"
    assert view[0].start_line == 5
    assert view[0].end_line == 8
    assert view[0].collapsed is False


def test_fragment_preserves_all_rows_counts_and_readonly_helpers() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\t**kern\n"
        '*I"Violin 2\t*\t*I"Trumpet\n'
        "=45\t=45\t=45\n"
        "!!Komentarz globalny\n"
        "*^\t*\t*^\n"
        "!\t!\t!\t!\t!\n"
        "2c 2e\t2ryy\tp\t2g\t2ryy\n"
        "*v\t*v\t*\t*\t*\n"
        "2d\t.\t2a\t2ryy\n"
        "=46\t=46\t=46\t=46\n"
        "*-\t*-\t*-\t*-\n"
    )

    original = document.to_text()
    trace = trace_spines(document)
    issues = find_split_issues(trace)
    problem = group_split_issues(trace, issues)[0]
    view = build_measure_view(trace, problem, issues)
    fragment = build_fragment_rows(trace, problem, view)

    assert [row.source_line for row in fragment] == list(range(3, 11))
    assert fragment[1].global_text == "!!Komentarz globalny"
    assert fragment[1].spine_count is None
    assert fragment[1].cells == ()

    data_row = next(row for row in fragment if row.source_line == 7)
    assert data_row.spine_count == 5
    assert [cell.source_column for cell in data_row.cells] == [0, 1, 3, 4]
    assert [cell.token for cell in data_row.cells] == [
        "2c 2e",
        "2ryy",
        "2g",
        "2ryy",
    ]
    assert [cell.editable for cell in data_row.cells] == [
        True,
        True,
        False,
        False,
    ]

    after_merge = next(row for row in fragment if row.source_line == 9)
    assert after_merge.spine_count == 4
    assert [cell.source_column for cell in after_merge.cells] == [0, 2, 3]
    assert document.to_text() == original


def make_test_draft() -> tuple[HumdrumDocument, FragmentDraft]:
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\t**kern\n"
        '*I"Violin 2\t*\t*I"Trumpet\n'
        "=45\t=45\t=45\n"
        "*^\t*\t*^\n"
        "2c 2e\t2ryy\tp\t2g\t2ryy\n"
        "*v\t*v\t*\t*\t*\n"
        "2d\tf\t2a\t2ryy\n"
        "=46\t=46\t=46\t=46\n"
        "*-\t*-\t*-\t*-\n"
    )
    trace = trace_spines(document)
    issues = find_split_issues(trace)
    problem = group_split_issues(trace, issues)[0]
    rows = build_fragment_rows(
        trace,
        problem,
        build_measure_view(trace, problem, issues),
    )
    return document, FragmentDraft(document, rows)


def test_draft_changes_only_selected_token_and_preserves_document() -> None:
    document, draft = make_test_draft()
    original = document.to_text()

    assert draft.edit_token(5, 0, "2d 2f") is True
    assert draft.token(5, 0) == "2d 2f"
    assert draft.to_text().splitlines()[4] == "2d 2f\t2ryy\tp\t2g\t2ryy"
    assert document.to_text() == original
    assert draft.dirty is True
    assert draft.can_undo is True

    assert draft.undo() is True
    assert draft.to_text() == original
    assert draft.dirty is False
    assert draft.can_undo is False


def test_draft_refuses_helper_and_hidden_cells() -> None:
    _, draft = make_test_draft()

    with pytest.raises(ValueError, match="nie jest edytowalne"):
        draft.edit_token(5, 3, "2b")

    with pytest.raises(ValueError, match="nie jest edytowalne"):
        draft.edit_token(5, 2, "ff")


def test_draft_allows_empty_token_for_incomplete_manual_edit() -> None:
    _, draft = make_test_draft()

    assert draft.edit_token(5, 0, "") is True
    assert draft.to_text().splitlines()[4] == "\t2ryy\tp\t2g\t2ryy"


def test_draft_rejects_field_separators_but_accepts_chord_spaces() -> None:
    _, draft = make_test_draft()

    for token in ("2c\t2e", "2c\n2e", "2c\r2e"):
        with pytest.raises(ValueError, match="Jedno pole"):
            draft.edit_token(5, 0, token)

    assert draft.dirty is False
    assert draft.can_undo is False
    assert draft.edit_token(5, 0, "2c 2e 2g") is True


def test_restoring_original_token_is_itself_undoable() -> None:
    document, draft = make_test_draft()

    assert draft.edit_token(5, 0, "2d") is True
    assert draft.edit_token(5, 0, "2c 2e") is True
    assert draft.dirty is False
    assert draft.to_text() == document.to_text()

    assert draft.undo() is True
    assert draft.token(5, 0) == "2d"


def test_draft_validation_reports_existing_early_merge() -> None:
    _, draft = make_test_draft()

    result = validate_draft(draft, start_line=3, end_line=8)

    assert result.state is ValidationState.ERROR
    assert any("Linia 6:" in message for message in result.messages)
    assert any("po *v występują dane" in message for message in result.messages)


def test_draft_validation_reports_empty_edited_field() -> None:
    _, draft = make_test_draft()
    draft.edit_token(5, 0, "")

    result = validate_draft(draft, start_line=3, end_line=8)

    assert result.state is ValidationState.ERROR
    assert any("Linia 5: Puste pole" in message for message in result.messages)


def test_draft_validation_ignores_placement_issues_in_other_measures() -> None:
    document = HumdrumDocument.from_text("**kern\n=1\n4c\n*^\n2d\t2e\n*v\t*v\n=2\n1f\n=3\n*-\n")
    draft = FragmentDraft(document, ())

    result = validate_draft(draft, start_line=7, end_line=9)

    assert result.state is ValidationState.VALID


def test_draft_validation_blocks_structure_failure_before_range() -> None:
    document = HumdrumDocument.from_text("**kern\n=1\n*^\n4c\n=2\t=2\n1d\t1e\n*-\t*-\n")
    draft = FragmentDraft(document, ())

    result = validate_draft(draft, start_line=5, end_line=7)

    assert result.state is ValidationState.ERROR
    assert any("Linia 4:" in message for message in result.messages)


def test_draft_validation_does_not_block_on_later_structure_failure() -> None:
    document = HumdrumDocument.from_text("**kern\n=1\n1c\n=2\n*^\n4d\n")
    draft = FragmentDraft(document, ())

    result = validate_draft(draft, start_line=2, end_line=4)

    assert result.state is ValidationState.VALID


def test_separates_merges_right_to_left_and_preserves_source() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\t**kern\n"
        '*I"Violin 2\t*\t*I"Oboe\n'
        "=45\t=45\t=45\n"
        "*^\t*\t*^\n"
        "1c\t1ryy\tp\t1e\t1ryy\n"
        "*v\t*v\t*\t*v\t*v\n"
        "=46\t=46\t=46\n"
        "*-\t*-\t*-\n"
    )
    original = document.to_text()

    replacement = separate_merge_rows(document, 6)

    assert replacement.source_line == 6
    assert replacement.lines == (
        "*\t*\t*\t*v\t*v",
        "*v\t*v\t*\t*",
    )
    assert [identity.instrument for identity in replacement.identities] == [
        "Oboe",
        "Violin 2",
    ]
    assert document.to_text() == original

    candidate_lines = document.lines.copy()
    candidate_lines[5:6] = replacement.lines
    candidate = HumdrumDocument(candidate_lines, document.trailing_newline)
    trace = trace_spines(candidate)

    assert trace.issue is None
    assert find_split_issues(trace) == ()


def test_separates_three_branch_merge_and_two_branch_merge() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\t**kern\n"
        "=1\t=1\t=1\n"
        "*^\t*\t*^\n"
        "*^\t*\t*\t*\t*\n"
        "1c\t1e\t1g\tp\t1a\t1b\n"
        "*v\t*v\t*v\t*\t*v\t*v\n"
        "=2\t=2\t=2\n"
        "*-\t*-\t*-\n"
    )

    replacement = separate_merge_rows(document, 6)

    assert replacement.lines == (
        "*\t*\t*\t*\t*v\t*v",
        "*v\t*v\t*v\t*\t*",
    )


def test_single_merge_replacement_is_unchanged() -> None:
    document = HumdrumDocument.from_text("**kern\n=1\n*^\n1c\t1e\n*v\t*v\n=2\n*-\n")

    replacement = separate_merge_rows(document, 5)

    assert replacement.lines == ("*v\t*v",)


def test_refuses_separating_merge_mixed_with_other_interpretations() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n=1\t=1\n*^\t*\n1c\t1e\t1g\n*v\t*v\t*clefG2\n=2\t=2\n*-\t*-\n"
    )

    with pytest.raises(HumdrumError, match="wyłącznie scalenia"):
        separate_merge_rows(document, 5)


def test_draft_separates_merges_with_descriptions_and_one_undo() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\t**kern\n"
        '*I"Violin 2\t*\t*I"Oboe\n'
        "=45\t=45\t=45\n"
        "*^\t*\t*^\n"
        "1c\t1ryy\tp\t1e\t1ryy\n"
        "*v\t*v\t*\t*v\t*v\n"
        "=46\t=46\t=46\n"
        "*-\t*-\t*-\n"
    )
    trace = trace_spines(document)
    issues = find_split_issues(trace)
    problem = group_split_issues(trace, issues)[0]
    rows = build_fragment_rows(
        trace,
        problem,
        build_measure_view(trace, problem, issues),
    )
    draft = FragmentDraft(document, rows)

    draft.edit_token(5, 0, "1d")
    before_operation = draft.to_text()

    assert draft.separate_merges(6) is True
    inserted = [line for line in draft.rendered_lines() if line.source_line is None]
    assert [line.description for line in inserted] == [
        "nowe: Oboe",
        "nowe: Violin 2",
    ]
    assert [line.text for line in inserted] == [
        "*\t*\t*\t*v\t*v",
        "*v\t*v\t*\t*",
    ]
    assert any(
        line.source_line == 7 and line.text == "=46\t=46\t=46" for line in draft.rendered_lines()
    )
    assert draft.separate_merges(6) is False
    assert document.to_text() == draft.original_text

    assert draft.undo() is True
    assert draft.to_text() == before_operation
    assert draft.token(5, 0) == "1d"

    assert draft.undo() is True
    assert draft.to_text() == document.to_text()


def make_merge_mapping_draft(
    *,
    data_after_merge: bool,
) -> FragmentDraft:
    following = "1d\t.\t1f\n" if data_after_merge else ""
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\t**kern\n"
        '*I"Violin 2\t*\t*I"Oboe\n'
        "=45\t=45\t=45\n"
        "*^\t*\t*^\n"
        "1c\t1ryy\tp\t1e\t1ryy\n"
        "*v\t*v\t*\t*v\t*v\n"
        f"{following}"
        "=46\t=46\t=46\n"
        "*-\t*-\t*-\n"
    )
    trace = trace_spines(document)
    issues = find_split_issues(trace)
    problem = group_split_issues(trace, issues)[0]
    rows = build_fragment_rows(
        trace,
        problem,
        build_measure_view(trace, problem, issues),
    )
    return FragmentDraft(document, rows)


def test_validates_source_range_after_inserting_merge_rows() -> None:
    draft = make_merge_mapping_draft(data_after_merge=False)

    assert draft.separate_merges(6) is True
    result = validate_draft(draft, start_line=3, end_line=7)

    assert result.state is ValidationState.VALID
    inserted = [line for line in draft.rendered_lines() if line.source_line is None]
    assert [line.anchor_line for line in inserted] == [6, 6]


def test_new_row_errors_use_descriptions_instead_of_result_numbers() -> None:
    draft = make_merge_mapping_draft(data_after_merge=True)

    assert draft.separate_merges(6) is True
    result = validate_draft(draft, start_line=3, end_line=8)

    assert result.state is ValidationState.ERROR
    assert any(message.startswith("nowe: Oboe:") for message in result.messages)
    assert any(message.startswith("nowe: Violin 2:") for message in result.messages)


def test_source_range_includes_record_shifted_by_inserted_rows() -> None:
    draft = make_merge_mapping_draft(data_after_merge=True)
    draft.separate_merges(6)

    # Source line 7 is now physical line 8.
    draft.edit_token(7, 0, "")
    result = validate_draft(draft, start_line=3, end_line=7)

    assert result.state is ValidationState.ERROR
    assert any(message.startswith("Linia 7: Puste pole") for message in result.messages)

    assert draft.undo() is True
    assert draft.undo() is True
    assert draft.to_text() == draft.original_text


def test_merge_move_plan_finds_existing_final_closing_block() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\t**kern\n"
        '*I"Violin 2\t*\t*I"Oboe\n'
        "=45\t=45\t=45\n"
        "*^\t*\t*^\n"
        "2c\t2ryy\tp\t2e\t2ryy\n"
        "*v\t*v\t*\t*\t*\n"
        "2d\t.\t2f\t2ryy\n"
        "*\t*\t*v\t*v\n"
        "!Komentarz\t!\t!\n"
        "!!Komentarz globalny\n"
        "=46\t=46\t=46\n"
        "*-\t*-\t*-\n"
    )

    original = document.to_text()
    plan = plan_merge_move(document, 6, 0)

    assert plan.identity.instrument == "Violin 2"
    assert plan.branch_count == 2
    assert plan.end_barline == 11
    assert plan.closing_block_start == 8
    assert document.to_text() == original


def test_merge_move_plan_without_existing_closing_block() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n=45\n*^\n2c\t2ryy\n*v\t*v\n2d\n!Komentarz\n=46\n*-\n"
    )

    plan = plan_merge_move(document, 5, 0)

    assert plan.end_barline == 8
    assert plan.closing_block_start == 8


def test_merge_move_plan_refuses_wrong_spine_selection() -> None:
    document = HumdrumDocument.from_text("**kern\n=45\n*^\n2c\t2ryy\n*v\t*v\n2d\n=46\n*-\n")

    with pytest.raises(HumdrumError, match="Wskaż jedno scalenie"):
        plan_merge_move(document, 5, 99)


def test_merge_extension_preserves_tokens_and_other_columns() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\t**kern\n"
        '*I"Violin 2\t*\t*I"Oboe\n'
        "=45\t=45\t=45\n"
        "*^\t*\t*^\n"
        "2c\t2ryy\tp\t2e\t2ryy\n"
        "*v\t*v\t*\t*\t*\n"
        "!LO:S:color=red\t!\t!\t!\n"
        "*clefG2\t*\t*\t*\n"
        "2d 2f\tff\t2g\t2ryy\n"
        "*\t*\t*v\t*v\n"
        "=46\t=46\t=46\n"
        "*-\t*-\t*-\n"
    )
    original = document.to_text()
    plan = plan_merge_move(document, 6, 0)

    rows = prepare_merge_extension(document, plan)

    assert [row.source_line for row in rows] == [7, 8, 9]
    assert rows[0].fields == (
        "!LO:S:color=red",
        "!",
        "!",
        "!",
        "!",
    )
    assert rows[1].fields == ("*clefG2", "*clefG2", "*", "*", "*")
    assert rows[2].fields == ("2d 2f", "", "ff", "2g", "2ryy")
    assert rows[2].proposed_columns == (1,)
    assert rows[0].proposed_columns == ()
    assert document.to_text() == original


def test_non_kern_extension_proposes_dots() -> None:
    document = HumdrumDocument.from_text("**text\n=1\n*^\nla\t.\n*v\t*v\nle\n=2\n*-\n")

    rows = prepare_merge_extension(
        document,
        plan_merge_move(document, 5, 0),
    )

    assert len(rows) == 1
    assert rows[0].fields == ("le", ".")
    assert rows[0].proposed_columns == (1,)


def test_merge_extension_keeps_global_comments_out_of_field_rows() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n=1\n*^\n2c\t2ryy\n*v\t*v\n!!Komentarz globalny\n2d\n=2\n*-\n"
    )

    rows = prepare_merge_extension(
        document,
        plan_merge_move(document, 5, 0),
    )

    assert [row.source_line for row in rows] == [7]


def test_closing_block_places_moved_left_merge_after_right_merge() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\t**kern\n"
        '*I"Violin 2\t*\t*I"Oboe\n'
        "=45\t=45\t=45\n"
        "*^\t*\t*^\n"
        "2c\t2ryy\tp\t2e\t2ryy\n"
        "*v\t*v\t*\t*\t*\n"
        "2d\t.\t2f\t2ryy\n"
        "*\t*\t*v\t*v\n"
        "=46\t=46\t=46\n"
        "*-\t*-\t*-\n"
    )
    original = document.to_text()
    plan = plan_merge_move(document, 6, 0)

    closing = prepare_closing_block(document, plan)

    assert [row.identity.instrument for row in closing] == [
        "Oboe",
        "Violin 2",
    ]
    assert [row.fields for row in closing] == [
        ("*", "*", "*", "*v", "*v"),
        ("*v", "*v", "*", "*"),
    ]
    assert document.to_text() == original


def test_closing_block_places_moved_right_merge_before_left_merge() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\t**kern\n"
        '*I"Violin 2\t*\t*I"Oboe\n'
        "=45\t=45\t=45\n"
        "*^\t*\t*^\n"
        "2c\t2ryy\tp\t2e\t2ryy\n"
        "*\t*\t*\t*v\t*v\n"
        "2d\t2ryy\t.\t2f\n"
        "*v\t*v\t*\t*\n"
        "=46\t=46\t=46\n"
        "*-\t*-\t*-\n"
    )

    closing = prepare_closing_block(
        document,
        plan_merge_move(document, 6, 2),
    )

    assert [row.identity.instrument for row in closing] == [
        "Oboe",
        "Violin 2",
    ]
    assert [len(row.fields) for row in closing] == [5, 4]


def test_closing_block_without_other_merges() -> None:
    document = HumdrumDocument.from_text("**kern\n=45\n*^\n2c\t2ryy\n*v\t*v\n2d\n=46\n*-\n")

    closing = prepare_closing_block(
        document,
        plan_merge_move(document, 5, 0),
    )

    assert len(closing) == 1
    assert closing[0].fields == ("*v", "*v")


def test_complete_merge_move_preserves_source_mapping_and_comments() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\t**kern\n"
        '*I"Violin 2\t*\t*I"Oboe\n'
        "=45\t=45\t=45\n"
        "*^\t*\t*^\n"
        "2c\t2ryy\tp\t2e\t2ryy\n"
        "*v\t*v\t*\t*\t*\n"
        "!LO:S:color=red\t!\t!\t!\n"
        "2d\tff\t2f\t2ryy\n"
        "*\t*\t*v\t*v\n"
        "!\t!\t!LO:TX:t=Test\n"
        "!!Komentarz globalny\n"
        "=46\t=46\t=46\n"
        "*-\t*-\t*-\n"
    )
    original = document.to_text()

    proposal = prepare_merge_move(document, 6, 0)
    replacements = dict(proposal.replacements)

    assert replacements[6] == ()
    assert proposal.proposed_cells == ((8, 1),)
    assert replacements[7][0].text == "!LO:S:color=red\t!\t!\t!\t!"
    assert replacements[8][0].text == "2d\t\tff\t2f\t2ryy"

    block = replacements[9]
    assert [line.description for line in block[:2]] == [
        "nowe: Oboe",
        "nowe: Violin 2",
    ]
    assert [line.text for line in block] == [
        "*\t*\t*\t*v\t*v",
        "*v\t*v\t*\t*",
        "!\t!\t!LO:TX:t=Test",
        "!!Komentarz globalny",
    ]
    assert block[2].source_line == 10
    assert block[3].source_line == 11
    assert replacements[10] == ()
    assert replacements[11] == ()
    assert document.to_text() == original

    candidate_lines: list[str] = []
    for source_line, text in enumerate(document.lines, start=1):
        if source_line in replacements:
            candidate_lines.extend(line.text for line in replacements[source_line])
        else:
            candidate_lines.append(text)

    # Fill the intentionally empty kern proposal solely for structural verification.
    candidate_lines = [line.replace("2d\t\tff", "2d\t2ryy\tff") for line in candidate_lines]
    candidate = HumdrumDocument(candidate_lines, document.trailing_newline)
    trace = trace_spines(candidate)

    assert trace.issue is None
    assert find_split_issues(trace) == ()


def test_complete_non_kern_merge_move_without_existing_closings() -> None:
    document = HumdrumDocument.from_text("**text\n=1\n*^\nla\t.\n*v\t*v\nle\n=2\n*-\n")

    proposal = prepare_merge_move(document, 5, 0)
    replacements = dict(proposal.replacements)

    assert replacements[5] == ()
    assert replacements[6][0].text == "le\t."
    assert proposal.proposed_cells == ((6, 1),)
    assert [line.text for line in replacements[7]] == [
        "*v\t*v",
        "=2",
    ]
    assert replacements[7][0].source_line is None
    assert replacements[7][1].source_line == 7


def test_draft_move_merge_is_one_undo_and_preserves_prior_token_edit() -> None:
    document, draft = make_test_draft()
    draft.edit_token(7, 0, "2e")
    before_move = draft.to_text()

    proposal = draft.move_merge(6, 0)

    assert proposal is not None
    assert proposal.proposed_cells == ((7, 1),)
    assert draft.dirty is True
    assert document.to_text() == draft.original_text

    rendered = draft.rendered_lines()
    assert not any(line.source_line == 6 for line in rendered)

    extended = next(line for line in rendered if line.source_line == 7)
    assert extended.text == "2e\t\tf\t2a\t2ryy"

    new_closing = next(line for line in rendered if line.description == "nowe: Violin 2")
    assert new_closing.source_line is None
    assert new_closing.text == "*v\t*v\t*\t*\t*"

    # The unfilled kern proposal keeps validation red.
    result = validate_draft(draft, start_line=3, end_line=8)
    assert result.state is ValidationState.ERROR
    assert any(message.startswith("Linia 7: Puste pole") for message in result.messages)

    assert draft.undo() is True
    assert draft.to_text() == before_move
    assert draft.token(7, 0) == "2e"

    assert draft.undo() is True
    assert draft.to_text() == document.to_text()


def test_draft_refuses_moving_readonly_helper_merge() -> None:
    document = HumdrumDocument.from_text("**kern\n=1\n*^\n2c\t2ryy\n*v\t*v\n2d\n=2\n*-\n")
    draft = FragmentDraft(document, ())

    with pytest.raises(ValueError, match="tylko do odczytu"):
        draft.move_merge(5, 0)

    assert draft.dirty is False
    assert draft.can_undo is False


def test_draft_merge_move_rejects_removed_source_line_without_changes() -> None:
    _, draft = make_test_draft()
    draft.move_merge(6, 0)
    before = draft.to_text()

    with pytest.raises(ValueError, match="usunięta lub zastąpiona"):
        draft.move_merge(6, 0)

    assert draft.to_text() == before
    assert draft.undo() is True
    assert draft.to_text() == draft.original_text


def test_edits_extended_branch_and_undoes_fill_before_move() -> None:
    _, draft = make_test_draft()
    draft.move_merge(6, 0)

    row_index = next(
        index for index, line in enumerate(draft.rendered_lines()) if line.source_line == 7
    )
    before_fill = draft.to_text()

    assert draft.edit_rendered_token(row_index, 1, "2ryy") is True
    result = validate_draft(draft, start_line=3, end_line=8)
    assert result.state is ValidationState.VALID

    assert draft.undo() is True
    assert draft.to_text() == before_fill

    assert draft.undo() is True
    assert draft.to_text() == draft.original_text


def test_extended_row_keeps_helper_cells_readonly() -> None:
    _, draft = make_test_draft()
    draft.move_merge(6, 0)

    row_index = next(
        index for index, line in enumerate(draft.rendered_lines()) if line.source_line == 7
    )
    before = draft.to_text()

    with pytest.raises(ValueError, match="tylko do odczytu"):
        draft.edit_rendered_token(row_index, 3, "2b")

    assert draft.to_text() == before


def test_both_extended_branches_are_editable() -> None:
    _, draft = make_test_draft()
    draft.move_merge(6, 0)

    row_index = next(
        index for index, line in enumerate(draft.rendered_lines()) if line.source_line == 7
    )

    assert draft.edit_rendered_token(row_index, 0, "2e 2g") is True
    assert draft.edit_rendered_token(row_index, 1, "2ryy") is True
    assert draft.rendered_lines()[row_index].text == "2e 2g\t2ryy\tf\t2a\t2ryy"


def test_missing_data_cells_follow_filling_and_undo() -> None:
    _, draft = make_test_draft()
    assert draft.missing_data_cells == ()

    draft.move_merge(6, 0)
    row_index = next(
        index for index, line in enumerate(draft.rendered_lines()) if line.source_line == 7
    )
    assert draft.missing_data_cells == ((row_index, 1),)

    draft.edit_rendered_token(row_index, 1, "2ryy")
    assert draft.missing_data_cells == ()

    assert draft.undo() is True
    assert draft.missing_data_cells == ((row_index, 1),)

    assert draft.undo() is True
    assert draft.missing_data_cells == ()


def test_missing_data_cells_accept_null_token() -> None:
    _, draft = make_test_draft()
    draft.move_merge(6, 0)
    row_index = next(
        index for index, line in enumerate(draft.rendered_lines()) if line.source_line == 7
    )

    draft.edit_rendered_token(row_index, 1, ".")

    assert draft.missing_data_cells == ()


def test_proposed_token_requires_approval() -> None:
    _, draft = make_test_draft()
    draft.move_merge(6, 0)

    assert draft.propose_token(7, 1, "2ryy") is True
    assert draft.pending_suggestions == ((7, 1),)
    assert draft.missing_data_cells == ()

    result = validate_draft(draft, start_line=3, end_line=8)
    assert result.state is ValidationState.PENDING

    assert draft.approve_suggestions() is True
    assert draft.pending_suggestions == ()

    result = validate_draft(draft, start_line=3, end_line=8)
    assert result.state is ValidationState.VALID


def test_undo_restores_approval_then_removes_proposed_token() -> None:
    _, draft = make_test_draft()
    draft.move_merge(6, 0)
    before_proposal = draft.to_text()

    draft.propose_token(7, 1, "2ryy")
    proposed_text = draft.to_text()
    draft.approve_suggestions()

    assert draft.undo() is True
    assert draft.to_text() == proposed_text
    assert draft.pending_suggestions == ((7, 1),)

    assert draft.undo() is True
    assert draft.to_text() == before_proposal
    assert draft.pending_suggestions == ()


def test_proposal_does_not_overwrite_manual_fill() -> None:
    _, draft = make_test_draft()
    draft.move_merge(6, 0)
    row_index = next(
        index for index, line in enumerate(draft.rendered_lines()) if line.source_line == 7
    )
    draft.edit_rendered_token(row_index, 1, "2r")

    assert draft.propose_token(7, 1, "2ryy") is False
    assert draft.pending_suggestions == ()
    assert draft.rendered_lines()[row_index].text.split("\t")[1] == "2r"


def test_repeated_proposal_is_noop() -> None:
    _, draft = make_test_draft()
    draft.move_merge(6, 0)
    draft.propose_token(7, 1, "2ryy")

    assert draft.propose_token(7, 1, "2ryy") is False

    assert draft.undo() is True
    assert draft.pending_suggestions == ()
    assert draft.missing_data_cells != ()


def test_approval_without_proposals_is_noop() -> None:
    _, draft = make_test_draft()

    assert draft.approve_suggestions() is False
    assert draft.can_undo is False


def test_proposal_group_is_one_undo_operation() -> None:
    _, draft = make_test_draft()
    draft.move_merge(6, 0)
    row_index = next(
        index for index, line in enumerate(draft.rendered_lines()) if line.source_line == 7
    )
    draft.edit_rendered_token(row_index, 0, "")
    before_group = draft.to_text()

    assert (
        draft.propose_tokens(
            (
                (7, 0, "2d"),
                (7, 1, "2ryy"),
            )
        )
        is True
    )
    assert draft.pending_suggestions == ((7, 0), (7, 1))

    assert draft.undo() is True
    assert draft.to_text() == before_group
    assert draft.pending_suggestions == ()

    # Cofnięcie grupy zachowało wcześniejszą historię edycji.
    assert draft.undo() is True
    assert draft.rendered_lines()[row_index].text.split("\t")[0] == "2d"


def test_invalid_proposal_group_rolls_back_all_changes() -> None:
    _, draft = make_test_draft()
    draft.move_merge(6, 0)
    before_group = draft.to_text()

    with pytest.raises(ValueError):
        draft.propose_tokens(
            (
                (7, 1, "2ryy"),
                (7, 4, "2ryy"),
            )
        )

    assert draft.to_text() == before_group
    assert draft.pending_suggestions == ()

    # Nie pozostał dodatkowy krok cofania po nieudanej operacji.
    assert draft.undo() is True
    assert draft.to_text() == draft.original_text


def test_repeated_proposal_group_does_not_add_undo_step() -> None:
    _, draft = make_test_draft()
    draft.move_merge(6, 0)
    before_group = draft.to_text()
    tokens = ((7, 1, "2ryy"),)

    assert draft.propose_tokens(tokens) is True
    assert draft.propose_tokens(tokens) is False

    assert draft.undo() is True
    assert draft.to_text() == before_group
    assert draft.pending_suggestions == ()


def test_proposal_group_rejects_duplicate_cells() -> None:
    _, draft = make_test_draft()
    draft.move_merge(6, 0)
    before_group = draft.to_text()

    with pytest.raises(ValueError, match="powtarza"):
        draft.propose_tokens(
            (
                (7, 1, "2ryy"),
                (7, 1, "."),
            )
        )

    assert draft.to_text() == before_group
    assert draft.pending_suggestions == ()


def test_empty_proposal_group_is_noop() -> None:
    _, draft = make_test_draft()

    assert draft.propose_tokens(()) is False
    assert draft.can_undo is False


def test_generated_merge_fill_requires_approval_and_preserves_document() -> None:
    document, draft = make_test_draft()
    original = document.to_text()

    suggestions = suggest_merge_fill(document, 6, 0)
    draft.move_merge(6, 0)
    before_fill = draft.to_text()

    assert (
        draft.propose_tokens(
            tuple((item.source_line, item.source_column, item.token) for item in suggestions)
        )
        is True
    )

    result = validate_draft(draft, start_line=3, end_line=8)
    assert result.state is ValidationState.PENDING

    proposed_text = draft.to_text()
    assert draft.approve_suggestions() is True

    result = validate_draft(draft, start_line=3, end_line=8)
    assert result.state is ValidationState.VALID
    assert document.to_text() == original

    # Cofnij zatwierdzenie.
    assert draft.undo() is True
    assert draft.to_text() == proposed_text
    assert (
        validate_draft(
            draft,
            start_line=3,
            end_line=8,
        ).state
        is ValidationState.PENDING
    )

    # Cofnij całą grupę propozycji.
    assert draft.undo() is True
    assert draft.to_text() == before_fill
    assert draft.pending_suggestions == ()

    # Cofnij przeniesienie scalenia.
    assert draft.undo() is True
    assert draft.to_text() == original


def test_draft_validation_rejects_shortened_fill_rest() -> None:
    _, draft = make_test_draft()
    draft.move_merge(6, 0)
    draft.propose_token(7, 1, "4ryy")
    draft.approve_suggestions()

    result = validate_draft(draft, start_line=3, end_line=8)

    assert result.state is ValidationState.ERROR
    assert any("różne pozostałe długości" in message for message in result.messages)


def test_draft_validation_rejects_null_without_active_duration() -> None:
    _, draft = make_test_draft()
    draft.move_merge(6, 0)
    draft.propose_token(7, 1, ".")
    draft.approve_suggestions()

    result = validate_draft(draft, start_line=3, end_line=8)

    assert result.state is ValidationState.ERROR
    assert any("kropka nie kontynuuje" in message for message in result.messages)


def test_rhythm_error_takes_priority_over_pending_approval() -> None:
    _, draft = make_test_draft()
    draft.move_merge(6, 0)
    draft.propose_token(7, 1, "4ryy")

    result = validate_draft(draft, start_line=3, end_line=8)

    assert draft.pending_suggestions == ((7, 1),)
    assert result.state is ValidationState.ERROR


def test_split_move_targets_first_data_row() -> None:
    document = HumdrumDocument.from_text("**kern\n=1\n4c\n*^\n4d\t4ryy\n*v\t*v\n=2\n*-\n")
    original = document.to_text()

    plan = plan_split_move(document, 4, 0)

    assert plan.source_line == 4
    assert plan.target_line == 3
    assert plan.start_barline == 2
    assert plan.identity.root_column == 0
    assert document.to_text() == original


def test_split_move_keeps_leading_global_comments_before_opening() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n"
        "=1\n"
        "!!Komentarz globalny\n"
        "!!!OMD: Allegro\n"
        "!Komentarz lokalny\n"
        "*clefG2\n"
        "4c\n"
        "*^\n"
        "4d\t4ryy\n"
        "*v\t*v\n"
        "=2\n"
        "*-\n"
    )

    plan = plan_split_move(document, 8, 0)

    assert plan.target_line == 5
    assert plan.start_barline == 2


def test_split_move_without_barline_preserves_header() -> None:
    document = HumdrumDocument.from_text("**kern\n*clefG2\n4c\n*^\n4d\t4ryy\n*v\t*v\n*-\n")

    plan = plan_split_move(document, 4, 0)

    assert plan.target_line == 3
    assert plan.start_barline is None


def test_split_move_already_at_start_targets_its_own_row() -> None:
    document = HumdrumDocument.from_text("**kern\n=1\n*^\n4c\t4ryy\n*v\t*v\n=2\n*-\n")

    plan = plan_split_move(document, 3, 0)

    assert plan.target_line == plan.source_line


def test_nested_split_move_keeps_parent_opening_first() -> None:
    document = HumdrumDocument.from_text("**kern\n=1\n*^\n*^\t*\n4c\t4e\t4g\n*v\t*v\t*v\n=2\n*-\n")

    plan = plan_split_move(document, 4, 0)

    assert plan.branch.path == (0,)
    assert plan.target_line == 4


def test_split_move_rejects_branch_created_after_first_data() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n=1\n4c\n*^\n*^\t*\n4d\t4e\t4g\n*v\t*v\t*v\n=2\n*-\n"
    )

    with pytest.raises(HumdrumError, match="gałąź powstaje"):
        plan_split_move(document, 5, 0)


def test_split_move_inserts_opening_and_extends_data() -> None:
    document = HumdrumDocument.from_text("**kern\n=1\n4c\n*^\n4d\t4ryy\n*v\t*v\n=2\n*-\n")
    original = document.to_text()

    proposal = prepare_split_move(document, 4, 0)
    replacements = dict(proposal.replacements)

    opening, data = replacements[3]
    assert opening.source_line is None
    assert opening.anchor_line == 3
    assert opening.text == "*^"
    assert data.source_line == 3
    assert data.text == "4c\t"
    assert replacements[4] == ()
    assert proposal.proposed_cells == ((3, 1),)
    assert document.to_text() == original


def test_split_move_fills_comments_and_copies_interpretations() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n"
        "=1\n"
        "!!Komentarz globalny\n"
        "!Komentarz lokalny\n"
        "*clefG2\n"
        "4c\n"
        "*^\n"
        "4d\t4ryy\n"
        "*v\t*v\n"
        "=2\n"
        "*-\n"
    )

    proposal = prepare_split_move(document, 7, 0)
    replacements = dict(proposal.replacements)

    assert 3 not in replacements
    assert replacements[4][0].text == "*^"
    assert replacements[4][1].text == "!Komentarz lokalny\t!"
    assert replacements[5][0].text == "*clefG2\t*clefG2"
    assert replacements[6][0].text == "4c\t"
    assert proposal.proposed_cells == ((6, 1),)


def test_split_move_preserves_other_spine_opening_in_source_row() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n"
        "=1\t=1\n"
        "4c\t4e\n"
        "*^\t*^\n"
        "4d\t4ryy\t4f\t4ryy\n"
        "*v\t*v\t*\t*\n"
        "*\t*v\t*v\n"
        "=2\t=2\n"
        "*-\t*-\n"
    )

    proposal = prepare_split_move(document, 4, 0)
    replacements = dict(proposal.replacements)

    assert replacements[3][0].text == "*^\t*"
    assert replacements[3][1].text == "4c\t\t4e"
    assert replacements[4][0].source_line == 4
    assert replacements[4][0].text == "*\t*\t*^"


def test_split_move_uses_dots_for_non_kern_data() -> None:
    document = HumdrumDocument.from_text(
        "**dynam\t**kern\n=1\t=1\np\t4c\n*^\t*\nf\tff\t4d\n*v\t*v\t*\n=2\t=2\n*-\t*-\n"
    )

    proposal = prepare_split_move(document, 4, 0)
    replacements = dict(proposal.replacements)

    assert replacements[3][1].text == "p\t.\t4c"
    assert proposal.proposed_cells == ((3, 1),)


def test_split_move_already_at_start_has_no_replacements() -> None:
    document = HumdrumDocument.from_text("**kern\n=1\n*^\n4c\t4ryy\n*v\t*v\n=2\n*-\n")

    proposal = prepare_split_move(document, 3, 0)

    assert proposal.replacements == ()
    assert proposal.proposed_cells == ()


def make_split_test_draft() -> tuple[HumdrumDocument, FragmentDraft]:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n"
        '*I"Violin 2\t*I"Trumpet\n'
        "=45\t=45\n"
        "4c\t4e\n"
        "*^\t*\n"
        "4d\t4ryy\t4f\n"
        "*v\t*v\t*\n"
        "=46\t=46\n"
        "*-\t*-\n"
    )
    trace = trace_spines(document)
    issues = find_split_issues(trace)
    problem = group_split_issues(trace, issues)[0]
    rows = build_fragment_rows(
        trace,
        problem,
        build_measure_view(trace, problem, issues),
    )
    return document, FragmentDraft(document, rows)


def test_draft_split_move_is_one_undo_and_preserves_prior_edit() -> None:
    document, draft = make_split_test_draft()
    draft.edit_token(4, 0, "4g")
    before_move = draft.to_text()

    proposal = draft.move_split(5, 0)

    assert proposal is not None
    assert proposal.proposed_cells == ((4, 1),)
    assert document.to_text() == draft.original_text

    rendered = draft.rendered_lines()
    extended = next(line for line in rendered if line.source_line == 4)
    assert extended.text == "4g\t\t4e"
    assert not any(line.source_line == 5 for line in rendered)

    assert draft.undo() is True
    assert draft.to_text() == before_move

    assert draft.undo() is True
    assert draft.to_text() == draft.original_text


def test_draft_split_move_allows_editing_both_branches() -> None:
    _, draft = make_split_test_draft()
    draft.move_split(5, 0)
    row_index = next(
        index for index, line in enumerate(draft.rendered_lines()) if line.source_line == 4
    )

    assert draft.edit_rendered_token(row_index, 0, "4g") is True
    assert draft.edit_rendered_token(row_index, 1, "4ryy") is True

    result = validate_draft(draft, start_line=3, end_line=8)
    assert result.state is ValidationState.VALID

    extended = draft.rendered_lines()[row_index]
    assert extended.text == "4g\t4ryy\t4e"


def test_draft_split_move_keeps_other_instrument_readonly() -> None:
    _, draft = make_split_test_draft()
    draft.move_split(5, 0)
    row_index = next(
        index for index, line in enumerate(draft.rendered_lines()) if line.source_line == 4
    )
    before_edit = draft.to_text()

    with pytest.raises(ValueError, match="tylko do odczytu"):
        draft.edit_rendered_token(row_index, 2, "4g")

    assert draft.to_text() == before_edit


def test_generated_split_fill_requires_approval() -> None:
    document, draft = make_split_test_draft()
    original = document.to_text()
    suggestions = suggest_split_fill(document, 5, 0)

    draft.move_split(5, 0)
    draft.propose_tokens(
        tuple((item.source_line, item.source_column, item.token) for item in suggestions)
    )

    assert (
        validate_draft(
            draft,
            start_line=3,
            end_line=8,
        ).state
        is ValidationState.PENDING
    )

    assert draft.approve_suggestions() is True
    assert (
        validate_draft(
            draft,
            start_line=3,
            end_line=8,
        ).state
        is ValidationState.VALID
    )

    assert document.to_text() == original

    assert draft.undo() is True
    assert (
        validate_draft(
            draft,
            start_line=3,
            end_line=8,
        ).state
        is ValidationState.PENDING
    )

    assert draft.undo() is True
    assert draft.missing_data_cells != ()

    assert draft.undo() is True
    assert draft.to_text() == original


def test_rendered_index_maps_source_line_after_merge_move() -> None:
    _, draft = make_test_draft()

    assert draft.rendered_index(7) == 6

    draft.move_merge(6, 0)

    assert draft.rendered_index(7) == 5
    assert draft.rendered_lines()[5].source_line == 7

    assert draft.undo() is True
    assert draft.rendered_index(7) == 6


def test_rendered_index_maps_source_line_after_split_move() -> None:
    _, draft = make_split_test_draft()

    assert draft.rendered_index(4) == 3

    draft.move_split(5, 0)

    assert draft.rendered_index(4) == 4
    assert draft.rendered_lines()[4].source_line == 4

    assert draft.undo() is True
    assert draft.rendered_index(4) == 3


def test_rendered_index_reports_removed_source_line() -> None:
    _, draft = make_split_test_draft()
    draft.move_split(5, 0)

    with pytest.raises(ValueError, match="usunięta lub zastąpiona"):
        draft.rendered_index(5)


def test_candidate_line_maps_back_to_source_after_merge_move() -> None:
    _, draft = make_test_draft()
    draft.move_merge(6, 0)
    rendered = draft.rendered_lines()

    mapped = draft._map_candidate_line(
        DraftLine(source_line=6, text="zmieniony wiersz"),
        rendered,
    )

    assert mapped.source_line == 7
    assert mapped.text == "zmieniony wiersz"


def test_candidate_line_preserves_inserted_opening_identity() -> None:
    _, draft = make_split_test_draft()
    draft.move_split(5, 0)
    rendered = draft.rendered_lines()
    opening_index = next(
        index
        for index, line in enumerate(rendered)
        if line.source_line is None and "otwarcie" in line.description
    )
    previous = rendered[opening_index]

    mapped = draft._map_candidate_line(
        DraftLine(source_line=opening_index + 1, text=previous.text),
        rendered,
    )

    assert mapped.source_line is None
    assert mapped.description == previous.description
    assert mapped.anchor_line == previous.anchor_line


def test_candidate_anchor_maps_to_original_source_line() -> None:
    _, draft = make_split_test_draft()
    draft.move_split(5, 0)
    rendered = draft.rendered_lines()
    current_line = draft.rendered_index(4) + 1

    mapped = draft._map_candidate_line(
        DraftLine(
            source_line=None,
            text="*\t*\t*",
            description="nowy wiersz",
            anchor_line=current_line,
        ),
        rendered,
    )

    assert mapped.source_line is None
    assert mapped.anchor_line == 4
    assert mapped.description == "nowy wiersz"


def test_candidate_line_rejects_number_outside_draft() -> None:
    _, draft = make_test_draft()
    rendered = draft.rendered_lines()

    with pytest.raises(ValueError, match="wykracza"):
        draft._map_candidate_line(
            DraftLine(source_line=len(rendered) + 1, text="*"),
            rendered,
        )


def test_composed_replacement_uses_original_source_number() -> None:
    _, draft = make_test_draft()
    draft.move_merge(6, 0)
    before = draft.to_text()
    current_line = draft.rendered_index(7) + 1

    composed, included = draft._compose_replacements(
        (
            (
                current_line,
                (
                    DraftLine(
                        source_line=current_line,
                        text="2d\t2ryy\tf\t2a\t2ryy",
                    ),
                ),
            ),
        )
    )

    assert composed[7][0].source_line == 7
    assert composed[7][0].text == "2d\t2ryy\tf\t2a\t2ryy"
    assert included == {7}
    assert draft.to_text() == before


def test_composed_replacement_preserves_previously_inserted_opening() -> None:
    _, draft = make_split_test_draft()
    draft.move_split(5, 0)
    rendered = draft.rendered_lines()
    current_line = draft.rendered_index(4) + 1
    opening = rendered[current_line - 2]

    composed, included = draft._compose_replacements(
        (
            (
                current_line,
                (
                    DraftLine(
                        source_line=current_line,
                        text="4c\t4ryy\t4e",
                    ),
                ),
            ),
        )
    )

    assert composed[4][0] == opening
    assert composed[4][1].source_line == 4
    assert composed[4][1].text == "4c\t4ryy\t4e"
    assert composed[5] == ()
    assert included == {4}


def test_composed_replacement_can_remove_previously_inserted_row() -> None:
    _, draft = make_split_test_draft()
    draft.move_split(5, 0)
    rendered = draft.rendered_lines()
    opening_index = next(
        index
        for index, line in enumerate(rendered)
        if line.source_line is None and "otwarcie" in line.description
    )

    composed, included = draft._compose_replacements(((opening_index + 1, ()),))

    assert len(composed[4]) == 1
    assert composed[4][0].source_line == 4
    assert composed[4][0].text == "4c\t\t4e"
    assert included == {4}


def test_composed_replacement_preserves_unrelated_token_edit() -> None:
    _, draft = make_test_draft()
    draft.edit_token(5, 0, "2g 2b")
    before = draft.to_text()

    composed, included = draft._compose_replacements(
        (
            (
                7,
                (DraftLine(source_line=7, text="2e\tf\t2a\t2ryy"),),
            ),
        )
    )

    assert 5 not in composed
    assert included == {7}
    assert draft.token(5, 0) == "2g 2b"
    assert draft.to_text() == before


def make_pending_split_preview(
    column: int,
) -> tuple[FragmentDraft, tuple[DraftLine, ...]]:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n"
        '*I"Violin 2\t*I"Trumpet\n'
        "=1\t=1\n"
        "4ryy\t4e\n"
        "*^\t*^\n"
        "4c\t4ryy\t4g\t4ryy\n"
        "*v\t*v\t*\t*\n"
        "*\t*v\t*v\n"
        "=2\t=2\n"
        "*-\t*-\n"
    )
    trace = trace_spines(document)
    issues = find_split_issues(trace)
    problem = group_split_issues(trace, issues)[0]
    rows = build_fragment_rows(
        trace,
        problem,
        build_measure_view(trace, problem, issues),
    )
    draft = FragmentDraft(document, rows)
    draft.propose_token(4, column, draft.token(4, column))

    rendered = draft.rendered_lines()
    proposal = prepare_split_move(document, 5, 0)
    updates = dict(proposal.replacements)
    preview: list[DraftLine] = []

    for number, line in enumerate(rendered, start=1):
        if number in updates:
            preview.extend(
                draft._map_candidate_line(candidate, rendered) for candidate in updates[number]
            )
        else:
            preview.append(line)

    return draft, tuple(preview)


def test_pending_proposal_moves_with_column_of_its_instrument() -> None:
    draft, preview = make_pending_split_preview(1)

    mapped = draft._remap_pending_suggestions(preview)

    assert mapped == {(4, 2)}
    assert draft.pending_suggestions == ((4, 1),)


def test_pending_proposal_stays_in_original_left_branch() -> None:
    draft, preview = make_pending_split_preview(0)

    mapped = draft._remap_pending_suggestions(preview)

    assert mapped == {(4, 0)}
    assert draft.pending_suggestions == ((4, 0),)


def test_pending_remapping_rejects_lost_token() -> None:
    draft, preview = make_pending_split_preview(1)
    changed = tuple(
        DraftLine(
            source_line=line.source_line,
            text="4ryy\t\t4f" if line.source_line == 4 else line.text,
            description=line.description,
            anchor_line=line.anchor_line,
        )
        for line in preview
    )
    before = draft.to_text()

    with pytest.raises(HumdrumError, match="utraciłaby"):
        draft._remap_pending_suggestions(changed)

    assert draft.to_text() == before
    assert draft.pending_suggestions == ((4, 1),)


def test_applies_two_structural_changes_with_separate_undo_steps() -> None:
    draft, _ = make_pending_split_preview(1)
    before_first = draft.to_text()
    original_pending = draft.pending_suggestions

    candidate = HumdrumDocument.from_text(draft.to_text())
    first = prepare_split_move(candidate, 5, 0)

    assert draft._apply_candidate_replacements(first.replacements) is True
    after_first = draft.to_text()
    assert draft.pending_suggestions == ((4, 2),)

    # Uzupełnij puste pole przed przygotowaniem kolejnej operacji.
    assert draft.propose_token(4, 1, "4ryy") is True
    before_second = draft.to_text()
    assert draft.pending_suggestions == ((4, 1), (4, 2))

    candidate = HumdrumDocument.from_text(draft.to_text())
    current_line = draft.rendered_index(5) + 1
    second = prepare_split_move(candidate, current_line, 1)

    assert draft._apply_candidate_replacements(second.replacements) is True
    assert draft.to_text() != before_second
    assert draft.pending_suggestions == ((4, 1), (4, 2))

    # Cofnij drugie przeniesienie.
    assert draft.undo() is True
    assert draft.to_text() == before_second
    assert draft.pending_suggestions == ((4, 1), (4, 2))

    # Cofnij propozycję wypełnienia.
    assert draft.undo() is True
    assert draft.to_text() == after_first
    assert draft.pending_suggestions == ((4, 2),)

    # Cofnij pierwsze przeniesienie.
    assert draft.undo() is True
    assert draft.to_text() == before_first
    assert draft.pending_suggestions == original_pending


def test_applying_invalid_replacements_preserves_draft_and_history() -> None:
    _, draft = make_test_draft()
    draft.edit_token(5, 0, "2g 2b")
    before = draft.to_text()

    with pytest.raises(ValueError, match="wykracza"):
        draft._apply_candidate_replacements(
            (
                (
                    len(draft.rendered_lines()) + 1,
                    (DraftLine(source_line=None, text="*"),),
                ),
            )
        )

    assert draft.to_text() == before
    assert draft.undo() is True
    assert draft.to_text() == draft.original_text


def test_applying_identical_replacement_is_noop() -> None:
    _, draft = make_test_draft()
    line = draft.rendered_lines()[4]

    assert draft._apply_candidate_replacements(((5, (line,)),)) is False
    assert draft.can_undo is False


def test_applying_empty_replacement_group_is_noop() -> None:
    _, draft = make_test_draft()

    assert draft._apply_candidate_replacements(()) is False
    assert draft.can_undo is False


def test_move_split_supports_successive_operations_by_source_number() -> None:
    draft, _ = make_pending_split_preview(1)
    before_first = draft.to_text()

    first = draft.move_split(5, 0)
    assert first is not None
    assert first.proposed_cells == ((4, 1),)
    assert draft.pending_suggestions == ((4, 2),)

    draft.propose_token(4, 1, "4ryy")
    before_second = draft.to_text()

    # Numer 5 pochodzi nadal z oryginalnego pliku.
    second = draft.move_split(5, 1)
    assert second is not None
    assert second.proposed_cells == ((4, 3),)
    assert draft.pending_suggestions == ((4, 1), (4, 2))

    extended = draft.rendered_lines()[draft.rendered_index(4)]
    assert extended.text == "4ryy\t4ryy\t4e\t"

    assert draft.undo() is True
    assert draft.to_text() == before_second
    assert draft.pending_suggestions == ((4, 1), (4, 2))

    assert draft.undo() is True
    assert draft.pending_suggestions == ((4, 2),)

    assert draft.undo() is True
    assert draft.to_text() == before_first
    assert draft.pending_suggestions == ((4, 1),)


def test_move_split_rejects_readonly_instrument_without_changes() -> None:
    _, draft = make_split_test_draft()
    before = draft.to_text()

    with pytest.raises(ValueError, match="tylko do odczytu"):
        draft.move_split(5, 1)

    assert draft.to_text() == before
    assert draft.can_undo is False


def test_move_split_reports_source_row_removed_by_previous_operation() -> None:
    _, draft = make_split_test_draft()
    draft.move_split(5, 0)
    before = draft.to_text()

    with pytest.raises(ValueError, match="usunięta lub zastąpiona"):
        draft.move_split(5, 0)

    assert draft.to_text() == before
    assert draft.undo() is True
    assert draft.to_text() == draft.original_text


def test_successive_merge_moves_preserve_fill_and_source_mapping() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n"
        '*I"Violin 2\t*I"Trumpet\n'
        "=1\t=1\n"
        "*^\t*^\n"
        "4c\t4ryy\t4e\t4ryy\n"
        "*v\t*v\t*\t*\n"
        "4d\t4f\t4ryy\n"
        "*\t*v\t*v\n"
        "4e\t4g\n"
        "=2\t=2\n"
        "*-\t*-\n"
    )
    trace = trace_spines(document)
    issues = find_split_issues(trace)
    problem = group_split_issues(trace, issues)[0]
    rows = build_fragment_rows(
        trace,
        problem,
        build_measure_view(trace, problem, issues),
    )
    draft = FragmentDraft(document, rows)

    first = draft.move_merge(6, 0)
    assert first is not None
    draft.propose_tokens(
        (
            (7, 1, "2ryy"),
            (9, 1, "."),
        )
    )
    before_second = draft.to_text()

    second = draft.move_merge(8, 1)
    assert second is not None
    assert second.proposed_cells == ((9, 3),)
    assert draft.pending_suggestions == ((7, 1), (9, 1))

    row = draft.rendered_lines()[draft.rendered_index(9)]
    assert row.text == "4e\t.\t4g\t"

    draft.propose_token(9, 3, "4ryy")
    assert (
        validate_draft(
            draft,
            start_line=3,
            end_line=10,
        ).state
        is ValidationState.PENDING
    )

    draft.approve_suggestions()
    assert (
        validate_draft(
            draft,
            start_line=3,
            end_line=10,
        ).state
        is ValidationState.VALID
    )

    # Cofnij zatwierdzenie, drugie wypełnienie i drugie przeniesienie.
    assert draft.undo() is True
    assert draft.undo() is True
    assert draft.undo() is True
    assert draft.to_text() == before_second
    assert draft.pending_suggestions == ((7, 1), (9, 1))
    assert document.to_text() == draft.original_text


def test_separate_merges_after_split_move_preserves_draft_history() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\t**kern\n"
        '*I"Violin 2\t*\t*I"Trumpet\n'
        "=1\t=1\t=1\n"
        "4c\tp\t4e\n"
        "*^\t*\t*^\n"
        "4d\t4ryy\tf\t4f\t4ryy\n"
        "*v\t*v\t*\t*v\t*v\n"
        "=2\t=2\t=2\n"
        "*-\t*-\t*-\n"
    )
    trace = trace_spines(document)
    issues = find_split_issues(trace)
    problem = group_split_issues(trace, issues)[0]
    rows = build_fragment_rows(
        trace,
        problem,
        build_measure_view(trace, problem, issues),
    )
    draft = FragmentDraft(document, rows)

    draft.move_split(5, 0)
    draft.propose_token(4, 1, "4ryy")
    before_separation = draft.to_text()

    assert draft.separate_merges(7) is True
    assert draft.pending_suggestions == ((4, 1),)

    closing = [
        line
        for line in draft.rendered_lines()
        if line.source_line is None and line.anchor_line == 7
    ]
    assert [line.description for line in closing] == [
        "nowe: Trumpet",
        "nowe: Violin 2",
    ]
    assert [line.text for line in closing] == [
        "*\t*\t*\t*v\t*v",
        "*v\t*v\t*\t*",
    ]

    assert draft.separate_merges(7) is False

    assert draft.undo() is True
    assert draft.to_text() == before_separation
    assert draft.pending_suggestions == ((4, 1),)

    assert draft.undo() is True
    assert draft.pending_suggestions == ()

    assert draft.undo() is True
    assert draft.to_text() == draft.original_text
    assert document.to_text() == draft.original_text


def test_merge_reopening_plan_finds_pair_in_same_measure() -> None:
    document = HumdrumDocument.from_text(
        '**kern\n*I"Bassoon\n*^\n=46\t=46\n8c\t8ryy\n*v\t*v\n8d\n*^\n8e\t8ryy\n=47\t=47\n*-\t*-\n'
    )
    original = document.to_text()

    plan = plan_merge_reopening(document, 6, 0)

    assert plan.source_line == 6
    assert plan.reopening_line == 8
    assert plan.identity.instrument == "Bassoon"
    assert plan.parent.path == ()
    assert tuple(branch.path for branch in plan.branches) == ((0,), (1,))
    assert document.to_text() == original


def test_merge_reopening_plan_allows_comments_and_interpretations() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n"
        "*^\n"
        "=1\t=1\n"
        "8c\t8ryy\n"
        "*v\t*v\n"
        "!!Komentarz globalny\n"
        "!Komentarz lokalny\n"
        "*clefF4\n"
        "8d\n"
        "*^\n"
        "8e\t8ryy\n"
        "=2\t=2\n"
        "*-\t*-\n"
    )

    plan = plan_merge_reopening(document, 5, 0)

    assert plan.reopening_line == 10


def test_merge_reopening_plan_does_not_cross_barline() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n*^\n=1\t=1\n8c\t8ryy\n*v\t*v\n8d\n=2\n*^\n8e\t8ryy\n*-\t*-\n"
    )

    with pytest.raises(HumdrumError, match="tym samym takcie"):
        plan_merge_reopening(document, 5, 0)


def test_merge_reopening_plan_ignores_opening_of_other_instrument() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n"
        "*^\t*\n"
        "=1\t=1\t=1\n"
        "8c\t8ryy\t8e\n"
        "*v\t*v\t*\n"
        "*\t*^\n"
        "8d\t8f\t8ryy\n"
        "=2\t=2\t=2\n"
        "*-\t*-\t*-\n"
    )

    with pytest.raises(HumdrumError, match="Nie znaleziono"):
        plan_merge_reopening(document, 5, 0)


def test_merge_reopening_removes_pair_and_extends_data() -> None:
    document = HumdrumDocument.from_text(
        '**kern\n*I"Bassoon\n*^\n=46\t=46\n8c\t8ryy\n*v\t*v\n8d\n*^\n8e\t8ryy\n=47\t=47\n*-\t*-\n'
    )
    original = document.to_text()

    proposal = prepare_merge_reopening(document, 6, 0)
    replacements = dict(proposal.replacements)

    assert replacements[6] == ()
    assert replacements[7][0].source_line == 7
    assert replacements[7][0].text == "8d\t"
    assert replacements[8] == ()
    assert proposal.proposed_cells == ((7, 1),)
    assert document.to_text() == original


def test_merge_reopening_preserves_comments_and_interpretations() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n"
        "*^\n"
        "=1\t=1\n"
        "8c\t8ryy\n"
        "*v\t*v\n"
        "!!Komentarz globalny\n"
        "!Komentarz lokalny\n"
        "*clefF4\n"
        "8d\n"
        "*^\n"
        "8e\t8ryy\n"
        "=2\t=2\n"
        "*-\t*-\n"
    )

    proposal = prepare_merge_reopening(document, 5, 0)
    replacements = dict(proposal.replacements)

    assert 6 not in replacements
    assert replacements[7][0].text == "!Komentarz lokalny\t!"
    assert replacements[8][0].text == "*clefF4\t*clefF4"
    assert replacements[9][0].text == "8d\t"
    assert proposal.proposed_cells == ((9, 1),)


def test_merge_reopening_preserves_other_instrument_operations() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n"
        "*^\t*\n"
        "=1\t=1\t=1\n"
        "8c\t8ryy\t8e\n"
        "*v\t*v\t*^\n"
        "8d\t8f\t8ryy\n"
        "*^\t*v\t*v\n"
        "8e\t8ryy\t8g\n"
        "=2\t=2\t=2\n"
        "*-\t*-\t*-\n"
    )

    proposal = prepare_merge_reopening(document, 5, 0)
    replacements = dict(proposal.replacements)

    assert replacements[5][0].text == "*\t*\t*^"
    assert replacements[6][0].text == "8d\t\t8f\t8ryy"
    assert replacements[7][0].text == "*\t*\t*v\t*v"


def test_merge_reopening_uses_dots_for_non_kern_data() -> None:
    document = HumdrumDocument.from_text(
        "**dynam\t**kern\n"
        "*^\t*\n"
        "=1\t=1\t=1\n"
        "p\tf\t8c\n"
        "*v\t*v\t*\n"
        "ff\t8d\n"
        "*^\t*\n"
        "p\tf\t8e\n"
        "=2\t=2\t=2\n"
        "*-\t*-\t*-\n"
    )

    proposal = prepare_merge_reopening(document, 5, 0)
    replacements = dict(proposal.replacements)

    assert replacements[6][0].text == "ff\t.\t8d"
    assert proposal.proposed_cells == ((6, 1),)


def test_merge_reopenings_combines_all_pairs_and_preserves_final_merge() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n"
        "*^\n"
        "=1\t=1\n"
        "8c\t8ryy\n"
        "*v\t*v\n"
        "8d\n"
        "*^\n"
        "8e\t8ryy\n"
        "*v\t*v\n"
        "8f\n"
        "*^\n"
        "8g\t8ryy\n"
        "*v\t*v\n"
        "=2\n"
        "*-\n"
    )
    original = document.to_text()

    proposal = prepare_merge_reopenings(document, 5, 0)
    replacements = dict(proposal.replacements)

    for source_line in (5, 7, 9, 11):
        assert replacements[source_line] == ()

    assert replacements[6][0].text == "8d\t"
    assert replacements[10][0].text == "8f\t"
    assert proposal.proposed_cells == ((6, 1), (10, 1))

    assert 13 not in replacements
    assert document.to_text() == original


def test_merge_reopenings_does_not_include_pairs_from_next_measure() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n"
        "*^\n"
        "=1\t=1\n"
        "8c\t8ryy\n"
        "*v\t*v\n"
        "8d\n"
        "*^\n"
        "8e\t8ryy\n"
        "=2\t=2\n"
        "*v\t*v\n"
        "8f\n"
        "*^\n"
        "8g\t8ryy\n"
        "=3\t=3\n"
        "*-\t*-\n"
    )

    proposal = prepare_merge_reopenings(document, 5, 0)
    replacements = dict(proposal.replacements)

    assert set(replacements) == {5, 6, 7}
    assert proposal.proposed_cells == ((6, 1),)
