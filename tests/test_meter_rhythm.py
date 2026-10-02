from fractions import Fraction

import pytest

from spineworks.humdrum import HumdrumError
from spineworks.meter_rhythm import MeterSignature, parse_meter


@pytest.mark.parametrize(
    ("token", "numerator", "denominator", "duration"),
    [
        ("*M4/4", 4, 4, Fraction(1)),
        ("*M3/4", 3, 4, Fraction(3, 4)),
        ("*M6/8", 6, 8, Fraction(3, 4)),
        ("*M9/8", 9, 8, Fraction(9, 8)),
        ("*M12/8", 12, 8, Fraction(3, 2)),
        ("*M6/4", 6, 4, Fraction(3, 2)),
        ("*M2/2", 2, 2, Fraction(1)),
    ],
)
def test_reads_meter_signature(
    token: str,
    numerator: int,
    denominator: int,
    duration: Fraction,
) -> None:
    meter = parse_meter(token)

    assert meter.numerator == numerator
    assert meter.denominator == denominator
    assert meter.duration == duration


def test_equal_durations_do_not_make_meters_identical() -> None:
    simple = parse_meter("*M3/4")
    compound = parse_meter("*M6/8")

    assert simple.duration == compound.duration
    assert simple != compound
    assert simple.requires_rest_choice is False
    assert compound.requires_rest_choice is True


@pytest.mark.parametrize(
    "token",
    ["*M6/8", "*M9/8", "*M12/8", "*M6/4"],
)
def test_selected_meters_require_rest_grouping_choice(token: str) -> None:
    assert parse_meter(token).requires_rest_choice is True


@pytest.mark.parametrize(
    "token",
    ["*M4/4", "*M3/4", "*M2/2"],
)
def test_standard_meters_do_not_require_rest_grouping_choice(token: str) -> None:
    assert parse_meter(token).requires_rest_choice is False


@pytest.mark.parametrize(
    "token",
    ["", "*", "4/4", "*MM120", "*M0/4", "*M4/0", "*M-3/4", "*M6/8\n"],
)
def test_rejects_invalid_meter_token(token: str) -> None:
    with pytest.raises(HumdrumError):
        parse_meter(token)


@pytest.mark.parametrize(
    ("numerator", "denominator"),
    [(0, 4), (4, 0), (-3, 4), (3, -4)],
)
def test_meter_cannot_have_nonpositive_values(
    numerator: int,
    denominator: int,
) -> None:
    with pytest.raises(HumdrumError):
        MeterSignature(numerator, denominator)
