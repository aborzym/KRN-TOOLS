from fractions import Fraction

import pytest

from spineworks.humdrum import HumdrumDocument
from spineworks.multibar_rests import annotate_multibar_rests
from spineworks.spine_rhythm import trace_rhythm


def test_null_row_and_visual_layout_do_not_change_measure_duration():
    source = (
        "**kern\t**kern\n"
        "*M3/4\t*M3/4\n"
        "=14\t=14\n"
        "! \t!LO:TX:t=P:problem:mixed beam\n"
        "8D\\L\t8b-\\L\n"
        "8E-\\J\t8gg\\\n"
        "!\t!LO:N:vis=8\n"
        "4F\\\t4f/\n"
        ".\t.\n"
        "4FF/\t4a/\n"
        "=15\t=15\n"
        "*-\t*-\n"
    )
    document = HumdrumDocument.from_text(source)

    rhythm = trace_rhythm(document)

    assert rhythm.issue is None
    timed = {record.line_number: record for record in rhythm.records}
    lines = source.splitlines()

    null_line = lines.index(".\t.") + 1
    following_line = lines.index("4FF/\t4a/") + 1
    barline = lines.index("=15\t=15") + 1

    assert timed[null_line].duration == 0
    assert timed[null_line].remaining_before == timed[following_line].remaining_before
    assert timed[null_line].onset == timed[following_line].onset
    assert timed[barline].onset == Fraction(3, 4)
    assert document.to_text() == source


@pytest.mark.parametrize(
    ("spine_type", "auxiliary_token"),
    [
        ("**fba", "6-"),
        ("**fbb", "5"),
        ("**dynam", "p"),
        ("**text", "la"),
        ("**fing", "2"),
    ],
)
def test_auxiliary_row_preserves_kern_timing(spine_type, auxiliary_token):
    source = (
        f"**kern\t{spine_type}\t**kern\n"
        "*M3/4\t*\t*M3/4\n"
        "=77\t=77\t=77\n"
        "2G\\\t.\t2.ryy\n"
        f".\t{auxiliary_token}\t.\n"
        "4C/\t.\t.\n"
        "=78\t=78\t=78\n"
        "*-\t*-\t*-\n"
    )
    document = HumdrumDocument.from_text(source)

    rhythm = trace_rhythm(document, allow_auxiliary_rows=True)

    assert rhythm.issue is None
    timed = {record.line_number: record for record in rhythm.records}
    assert timed[5].duration == 0
    assert timed[5].onset == timed[6].onset
    assert timed[5].remaining_before == timed[6].remaining_before
    assert timed[7].onset == Fraction(3, 4)
    assert document.to_text() == source


def test_multibar_annotation_accepts_auxiliary_rows():
    source = (
        "**kern\t**fba\t**kern\n"
        "*M3/4\t*\t*M3/4\n"
        "=1\t=1\t=1\n"
        "1.r\t.\t2c\n"
        ".\t6-\t.\n"
        ".\t5\t4d\n"
        "=2\t=2\t=2\n"
        ".\t.\t2e\n"
        ".\t.\t4f\n"
        "=3\t=3\t=3\n"
        "2.r\t.\t2.g\n"
        "*-\t*-\t*-\n"
    )
    document = HumdrumDocument.from_text(source)

    result, count, warnings = annotate_multibar_rests(document)

    assert count == 1
    assert not warnings
    assert result.to_text() == source.replace(
        "1.r\t.\t2c\n",
        "!LO:N:vis=0\t!\t!\n1.r\t.\t2c\n",
    )
    assert document.to_text() == source
