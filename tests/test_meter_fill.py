from fractions import Fraction

import pytest

from spineworks.humdrum import HumdrumDocument, HumdrumError
from spineworks.meter_rhythm import MeterSignature, meter_rest_options
from spineworks.spine_rhythm import (
    TimedRecord,
    _meter_fill_tokens,
    suggest_merge_fill,
)


def test_four_four_fill_respects_half_measure_boundary() -> None:
    option = meter_rest_options(MeterSignature(4, 4))[0]
    rows = (
        TimedRecord(10, Fraction(1, 4), Fraction(1, 4)),
        TimedRecord(11, Fraction(1, 2), Fraction(1, 4)),
        TimedRecord(12, Fraction(3, 4), Fraction(1, 4)),
    )

    tokens = _meter_fill_tokens(
        rows,
        option=option,
        measure_start=Fraction(0),
        active_until=Fraction(1, 4),
        end_time=Fraction(1),
    )

    assert tokens == {10: "4ryy", 11: "2ryy", 12: "."}


def test_three_four_fill_uses_two_quarter_rests_from_second_beat() -> None:
    option = meter_rest_options(MeterSignature(3, 4))[0]
    rows = (
        TimedRecord(10, Fraction(1, 4), Fraction(1, 4)),
        TimedRecord(11, Fraction(1, 2), Fraction(1, 4)),
    )

    tokens = _meter_fill_tokens(
        rows,
        option=option,
        measure_start=Fraction(0),
        active_until=Fraction(1, 4),
        end_time=Fraction(3, 4),
    )

    assert tokens == {10: "4ryy", 11: "4ryy"}


def test_fill_uses_position_relative_to_measure_start() -> None:
    option = meter_rest_options(MeterSignature(4, 4))[0]
    rows = (
        TimedRecord(20, Fraction(41, 4), Fraction(1, 4)),
        TimedRecord(21, Fraction(21, 2), Fraction(1, 4)),
        TimedRecord(22, Fraction(43, 4), Fraction(1, 4)),
    )

    tokens = _meter_fill_tokens(
        rows,
        option=option,
        measure_start=Fraction(10),
        active_until=Fraction(41, 4),
        end_time=Fraction(11),
    )

    assert tokens == {20: "4ryy", 21: "2ryy", 22: "."}


def test_grace_rows_and_sounding_continuations_receive_dots() -> None:
    option = meter_rest_options(MeterSignature(4, 4))[0]
    rows = (
        TimedRecord(10, Fraction(1, 4), Fraction(1, 4)),
        TimedRecord(11, Fraction(1, 2), Fraction(0)),
        TimedRecord(12, Fraction(1, 2), Fraction(1, 4)),
        TimedRecord(13, Fraction(3, 4), Fraction(1, 4)),
    )

    tokens = _meter_fill_tokens(
        rows,
        option=option,
        measure_start=Fraction(0),
        active_until=Fraction(1, 2),
        end_time=Fraction(1),
    )

    assert tokens == {10: ".", 11: ".", 12: "2ryy", 13: "."}


def test_missing_meter_boundary_requires_manual_fill() -> None:
    option = meter_rest_options(MeterSignature(4, 4))[0]
    rows = (
        TimedRecord(10, Fraction(1, 4), Fraction(1, 2)),
        TimedRecord(11, Fraction(3, 4), Fraction(1, 4)),
    )

    with pytest.raises(HumdrumError, match="granicy wymaganej"):
        _meter_fill_tokens(
            rows,
            option=option,
            measure_start=Fraction(0),
            active_until=Fraction(1, 4),
            end_time=Fraction(1),
        )


def test_missing_silence_start_requires_manual_fill() -> None:
    option = meter_rest_options(MeterSignature(4, 4))[0]
    rows = (TimedRecord(10, Fraction(1, 2), Fraction(1, 2)),)

    with pytest.raises(HumdrumError, match="Początek ciszy"):
        _meter_fill_tokens(
            rows,
            option=option,
            measure_start=Fraction(0),
            active_until=Fraction(1, 4),
            end_time=Fraction(1),
        )


def test_no_rest_needed_when_voice_sounds_until_end() -> None:
    option = meter_rest_options(MeterSignature(4, 4))[0]
    rows = (TimedRecord(10, Fraction(1, 2), Fraction(1, 2)),)

    tokens = _meter_fill_tokens(
        rows,
        option=option,
        measure_start=Fraction(0),
        active_until=Fraction(1),
        end_time=Fraction(1),
    )

    assert tokens == {10: "."}


def test_merge_fill_uses_meter_grouping_after_first_quarter() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n"
        "*M4/4\t*M4/4\n"
        "=1\t=1\n"
        "*^\t*\n"
        "4c\t4ryy\t4g\n"
        "*v\t*v\t*\n"
        "4d\t4a\n"
        "4e\t4b\n"
        "4f\t4cc\n"
        "=2\t=2\n"
        "*-\t*-\n"
    )
    option = meter_rest_options(MeterSignature(4, 4))[0]
    original = document.to_text()

    suggestions = suggest_merge_fill(
        document,
        6,
        0,
        rest_option=option,
    )

    assert tuple((item.source_line, item.source_column, item.token) for item in suggestions) == (
        (7, 1, "4ryy"),
        (8, 1, "2ryy"),
        (9, 1, "."),
    )
    assert document.to_text() == original


def test_merge_fill_rejects_option_for_different_meter() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n*M4/4\n=1\n*^\n4c\t4ryy\n*v\t*v\n4d\n4e\n4f\n=2\n*-\n"
    )
    option = meter_rest_options(MeterSignature(3, 4))[0]

    with pytest.raises(HumdrumError, match="nie odpowiada metrum"):
        suggest_merge_fill(document, 6, 0, rest_option=option)
