from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from linguaspindle import (
    AdapterHealth,
    AdapterManifest,
    ArchiveLimits,
    BatchStatus,
    CancellationToken,
    ErrorCode,
    EventKind,
    LinguaError,
    MangaAdapterResult,
    MockMangaAdapter,
    SourceFormat,
    TranslationEvent,
    TranslationOptions,
    TranslationStatus,
    build_manga_output,
    extract_manga_pages,
    inspect_manga,
    translate_manga,
)

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02"
    "0000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082"
)


def _cbz(entries: list[tuple[str, bytes]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)
    return output.getvalue()


def _manifest(adapter_id: str) -> AdapterManifest:
    return AdapterManifest(
        id=adapter_id,
        display_name=adapter_id,
        adapter_version="1",
        upstream_version="test",
        invocation_type="in_process",
        capabilities=("manga_full_pipeline",),
        input_formats=("png",),
        output_formats=("png",),
        languages=("*",),
        requires_gpu=False,
        supports_cancel=True,
        supports_progress=False,
        health_check="call",
        configuration_help="none",
        upstream_url="",
        upstream_license="Apache-2.0",
        modified=False,
    )


def test_real_png_runs_through_mock_adapter_and_binary_output_stream() -> None:
    manifest = inspect_manga(PNG_1X1, filename="single.png")
    result = translate_manga(
        PNG_1X1,
        MockMangaAdapter(),
        TranslationOptions(target_language="ja", max_retries=0),
        manifest=manifest,
    )
    output = io.BytesIO()
    built = build_manga_output(result, output)

    assert manifest.source_format is SourceFormat.IMAGE
    assert result.status is BatchStatus.SUCCEEDED
    assert result.pages[0].status is TranslationStatus.SUCCEEDED
    assert output.getvalue() == PNG_1X1
    assert built.translated_count == 1
    assert built.preserved_count == 0


def test_cbz_filename_requires_an_actual_zip_archive() -> None:
    with pytest.raises(LinguaError) as raised:
        inspect_manga(PNG_1X1, filename="not-an-archive.cbz")
    assert raised.value.code is ErrorCode.INVALID_FORMAT


@pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_core_limits_are_rejected(non_finite: float) -> None:
    with pytest.raises(ValueError):
        ArchiveLimits(max_compression_ratio=non_finite)
    with pytest.raises(ValueError):
        TranslationOptions(retry_backoff_seconds=non_finite)


def test_pre_cancelled_manga_does_not_probe_or_invoke_adapter() -> None:
    token = CancellationToken()
    token.cancel()

    class NeverCalledAdapter:
        manifest = _manifest("never-called")

        def health(self) -> AdapterHealth:
            raise AssertionError("pre-cancelled work must not probe Adapter health")

        def translate_image(
            self,
            *,
            image: bytes,
            filename: str,
            source_language: str,
            target_language: str,
        ) -> MangaAdapterResult:
            raise AssertionError("pre-cancelled work must not invoke the Adapter")

    result = translate_manga(
        PNG_1X1,
        NeverCalledAdapter(),
        TranslationOptions(max_retries=0),
        filename="cancelled.png",
        cancellation=token,
    )

    assert result.status is BatchStatus.CANCELLED
    assert result.pages[0].status is TranslationStatus.CANCELLED


def test_manga_success_event_callback_failure_is_not_adapter_failure() -> None:
    events: list[EventKind] = []

    def on_event(event: TranslationEvent) -> None:
        kind = event.kind
        events.append(kind)
        if kind is EventKind.SUCCEEDED:
            raise RuntimeError("caller callback failed")

    with pytest.raises(RuntimeError, match="caller callback failed"):
        translate_manga(
            PNG_1X1,
            MockMangaAdapter(),
            TranslationOptions(max_retries=0),
            filename="callback.png",
            on_event=on_event,
        )
    assert EventKind.FAILED not in events


def test_real_cbz_has_natural_stable_order_and_ordered_mock_output(tmp_path: Path) -> None:
    source = _cbz(
        [
            ("pages/10.png", PNG_1X1),
            ("pages/2.png", PNG_1X1),
            ("pages/1.png", PNG_1X1),
        ]
    )
    from_bytes = inspect_manga(source, filename="tiny.cbz")
    from_stream = inspect_manga(io.BytesIO(source), filename="tiny.cbz")

    assert [page.name for page in from_bytes.pages] == ["1.png", "2.png", "10.png"]
    assert [page.page_id for page in from_bytes.pages] == [
        page.page_id for page in from_stream.pages
    ]

    result = translate_manga(
        source,
        MockMangaAdapter(),
        TranslationOptions(target_language="ko", max_retries=0),
        manifest=from_bytes,
    )
    output = tmp_path / "translated.cbz"
    built = build_manga_output(result, output)

    with zipfile.ZipFile(output) as archive:
        assert archive.namelist() == ["0001.png", "0002.png", "0003.png"]
        assert [archive.read(name) for name in archive.namelist()] == [PNG_1X1] * 3
    assert built.translated_count == 3
    assert built.preserved_count == 0


def test_manga_partial_failure_keeps_successful_pages_and_builds_partial_output() -> None:
    class PartialAdapter:
        manifest = _manifest("partial")

        def health(self) -> AdapterHealth:
            return AdapterHealth(True, "ready")

        def translate_image(
            self,
            *,
            image: bytes,
            filename: str,
            source_language: str,
            target_language: str,
        ) -> MangaAdapterResult:
            if filename == "2.png":
                raise LinguaError(ErrorCode.MODEL_API, "expected page failure")
            return MangaAdapterResult(image, "image/png", {"page": filename})

    source = _cbz([("1.png", PNG_1X1), ("2.png", PNG_1X1), ("3.png", PNG_1X1)])
    result = translate_manga(
        source,
        PartialAdapter(),
        TranslationOptions(max_retries=0, retry_backoff_seconds=0),
        filename="partial.cbz",
    )

    assert result.status is BatchStatus.PARTIALLY_SUCCEEDED
    assert [page.status for page in result.pages] == [
        TranslationStatus.SUCCEEDED,
        TranslationStatus.FAILED,
        TranslationStatus.SUCCEEDED,
    ]
    assert result.pages[1].error is not None
    assert result.pages[1].error.code is ErrorCode.MODEL_API

    output = io.BytesIO()
    built = build_manga_output(result, output)
    with zipfile.ZipFile(io.BytesIO(output.getvalue())) as archive:
        assert archive.namelist() == ["0001.png", "0002.png"]
    assert built.translated_count == 2
    assert built.preserved_count == 0
    assert built.details["omitted_count"] == 1


@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        ("fake.png", b"\x89PNG\r\n\x1a\nnot-a-real-png"),
        ("fake.jpg", b"\xff\xd8\xff\xd9"),
        (
            "fake.webp",
            b"RIFF" + (12).to_bytes(4, "little") + b"WEBPVP8 " + (0).to_bytes(4, "little"),
        ),
    ],
)
def test_manga_rejects_magic_only_or_structurally_invalid_images(
    filename: str,
    payload: bytes,
) -> None:
    with pytest.raises(LinguaError) as raised:
        inspect_manga(payload, filename=filename)

    assert raised.value.code is ErrorCode.INVALID_FORMAT


