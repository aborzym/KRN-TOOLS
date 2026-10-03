from fractions import Fraction

import pytest

from spineworks.humdrum import HumdrumDocument, HumdrumError
from spineworks.spine_rhythm import (
    remap_spine_remaining,
    suggest_merge_fill,
    suggest_split_fill,
    trace_rhythm,
)
from spineworks.spine_validation import SpineBranch, SpineIdentity


def rhythm_branch(
    path: tuple[int, ...] = (),
    opening_lines: tuple[int, ...] = (),
    spine_type: str = "**kern",
) -> SpineBranch:
    return SpineBranch(
        identity=SpineIdentity(
            root_column=0,
            spine_type=spine_type,
            instrument="Violin 2",
            part="*part1",
            staff="*staff1",
        ),
        path=path,
        opening_lines=opening_lines,
    )


def test_preserves_remaining_duration_of_unchanged_branch() -> None:
    branch = rhythm_branch()

    assert remap_spine_remaining(
        (branch,),
        (Fraction(1, 4),),
        (branch,),
    ) == (Fraction(1, 4),)


def test_split_copies_remaining_duration_to_both_branches() -> None:
    parent = rhythm_branch()
    left = rhythm_branch((0,), (4,))
    right = rhythm_branch((1,), (4,))

    assert remap_spine_remaining(
        (parent,),
        (Fraction(1, 4),),
        (left, right),
    ) == (Fraction(1, 4), Fraction(1, 4))


def test_merge_preserves_equal_remaining_durations() -> None:
    left = rhythm_branch((0,), (4,))
    right = rhythm_branch((1,), (4,))

    assert remap_spine_remaining(
        (left, right),
        (Fraction(1, 4), Fraction(1, 4)),
        (rhythm_branch(),),
    ) == (Fraction(1, 4),)


def test_merge_rejects_different_remaining_durations() -> None:
    left = rhythm_branch((0,), (4,))
    right = rhythm_branch((1,), (4,))

    with pytest.raises(HumdrumError, match="różne"):
        remap_spine_remaining(
            (left, right),
            (Fraction(0), Fraction(1, 4)),
            (rhythm_branch(),),
        )


def test_nested_merge_preserves_other_branch() -> None:
    left = rhythm_branch((0,), (4,))
    right_left = rhythm_branch((1, 0), (4, 6))
    right_right = rhythm_branch((1, 1), (4, 6))
    right = rhythm_branch((1,), (4,))

    assert remap_spine_remaining(
        (left, right_left, right_right),
        (Fraction(1, 2), Fraction(1, 4), Fraction(1, 4)),
        (left, right),
    ) == (Fraction(1, 2), Fraction(1, 4))


def test_does_not_confuse_separate_split_histories() -> None:
    old_branch = rhythm_branch((0,), (4,))
    new_branch = rhythm_branch((0,), (8,))

    with pytest.raises(HumdrumError, match="poprzednika"):
        remap_spine_remaining(
            (old_branch,),
            (Fraction(1, 4),),
            (new_branch,),
        )


def test_non_kern_spine_has_no_rhythmic_duration() -> None:
    branch = rhythm_branch(spine_type="**dynam")

    assert remap_spine_remaining(
        (branch,),
        (Fraction(0),),
        (branch,),
    ) == (Fraction(0),)


def test_final_termination_removes_all_remaining_durations() -> None:
    assert (
        remap_spine_remaining(
            (rhythm_branch(),),
            (Fraction(0),),
            (),
        )
        == ()
    )


def test_rejects_mismatched_number_of_durations() -> None:
    with pytest.raises(HumdrumError, match="Liczba długości"):
        remap_spine_remaining(
            (rhythm_branch(),),
            (),
            (rhythm_branch(),),
        )


def test_rejects_negative_remaining_duration() -> None:
    branch = rhythm_branch()

    with pytest.raises(HumdrumError, match="ujemna"):
        remap_spine_remaining(
            (branch,),
            (Fraction(-1, 4),),
            (branch,),
        )


def test_timeline_tracks_sustained_notes_and_barline() -> None:
    document = HumdrumDocument.from_text("**kern\t**kern\n=1\t=1\n2c\t4e\n.\t4f\n=2\t=2\n*-\t*-\n")

    result = trace_rhythm(document)
    rows = {row.line_number: row for row in result.records}

    assert result.issue is None
    assert rows[3].onset == 0
    assert rows[3].duration == Fraction(1, 4)
    assert rows[4].onset == Fraction(1, 4)
    assert rows[4].duration == Fraction(1, 4)
    assert rows[5].onset == Fraction(1, 2)
    assert rows[5].duration == 0


def test_timeline_preserves_duration_across_split() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n2c\t4e\n*^\t*\n.\t.\t4f\n*v\t*v\t*\n*-\t*-\n"
    )

    result = trace_rhythm(document)
    rows = {row.line_number: row for row in result.records}

    assert result.issue is None
    assert rows[3].onset == Fraction(1, 4)
    assert rows[4].onset == Fraction(1, 4)
    assert rows[4].duration == Fraction(1, 4)
    assert rows[5].onset == Fraction(1, 2)


