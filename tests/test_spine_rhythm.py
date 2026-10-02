from fractions import Fraction

import pytest

from spineworks.humdrum import HumdrumError
from spineworks.spine_rhythm import remap_spine_remaining
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
