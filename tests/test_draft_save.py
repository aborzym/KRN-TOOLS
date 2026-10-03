import stat
from pathlib import Path

import pytest

from spineworks.draft_save import (
    compose_drafts,
    prepare_save_text,
    write_verified_text,
)
from spineworks.humdrum import HumdrumDocument, HumdrumError
from spineworks.spine_validation import (
    FragmentDraft,
    build_fragment_rows,
    build_measure_view,
    find_split_issues,
    group_split_issues,
    trace_spines,
)


def make_save_drafts() -> tuple[
    HumdrumDocument,
    FragmentDraft,
    FragmentDraft,
]:
    document = HumdrumDocument.from_text(
        "**kern\n"
        "=1\n"
        "4c\n"
        "*^\n"
        "4d\t4ryy\n"
        "2e\t2ryy\n"
        "*v\t*v\n"
        "=2\n"
        "4f\n"
        "*^\n"
        "4g\t4ryy\n"
        "2a\t2ryy\n"
        "*v\t*v\n"
        "=3\n"
        "*-\n"
    )
    trace = trace_spines(document)
    issues = find_split_issues(trace)
    problems = group_split_issues(trace, issues)
    drafts = tuple(
        FragmentDraft(
            document,
            build_fragment_rows(
                trace,
                problem,
                build_measure_view(trace, problem, issues),
            ),
        )
        for problem in problems
    )
    assert len(drafts) == 2
    return document, drafts[0], drafts[1]


@pytest.mark.parametrize("reverse", [False, True])
def test_composes_two_ranges_and_preserves_original_numbers(
    reverse: bool,
) -> None:
    document, first, second = make_save_drafts()
    original = document.to_text()

    for draft, opening, data_line, note in (
        (first, 4, 3, "4b"),
        (second, 10, 9, "4cc"),
    ):
        draft.edit_token(data_line, 0, note)
        with draft.group_changes():
            assert draft.move_split(opening, 0) is not None
            draft.propose_tokens(((data_line, 1, "4ryy"),))

    first_text = first.to_text()
    second_text = second.to_text()
    drafts = (second, first) if reverse else (first, second)

    combined = compose_drafts(document, drafts)
    candidate = HumdrumDocument.from_text(combined)
    trace = trace_spines(candidate)

    assert trace.issue is None
    assert find_split_issues(trace) == ()
    assert "4b\t4ryy" in combined
    assert "4cc\t4ryy" in combined
    assert document.to_text() == original
    assert first.to_text() == first_text
    assert second.to_text() == second_text
    assert first.pending_suggestions == ((3, 1),)
    assert second.pending_suggestions == ((9, 1),)


def test_conflicting_changes_are_rejected_without_mutating_drafts() -> None:
    document, first, _ = make_save_drafts()
    _, conflicting, _ = make_save_drafts()
    first.edit_token(3, 0, "4g")
    conflicting.edit_token(3, 0, "4a")
    before = (first.to_text(), conflicting.to_text())

    with pytest.raises(ValueError, match="sprzeczne zmiany"):
        compose_drafts(document, (first, conflicting))

    assert (first.to_text(), conflicting.to_text()) == before


def test_identical_changes_can_be_combined() -> None:
    document, first, _ = make_save_drafts()
    _, duplicate, _ = make_save_drafts()
    first.edit_token(3, 0, "4g")
    duplicate.edit_token(3, 0, "4g")

    assert compose_drafts(document, (first, duplicate)) == first.to_text()


def test_rejects_draft_from_different_source_version() -> None:
    document, first, _ = make_save_drafts()
    changed = HumdrumDocument.from_text(document.to_text().replace("4c\n", "4b\n", 1))

    with pytest.raises(ValueError, match="innej wersji"):
        compose_drafts(changed, (first,))


def test_rejects_unfilled_structural_edit() -> None:
    document, first, _ = make_save_drafts()
    assert first.move_split(4, 0) is not None

    with pytest.raises(HumdrumError, match="Puste pole"):
        compose_drafts(document, (first,))


def test_empty_selection_preserves_source_text() -> None:
    document, _, _ = make_save_drafts()

    assert compose_drafts(document, ()) == document.to_text()


def test_save_accepts_pending_proposals_without_approving_them() -> None:
    document, first, second = make_save_drafts()

    with first.group_changes():
        assert first.move_split(4, 0) is not None
        first.propose_tokens(((3, 1, "4ryy"),))

    before = first.to_text()
    pending = first.pending_suggestions
    result = prepare_save_text(
        document,
        (
            (first, 2, 8),
            (second, 8, 14),
        ),
    )

    assert result == before
    assert first.to_text() == before
    assert first.pending_suggestions == pending
    assert pending == ((3, 1),)
    assert second.dirty is False


def test_save_rejects_changed_range_that_still_has_placement_error() -> None:
    document, first, _ = make_save_drafts()
    first.edit_token(3, 0, "4g")
    before = first.to_text()

    with pytest.raises(ValueError, match="Nie można zapisać zmian"):
        prepare_save_text(document, ((first, 2, 8),))

    assert first.to_text() == before


def test_save_accepts_approved_changes() -> None:
    document, first, _ = make_save_drafts()

    with first.group_changes():
        assert first.move_split(4, 0) is not None
        first.propose_tokens(((3, 1, "4ryy"),))
    first.approve_suggestions()

    result = prepare_save_text(document, ((first, 2, 8),))

    assert result == first.to_text()
    assert first.pending_suggestions == ()


def test_write_preserves_permissions_and_cleans_temporary_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "test.krn"
    path.write_text("oryginał\n", encoding="utf-8")
    path.chmod(0o640)

    write_verified_text(
        path,
        expected_text="oryginał\n",
        new_text="poprawiony plik\n",
    )

    assert path.read_text(encoding="utf-8") == "poprawiony plik\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert sorted(item.name for item in tmp_path.iterdir()) == ["test.krn"]


def test_write_rejects_external_changes_without_overwriting_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "test.krn"
    path.write_text("zmiana z VHV\n", encoding="utf-8")

    with pytest.raises(ValueError, match="zmienił się"):
        write_verified_text(
            path,
            expected_text="oryginał\n",
            new_text="zmiana ze SPINEWORKS\n",
        )

    assert path.read_text(encoding="utf-8") == "zmiana z VHV\n"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["test.krn"]


def test_failed_replace_preserves_original_and_cleans_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "test.krn"
    path.write_text("oryginał\n", encoding="utf-8")

    def fail_replace(source: object, destination: object) -> None:
        raise OSError("Próbny błąd zapisu.")

    monkeypatch.setattr("spineworks.draft_save.os.replace", fail_replace)

    with pytest.raises(OSError, match="Próbny błąd"):
        write_verified_text(
            path,
            expected_text="oryginał\n",
            new_text="poprawiony plik\n",
        )

    assert path.read_text(encoding="utf-8") == "oryginał\n"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["test.krn"]