def test_timeline_grace_row_does_not_shift_following_note() -> None:
    document = HumdrumDocument.from_text("**kern\t**kern\n8cq\t.\n4c\t4e\n*-\t*-\n")

    result = trace_rhythm(document)
    rows = {row.line_number: row for row in result.records}

    assert result.issue is None
    assert rows[2].onset == 0
    assert rows[2].duration == 0
    assert rows[3].onset == 0
    assert rows[3].duration == Fraction(1, 4)


def test_timeline_comments_and_interpretations_do_not_advance_time() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n4c\n!!Komentarz globalny\n!Komentarz lokalny\n*clefG2\n4d\n*-\n"
    )

    result = trace_rhythm(document)
    rows = {row.line_number: row for row in result.records}

    assert result.issue is None
    for line_number in (3, 4, 5):
        assert rows[line_number].onset == Fraction(1, 4)
        assert rows[line_number].duration == 0
    assert rows[6].onset == Fraction(1, 4)


def test_timeline_ignores_non_kern_tokens_when_calculating_time() -> None:
    document = HumdrumDocument.from_text("**kern\t**dynam\n4c\tp\n4d\t<\n*-\t*-\n")

    result = trace_rhythm(document)

    assert result.issue is None
    assert result.records[-1].onset == Fraction(1, 2)


def test_timeline_reports_ambiguous_null_only_data_row() -> None:
    document = HumdrumDocument.from_text("**kern\t**dynam\n2c\tp\n.\tf\n*-\t*-\n")

    result = trace_rhythm(document)

    assert result.issue is not None
    assert result.issue.line_number == 3
    assert "brak nowego tokenu" in result.issue.message


def test_timeline_reports_overlapping_note_with_line_number() -> None:
    document = HumdrumDocument.from_text("**kern\t**kern\n2c\t4e\n4d\t4f\n*-\t*-\n")

    result = trace_rhythm(document)

    assert result.issue is not None
    assert result.issue.line_number == 3
    assert "przed zakończeniem" in result.issue.message


def test_timeline_reports_structure_failure() -> None:
    document = HumdrumDocument.from_text("**kern\t**kern\n4c\t4e\n4d\n*-\t*-\n")

    result = trace_rhythm(document)

    assert result.issue is not None
    assert result.issue.line_number == 3
    assert "liczba spinów" in result.issue.message


def test_timeline_records_remaining_duration_before_merge() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n*^\t*\n2c\t2e\t4g\n*v\t*v\t*\n.\t4a\n*-\t*-\n"
    )

    result = trace_rhythm(document)
    rows = {row.line_number: row for row in result.records}

    assert result.issue is None
    assert rows[4].remaining_before == (
        Fraction(1, 4),
        Fraction(1, 4),
        Fraction(0),
    )
    assert rows[5].remaining_before == (
        Fraction(1, 4),
        Fraction(0),
    )


def test_merge_fill_proposes_rest_followed_by_null_token() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n=1\t=1\n*^\t*\n4c\t4ryy\t4e\n*v\t*v\t*\n4d\t8f\n.\t8g\n=2\t=2\n*-\t*-\n"
    )
    original = document.to_text()

    suggestions = suggest_merge_fill(document, 5, 0)

    assert [(item.source_line, item.source_column, item.token) for item in suggestions] == [
        (6, 1, "4ryy"),
        (7, 1, "."),
    ]
    assert document.to_text() == original


def test_merge_fill_continues_value_started_before_merge() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n=1\t=1\n*^\t*\n2c\t2ryy\t4e\n*v\t*v\t*\n.\t4f\n4d\t4g\n=2\t=2\n*-\t*-\n"
    )

    suggestions = suggest_merge_fill(document, 5, 0)

    assert [(item.source_line, item.source_column, item.token) for item in suggestions] == [
        (6, 1, "."),
        (7, 1, "4ryy"),
    ]


def test_merge_fill_splits_duration_at_existing_row_boundary() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n"
        "=1\t=1\n"
        "*^\t*\n"
        "4c\t4ryy\t4e\n"
        "*v\t*v\t*\n"
        "8%5d\t8f\n"
        ".\t8g\n"
        ".\t8a\n"
        ".\t8b\n"
        ".\t8cc\n"
        "=2\t=2\n"
        "*-\t*-\n"
    )

    suggestions = suggest_merge_fill(document, 5, 0)

    assert [(item.source_line, item.source_column, item.token) for item in suggestions] == [
        (6, 1, "2ryy"),
        (7, 1, "."),
        (8, 1, "."),
        (9, 1, "."),
        (10, 1, "8ryy"),
    ]


