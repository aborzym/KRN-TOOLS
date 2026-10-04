import pytest

from spineworks.hidden_ties import repair_hidden_ties
from spineworks.humdrum import HumdrumDocument


@pytest.mark.parametrize(
    ("start", "end", "expected_start", "expected_end", "count"),
    [
        ("[8BB/yy", "4.E\\]", "8BB/yy", "4.E\\", 1),
        ("[4B-yy", "4Bn]", "4B-yy", "4Bn", 1),
        ("[4B-yy", "4B]", "4B-yy", "4B", 1),
        ("[4Byy", "4Bn]", "[4Byy", "4Bn]", 0),
        ("[4Fyy", "4F]", "[4Fyy", "4F]", 0),
        ("[4C", "4D]", "[4C", "4D]", 0),
        (
            "[4Cyy [4E",
            "4E] 4D]",
            "4Cyy [4E",
            "4E] 4D",
            1,
        ),
        (
            "[4Cyy [4Eyy",
            "4F] 4D]",
            "4Cyy 4Eyy",
            "4F 4D",
            1,
        ),
        (
            "[4Cyy [4E",
            "4D] 4F]",
            "[4Cyy [4E",
            "4D] 4F]",
            0,
        ),
        ("[4Cyy", "[4D]", "4Cyy", "[4D", 1),
        ("4C_yy", "4D]", "4C]yy", "4D", 1),
        ("[4Cyy", "4D_", "4Cyy", "4D[", 1),
    ],
)
def test_cross_bar_hidden_ties(start, end, expected_start, expected_end, count):
    source = f"**kern\n=51\n{start}\n.\n!komentarz\n=52\n{end}\n*-\n"
    document = HumdrumDocument.from_text(source)

    result, repairs, warnings = repair_hidden_ties(document)

    expected = f"**kern\n=51\n{expected_start}\n.\n!komentarz\n=52\n{expected_end}\n*-\n"
    assert result.to_text() == expected
    assert len(repairs) == count
    assert document.to_text() == source

    if start == "[4Cyy [4E":
        assert bool(warnings) == (end == "4D] 4F]")

    again, repeated_repairs, _ = repair_hidden_ties(result)
    assert again.to_text() == result.to_text()
    assert not repeated_repairs


def test_preserves_ties_inside_measure():
    source = "**kern\n=51\n[4Cyy\n4D]\n=52\n4E\n*-\n"
    result, repairs, _ = repair_hidden_ties(HumdrumDocument.from_text(source))

    assert result.to_text() == source
    assert not repairs


def test_tracks_column_shift_from_other_spine_split():
    source = (
        "**kern\t**kern\n"
        "=51\t=51\n"
        "4r\t[4Cyy\n"
        "*^\t*\n"
        "!\t!\t!\n"
        "=52\t=52\t=52\n"
        "4r\t4r\t4D]\n"
        "*-\t*-\t*-\n"
    )
    result, repairs, _ = repair_hidden_ties(HumdrumDocument.from_text(source))

    assert result.to_text() == source.replace("[4Cyy", "4Cyy").replace("4D]", "4D")
    assert len(repairs) == 1


def test_preserves_spacing_and_non_kern_data():
    source = "**kern\t**text\n=51\t=51\n[4Cyy  [4E\t[tekstyy\n=52\t=52\n4E]  4D]\ttekst]\n*-\t*-\n"
    result, repairs, _ = repair_hidden_ties(HumdrumDocument.from_text(source))

    assert result.to_text() == source.replace("[4Cyy", "4Cyy").replace("4D]", "4D")
    assert len(repairs) == 1
