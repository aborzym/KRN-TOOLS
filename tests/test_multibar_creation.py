import pytest

from spineworks.humdrum import HumdrumDocument
from spineworks.multibar_creation import (
    create_multibar_rests,
    find_full_measure_rests,
    plan_rest_groups,
)
from spineworks.spine_rhythm import trace_rhythm


def make_rest_document(
    count: int,
    *,
    meter: str = "*M3/4",
    rest: str = "2.r",
) -> HumdrumDocument:
    lines = ["**kern", meter]

    for measure in range(1, count + 1):
        lines.extend([f"={measure}", rest])

    lines.extend([f"={count + 1}", "*-"])
    return HumdrumDocument.from_text("\n".join(lines) + "\n")


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, []),
        (2, [2]),
        (3, [2]),
        (4, [4]),
        (5, [4]),
        (6, [4, 2]),
        (7, [4, 2]),
        (8, [4, 4]),
        (10, [4, 4, 2]),
    ],
)
def test_groups_four_bars_before_two(count, expected):
    document = make_rest_document(count)
    original = document.to_text()

    rests = find_full_measure_rests(document, kern_columns={0})
    groups = plan_rest_groups(rests)

    assert [len(group) for group in groups] == expected
    assert document.to_text() == original


@pytest.mark.parametrize("meter", ["*M4/4", "*M2/2"])
def test_includes_common_and_cut_time(meter):
    document = make_rest_document(4, meter=meter, rest="1r")

    rests = find_full_measure_rests(document, kern_columns={0})

    assert [len(group) for group in plan_rest_groups(rests)] == [4]


def test_respects_selected_measure_range():
    document = make_rest_document(8)

    rests = find_full_measure_rests(
        document,
        kern_columns={0},
        start_measure=2,
        end_measure=7,
    )
    groups = plan_rest_groups(rests)

    assert [[rest.measure_number for rest in group] for group in groups] == [[2, 3, 4, 5], [6, 7]]


@pytest.mark.parametrize(
    "replacement",
    ["2.ryy", "2.ryyyy", "2.c"],
)
def test_hidden_rest_or_note_interrupts_run(replacement):
    document = make_rest_document(7)
    document.lines[7] = replacement

    rests = find_full_measure_rests(document, kern_columns={0})
    groups = plan_rest_groups(rests)

    assert [[rest.measure_number for rest in group] for group in groups] == [[1, 2], [4, 5, 6, 7]]


def test_double_barline_interrupts_run():
    document = make_rest_document(6)
    document.lines[6] = "=3||"

    rests = find_full_measure_rests(document, kern_columns={0})
    groups = plan_rest_groups(rests)

    assert [[rest.measure_number for rest in group] for group in groups] == [[1, 2], [3, 4, 5, 6]]


def test_creates_four_and_two_bar_rests():
    document = make_rest_document(7)
    source = document.to_text()

    result, count = create_multibar_rests(document, kern_columns={0})

    assert count == 2
    assert result.lines == [
        "**kern",
        "*M3/4",
        "=1",
        "0.r",
        "=2",
        ".",
        "=3",
        ".",
        "=4",
        ".",
        "=5",
        "1.r",
        "=6",
        ".",
        "=7",
        "2.r",
        "=8",
        "*-",
    ]
    assert document.to_text() == source


def test_creates_rests_only_in_selected_spine():
    source = (
        "**kern\t**kern\n"
        "*M3/4\t*M3/4\n"
        "=1\t=1\n"
        "2.r\t2.c\n"
        "=2\t=2\n"
        "2.r\t2.d\n"
        "=3\t=3\n"
        "2.r\t2.e\n"
        "=4\t=4\n"
        "2.r\t2.f\n"
        "=5\t=5\n"
        "*-\t*-\n"
    )
    document = HumdrumDocument.from_text(source)

    result, count = create_multibar_rests(document, kern_columns={0})

    assert count == 1
    assert result.to_text() == (
        source.replace("2.r\t2.c", "0.r\t2.c")
        .replace("2.r\t2.d", ".\t2.d")
        .replace("2.r\t2.e", ".\t2.e")
        .replace("2.r\t2.f", ".\t2.f")
    )
    assert document.to_text() == source

    original_rhythm = trace_rhythm(document, allow_auxiliary_rows=True)
    result_rhythm = trace_rhythm(result, allow_auxiliary_rows=True)

    assert original_rhythm.issue is None
    assert result_rhythm.issue is None
    assert [(record.line_number, record.onset) for record in result_rhythm.records] == [
        (record.line_number, record.onset) for record in original_rhythm.records
    ]


