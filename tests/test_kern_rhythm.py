from fractions import Fraction

import pytest

from spineworks.humdrum import HumdrumError
from spineworks.kern_rhythm import kern_duration


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("1c", Fraction(1)),
        ("2ryy", Fraction(1, 2)),
        ("4c", Fraction(1, 4)),
        ("8.c", Fraction(3, 16)),
        ("2..ryy", Fraction(7, 8)),
        ("6c", Fraction(1, 6)),
        ("12c", Fraction(1, 12)),
        ("0r", Fraction(2)),
        ("00r", Fraction(4)),
        ("[4c", Fraction(1, 4)),
        ("2c 2e 2g", Fraction(1, 2)),
        ("8cq", Fraction(0)),
        ("cq", Fraction(0)),
        ("8cq 8eq", Fraction(0)),
    ],
)
def test_reads_kern_duration(
    token: str,
    expected: Fraction,
) -> None:
    assert kern_duration(token) == expected


def test_null_token_has_no_new_duration() -> None:
    assert kern_duration(".") is None


@pytest.mark.parametrize(
    "token",
    [
        "",
        " ",
        "*",
        "*^",
        "!komentarz",
        "=45",
        "c",
        "4c\t4e",
        "4c\n4e",
        "4c\r4e",
        "4c 8e",
        "8cq 8e",
        "03c",
        "3%2c",
    ],
)
def test_rejects_invalid_or_unsupported_rhythm(token: str) -> None:
    with pytest.raises(HumdrumError):
        kern_duration(token)
