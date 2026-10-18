from fractions import Fraction

from spineworks.humdrum import HumdrumDocument
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
