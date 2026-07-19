from __future__ import annotations

from linguaspindle.orchestration.engine import JobRunner


def test_segmentation_preserves_paragraph_and_dialogue_blocks() -> None:
    source = "Chapter 1\n\n“Hello,” she said.\n“Welcome.”\n\nLast paragraph."
    assert JobRunner.segment_text(source) == [
        "Chapter 1",
        "“Hello,” she said.\n“Welcome.”",
        "Last paragraph.",
    ]


def test_long_paragraph_splits_without_losing_text() -> None:
    source = "First sentence. Second sentence. Third sentence."
    segments = JobRunner.segment_text(source, maximum_chars=22)
    assert "".join(segments).replace(" ", "") == source.replace(" ", "")
    assert all(len(segment) <= 22 for segment in segments)
