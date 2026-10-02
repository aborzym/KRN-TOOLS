from fractions import Fraction

import pytest

from spineworks.humdrum import HumdrumError
from spineworks.kern_rhythm import (
    advance_kern_row,
    hidden_rest_token,
    kern_duration,
)


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


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        (Fraction(1), "1ryy"),
        (Fraction(1, 2), "2ryy"),
        (Fraction(3, 4), "2.ryy"),
        (Fraction(7, 8), "2..ryy"),
        (Fraction(1, 6), "6ryy"),
        (Fraction(2), "0ryy"),
        (Fraction(4), "00ryy"),
        (Fraction(3), "0.ryy"),
    ],
)
def test_creates_hidden_rest(
    duration: Fraction,
    expected: str,
) -> None:
    token = hidden_rest_token(duration)

    assert token == expected
    assert kern_duration(token) == duration


@pytest.mark.parametrize(
    "duration",
    [Fraction(0), Fraction(-1, 4), Fraction(5, 8)],
)
def test_rejects_duration_unsuitable_for_single_rest(
    duration: Fraction,
) -> None:
    with pytest.raises(HumdrumError):
        hidden_rest_token(duration)


def test_row_advances_by_shortest_active_duration() -> None:
    elapsed, remaining = advance_kern_row(
        ("2c", "4e"),
        (Fraction(0), Fraction(0)),
    )

    assert elapsed == Fraction(1, 4)
    assert remaining == (Fraction(1, 4), Fraction(0))


def test_null_token_continues_longer_note() -> None:
    elapsed, remaining = advance_kern_row(
        (".", "4f"),
        (Fraction(1, 4), Fraction(0)),
    )

    assert elapsed == Fraction(1, 4)
    assert remaining == (Fraction(0), Fraction(0))


def test_grace_row_does_not_advance_time() -> None:
    elapsed, remaining = advance_kern_row(
        ("8cq", "."),
        (Fraction(0), Fraction(1, 4)),
    )

    assert elapsed == 0
    assert remaining == (Fraction(0), Fraction(1, 4))


def test_grace_note_preserves_active_duration() -> None:
    elapsed, remaining = advance_kern_row(
        ("8cq", "8eq"),
        (Fraction(1, 4), Fraction(0)),
    )

    assert elapsed == 0
    assert remaining == (Fraction(1, 4), Fraction(0))


def test_regular_note_in_grace_row_starts_without_advancing_time() -> None:
    elapsed, remaining = advance_kern_row(
        ("8cq", "4e"),
        (Fraction(0), Fraction(0)),
    )

    assert elapsed == 0
    assert remaining == (Fraction(0), Fraction(1, 4))


def test_null_token_without_active_note_is_allowed_in_grace_row() -> None:
    elapsed, remaining = advance_kern_row(
        ("8cq", "."),
        (Fraction(0), Fraction(0)),
    )

    assert elapsed == 0
    assert remaining == (Fraction(0), Fraction(0))


@pytest.mark.parametrize(
    ("tokens", "remaining"),
    [
        ((), ()),
        (("4c",), (Fraction(0), Fraction(0))),
        (("4c",), (Fraction(-1, 4),)),
        ((".",), (Fraction(0),)),
        (("4c",), (Fraction(1, 8),)),
    ],
)
def test_rejects_invalid_row_timing(
    tokens: tuple[str, ...],
    remaining: tuple[Fraction, ...],
) -> None:
    with pytest.raises(HumdrumError):
        advance_kern_row(tokens, remaining)
