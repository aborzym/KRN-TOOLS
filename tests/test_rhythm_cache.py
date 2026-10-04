from spineworks import spine_rhythm
from spineworks.humdrum import HumdrumDocument
from spineworks.spine_rhythm import RhythmCache, trace_rhythm

SOURCE = (
    "**kern\t**kern\n"
    "=1\t=1\n"
    "00r\t1c\n"
    "=2\t=2\n"
    ".\t1d\n"
    "=3\t=3\n"
    ".\t1e\n"
    "=4\t=4\n"
    ".\t1f\n"
    "=5\t=5\n"
    "1r\t1g\n"
    "*-\t*-\n"
)


def test_cached_rhythm_matches_fresh_analysis_after_changes() -> None:
    cache = RhythmCache()
    split = SOURCE.replace(
        ".\t1d\n",
        "*^\t*\n.\t.\t1d\n*v\t*v\t*\n",
    )
    invalid = SOURCE.replace(".\t1e\n", "1r\t1e\n")

    for text in (
        SOURCE,
        SOURCE.replace("1g", "1a"),
        split,
        invalid,
        SOURCE,
        SOURCE.replace(".\t1f\n", "!!Komentarz\n.\t1f\n"),
        SOURCE,
    ):
        document = HumdrumDocument.from_text(text)
        expected = trace_rhythm(document)
        actual = trace_rhythm(document, cache=cache)

        assert actual == expected
        assert len(cache.checkpoints) == len(actual.records)


def test_cache_reuses_unchanged_rhythm_prefix(monkeypatch) -> None:
    calls = 0
    original = spine_rhythm.advance_kern_row

    def counted(tokens, remaining):
        nonlocal calls
        calls += 1
        return original(tokens, remaining)

    monkeypatch.setattr(spine_rhythm, "advance_kern_row", counted)
    cache = RhythmCache()
    document = HumdrumDocument.from_text(SOURCE)

    first = trace_rhythm(document, cache=cache)
    assert first.issue is None
    assert calls == 5

    calls = 0
    assert trace_rhythm(document, cache=cache) == first
    assert calls == 0

    changed = HumdrumDocument.from_text(SOURCE.replace("1g", "1a"))
    calls = 0
    result = trace_rhythm(changed, cache=cache)

    assert result.issue is None
    assert calls == 1
    assert result == trace_rhythm(changed)
