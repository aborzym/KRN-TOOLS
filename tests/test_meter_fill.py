from fractions import Fraction

import pytest

from spineworks.humdrum import HumdrumError
from spineworks.meter_rhythm import MeterSignature, meter_rest_options
from spineworks.spine_rhythm import TimedRecord, _meter_fill_tokens


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