def test_manga_cancellation_is_observed_at_the_next_page_boundary() -> None:
    token = CancellationToken()

    class CancelAfterFirstAdapter:
        manifest = _manifest("cancel-after-first")

        def __init__(self) -> None:
            self.calls: list[str] = []

        def health(self) -> AdapterHealth:
            return AdapterHealth(True, "ready")

        def translate_image(
            self,
            *,
            image: bytes,
            filename: str,
            source_language: str,
            target_language: str,
        ) -> MangaAdapterResult:
            self.calls.append(filename)
            token.cancel()
            return MangaAdapterResult(image, "image/png", {"page": filename})

    source = _cbz([("1.png", PNG_1X1), ("2.png", PNG_1X1), ("3.png", PNG_1X1)])
    adapter = CancelAfterFirstAdapter()
    result = translate_manga(
        source,
        adapter,
        TranslationOptions(max_retries=0),
        filename="cancel.cbz",
        cancellation=token,
    )

    assert adapter.calls == ["1.png"]
    assert result.status is BatchStatus.PARTIALLY_SUCCEEDED
    assert [page.status for page in result.pages] == [
        TranslationStatus.SUCCEEDED,
        TranslationStatus.CANCELLED,
        TranslationStatus.CANCELLED,
    ]


def test_manga_cancellation_from_retry_event_stops_before_another_adapter_call() -> None:
    token = CancellationToken()

    class RetryAdapter:
        manifest = _manifest("retry-cancel")

        def __init__(self) -> None:
            self.calls = 0

        def health(self) -> AdapterHealth:
            return AdapterHealth(True, "ready")

        def translate_image(
            self,
            *,
            image: bytes,
            filename: str,
            source_language: str,
            target_language: str,
        ) -> MangaAdapterResult:
            self.calls += 1
            raise LinguaError(ErrorCode.TIMEOUT, "retry me", retryable=True)

    adapter = RetryAdapter()
    result = translate_manga(
        PNG_1X1,
        adapter,
        TranslationOptions(max_retries=2, retry_backoff_seconds=1),
        filename="retry.png",
        cancellation=token,
        on_event=lambda event: token.cancel() if event.kind is EventKind.RETRY else None,
    )

    assert adapter.calls == 1
    assert result.status is BatchStatus.CANCELLED
    assert result.pages[0].status is TranslationStatus.CANCELLED
    assert result.pages[0].attempts == 1


