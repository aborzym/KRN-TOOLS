import pytest

from spineworks.humdrum import HumdrumDocument
from spineworks.meter_rhythm import parse_meter
from spineworks.multibar_rests import (
    annotate_multibar_rests,
    rest_duration_matches,
    rest_layout_candidate,
)


@pytest.mark.parametrize(
    ("meter_token", "token", "bars", "visual"),
    [
        ("*M3/4", "1.r", 2, "0"),
        ("*M3/4", "0.r", 4, "00"),
        ("*M2/4", "1r", 2, "0"),
        ("*M2/4", "0r", 4, "00"),
        ("*M3/8", "2.r", 2, "0"),
        ("*M3/8", "1.r", 4, "00"),
        ("*M6/8", "1.r", 2, "0"),
        ("*M6/8", "0.r", 4, "00"),
        ("*M12/8", "0.r", 2, "0"),
        ("*M12/8", "00.r", 4, "00"),
        ("*M3/2", "0.r", 2, "0"),
        ("*M3/2", "00.r", 4, "00"),
        ("*M2/1", "00r", 2, "0"),
        ("*M3/1", "00.r", 2, "0"),
    ],
)
def test_recognizes_multibar_rest(meter_token, token, bars, visual):
    meter = parse_meter(meter_token)

    assert rest_layout_candidate(token, meter) == (bars, visual)
    assert rest_duration_matches(token, meter, bars)


@pytest.mark.parametrize(
    ("meter_token", "token"),
    [
        ("*M4/4", "0r"),
        ("*M2/2", "00r"),
        ("*M3/4", "1.ryy"),
        ("*M3/4", "1.ryyyy"),
        ("*M3/4", "2.r"),
        ("*M3/4", "1.c"),
        ("*M3/4", "1.r 1.r"),
        ("*M3/4", "."),
    ],
)
def test_ignores_ineligible_rest(meter_token, token):
    assert rest_layout_candidate(token, parse_meter(meter_token)) is None


@pytest.mark.parametrize(
    ("meter_token", "token"),
    [
        ("*M2/1", "0000r"),
        ("*M3/1", "0000.r"),
    ],
)
def test_rejects_duration_inconsistent_with_four_bars(meter_token, token):
    meter = parse_meter(meter_token)

    assert rest_layout_candidate(token, meter) == (4, "00")
    assert not rest_duration_matches(token, meter, 4)


def multibar_source(comments: str) -> str:
    return (
        "**kern\t**kern\n"
        "*M3/4\t*M3/4\n"
        "=1\t=1\n"
        f"{comments}"
        "1.r\t2.r\n"
        "=2\t=2\n"
        ".\t2.r\n"
        "=3\t=3\n"
        "2.r\t2.r\n"
        "*-\t*-\n"
    )


@pytest.mark.parametrize(
    ("comments", "expected_comments"),
    [
        (
            "!\t!\n",
            "!LO:N:vis=0\t!\n",
        ),
        (
            "!opis\t!\n!\t!\n",
            "!opis\t!\n!LO:N:vis=0\t!\n",
        ),
        (
            "!\t!LO:MO:mod=2.r\n!opis\t!\n!drugi opis\t!\n",
            "!LO:N:vis=0\t!LO:MO:mod=2.r\n!opis\t!\n!drugi opis\t!\n",
        ),
        (
            "!opis\t!\n",
            "!opis\t!\n!LO:N:vis=0\t!\n",
        ),
        (
            "!opis\t!LO:MO:mod=2.r\n!drugi opis\t!\n",
            "!LO:N:vis=0\t!\n!opis\t!LO:MO:mod=2.r\n!drugi opis\t!\n",
        ),
        (
            "",
            "!LO:N:vis=0\t!\n",
        ),
    ],
)
def test_places_multibar_layout(comments, expected_comments):
    source = multibar_source(comments)
    document = HumdrumDocument.from_text(source)

    result, count, warnings = annotate_multibar_rests(document)

    assert count == 1
    assert not warnings
    assert result.to_text() == multibar_source(expected_comments)
    assert document.to_text() == source

    repeated, repeated_count, repeated_warnings = annotate_multibar_rests(result)
    assert repeated_count == 0
    assert not repeated_warnings
    assert repeated.to_text() == result.to_text()


def test_preserves_existing_multibar_visual():
    source = multibar_source("!LO:N:vis=inne\t!\n")
    document = HumdrumDocument.from_text(source)

    result, count, warnings = annotate_multibar_rests(document)

    assert count == 0
    assert not warnings
    assert result.to_text() == source


def test_skips_hidden_multibar_rest():
    source = multibar_source("").replace("1.r\t", "1.ryy\t")
    document = HumdrumDocument.from_text(source)

    result, count, warnings = annotate_multibar_rests(document)

    assert count == 0
    assert not warnings
    assert result.to_text() == source


def test_rejects_incorrect_internal_bar_boundary():
    source = (
        "**kern\t**kern\n*M3/4\t*M3/4\n=1\t=1\n1.r\t2r\n=2\t=2\n.\t1r\n=3\t=3\n2.r\t2.r\n*-\t*-\n"
    )
    document = HumdrumDocument.from_text(source)

    result, count, warnings = annotate_multibar_rests(document)

    assert count == 0
    assert len(warnings) == 1
    assert result.to_text() == source
