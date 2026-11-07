from spineworks.header_templates import collect_header_template
from spineworks.humdrum import HumdrumDocument


def test_collects_existing_rows_in_template_order():
    source = (
        "**kern\t**dynam\t**kern\n"
        "*IGstrings\t*\t*IGvoices\n"
        "*ICstr\t*\t*ICvox\n"
        "*Ivioln\t*\t*Ivox\n"
        "*I'Vl\t*\t*I'S\n"
        '*mI"Violin\t*\t*mI"Soprano\n'
        '*I"Violino\t*\t*I"Canto\n'
        "*staff2\t*staff2\t*staff1\n"
        "*part2\t*part2\t*part1\n"
        "*clefG2\t*\t*clefC1\n"
        "*k[b-]\t*\t*k[b-]\n"
        "*ITrd0c0\t*\t*ITrd0c0\n"
        "=1\t=1\t=1\n"
        "4c\tp\t4e\n"
        "*-\t*-\t*-\n"
    )
    document = HumdrumDocument.from_text(source)

    template = collect_header_template(document, name="Próba")

    assert template["kern_count"] == 2
    assert template["row_order"] == [
        "part",
        "staff",
        "name",
        "modern_name",
        "abbreviation",
        "group",
        "class",
        "code",
        "transposition",
    ]
    assert template["rows"] == {
        "part": ["*part2", "*part1"],
        "staff": ["*staff2", "*staff1"],
        "name": ['*I"Violino', '*I"Canto'],
        "modern_name": ['*mI"Violin', '*mI"Soprano'],
        "abbreviation": ["*I'Vl", "*I'S"],
        "group": ["*IGstrings", "*IGvoices"],
        "class": ["*ICstr", "*ICvox"],
        "code": ["*Ivioln", "*Ivox"],
        "transposition": ["*ITrd0c0", "*ITrd0c0"],
    }
    assert document.to_text() == source


def test_collects_only_selected_existing_rows():
    document = HumdrumDocument.from_text(
        '**kern\n*part1\n*staff1\n*I"Violino\n*clefG2\n*k[]\n4c\n*-\n'
    )

    template = collect_header_template(
        document,
        name="  Violino  ",
        selected_rows={"name", "modern_name", "modern_abbreviation"},
    )

    assert template["name"] == "Violino"
    assert template["row_order"] == ["name"]
    assert template["rows"] == {"name": ['*I"Violino']}


def test_applies_template_to_different_auxiliary_spines():
    from spineworks.header_templates import apply_header_template

    source = HumdrumDocument.from_text(
        "**kern\t**dynam\t**kern\n"
        "*part2\t*part2\t*part1\n"
        "*staff2\t*staff2\t*staff1\n"
        '*I"Violino\t*\t*I"Canto\n'
        '*mI"Violin\t*\t*mI"Soprano\n'
        "*IGstrings\t*\t*IGvoices\n"
        "*ICstr\t*\t*ICvox\n"
        "*Ivioln\t*\t*Ivox\n"
        "*ITrd0c0\t*\t*ITrd0c0\n"
        "4c\tp\t4e\n"
        "*-\t*-\t*-\n"
    )
    target_text = (
        "**kern\t**text\t**kern\t**dynam\n"
        "*ITrd1c2\t*\t*ITrd1c2\t*\n"
        "*k[b-]\t*\t*k[b-]\t*\n"
        "*clefF4\t*\t*clefC1\t*\n"
        '*I"Old\t*I"Tekst\t*I"Old2\t*\n'
        "*staff9\t*staff9\t*staff8\t*staff8\n"
        "*part9\t*part9\t*part8\t*part8\n"
        "*M3/4\t*\t*M3/4\t*\n"
        "=1\t=1\t=1\t=1\n"
        "4c\tla\t4e\tp\n"
        "*-\t*-\t*-\t*-\n"
    )
    target = HumdrumDocument.from_text(target_text)
    template = collect_header_template(source, name="Próba")

    result = apply_header_template(target, template)

    assert result.lines == [
        "**kern\t**text\t**kern\t**dynam",
        "*part2\t*part2\t*part1\t*part1",
        "*staff2\t*staff2\t*staff1\t*staff1",
        '*I"Violino\t*I"Tekst\t*I"Canto\t*',
        '*mI"Violin\t*\t*mI"Soprano\t*',
        "*IGstrings\t*\t*IGvoices\t*",
        "*ICstr\t*\t*ICvox\t*",
        "*Ivioln\t*\t*Ivox\t*",
        "*clefF4\t*\t*clefC1\t*",
        "*k[b-]\t*\t*k[b-]\t*",
        "*ITrd0c0\t*\t*ITrd0c0\t*",
        "*M3/4\t*\t*M3/4\t*",
        "=1\t=1\t=1\t=1",
        "4c\tla\t4e\tp",
        "*-\t*-\t*-\t*-",
    ]
    assert target.to_text() == target_text
    assert apply_header_template(result, template).to_text() == result.to_text()


def test_rejects_different_kern_count_without_changing_target():
    import pytest

    from spineworks.header_templates import apply_header_template
    from spineworks.humdrum import HumdrumError

    source = HumdrumDocument.from_text('**kern\n*I"Violino\n4c\n*-\n')
    target_text = "**kern\t**kern\n4c\t4e\n*-\t*-\n"
    target = HumdrumDocument.from_text(target_text)
    template = collect_header_template(source, name="Jeden instrument")

    with pytest.raises(HumdrumError, match="kernów"):
        apply_header_template(target, template)

    assert target.to_text() == target_text


def test_suggested_name_preserves_metadata_spelling():
    from spineworks.header_templates import suggest_header_template_name

    document = HumdrumDocument.from_text(
        "!!!COM: Bernardini, Marcello\n"
        "!!!OTL: Con un moto orrendo e strano. Aria\n"
        "!!!SMS-siglum: PL-ŁA\n"
        "!!!SMS-shelfmark: RM 192\n"
        "**kern\n4c\n*-\n"
    )

    assert suggest_header_template_name(document) == (
        "Bernardini - Con un moto orrendo e strano. Aria - PL-ŁA-RM-192"
    )


def test_suggested_name_prefers_work_title():
    from spineworks.header_templates import suggest_header_template_name

    document = HumdrumDocument.from_text(
        "!!!COM: Pokorny, Franz Xaver\n"
        "!!!OPR: Requiem ex Dis\n"
        "!!!OTL: Dies irae\n"
        "!!!SMS-siglum: PL-CZ\n"
        "!!!SMS-shelfmark: III 545\n"
        "**kern\n4c\n*-\n"
    )

    assert suggest_header_template_name(document) == ("Pokorny - Requiem ex Dis - PL-CZ-III-545")


def test_suggested_name_falls_back_to_filename():
    from spineworks.header_templates import suggest_header_template_name

    document = HumdrumDocument.from_text("**kern\n4c\n*-\n")

    assert (
        suggest_header_template_name(document, "Próba Wielkich Liter.krn") == "Próba Wielkich Liter"
    )
