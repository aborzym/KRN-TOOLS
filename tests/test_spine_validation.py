from spineworks.humdrum import HumdrumDocument
from spineworks.spine_validation import RecordKind, read_records, trace_spines


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


def test_tracks_identity_and_width_before_each_operation() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**dynam\n"
        '*I"Violin 2\t*\n'
        "*part14\t*part14\n"
        "*staff14\t*staff14\n"
        "=45\t=45\n"
        "*^\t*\n"
        "2c\t2ryy\tp\n"
        "*v\t*v\t*\n"
        "=46\t=46\n"
        "*-\t*-\n"
    )

    trace = trace_spines(document)

    assert trace.issue is None
    opening = trace.records[5]
    data = trace.records[6]
    closing = trace.records[7]
    next_barline = trace.records[8]

    assert len(opening.branches) == 2
    assert len(data.branches) == 3
    assert len(closing.branches) == 3
    assert len(next_barline.branches) == 2

    left, right = data.branches[:2]
    assert left.identity == right.identity
    assert left.identity.instrument == "Violin 2"
    assert left.identity.spine_type == "**kern"
    assert left.identity.part == "*part14"
    assert left.identity.staff == "*staff14"
    assert left.path == (0,)
    assert right.path == (1,)
    assert next_barline.branches[0].path == ()


def test_tracks_nested_split_and_partial_then_full_merge() -> None:
    document = HumdrumDocument.from_text(
        "**kern\n=1\n*^\n*^\t*\n4c\t4e\t4g\n*v\t*v\t*\n*v\t*v\n=2\n*-\n"
    )

    trace = trace_spines(document)

    assert trace.issue is None
    assert [branch.path for branch in trace.records[4].branches] == [
        (0, 0),
        (0, 1),
        (1,),
    ]
    assert [branch.path for branch in trace.records[6].branches] == [(0,), (1,)]
    assert trace.records[7].branches[0].path == ()


def test_allows_final_termination_of_unmerged_branches() -> None:
    document = HumdrumDocument.from_text("**kern\n=1\n*^\n2c\t2e\n*-\t*-\n!!!END: Test\n")

    assert trace_spines(document).issue is None


def test_stops_at_wrong_width_without_guessing_later_identity() -> None:
    document = HumdrumDocument.from_text("**kern\n=1\n*^\n4c\n=2\t=2\n")

    trace = trace_spines(document)

    assert trace.issue is not None
    assert trace.issue.line_number == 4
    assert "oczekiwano 2, znaleziono 1" in trace.issue.message
    assert len(trace.records) == 4


def test_rejects_merge_of_independent_root_spines() -> None:
    document = HumdrumDocument.from_text("**kern\t**kern\n=1\t=1\n2c\t2e\n*v\t*v\n")

    trace = trace_spines(document)

    assert trace.issue is not None
    assert trace.issue.line_number == 4
    assert "Nieprawidłowe scalenie" in trace.issue.message


def test_reports_unsupported_manipulators() -> None:
    for token in ("*x", "*+"):
        document = HumdrumDocument.from_text(f"**kern\t**kern\n=1\t=1\n{token}\t*\n")

        trace = trace_spines(document)

        assert trace.issue is not None
        assert trace.issue.line_number == 3
        assert token in trace.issue.message


def test_rejects_early_termination() -> None:
    document = HumdrumDocument.from_text("**kern\t**kern\n=1\t=1\n*-\t*\n4c\n")

    trace = trace_spines(document)

    assert trace.issue is not None
    assert trace.issue.line_number == 3
    assert "przed końcem utworu" in trace.issue.message
