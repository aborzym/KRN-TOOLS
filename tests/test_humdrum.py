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


def test_adds_normalized_instrument_code_row_after_abbreviations() -> None:
    document = HumdrumDocument.from_text(
        f"{EXCLUSIVE}\n*part2\t*\t*\t*part1\t*\n"
        "*staff2\t*\t*\t*staff1\t*\n"
        "*I'Org\t*\t*\t*I'Vln\t*\n=1\t=1\t=1\t=1\t=1\n"
    )

    assert document.set_instrument_codes(["org", "ignored", "*", "Ivioln", "ignored"])
    assert document.instrument_codes() == ["*Iorg", "*", "*", "*Ivioln", "*"]
    assert document.lines[document.header.instrument_abbr_line + 1] == (
        "*Iorg\t*\t*\t*Ivioln\t*"
    )


def test_updates_existing_instrument_code_row() -> None:
    document = HumdrumDocument.from_text(
        f"{EXCLUSIVE}\n*part2\t*\t*\t*part1\t*\n"
        "*staff2\t*\t*\t*staff1\t*\n"
        "*Iorg\t*\t*\t*Ivioln\t*\n=1\t=1\t=1\t=1\t=1\n"
    )

    assert document.set_instrument_codes(["*Iorg", "*", "*", "*Iclars", "*"])
    assert document.instrument_codes()[3] == "*Iclars"


def test_updates_names_with_protected_prefixes() -> None:
    document = HumdrumDocument.from_text(
        f"{EXCLUSIVE}\n*part2\t*\t*\t*part1\t*\n"
        "*staff2\t*\t*\t*staff1\t*\n"
        '*I"Organo.\t*\t*\t*I"Violino.\t*\n'
        "*I'Org\t*\t*\t*I'Vln\t*\n=1\t=1\t=1\t=1\t=1\n"
    )

    assert document.set_instrument_names(["Organo", "", "", "Clarino", ""])
    assert document.set_instrument_abbreviations(["Org", "", "", "Cl", ""])
    assert document.fields(document.header.instrument_name_line)[3] == '*I"Clarino'
    assert document.fields(document.header.instrument_abbr_line)[3] == "*I'Cl"


def test_adds_instrument_group_between_class_and_code() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n*ICklav\t*ICvox\n*Iorgan\t*Ibass\n*-\t*-\n"
    )

    assert document.set_instrument_groups(["cont", ""])
    assert document.instrument_groups() == ["*IGcont", "*"]
    assert document.lines[1:4] == [
        "*ICklav\t*ICvox",
        "*IGcont\t*",
        "*Iorgan\t*Ibass",
    ]
    assert document.remove_instrument_groups()
    assert document.instrument_groups() == ["*", "*"]
    assert document.instrument_codes() == ["*Iorgan", "*Ibass"]


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


def test_recalculates_parts_and_staffs_with_keyboard_pairs() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**fing\t**kern\t**text\t**kern\t**kern\n"
        "*part9\t*\t*part8\t*\t*part7\t*part6\n"
        "*staff9\t*\t*staff8\t*\t*staff7\t*staff6\n"
        '*I"Organo\t*\t*I"Organo\t*\t*I"Piano\t*I"Piano\n'
        "*ICklav\t*\t*ICklav\t*\t*ICklav\t*ICklav\n"
        "=1\t=1\t=1\t=1\t=1\t=1\n"
    )

    assert document.propagate_kern_assignments() is True
    assert document.fields(document.header.part_line) == [
        "*part2", "*part2", "*part2", "*part2", "*part1", "*part1"
    ]
    assert document.fields(document.header.staff_line) == [
        "*staff4", "*staff4", "*staff3", "*staff3", "*staff2", "*staff1"
    ]


def test_adds_updates_and_removes_system_decoration() -> None:
    document = HumdrumDocument.from_text(
        "!!!COM: Test, Composer\n**kern\n*part1\n*staff1\n*-\n"
    )

    assert document.system_decoration() == ""
    assert document.set_system_decoration("[(s1)]") is True
    assert document.system_decoration() == "[(s1)]"
    assert document.lines[1] == "!!!system-decoration: [(s1)]"
    assert document.set_system_decoration("[(s1,s2)]") is True
    assert document.system_decoration() == "[(s1,s2)]"
    assert document.set_system_decoration("") is True
    assert document.system_decoration() == ""
    assert all(not line.startswith("!!!system-decoration:") for line in document.lines)


def test_adds_segment_as_first_line() -> None:
    document = HumdrumDocument.from_text("!!!COM: Test, Composer\n**kern\n*-\n")

    assert document.set_segment("test.krn") is True
    assert document.lines[0] == "!!!!SEGMENT: test.krn"
    assert document.set_segment("test.krn") is False


def test_updates_moves_and_deduplicates_segment() -> None:
    document = HumdrumDocument.from_text(
        "!!!COM: Test, Composer\n"
        "!!!!SEGMENT: old.krn\n"
        "!!!!SEGMENT: duplicate.krn\n"
        "**kern\n*-\n"
    )

    assert document.set_segment("new.krn") is True
    assert document.lines[0] == "!!!!SEGMENT: new.krn"
    assert sum(line.startswith("!!!!SEGMENT:") for line in document.lines) == 1
