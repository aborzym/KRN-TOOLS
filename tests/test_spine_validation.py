import pytest

from spineworks.humdrum import HumdrumDocument, HumdrumError
from spineworks.spine_validation import (
    FragmentDraft,
    RecordKind,
    ValidationState,
    build_fragment_rows,
    build_measure_view,
    find_split_issues,
    group_split_issues,
    plan_merge_move,
    prepare_closing_block,
    prepare_merge_extension,
    prepare_merge_move,
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
