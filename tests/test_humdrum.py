from pathlib import Path

import pytest

from spineworks.humdrum import HumdrumDocument, HumdrumError


EXCLUSIVE = "**kern\t**fba\t**dynam\t**kern\t**text"


def test_reads_spine_types() -> None:
    document = HumdrumDocument.from_text(
        f"!!!OTL: Test\n{EXCLUSIVE}\n*part2\t*\t*part2\t*part1\t*part1\n"
        "*staff2\t*\t*\t*staff1\t*staff1\n=1\t=1\t=1\t=1\t=1\n"
    )

    assert document.spine_count == 5
    assert document.spine_types == ["**kern", "**fba", "**dynam", "**kern", "**text"]


def test_propagates_part_and_staff_until_next_kern() -> None:
    document = HumdrumDocument.from_text(
        f"{EXCLUSIVE}\n*part2\t*\t*part2\t*part1\t*part1\n"
        "*staff2\t*\t*\t*staff1\t*\n=1\t=1\t=1\t=1\t=1\n"
    )

    assert document.propagate_kern_assignments() is True
    assert document.fields(document.header.part_line) == [
        "*part2",
        "*part2",
        "*part2",
        "*part1",
        "*part1",
    ]
    assert document.fields(document.header.staff_line) == [
        "*staff2",
        "*staff2",
        "*staff2",
        "*staff1",
        "*staff1",
    ]


def test_second_propagation_is_noop() -> None:
    document = HumdrumDocument.from_text(
        f"{EXCLUSIVE}\n*part2\t*part2\t*part2\t*part1\t*part1\n"
        "*staff2\t*staff2\t*staff2\t*staff1\t*staff1\n=1\t=1\t=1\t=1\t=1\n"
    )

    assert document.propagate_kern_assignments() is False


def test_rejects_missing_staff_row() -> None:
    document = HumdrumDocument.from_text(
        f"{EXCLUSIVE}\n*part2\t*\t*\t*part1\t*part1\n=1\t=1\t=1\t=1\t=1\n"
    )

    with pytest.raises(HumdrumError, match="staff"):
        document.propagate_kern_assignments()


def test_uploaded_file_has_sixteen_spines() -> None:
    sample = Path(__file__).parents[2] / "upload" / "data.krn"
    if not sample.exists():
        pytest.skip("Załączony plik jest dostępny tylko w środowisku roboczym.")

    document = HumdrumDocument.from_path(sample)

    assert document.spine_count == 16

