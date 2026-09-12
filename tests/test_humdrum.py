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
    assert document.lines[document.header.instrument_abbr_line + 1] == ("*Iorg\t*\t*\t*Ivioln\t*")


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
        "*part2",
        "*part2",
        "*part2",
        "*part2",
        "*part1",
        "*part1",
    ]
    assert document.fields(document.header.staff_line) == [
        "*staff4",
        "*staff4",
        "*staff3",
        "*staff3",
        "*staff2",
        "*staff1",
    ]


def test_adds_updates_and_removes_system_decoration() -> None:
    document = HumdrumDocument.from_text("!!!COM: Test, Composer\n**kern\n*part1\n*staff1\n*-\n")

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
        "!!!COM: Test, Composer\n!!!!SEGMENT: old.krn\n!!!!SEGMENT: duplicate.krn\n**kern\n*-\n"
    )

    assert document.set_segment("new.krn") is True
    assert document.lines[0] == "!!!!SEGMENT: new.krn"
    assert sum(line.startswith("!!!!SEGMENT:") for line in document.lines) == 1


def test_marks_text_italics_using_existing_interpretation_records() -> None:
    document = HumdrumDocument.from_text("**text\nKy-\n*\n! komentarz\n/ri-\ne/\n*\nA-\n*-\n")

    assert document.mark_text_italics() is True
    assert document.lines == [
        "**text",
        "Ky-",
        "*ij",
        "! komentarz",
        "ri-",
        "e",
        "*Xij",
        "A-",
        "*-",
    ]


def test_inserts_text_italics_around_local_comments() -> None:
    document = HumdrumDocument.from_text(
        "**text\nGlo-\n! pierwszy komentarz\n! drugi komentarz\n/ri-a/\nPa-\ntri\n*-\n"
    )

    assert document.mark_text_italics() is True
    assert document.lines == [
        "**text",
        "Glo-",
        "*ij",
        "! pierwszy komentarz",
        "! drugi komentarz",
        "ri-a",
        "*Xij",
        "Pa-",
        "tri",
        "*-",
    ]


def test_joins_adjacent_text_italic_ranges() -> None:
    document = HumdrumDocument.from_text("**text\n/Do\nmi\nne/\n/De-\nus/\nA-\nmen\n*-\n")

    assert document.mark_text_italics() is True
    assert document.lines == [
        "**text",
        "*ij",
        "Do",
        "mi",
        "ne",
        "De-",
        "us",
        "*Xij",
        "A-",
        "men",
        "*-",
    ]


def test_reports_all_text_italic_errors_with_staff_context() -> None:
    source = (
        "**kern\t**text\t**kern\t**text\n"
        "*staff2\t*staff2\t*staff1\t*staff1\n"
        '*I"Violino\t*\t*I"Violoncello\t*\n'
        "*I'vl\t*\t*\t*\n"
        "4c\t/Ky-\t4C\t-e/\n"
        "*-\t*-\t*-\t*-\n"
    )
    document = HumdrumDocument.from_text(source)

    with pytest.raises(HumdrumError) as caught:
        document.mark_text_italics()

    assert str(caught.value).splitlines() == [
        "Brak zamknięcia kursywy — staff 2 (vl), linia 5: /Ky-",
        "Brak otwarcia kursywy — staff 1 (Violoncello), linia 5: -e/",
    ]
    assert document.to_text() == source


def test_reports_text_italic_spine_split_as_an_error() -> None:
    source = (
        "**kern\t**text\n*staff1\t*staff1\n*I\"Voce\t*\n*I'V\t*\n4c\t/Ky-\n*\t*^\n4d\te/\n*-\t*-\n"
    )
    document = HumdrumDocument.from_text(source)

    with pytest.raises(HumdrumError) as caught:
        document.mark_text_italics()

    assert str(caught.value) == ("Błędne rozdwojenie spine’u **text — staff 1 (V), linia 6: *^")
    assert document.to_text() == source


def test_combines_text_italic_markers_in_shared_records() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**text\t**mod-text\n"
        "*staff1\t*staff1\t*staff1\n"
        '*I"Voce\t*\t*\n'
        "*I'V\t*\t*\n"
        "4c\t/Ky-\t/Glo-\n"
        "4d\te/\tria/\n"
        "*-\t*-\t*-\n"
    )

    assert document.mark_text_italics() is True
    assert document.lines == [
        "**kern\t**text\t**mod-text",
        "*staff1\t*staff1\t*staff1",
        '*I"Voce\t*\t*',
        "*I'V\t*\t*",
        "*\t*ij\t*ij",
        "4c\tKy-\tGlo-",
        "4d\te\tria",
        "*\t*Xij\t*Xij",
        "*-\t*-\t*-",
    ]