def test_creation_preserves_data_row_count_and_comments():
    source = (
        "**kern\t**kern\n"
        "*M3/4\t*M3/4\n"
        "=1\t=1\n"
        "!pierwszy\t!\n"
        "2.r\t2.c\n"
        "=2\t=2\n"
        "!drugi\t!\n"
        "2.r\t2.d\n"
        "=3\t=3\n"
        "*-\t*-\n"
    )
    document = HumdrumDocument.from_text(source)

    result, count = create_multibar_rests(document, kern_columns={0})

    assert count == 1
    assert len(result.lines) == len(document.lines)
    assert result.lines[3] == "!pierwszy\t!"
    assert result.lines[6] == "!drugi\t!"
    assert result.lines[4] == "1.r\t2.c"
    assert result.lines[7] == ".\t2.d"


def test_creation_preserves_timing_when_all_spines_have_rests():
    source = (
        "**kern\t**kern\n"
        "*M3/4\t*M3/4\n"
        "=1\t=1\n"
        "2.r\t2.r\n"
        "=2\t=2\n"
        "2.r\t2.r\n"
        "=3\t=3\n"
        "2.r\t2.r\n"
        "=4\t=4\n"
        "2.r\t2.r\n"
        "=5\t=5\n"
        "*-\t*-\n"
    )
    document = HumdrumDocument.from_text(source)

    result, count = create_multibar_rests(
        document,
        kern_columns={0, 1},
    )

    assert count == 2
    assert result.to_text() == (
        source.replace("2.r\t2.r", "0.r\t0.r", 1).replace("2.r\t2.r", ".\t.")
    )

    before = trace_rhythm(document, allow_auxiliary_rows=True)
    after = trace_rhythm(result, allow_auxiliary_rows=True)

    assert before.issue is None
    assert after.issue is None

    barline_numbers = {
        number for number, line in enumerate(document.lines, start=1) if line.startswith("=")
    }
    assert [
        (record.line_number, record.onset)
        for record in after.records
        if record.line_number in barline_numbers
    ] == [
        (record.line_number, record.onset)
        for record in before.records
        if record.line_number in barline_numbers
    ]


def test_splits_multibar_rest_and_removes_its_visual_layout():
    from spineworks.multibar_creation import split_multibar_rests

    source = (
        "**kern\t**kern\n"
        "*M3/4\t*M3/4\n"
        "=1\t=1\n"
        "!LO:N:vis=0\t!komentarz\n"
        "1.r\t2.r\n"
        "=2\t=2\n"
        ".\t2.r\n"
        "=3\t=3\n"
        "*-\t*-\n"
    )
    document = HumdrumDocument.from_text(source)

    result, count, warnings = split_multibar_rests(
        document,
        kern_columns={0},
    )

    assert count == 1
    assert not warnings
    assert result.to_text() == (
        source.replace("!LO:N:vis=0", "!")
        .replace("1.r\t2.r", "2.r\t2.r")
        .replace(".\t2.r", "2.r\t2.r")
    )
    assert len(result.lines) == len(document.lines)
    assert [
        line for line in result.lines if line.startswith("=")
    ] == [
        line for line in document.lines if line.startswith("=")
    ]
    assert document.to_text() == source


def test_split_skips_horizontal_grace_row():
    from spineworks.multibar_creation import split_multibar_rests

    source = (
        "**kern\t**kern\n"
        "*M3/4\t*M3/4\n"
        "=1\t=1\n"
        "1.r\t2.r\n"
        "=2\t=2\n"
        ".\t8qg\n"
        ".\t2.r\n"
        "=3\t=3\n"
        "*-\t*-\n"
    )
    document = HumdrumDocument.from_text(source)

    result, count, warnings = split_multibar_rests(
        document,
        kern_columns={0},
    )

    assert count == 1
    assert not warnings
    assert result.to_text() == (
        source.replace("1.r\t2.r", "2.r\t2.r")
        .replace(".\t2.r", "2.r\t2.r")
    )
    assert ".\t8qg" in result.lines
    assert len(result.lines) == len(document.lines)


def test_split_preserves_rest_partly_outside_range():
    from spineworks.multibar_creation import split_multibar_rests

    source = (
        "**kern\n*M3/4\n=1\n!LO:N:vis=0\n1.r\n"
        "=2\n.\n=3\n*-\n"
    )
    document = HumdrumDocument.from_text(source)

    result, count, warnings = split_multibar_rests(
        document,
        kern_columns={0},
        start_measure=2,
        end_measure=2,
    )

    assert result.to_text() == source
    assert count == 0
    assert len(warnings) == 1
    assert "częściowo" in warnings[0]


def test_split_supports_common_and_cut_time():
    from spineworks.multibar_creation import split_multibar_rests

    for meter in ("*M4/4", "*M2/2"):
        source = f"**kern\n{meter}\n=1\n0r\n=2\n.\n=3\n*-\n"
        document = HumdrumDocument.from_text(source)

        result, count, warnings = split_multibar_rests(
            document,
            kern_columns={0},
        )

        assert count == 1
        assert not warnings
        assert result.to_text() == source.replace("0r\n", "1r\n").replace(
            "=2\n.\n", "=2\n1r\n"
        )
