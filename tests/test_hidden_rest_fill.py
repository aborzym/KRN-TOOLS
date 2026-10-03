from fractions import Fraction

import pytest

from spineworks.humdrum import HumdrumDocument, HumdrumError
from spineworks.meter_rhythm import MeterSignature, meter_rest_options
from spineworks.spine_rhythm import (
    TimedRecord,
    suggest_hidden_rest_span,
    suggest_reopening_fill,
)


def test_combines_short_hidden_rests_into_full_measure() -> None:
    rows = tuple(
        TimedRecord(
            line_number=index + 10,
            onset=Fraction(index, 8),
            duration=Fraction(1, 8),
        )
        for index in range(8)
    )
    option = meter_rest_options(MeterSignature(4, 4))[0]

    suggestions = suggest_hidden_rest_span(
        rows,
        ("8ryy", "", "8ryy", "", "8ryy", "", "8ryy", ""),
        source_column=1,
        option=option,
        measure_start=Fraction(0),
        end_time=Fraction(1),
    )

    assert [item.token for item in suggestions] == ["1ryy"] + ["."] * 7
    assert [item.source_line for item in suggestions] == list(range(10, 18))
    assert all(item.source_column == 1 for item in suggestions)


@pytest.mark.parametrize("protected_token", ["4c", "4r", "4ryy;"])
def test_refuses_to_overwrite_musical_or_decorated_tokens(
    protected_token: str,
) -> None:
    rows = (
        TimedRecord(10, Fraction(0), Fraction(1, 4)),
        TimedRecord(11, Fraction(1, 4), Fraction(1, 4)),
    )
    option = meter_rest_options(MeterSignature(4, 4))[0]

    with pytest.raises(HumdrumError, match="ręcznej kontroli"):
        suggest_hidden_rest_span(
            rows,
            ("4ryy", protected_token),
            source_column=1,
            option=option,
            measure_start=Fraction(0),
            end_time=Fraction(1, 2),
        )


def make_reopening_document(
    middle_token: str = "8ryy",
) -> HumdrumDocument:
    return HumdrumDocument.from_text(
        "**kern\t**kern\n"
        '*I"Bassoon\t*I"Violin\n'
        "*M4/4\t*M4/4\n"
        "=46\t=46\n"
        "*^\t*\n"
        "8C\t8ryy\t1c\n"
        "*v\t*v\t*\n"
        "8D\t.\n"
        "*^\t*\n"
        f"8E\t{middle_token}\t.\n"
        "*v\t*v\t*\n"
        "8F\t.\n"
        "*^\t*\n"
        "8G\t8ryy\t.\n"
        "*v\t*v\t*\n"
        "8A\t.\n"
        "*^\t*\n"
        "8B\t8ryy\t.\n"
        "8c\t8ryy\t.\n"
        "*v\t*v\t*\n"
        "=47\t=47\n"
        "*-\t*-\n"
    )


def test_reopening_fill_proposes_one_full_measure_rest() -> None:
    document = make_reopening_document()
    original = document.to_text()
    option = meter_rest_options(MeterSignature(4, 4))[0]

    suggestions = suggest_reopening_fill(
        document,
        7,
        0,
        rest_option=option,
    )

    assert [item.source_line for item in suggestions] == [
        6,
        8,
        10,
        12,
        14,
        16,
        18,
        19,
    ]
    assert [item.token for item in suggestions] == ["1ryy"] + ["."] * 7
    assert all(item.source_column == 1 for item in suggestions)
    assert document.to_text() == original


@pytest.mark.parametrize("protected_token", ["8g", "8r", "8ryy;"])
def test_reopening_fill_preserves_tokens_between_silence_spans(
    protected_token: str,
) -> None:
    document = make_reopening_document(protected_token)
    original = document.to_text()
    option = meter_rest_options(MeterSignature(4, 4))[0]

    suggestions = suggest_reopening_fill(
        document,
        7,
        0,
        rest_option=option,
    )

    assert [(item.source_line, item.token) for item in suggestions] == [
        (6, "4ryy"),
        (8, "."),
        (12, "8ryy"),
        (14, "2ryy"),
        (16, "."),
        (18, "."),
        (19, "."),
    ]
    assert all(item.source_line != 10 for item in suggestions)
    assert document.to_text() == original
