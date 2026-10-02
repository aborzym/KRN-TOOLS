import pytest

from spineworks.humdrum import HumdrumDocument, HumdrumError
from spineworks.meter_rhythm import MeterSignature
from spineworks.spine_rhythm import meter_at_line


def test_reads_independent_instrument_meters() -> None:
    document = HumdrumDocument.from_text(
        "**kern\t**kern\n*M3/4\t*M6/8\n=1\t=1\n2.ryy\t2.ryy\n*-\t*-\n"
    )

    assert meter_at_line(document, 4, 0) == MeterSignature(3, 4)
    assert meter_at_line(document, 4, 1) == MeterSignature(6, 8)


def test_meter_change_applies_from_its_line() -> None:
    document = HumdrumDocument.from_text("**kern\n*M4/4\n=1\n1ryy\n*M3/4\n=2\n2.ryy\n*-\n")

    assert meter_at_line(document, 4, 0) == MeterSignature(4, 4)
    assert meter_at_line(document, 5, 0) == MeterSignature(3, 4)
    assert meter_at_line(document, 7, 0) == MeterSignature(3, 4)


def test_split_branches_inherit_meter() -> None:
    document = HumdrumDocument.from_text("**kern\n*M6/4\n=1\n*^\n*\t*\n1.ryy\t1.ryy\n*v\t*v\n*-\n")

    assert meter_at_line(document, 6, 0) == MeterSignature(6, 4)


def test_rejects_conflicting_meter_tokens_in_split_row() -> None:
    document = HumdrumDocument.from_text("**kern\n*M4/4\n=1\n*^\n*M3/4\t*M6/8\n*v\t*v\n*-\n")

    with pytest.raises(HumdrumError, match="różne metra"):
        meter_at_line(document, 5, 0)


def test_missing_meter_is_not_assumed_to_be_four_four() -> None:
    document = HumdrumDocument.from_text("**kern\n=1\n1ryy\n*-\n")

    with pytest.raises(HumdrumError, match="brak metrum"):
        meter_at_line(document, 3, 0)


@pytest.mark.parametrize("source_line", [0, 5])
def test_rejects_line_outside_document(source_line: int) -> None:
    document = HumdrumDocument.from_text("**kern\n*M4/4\n1ryy\n*-\n")

    with pytest.raises(HumdrumError, match="wykracza poza dokument"):
        meter_at_line(document, source_line, 0)


@pytest.mark.parametrize("root_column", [-1, 1])
def test_rejects_unknown_root_spine(root_column: int) -> None:
    document = HumdrumDocument.from_text("**kern\n*M4/4\n1ryy\n*-\n")

    with pytest.raises(HumdrumError, match="spine źródłowy"):
        meter_at_line(document, 3, root_column)
