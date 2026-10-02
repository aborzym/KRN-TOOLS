from fractions import Fraction

import pytest

from spineworks.humdrum import HumdrumError
from spineworks.meter_rhythm import MeterRestOption, MeterSignature, meter_rest_options, parse_meter


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


@pytest.mark.parametrize("numerator", [6, 9, 12])
def test_compound_eighth_meter_offers_two_rest_styles(numerator: int) -> None:
    meter = MeterSignature(numerator, 8)

    options = meter_rest_options(meter)

    assert tuple(option.key for option in options) == (
        "quarter_eighth",
        "dotted",
    )
    assert all(option.groups == (3,) * (numerator // 3) for option in options)
    assert options[0].split_three_units is True
    assert options[1].split_three_units is False


def test_six_four_offers_both_groupings() -> None:
    options = meter_rest_options(MeterSignature(6, 4))

    assert tuple(option.groups for option in options) == (
        (3, 3),
        (2, 2, 2),
    )
    assert all(option.split_three_units is False for option in options)


@pytest.mark.parametrize(
    ("numerator", "groups"),
    [
        (2, (1, 1)),
        (3, (2, 1)),
        (4, (2, 2)),
    ],
)
def test_simple_meter_has_one_standard_grouping(
    numerator: int,
    groups: tuple[int, ...],
) -> None:
    options = meter_rest_options(MeterSignature(numerator, 4))

    assert len(options) == 1
    assert options[0].groups == groups
    assert options[0].split_three_units is False


def test_rejects_groups_not_matching_meter() -> None:
    with pytest.raises(HumdrumError):
        MeterRestOption(
            meter=MeterSignature(6, 8),
            key="invalid",
            label="Nieprawidłowy podział",
            groups=(3, 2),
        )


def test_rejects_quarter_eighth_style_in_six_four() -> None:
    with pytest.raises(HumdrumError):
        MeterRestOption(
            meter=MeterSignature(6, 4),
            key="invalid",
            label="Nieprawidłowy podział",
            groups=(3, 3),
            split_three_units=True,
        )


def test_unknown_grouping_requires_explicit_rules() -> None:
    with pytest.raises(HumdrumError, match="nie ustalono"):
        meter_rest_options(MeterSignature(5, 4))