def test_manga_rejects_unsafe_paths_and_explicit_archive_limits() -> None:
    unsafe = _cbz([("../escape.png", PNG_1X1)])
    with pytest.raises(LinguaError) as unsafe_error:
        inspect_manga(unsafe, filename="unsafe.cbz")
    assert unsafe_error.value.code is ErrorCode.ARCHIVE_UNSAFE

    two_pages = _cbz([("1.png", PNG_1X1), ("2.png", PNG_1X1)])
    limits = ArchiveLimits(max_files=1)
    with pytest.raises(LinguaError) as limit_error:
        inspect_manga(two_pages, filename="limited.cbz", archive_limits=limits)
    assert limit_error.value.code is ErrorCode.ARCHIVE_LIMIT_EXCEEDED


@pytest.mark.parametrize("operation", ["translate", "extract"])
def test_caller_manifest_cannot_bypass_tighter_archive_limits(operation: str) -> None:
    source = _cbz([("1.png", PNG_1X1), ("2.png", PNG_1X1)])
    manifest = inspect_manga(source, filename="caller-manifest.cbz")
    limits = ArchiveLimits(max_files=1)

    with pytest.raises(LinguaError) as raised:
        if operation == "translate":
            translate_manga(
                source,
                MockMangaAdapter(),
                TranslationOptions(max_retries=0),
                manifest=manifest,
                archive_limits=limits,
            )
        else:
            extract_manga_pages(source, manifest, archive_limits=limits)

    assert raised.value.code is ErrorCode.ARCHIVE_LIMIT_EXCEEDED


def test_manga_surfaces_adapter_logs_and_redacts_known_values() -> None:
    sensitive_marker = "adapter-private-value"

    class LoggingAdapter:
        manifest = _manifest("logging")

        def health(self) -> AdapterHealth:
            return AdapterHealth(True, "ready")

        def translate_image(
            self,
            *,
            image: bytes,
            filename: str,
            source_language: str,
            target_language: str,
        ) -> MangaAdapterResult:
            return MangaAdapterResult(
                image,
                "image/png",
                {"page": filename},
                logs=(f"adapter started with {sensitive_marker}", "adapter completed"),
            )

    result = translate_manga(
        PNG_1X1,
        LoggingAdapter(),
        TranslationOptions(max_retries=0),
        filename="logs.png",
        sensitive_values=(sensitive_marker,),
    )

    assert result.pages[0].logs == (
        "adapter started with [REDACTED]",
        "adapter completed",
        "page translated on attempt 1",
    )
    assert sensitive_marker not in str(result.to_dict())


def test_manga_normalizes_health_failures_without_leaking_sensitive_values() -> None:
    redaction_marker = "adapter-" + "private-value"

    class BrokenHealthAdapter:
        manifest = _manifest("broken-health")

        def health(self) -> AdapterHealth:
            raise RuntimeError(f"unreachable with {redaction_marker}")

        def translate_image(
            self,
            *,
            image: bytes,
            filename: str,
            source_language: str,
            target_language: str,
        ) -> MangaAdapterResult:
            raise AssertionError("translation must not start after a failed health check")

    with pytest.raises(LinguaError) as raised:
        translate_manga(
            PNG_1X1,
            BrokenHealthAdapter(),
            TranslationOptions(max_retries=0),
            filename="page.png",
            sensitive_values=(redaction_marker,),
        )

    assert raised.value.code is ErrorCode.ADAPTER_UNAVAILABLE
    assert raised.value.retryable is True
    assert redaction_marker not in str(raised.value.to_dict())


def test_manga_normalizes_corrupt_archive_member() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("page.png", PNG_1X1)
    corrupted = bytearray(output.getvalue())
    payload_offset = corrupted.find(PNG_1X1)
    assert payload_offset >= 0
    corrupted[payload_offset + 32] ^= 1

    with pytest.raises(LinguaError) as raised:
        inspect_manga(bytes(corrupted), filename="corrupt.cbz")

    assert raised.value.code is ErrorCode.INVALID_FORMAT
    assert raised.value.details == {"member": "page.png", "reason": "BadZipFile"}


def test_manga_manifest_rejects_same_size_wrong_source() -> None:
    source = _cbz([("1.png", PNG_1X1), ("2.png", PNG_1X1)])
    manifest = inspect_manga(source, filename="source.cbz")
    wrong_source = bytearray(source)
    wrong_source[-1] ^= 1

    with pytest.raises(LinguaError) as raised:
        translate_manga(
            bytes(wrong_source),
            MockMangaAdapter(),
            TranslationOptions(max_retries=0),
            manifest=manifest,
        )
    assert raised.value.code is ErrorCode.SOURCE_MISMATCH