def test_merge_fill_proposes_dots_for_non_kern_spine() -> None:
    document = HumdrumDocument.from_text(
        "**dynam\t**kern\n=1\t=1\n*^\t*\np\tf\t4c\n*v\t*v\t*\nff\t4d\n=2\t=2\n*-\t*-\n"
    )

    suggestions = suggest_merge_fill(document, 5, 0)

    assert [(item.source_line, item.source_column, item.token) for item in suggestions] == [
        (6, 1, "."),
    ]


def test_split_fill_proposes_long_rest_with_continuation() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n=1\t=1\n2c\t4e\n.\t4f\n*^\t*\n4d\t4ryy\t4g\n*v\t*v\t*\n=2\t=2\n*-\t*-\n"
    )
    original = document.to_text()

    suggestions = suggest_split_fill(document, 5, 0)

    assert [(item.source_line, item.source_column, item.token) for item in suggestions] == [
        (3, 1, "2ryy"),
        (4, 1, "."),
    ]
    assert document.to_text() == original


def test_split_fill_preserves_note_continuing_from_previous_measure() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n2c\t4e\n=2\t=2\n.\t4f\n*^\t*\n4g\t4ryy\t4a\n*v\t*v\t*\n=3\t=3\n*-\t*-\n"
    )

    suggestions = suggest_split_fill(document, 5, 0)

    assert [(item.source_line, item.source_column, item.token) for item in suggestions] == [
        (4, 1, "."),
    ]


def test_split_fill_proposes_dots_for_non_kern_spine() -> None:
    document = HumdrumDocument.from_text(
        "**dynam\t**kern\n=1\t=1\np\t4c\n*^\t*\nf\tff\t4d\n*v\t*v\t*\n=2\t=2\n*-\t*-\n"
    )

    suggestions = suggest_split_fill(document, 4, 0)

    assert [(item.source_line, item.source_column, item.token) for item in suggestions] == [
        (3, 1, "."),
    ]


def test_multimeasure_rest_keeps_remaining_duration_across_barlines() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n"
        "*M4/4\t*M4/4\n"
        "=1\t=1\n"
        "00r\t1c\n"
        "=2\t=2\n"
        ".\t1d\n"
        "=3\t=3\n"
        ".\t1e\n"
        "=4\t=4\n"
        ".\t1f\n"
        "=5\t=5\n"
        "1r\t1g\n"
        "*-\t*-\n"
    )

    rhythm = trace_rhythm(document)
    rows = {row.line_number: row for row in rhythm.records}

    assert rhythm.issue is None
    assert rows[6].remaining_before[0] == Fraction(3)
    assert rows[8].remaining_before[0] == Fraction(2)
    assert rows[10].remaining_before[0] == Fraction(1)
    assert rows[12].remaining_before[0] == Fraction(0)
    assert rows[12].onset == Fraction(4)


def test_rejects_new_rest_inside_multimeasure_rest() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n*M4/4\t*M4/4\n=1\t=1\n00r\t1c\n=2\t=2\n1r\t1d\n*-\t*-\n"
    )

    rhythm = trace_rhythm(document)

    assert rhythm.issue is not None
    assert rhythm.issue.line_number == 6
    assert "przed zakończeniem poprzedniej wartości" in rhythm.issue.message


def test_split_fill_continues_multimeasure_rest_without_new_rest() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n"
        "*M4/4\t*M4/4\n"
        "=1\t=1\n"
        "00r\t1c\n"
        "=2\t=2\n"
        ".\t2d\n"
        "*^\t*\n"
        ".\t.\t2e\n"
        "=3\t=3\t=3\n"
        ".\t.\t1f\n"
        "=4\t=4\t=4\n"
        ".\t.\t1g\n"
        "=5\t=5\t=5\n"
        "1r\t1r\t1a\n"
        "*-\t*-\t*-\n"
    )

    suggestions = suggest_split_fill(document, source_line=7, root_column=0)

    assert len(suggestions) == 1
    assert suggestions[0].source_line == 6
    assert suggestions[0].source_column == 1
    assert suggestions[0].token == "."
    assert document.lines[3] == "00r\t1c"


def test_merge_fill_continues_multimeasure_rest_without_new_rest() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n"
        "*M4/4\t*M4/4\n"
        "=1\t=1\n"
        "*^\t*\n"
        "00r\t00ryy\t1c\n"
        "=2\t=2\t=2\n"
        ".\t.\t2d\n"
        "*v\t*v\t*\n"
        ".\t2e\n"
        "=3\t=3\n"
        ".\t1f\n"
        "=4\t=4\n"
        ".\t1g\n"
        "=5\t=5\n"
        "1r\t1a\n"
        "*-\t*-\n"
    )

    suggestions = suggest_merge_fill(document, source_line=8, root_column=0)

    assert len(suggestions) == 1
    assert suggestions[0].source_line == 9
    assert suggestions[0].source_column == 1
    assert suggestions[0].token == "."
    assert document.lines[4] == "00r\t00ryy\t1c"