def test_leaves_text_without_italic_markers_unchanged() -> None:
    source = "**text\nKy-\nri-\ne\n*-\n"
    document = HumdrumDocument.from_text(source)

    assert document.mark_text_italics() is False
    assert document.to_text() == source


def test_corrects_custos_comments_before_barline() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\t**kern\n"
        "*staff3\t*staff2\t*staff1\n"
        "!LO:SIC:custos G:v\t"
        "!LO:SIC:custos:G:t=v\t"
        "!LO:TX:t=P:problem&colon;custos:f#:v\n"
        "4c\t4d\t4e\n"
        "! pierwszy komentarz\t!\t! trzeci komentarz\n"
        "=2\t=2\t=2\n"
        "4d\t4e\t4f#\n"
        "*-\t*-\t*-\n"
    )

    assert document.correct_custos() is True
    assert document.lines == [
        "**kern\t**kern\t**kern",
        "*staff3\t*staff2\t*staff1",
        "!\t!\t!",
        "4c\t4d\t4e",
        "*custos:G\t*custos:G\t*custos:f#",
        "! pierwszy komentarz\t!\t! trzeci komentarz",
        "=2\t=2\t=2",
        "4d\t4e\t4f#",
        "*-\t*-\t*-",
    ]


def test_corrects_custos_before_next_note_using_empty_interpretation() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n"
        "*staff1\n"
        "!LO:TX:problem=custos a:v\n"
        "4c\n"
        "*\n"
        "! komentarz przed następną nutą\n"
        "4d\n"
        "*-\n"
    )

    assert document.correct_custos() is True
    assert document.lines == [
        "**kern",
        "*staff1",
        "!",
        "4c",
        "*custos:a",
        "! komentarz przed następną nutą",
        "4d",
        "*-",
    ]


def test_inserts_custos_directly_before_next_note() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n*staff1\n!LO:SIC&colon;custos:cc:t=v\n4c\n4d\n*-\n"
    )

    assert document.correct_custos() is True
    assert document.lines == [
        "**kern",
        "*staff1",
        "!",
        "4c",
        "*custos:cc",
        "4d",
        "*-",
    ]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            "!LO:SIC:custos:G:t=v\n4c\n!LO:SIC:custos:A:t=v\n4d\n*-\n",
            "Drugi custos przed następną nutą",
        ),
        (
            "!LO:SIC:custos\n4c\n4d\n*-\n",
            "Brak dźwięku w oznaczeniu custos",
        ),
        (
            "!LO:SIC:custos:G:t=v\n*-\n",
            "Brak nuty opisanej przez custos",
        ),
        (
            "!LO:SIC:custos:G:t=v\n4c\n*^\n4d\n*-\n",
            "Błędne rozdwojenie spine’u **kern",
        ),
    ],
)
def test_reports_custos_errors_without_changing_document(
    body: str,
    message: str,
) -> None:
    source = f"**kern\n*staff1\n*I'vl\n{body}"
    document = HumdrumDocument.from_text(source)
    original_lines = document.lines.copy()

    with pytest.raises(HumdrumError) as caught:
        document.correct_custos()

    assert message in str(caught.value)
    assert document.lines == original_lines


def test_hides_selected_kern_and_dynam_in_inclusive_measure_range() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\t**kern\t**dynam\n"
        "*staff2\t*staff2\t*staff1\t*staff1\n"
        "=1\t=1\t=1\t=1\n"
        "4c\tf\t4e\tp\n"
        "=2\t=2\t=2\t=2\n"
        "(16ccc#\\;LL\tf<\t4e\tpp\n"
        "4d)\t>\t4f\t<\n"
        "=3\t=3\t=3\t=3\n"
        "[yy4eyy\tppyy\t[4g\tmf\n"
        "4e]\t<\t4g]\t>\n"
        "=4\t=4\t=4\t=4\n"
        "4f\t.\t4a\tff\n"
        "*-\t*-\t*-\t*-\n"
    )

    assert (
        document.hide_measure_range(
            start_measure=2,
            end_measure=3,
            kern_columns={0},
            duplicate_existing=True,
        )
        is True
    )
    assert document.lines == [
        "**kern\t**dynam\t**kern\t**dynam",
        "*staff2\t*staff2\t*staff1\t*staff1",
        "=1\t=1\t=1\t=1",
        "4c\tf\t4e\tp",
        "=2\t=2\t=2\t=2",
        "(yy16ccc#\\;LLyy\tf<yy\t4e\tpp",
        "4d)yy\t>yy\t4f\t<",
        "=3\t=3\t=3\t=3",
        "[yyyy4eyyyy\tppyyyy\t[4g\tmf",
        "4e]yy\t<yy\t4g]\t>",
        "=4\t=4\t=4\t=4",
        "4f\t.\t4a\tff",
        "*-\t*-\t*-\t*-",
    ]


