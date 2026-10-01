from spineworks.spine_validation import RecordKind, read_records


def test_spaces_do_not_create_spines() -> None:
    record = read_records("4e\\ 4cc 4aa\t2ryy\n")[0]

    assert record.kind is RecordKind.DATA
    assert record.spine_count == 2
    assert record.fields == ("4e\\ 4cc 4aa", "2ryy")


def test_global_records_have_no_spine_count() -> None:
    records = read_records("!!Komentarz\n!!!OMD: Allegro\n")

    assert len(records) == 2
    assert all(record.kind is RecordKind.GLOBAL for record in records)
    assert all(record.spine_count is None for record in records)


def test_preserves_every_line_and_its_number() -> None:
    records = read_records(
        "**kern\n=45\n!!Komentarz globalny\n\n*^\n!\t!\n2c\t2ryy\n.\t.\n*v\t*v\n=46\n*-\n"
    )

    assert [record.line_number for record in records] == list(range(1, 12))
    assert [record.kind for record in records] == [
        RecordKind.INTERPRETATION,
        RecordKind.BARLINE,
        RecordKind.GLOBAL,
        RecordKind.EMPTY,
        RecordKind.INTERPRETATION,
        RecordKind.LOCAL_COMMENT,
        RecordKind.DATA,
        RecordKind.DATA,
        RecordKind.INTERPRETATION,
        RecordKind.BARLINE,
        RecordKind.INTERPRETATION,
    ]
    assert records[7].fields == (".", ".")
    assert records[7].spine_count == 2


def test_empty_field_is_preserved_for_later_validation() -> None:
    record = read_records("4c\t\t4e\t\n")[0]

    assert record.spine_count == 4
    assert record.fields == ("4c", "", "4e", "")
