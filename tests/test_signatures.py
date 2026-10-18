from datetime import date

import pytest

from spineworks.humdrum import HumdrumDocument
from spineworks.signatures import WORKFLOWS, add_signature, existing_signatures


def doc(metadata="", newline=True):
    return HumdrumDocument.from_text(metadata + "**kern\n4c\n*-" + ("\n" if newline else ""))


@pytest.mark.parametrize("workflow", WORKFLOWS)
@pytest.mark.parametrize("newline", [False, True])
def test_each_workflow_and_source_preservation(workflow, newline):
    original = doc("!!!system-decoration: s1\n", newline)
    before = original.to_text()
    updated = add_signature(original, workflow, "Łucja de TEST")
    spec = WORKFLOWS[workflow]
    assert updated.lines[1:3] == [
        f"!!!{spec.author}: Łucja de TEST",
        f"!!!{spec.dated}: {date.today().isoformat()}",  # noqa: DTZ011 — required local computer date
    ]
    assert original.to_text() == before
    assert updated.trailing_newline == newline
    assert updated.spine_types == ["**kern"]


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_preferred_anchor_priority_and_last_occurrence(workflow):
    spec = WORKFLOWS[workflow]
    metadata = "".join(f"!!!{anchor}: old\n" for anchor in spec.anchors)
    metadata += f"!!!{spec.anchors[0]}: last\n!!!END-other: newer\n"
    source = doc(metadata)
    updated = add_signature(source, workflow, "Jan Kowalski")
    index = source.lines.index(f"!!!{spec.anchors[0]}: last")
    assert updated.lines[index + 1].startswith(f"!!!{spec.author}:")


@pytest.mark.parametrize("anchor", ["END-other", "EEV-other", "END", "EEV"])
def test_date_signature_fallback(anchor):
    source = doc(f"!!!{anchor}: date\n!!!ODT: 1800\n")
    assert add_signature(source, "xml", "Jan").lines[1] == "!!!ENC-review: Jan"


def test_fallback_end_ignores_composition_date():
    source = doc("!!!ODT: 1800\n")
    assert add_signature(source, "xml", "Jan").lines[-2] == "!!!ENC-review: Jan"


@pytest.mark.parametrize("workflow", WORKFLOWS)
@pytest.mark.parametrize("partial", ["author", "date", "complete"])
def test_replace_and_append_preserve_unrelated_metadata(workflow, partial):
    spec = WORKFLOWS[workflow]
    metadata = f"!!!{spec.author}: Old\n" if partial != "date" else ""
    metadata += "!!!OTL: Keep me\n"
    metadata += f"!!!{spec.dated}: 2000-01-01\n" if partial != "author" else ""
    source = doc(metadata)
    (selected,) = existing_signatures(source, workflow)
    replaced = add_signature(source, workflow, "New", selected=selected, action="replace")
    assert "!!!OTL: Keep me" in replaced.lines
    assert f"!!!{spec.author}: New" in replaced.lines
    assert f"!!!{spec.dated}: {date.today().isoformat()}" in replaced.lines  # noqa: DTZ011 — required local computer date
    appended = add_signature(source, workflow, "New", selected=selected)
    index = max(selected.positions) + 1
    assert appended.lines[index] == f"!!!{spec.author}: New"
    assert appended.lines[:index] == source.lines[:index]


def test_duplicate_selection_and_incomplete_pairs():
    source = doc("!!!ENC-review: A\n!!!ENC-review: B\n!!!END-review: b\n!!!END-review: orphan\n")
    signatures = existing_signatures(source, "xml")
    assert len(signatures) == 3
    with pytest.raises(ValueError):
        add_signature(source, "xml", "New")
    updated = add_signature(source, "xml", "New", selected=signatures[1], action="replace")
    assert updated.lines[0] == source.lines[0]
    assert updated.lines[3] == source.lines[3]


def test_date_is_read_at_confirmation(monkeypatch):
    class Today:
        @staticmethod
        def today():
            return date(2040, 1, 2)

    monkeypatch.setattr("spineworks.signatures.date", Today)
    assert add_signature(doc(), "xml", "Jan").lines[-1] == "!!!END-review: 2040-01-02"


@pytest.mark.parametrize("name", ["", "  ", "A\nB", "A\tB"])
def test_invalid_name(name):
    with pytest.raises(ValueError):
        add_signature(doc(), "xml", name)