@pytest.mark.parametrize(
    ("selected_columns", "expected_dynam"),
    [
        ({0}, "f"),
        ({1}, "f"),
        ({0, 1}, "fyy"),
    ],
)
def test_hides_shared_dynam_only_when_all_related_kerns_are_selected(
    selected_columns: set[int],
    expected_dynam: str,
) -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\t**dynam\n"
        "*staff1\t*staff1\t*staff1\n"
        "=2\t=2\t=2\n"
        "4c\t4e\tf\n"
        "=3\t=3\t=3\n"
        "4d\t4f\t.\n"
        "*-\t*-\t*-\n"
    )

    assert (
        document.hide_measure_range(
            start_measure=2,
            end_measure=2,
            kern_columns=selected_columns,
        )
        is True
    )

    expected_first_kern = "4cyy" if 0 in selected_columns else "4c"
    expected_second_kern = "4eyy" if 1 in selected_columns else "4e"
    assert document.lines[3] == (f"{expected_first_kern}\t{expected_second_kern}\t{expected_dynam}")


def test_hides_both_split_branches_and_the_merged_kern() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\n"
        "*staff1\t*staff1\n"
        "=2a\t=2a\n"
        "4c\tf\n"
        "*^\t*\n"
        "(4d\t4e\t<\n"
        "4f\t4g\t.\n"
        "*v\t*v\t*\n"
        "4a\tff\n"
        "=3\t=3\n"
        "4b\tp\n"
        "*-\t*-\n"
    )

    assert (
        document.hide_measure_range(
            start_measure=2,
            end_measure=2,
            kern_columns={0},
        )
        is True
    )
    assert document.lines == [
        "**kern\t**dynam",
        "*staff1\t*staff1",
        "=2a\t=2a",
        "4cyy\tfyy",
        "*^\t*",
        "(yy4dyy\t4eyy\t<yy",
        "4fyy\t4gyy\t.",
        "*v\t*v\t*",
        "4ayy\tffyy",
        "=3\t=3",
        "4b\tp",
        "*-\t*-",
    ]


@pytest.mark.parametrize(
    "manipulator_line",
    [
        "*x\t*x",
        "*+\t*",
    ],
)
def test_rejects_unsupported_manipulators_when_hiding_range(
    manipulator_line: str,
) -> None:
    source = (
        f"**kern\t**kern\n*staff2\t*staff1\n=2\t=2\n4c\t4e\n{manipulator_line}\n4d\t4f\n*-\t*-\n"
    )
    document = HumdrumDocument.from_text(source)
    original_lines = document.lines.copy()

    with pytest.raises(HumdrumError, match="Nieobsługiwany manipulator spine’u"):
        document.hide_measure_range(
            start_measure=2,
            end_measure=2,
            kern_columns={0},
        )

    assert document.lines == original_lines


def test_does_not_duplicate_existing_yy_by_default() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\n*staff1\t*staff1\n=2\t=2\n[yy4cyy\tppyy\n4d)yy\t<yy\n*-\t*-\n"
    )
    original_lines = document.lines.copy()

    assert (
        document.hide_measure_range(
            start_measure=2,
            end_measure=2,
            kern_columns={0},
        )
        is False
    )
    assert document.lines == original_lines


def test_caps_existing_yy_at_four() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\n"
        "*staff1\t*staff1\n"
        "=2\t=2\n"
        "[yyyyyy4cyyyyyy\tppyyyyyy\n"
        "4d)yyyyyy\t<yyyyyy\n"
        "*-\t*-\n"
    )

    assert (
        document.hide_measure_range(
            start_measure=2,
            end_measure=2,
            kern_columns={0},
            duplicate_existing=True,
        )
        is True
    )
    assert document.lines == [
        "**kern\t**dynam",
        "*staff1\t*staff1",
        "=2\t=2",
        "[yyyy4cyyyy\tppyyyy",
        "4d)yyyy\t<yyyy",
        "*-\t*-",
    ]
