from spineworks.humdrum import HumdrumDocument
from spineworks.spine_validation import (
    RecordKind,
    build_measure_view,
    find_split_issues,
    group_split_issues,
    read_records,
    trace_spines,
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
