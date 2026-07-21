from __future__ import annotations

import os
import time
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from threading import Barrier, Lock

import pytest

from linguaspindle import (
    BatchStatus,
    BuildResult,
    CancellationToken,
    DocumentManifest,
    ErrorCode,
    EventKind,
    LinguaError,
    MockProvider,
    SourceFormat,
    TranslationEvent,
    TranslationOptions,
    TranslationRecord,
    TranslationRequest,
    TranslationResult,
    TranslationStatus,
    build_translated_epub,
    extract_segments,
    inspect_document,
    inspect_epub,
    rebuild_document,
    translate_document,
    translate_segments,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EPUB_SAMPLE = (
    REPOSITORY_ROOT
    / "acceptance"
    / "v0.2.0"
    / "artifacts"
    / "samples"
    / "epub"
    / "source-multichapter.epub"
)
TXT_CRLF = b'Chapter One\r\n\r\n"Hello there."\r\n\r\nLast line.\r\n'


class RecordingProvider:
    id = "recording"

    def __init__(self) -> None:
        self.requests: list[str] = []
        self._lock = Lock()

    def translate(self, request: TranslationRequest) -> TranslationResult:
        with self._lock:
            self.requests.append(request.text)
        return TranslationResult(f"translated:{request.text}", model="recording-v1")


def test_txt_ids_are_stable_for_bytes_and_streams_and_crlf_rebuild_is_structural() -> None:
    from_bytes = inspect_document(TXT_CRLF, filename="novel.txt")
    stream = BytesIO(TXT_CRLF)
    from_stream = inspect_document(stream, filename="novel.txt")

    assert from_bytes.source_format is SourceFormat.TXT
    assert from_bytes.newline == "crlf"
    assert [segment.segment_id for segment in from_bytes.segments] == [
        segment.segment_id for segment in from_stream.segments
    ]
    assert extract_segments(BytesIO(TXT_CRLF), from_bytes, filename="novel.txt") == (
        from_bytes.segments
    )

    translated = {from_bytes.segments[1].segment_id: "\u300c\u4eba\u5de5\u8bd1\u6587\u300d"}
    output = BytesIO(b"stale trailing bytes" * 8)
    output.seek(0)
    built = rebuild_document(TXT_CRLF, from_bytes, translated, output)

    expected = "Chapter One\n\n\u300c\u4eba\u5de5\u8bd1\u6587\u300d\n\nLast line.\n".encode()
    assert output.getvalue() == expected
    assert built.translated_count == 1
    assert built.preserved_count == 2
    assert built.details == {"encoding": "utf-8", "newline": "lf"}

    shared_stream = BytesIO(TXT_CRLF)
    with pytest.raises(LinguaError) as same_stream:
        rebuild_document(shared_stream, from_bytes, {}, shared_stream)
    assert same_stream.value.code is ErrorCode.INVALID_STATE


def test_rebuild_rejects_path_stream_and_hardlink_aliases(tmp_path: Path) -> None:
    source_path = tmp_path / "immutable.txt"
    source_path.write_bytes(TXT_CRLF)
    manifest = inspect_document(source_path)

    with source_path.open("rb") as source_stream:
        with pytest.raises(LinguaError) as same_path:
            rebuild_document(source_stream, manifest, {}, source_path, overwrite=True)
    assert same_path.value.code is ErrorCode.INVALID_STATE
    assert source_path.read_bytes() == TXT_CRLF

    hardlink = tmp_path / "immutable-alias.txt"
    os.link(source_path, hardlink)
    with pytest.raises(LinguaError) as same_inode:
        rebuild_document(source_path, manifest, {}, hardlink, overwrite=True)
    assert same_inode.value.code is ErrorCode.INVALID_STATE
    assert source_path.read_bytes() == TXT_CRLF


def test_translate_document_materializes_a_non_seekable_stream_once() -> None:
    class OneShotStream:
        def __init__(self, payload: bytes):
            self._stream = BytesIO(payload)

        def seekable(self) -> bool:
            return False

        def read(self, size: int = -1) -> bytes:
            return self._stream.read(size)

    output = BytesIO()
    result = translate_document(
        OneShotStream(TXT_CRLF),  # type: ignore[arg-type]
        output,
        MockProvider(),
        TranslationOptions(target_language="fr", max_retries=0),
        filename="one-shot.txt",
    )

    assert result.translations.status is BatchStatus.SUCCEEDED
    assert output.getvalue().count(b"[fr]") == 3


def test_explicit_txt_rejects_known_binary_signatures() -> None:
    disguised_jpeg = b"\xff\xd8\xff\xe0JFIF\x00 printable words that are not a text document"

    with pytest.raises(LinguaError) as raised:
        inspect_document(disguised_jpeg, filename="disguised.txt", format_hint=SourceFormat.TXT)
    assert raised.value.code is ErrorCode.INVALID_FORMAT


def test_rebuild_rejects_truncated_or_swapped_segment_manifests() -> None:
    payload = EPUB_SAMPLE.read_bytes()
    manifest = inspect_document(payload, filename=EPUB_SAMPLE.name)
    first, second, *remaining = manifest.segments
    forged_manifests = (
        replace(manifest, segments=(first, second)),
        replace(
            manifest,
            segments=(replace(first, locator=second.locator), second, *remaining),
        ),
    )

    for forged in forged_manifests:
        with pytest.raises(LinguaError) as raised:
            rebuild_document(
                payload,
                forged,
                {first.segment_id: "must not move"},
                BytesIO(),
                target_language="en",
            )
        assert raised.value.code is ErrorCode.SOURCE_MISMATCH


def test_rebuild_reports_source_mismatch_when_inspected_source_grows(tmp_path: Path) -> None:
    source = tmp_path / "growing.txt"
    source.write_bytes(b"original")
    manifest = inspect_document(source)
    source.write_bytes(b"original plus appended content")

    with pytest.raises(LinguaError) as raised:
        rebuild_document(source, manifest, {}, BytesIO())
    assert raised.value.code is ErrorCode.SOURCE_MISMATCH


def test_txt_selection_empty_selection_unknown_id_and_manual_text() -> None:
    manifest = inspect_document(TXT_CRLF, filename="selection.txt")
    selected = manifest.segments[1]
    provider = RecordingProvider()
    options = TranslationOptions(max_retries=0, retry_backoff_seconds=0)

    one = translate_segments(
        manifest,
        provider,
        options,
        selected_segment_ids=[selected.segment_id],
    )

    assert provider.requests == [selected.source_text]
    assert [record.status for record in one.records] == [
        TranslationStatus.SOURCE,
        TranslationStatus.SUCCEEDED,
        TranslationStatus.SOURCE,
    ]

    empty_provider = RecordingProvider()
    empty = translate_segments(
        manifest,
        empty_provider,
        options,
        selected_segment_ids=[],
    )
    assert empty.status is BatchStatus.NOOP
    assert empty_provider.requests == []
    assert all(record.status is TranslationStatus.SOURCE for record in empty.records)

    with pytest.raises(LinguaError) as raised:
        translate_segments(
            manifest,
            provider,
            options,
            selected_segment_ids=["unknown-segment"],
        )
    assert raised.value.code is ErrorCode.SEGMENT_NOT_FOUND

    manual_provider = RecordingProvider()
    manual = translate_segments(
        manifest,
        manual_provider,
        options,
        existing_translations={selected.segment_id: "caller-authored text"},
    )
    selected_record = next(
        record for record in manual.records if record.segment_id == selected.segment_id
    )
    assert selected_record.status is TranslationStatus.MANUAL
    assert selected_record.translated_text == "caller-authored text"
    assert selected.source_text not in manual_provider.requests


def test_txt_partial_failure_keeps_successes() -> None:
    manifest = inspect_document(
        b"first\n\n[[MOCK_FAIL]]\n\nlast\n",
        filename="partial.txt",
    )

    result = translate_segments(
        manifest,
        MockProvider(),
        TranslationOptions(max_retries=0, retry_backoff_seconds=0),
    )

    assert result.status is BatchStatus.PARTIALLY_SUCCEEDED
    assert [record.status for record in result.records] == [
        TranslationStatus.SUCCEEDED,
        TranslationStatus.FAILED,
        TranslationStatus.SUCCEEDED,
    ]
    assert result.records[0].translated_text == "[en] first"
    assert result.records[2].translated_text == "[en] last"
    assert result.records[1].error is not None
    assert result.records[1].error.code is ErrorCode.MODEL_API


def test_existing_success_contributes_to_partial_status_and_requires_text() -> None:
    manifest = inspect_document(b"kept\n\n[[MOCK_FAIL]]", filename="existing-partial.txt")
    first = manifest.segments[0]
    existing = TranslationRecord(
        segment_id=first.segment_id,
        order=first.order,
        source_hash=first.source_hash,
        translation_input_hash=first.translation_input_hash,
        status=TranslationStatus.SUCCEEDED,
        translated_text="already translated",
    )

    result = translate_segments(
        manifest,
        MockProvider(),
        TranslationOptions(max_retries=0, retry_backoff_seconds=0),
        existing_translations=(existing,),
    )

    assert result.status is BatchStatus.PARTIALLY_SUCCEEDED
    assert [record.status for record in result.records] == [
        TranslationStatus.SUCCEEDED,
        TranslationStatus.FAILED,
    ]

    invalid = replace(existing, translated_text=None)
    with pytest.raises(LinguaError) as raised:
        translate_segments(
            manifest,
            MockProvider(),
            TranslationOptions(max_retries=0),
            existing_translations=(invalid,),
        )
    assert raised.value.code is ErrorCode.INVALID_FORMAT

    wrong_policy = replace(existing, translation_input_hash="")
    with pytest.raises(LinguaError) as policy_error:
        translate_segments(
            manifest,
            MockProvider(),
            TranslationOptions(max_retries=0),
            existing_translations=(wrong_policy,),
        )
    assert policy_error.value.code is ErrorCode.SOURCE_MISMATCH


def test_rebuild_rejects_succeeded_records_from_a_different_translation_policy() -> None:
    source = b"policy-bound text"
    english = inspect_document(
        source,
        filename="policy.txt",
        options=TranslationOptions(target_language="en"),
    )
    french = inspect_document(
        source,
        filename="policy.txt",
        options=TranslationOptions(target_language="fr"),
    )
    translated = translate_segments(
        english,
        MockProvider(),
        TranslationOptions(target_language="en", max_retries=0),
    )

    with pytest.raises(LinguaError) as raised:
        rebuild_document(source, french, translated, BytesIO())
    assert raised.value.code is ErrorCode.SOURCE_MISMATCH

    wrong_source_batch = replace(translated, source_sha256="0" * 64)
    with pytest.raises(LinguaError) as wrong_batch:
        rebuild_document(source, english, wrong_source_batch, BytesIO())
    assert wrong_batch.value.code is ErrorCode.SOURCE_MISMATCH

    missing_text = replace(translated.records[0], translated_text=None)
    with pytest.raises(LinguaError) as missing:
        rebuild_document(source, english, (missing_text,), BytesIO())
    assert missing.value.code is ErrorCode.INVALID_FORMAT


@pytest.mark.parametrize("leak_field", ["text", "model", "usage"])
def test_provider_success_cannot_echo_a_protected_runtime_value(leak_field: str) -> None:
    marker = "runtime-secret-784bac"
    manifest = inspect_document(b"safe source", filename="provider-secret.txt")

    class SecretEchoProvider:
        id = f"provider-{marker}"

        def translate(self, request: TranslationRequest) -> TranslationResult:
            return TranslationResult(
                marker if leak_field == "text" else f"translated:{request.text}",
                marker if leak_field == "model" else "safe-model",
                {marker if leak_field == "usage" else "input_tokens": 1},
            )

    result = translate_segments(
        manifest,
        SecretEchoProvider(),
        TranslationOptions(max_retries=0),
        sensitive_values=(marker,),
    )

    assert result.status is BatchStatus.FAILED
    assert result.records[0].error is not None
    assert result.records[0].error.code is ErrorCode.MODEL_API
    assert marker not in str(result.to_dict())


def test_success_event_callback_failure_is_not_misattributed_to_provider() -> None:
    manifest = inspect_document(b"callback source", filename="callback.txt")
    provider = RecordingProvider()

    def on_event(event: TranslationEvent) -> None:
        if event.kind is EventKind.SUCCEEDED:
            raise RuntimeError("caller callback failed")

    with pytest.raises(RuntimeError, match="caller callback failed"):
        translate_segments(
            manifest,
            provider,
            TranslationOptions(max_retries=0),
            on_event=on_event,
        )
    assert provider.requests == ["callback source"]


def test_core_owns_bounded_retry_and_attempt_count() -> None:
    manifest = inspect_document(b"retry me", filename="retry.txt")

    class RetryOnceProvider:
        id = "retry-once"

        def __init__(self) -> None:
            self.calls = 0

        def translate(self, request: TranslationRequest) -> TranslationResult:
            self.calls += 1
            if self.calls == 1:
                raise LinguaError(ErrorCode.RATE_LIMIT, "try later", retryable=True)
            return TranslationResult(f"done:{request.text}", model="retry-v1")

    provider = RetryOnceProvider()
    result = translate_segments(
        manifest,
        provider,
        TranslationOptions(max_retries=1, retry_backoff_seconds=0),
    )

    assert provider.calls == 2
    assert result.status is BatchStatus.SUCCEEDED
    assert result.records[0].attempts == 2
    assert result.records[0].translated_text == "done:retry me"


def test_retry_event_is_live_has_batch_total_and_can_cancel_before_next_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = inspect_document(b"retry me", filename="retry-event.txt")
    token = CancellationToken()
    events: list[TranslationEvent] = []

    class AlwaysRetryProvider:
        id = "always-retry"

        def __init__(self) -> None:
            self.calls = 0

        def translate(self, request: TranslationRequest) -> TranslationResult:
            self.calls += 1
            raise LinguaError(ErrorCode.RATE_LIMIT, "try later", retryable=True)

    provider = AlwaysRetryProvider()

    def on_event(event: TranslationEvent) -> None:
        events.append(event)
        if event.kind is EventKind.RETRY:
            assert provider.calls == 1
            assert event.total == 1
            assert event.attempt == 1
            token.cancel()

    def unexpected_sleep(_seconds: float) -> None:
        raise AssertionError("cancellation from RETRY must skip retry backoff")

    monkeypatch.setattr("linguaspindle.core.orchestration.time.sleep", unexpected_sleep)
    result = translate_segments(
        manifest,
        provider,
        TranslationOptions(max_retries=3, retry_backoff_seconds=10),
        cancellation=token,
        on_event=on_event,
    )

    assert provider.calls == 1
    assert result.status is BatchStatus.CANCELLED
    assert result.records[0].status is TranslationStatus.CANCELLED
    assert result.records[0].attempts == 1
    assert [event.kind for event in events] == [
        EventKind.STARTED,
        EventKind.RETRY,
        EventKind.CANCELLED,
        EventKind.PROGRESS,
        EventKind.COMPLETED,
    ]
    assert all(event.total == 1 for event in events)


def test_text_cancellation_is_observed_at_segment_boundaries() -> None:
    manifest = inspect_document(b"one\n\ntwo\n\nthree", filename="cancel.txt")
    token = CancellationToken()

    class CancelAfterFirstProvider:
        id = "cancel-after-first"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def translate(self, request: TranslationRequest) -> TranslationResult:
            self.calls.append(request.text)
            token.cancel()
            return TranslationResult(f"done:{request.text}", model="cancel-v1")

    provider = CancelAfterFirstProvider()
    result = translate_segments(
        manifest,
        provider,
        TranslationOptions(max_retries=0),
        cancellation=token,
    )

    assert provider.calls == ["one"]
    assert result.status is BatchStatus.PARTIALLY_SUCCEEDED
    assert [record.status for record in result.records] == [
        TranslationStatus.SUCCEEDED,
        TranslationStatus.CANCELLED,
        TranslationStatus.CANCELLED,
    ]


def test_rebuild_retries_short_stream_writes_until_payload_is_complete() -> None:
    manifest = inspect_document(TXT_CRLF, filename="short-write.txt")

    class ShortWriter(BytesIO):
        def write(self, payload: bytes) -> int:
            return super().write(payload[:3])

    output = ShortWriter()
    rebuilt = rebuild_document(TXT_CRLF, manifest, {}, output)

    assert output.getvalue() == TXT_CRLF.replace(b"\r\n", b"\n")
    assert rebuilt.output_size == len(output.getvalue())


@pytest.mark.parametrize("reported_count", [0, -1, True, "all", 10_000])
def test_rebuild_rejects_invalid_stream_write_counts(reported_count: object) -> None:
    manifest = inspect_document(b"one", filename="bad-writer.txt")

    class InvalidWriter(BytesIO):
        def write(self, payload: bytes) -> object:
            return reported_count

    with pytest.raises(LinguaError) as raised:
        rebuild_document(b"one", manifest, {}, InvalidWriter())

    assert raised.value.code is ErrorCode.STORAGE


def test_txt_concurrent_completion_does_not_change_result_order() -> None:
    manifest = inspect_document(b"slow\n\nmedium\n\nfast\n", filename="ordered.txt")

    class DelayedProvider:
        id = "delayed"

        def __init__(self) -> None:
            self.barrier = Barrier(3)
            self.completed: list[str] = []
            self.lock = Lock()

        def translate(self, request: TranslationRequest) -> TranslationResult:
            self.barrier.wait(timeout=2)
            time.sleep({"slow": 0.06, "medium": 0.03, "fast": 0.0}[request.text])
            with self.lock:
                self.completed.append(request.text)
            return TranslationResult(f"done:{request.text}", model="delayed-v1")

    provider = DelayedProvider()
    result = translate_segments(
        manifest,
        provider,
        TranslationOptions(concurrency=3, max_retries=0, retry_backoff_seconds=0),
    )

    assert provider.completed == ["fast", "medium", "slow"]
    assert [record.segment_id for record in result.records] == [
        segment.segment_id for segment in manifest.segments
    ]
    assert [record.translated_text for record in result.records] == [
        "done:slow",
        "done:medium",
        "done:fast",
    ]


def test_epub_acceptance_sample_has_stable_ids_for_path_and_stream() -> None:
    payload = EPUB_SAMPLE.read_bytes()
    from_path = inspect_document(EPUB_SAMPLE)
    from_stream = inspect_document(BytesIO(payload), filename=EPUB_SAMPLE.name)

    assert from_path.source_format is SourceFormat.EPUB3
    assert len(from_path.segments) > 1
    assert [segment.segment_id for segment in from_path.segments] == [
        segment.segment_id for segment in from_stream.segments
    ]
    assert extract_segments(BytesIO(payload), from_path, filename=EPUB_SAMPLE.name) == (
        from_path.segments
    )


def test_typed_epub_wrappers_are_exported_and_rebuild_from_segment_ids() -> None:
    from linguaspindle.core import build_translated_epub as core_build_translated_epub
    from linguaspindle.core import inspect_epub as core_inspect_epub

    payload = EPUB_SAMPLE.read_bytes()
    manifest = inspect_epub(BytesIO(payload), filename=EPUB_SAMPLE.name)
    core_manifest = core_inspect_epub(EPUB_SAMPLE)
    selected = manifest.segments[0]
    output = BytesIO()

    built = build_translated_epub(
        payload,
        output,
        manifest,
        {selected.segment_id: "Typed EPUB wrapper translation"},
        "en",
    )

    assert isinstance(manifest, DocumentManifest)
    assert manifest == core_manifest
    assert manifest.source_format in {SourceFormat.EPUB2, SourceFormat.EPUB3}
    assert isinstance(built, BuildResult)
    assert built.translated_count == 1
    assert built.preserved_count == len(manifest.segments) - 1
    assert any(
        segment.source_text == "Typed EPUB wrapper translation"
        for segment in inspect_epub(BytesIO(output.getvalue()), filename="rebuilt.epub").segments
    )
    assert core_build_translated_epub is build_translated_epub


def test_typed_epub_builder_rejects_a_txt_manifest() -> None:
    manifest = inspect_document(b"not an epub", filename="novel.txt")

    with pytest.raises(LinguaError) as raised:
        build_translated_epub(
            b"not an epub",
            BytesIO(),
            manifest,
            {},
            "en",
        )

    assert raised.value.code is ErrorCode.INVALID_FORMAT


def test_epub_acceptance_sample_rebuilds_with_mock_provider_to_stream() -> None:
    output = BytesIO()
    translated = translate_document(
        EPUB_SAMPLE,
        output,
        MockProvider(),
        TranslationOptions(target_language="fr", max_retries=0, retry_backoff_seconds=0),
    )

    rebuilt = inspect_document(BytesIO(output.getvalue()), filename="translated.epub")
    assert translated.build.translated_count == len(translated.manifest.segments)
    assert translated.build.preserved_count == 0
    assert translated.translations.status is BatchStatus.SUCCEEDED
    assert any(segment.source_text.startswith("[fr] ") for segment in rebuilt.segments)


def test_epub_acceptance_sample_supports_manual_rebuild_and_rejects_wrong_source(
    tmp_path: Path,
) -> None:
    manifest = inspect_document(EPUB_SAMPLE)
    selected = next(segment for segment in manifest.segments if segment.content_role == "xhtml")
    manual_text = "Manual core reconstruction"
    output = tmp_path / "manual.epub"

    built = rebuild_document(
        EPUB_SAMPLE,
        manifest,
        {selected.segment_id: manual_text},
        output,
        target_language="en",
    )

    inspected_output = inspect_document(output)
    assert built.translated_count == 1
    assert built.preserved_count == len(manifest.segments) - 1
    assert any(segment.source_text == manual_text for segment in inspected_output.segments)

    wrong_source = bytearray(EPUB_SAMPLE.read_bytes())
    wrong_source[-1] ^= 1
    with pytest.raises(LinguaError) as raised:
        rebuild_document(
            bytes(wrong_source),
            manifest,
            {},
            BytesIO(),
            target_language="en",
        )
    assert raised.value.code is ErrorCode.SOURCE_MISMATCH
