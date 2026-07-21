"""Synchronous, persistence-free orchestration for novel translation units."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeAlias, cast

from ..errors import ErrorCode, LinguaError
from ..json_types import normalize_json_object
from ..providers.base import TranslationProvider, TranslationRequest, TranslationResult
from ..security import redact, redact_text
from .models import (
    BatchStatus,
    CancellationToken,
    DocumentManifest,
    ErrorRecord,
    EventKind,
    Segment,
    TranslationBatchResult,
    TranslationEvent,
    TranslationOptions,
    TranslationRecord,
    TranslationStatus,
)

EventHandler: TypeAlias = Callable[[TranslationEvent], None]
ExistingTranslation: TypeAlias = str | TranslationRecord


def translate_segments(
    source: DocumentManifest | Sequence[Segment],
    provider: TranslationProvider,
    options: TranslationOptions,
    *,
    selected_segment_ids: Iterable[str] | None = None,
    existing_translations: Mapping[str, ExistingTranslation] | Iterable[TranslationRecord] = (),
    cancellation: CancellationToken | None = None,
    on_event: EventHandler | None = None,
    sensitive_values: Sequence[str] = (),
) -> TranslationBatchResult:
    """Translate selected Segments while retaining deterministic final ordering.

    ``None`` selects every Segment. An explicitly empty iterable selects none.
    Existing successful or caller-authored text always wins and is never sent to
    the Provider again.
    """

    if isinstance(source, DocumentManifest):
        manifest: DocumentManifest | None = source
        segments = tuple(source.segments)
    else:
        manifest = None
        segments = tuple(source)
    ordered = tuple(sorted(segments, key=lambda item: item.order))
    ids = {segment.segment_id for segment in ordered}
    if len(ids) != len(ordered):
        raise LinguaError(ErrorCode.INVALID_FORMAT, "Segment IDs must be unique")

    selected = ids if selected_segment_ids is None else set(selected_segment_ids)
    unknown = sorted(selected - ids)
    if unknown:
        raise LinguaError(
            ErrorCode.SEGMENT_NOT_FOUND,
            "Selected Segment ID is not present in the manifest",
            {"unknown_segment_ids": unknown},
        )

    existing = _existing_map(existing_translations)
    unknown_existing = sorted(set(existing) - ids)
    if unknown_existing:
        raise LinguaError(
            ErrorCode.SEGMENT_NOT_FOUND,
            "Existing translation references an unknown Segment ID",
            {"unknown_segment_ids": unknown_existing},
        )

    token = cancellation or CancellationToken()
    records: dict[str, TranslationRecord] = {}
    work: list[Segment] = []
    for segment in ordered:
        supplied = existing.get(segment.segment_id)
        if supplied is not None:
            normalized = _existing_record(segment, supplied)
            if normalized.status in {TranslationStatus.SUCCEEDED, TranslationStatus.MANUAL}:
                records[segment.segment_id] = normalized
                continue
            if segment.segment_id not in selected:
                records[segment.segment_id] = normalized
                continue
        if segment.segment_id in selected:
            work.append(segment)
        else:
            records[segment.segment_id] = _source_record(segment)

    total = len(work)
    _emit(on_event, TranslationEvent(EventKind.STARTED, 0, total, message="translation"))
    if not work:
        result = TranslationBatchResult(
            records=tuple(records[segment.segment_id] for segment in ordered),
            status=BatchStatus.NOOP,
            selected_segment_ids=tuple(
                segment.segment_id for segment in ordered if segment.segment_id in selected
            ),
            source_sha256=manifest.source_sha256 if manifest else None,
        )
        _emit(on_event, TranslationEvent(EventKind.COMPLETED, 0, 0, message=result.status.value))
        return result

    completed = 0
    if options.concurrency == 1:
        for segment in work:
            record = _translate_one(
                segment,
                provider,
                options,
                token,
                sensitive_values,
                on_event,
                total,
            )
            records[segment.segment_id] = record
            completed += 1
            _emit(
                on_event,
                TranslationEvent(
                    EventKind.PROGRESS,
                    completed,
                    total,
                    segment_id=segment.segment_id,
                ),
            )
    else:
        with ThreadPoolExecutor(
            max_workers=options.concurrency,
            thread_name_prefix="linguaspindle-core",
        ) as executor:
            futures = {
                executor.submit(
                    _translate_one,
                    segment,
                    provider,
                    options,
                    token,
                    sensitive_values,
                    on_event,
                    total,
                ): segment
                for segment in work
            }
            for future in as_completed(futures):
                segment = futures[future]
                try:
                    record = future.result()
                except Exception as exc:  # defensive Provider boundary
                    error = _normalize_error(exc, sensitive_values)
                    record = _failed_record(segment, error, 1)
                    _emit(
                        on_event,
                        TranslationEvent(
                            EventKind.FAILED,
                            completed,
                            total,
                            segment_id=segment.segment_id,
                            error=error,
                        ),
                    )
                records[segment.segment_id] = record
                completed += 1
                _emit(
                    on_event,
                    TranslationEvent(
                        EventKind.PROGRESS,
                        completed,
                        total,
                        segment_id=segment.segment_id,
                    ),
                )

    final_records = tuple(records[segment.segment_id] for segment in ordered)
    targeted = [
        records[segment.segment_id] for segment in ordered if segment.segment_id in selected
    ]
    status = _batch_status(targeted)
    result = TranslationBatchResult(
        records=final_records,
        status=status,
        selected_segment_ids=tuple(
            segment.segment_id for segment in ordered if segment.segment_id in selected
        ),
        source_sha256=manifest.source_sha256 if manifest else None,
    )
    _emit(on_event, TranslationEvent(EventKind.COMPLETED, total, total, message=status.value))
    return result


def _existing_map(
    values: Mapping[str, ExistingTranslation] | Iterable[TranslationRecord],
) -> dict[str, ExistingTranslation]:
    if isinstance(values, Mapping):
        return {str(key): value for key, value in values.items()}
    return {record.segment_id: record for record in values}


def _existing_record(segment: Segment, value: ExistingTranslation) -> TranslationRecord:
    if isinstance(value, str):
        return TranslationRecord(
            segment_id=segment.segment_id,
            order=segment.order,
            source_hash=segment.source_hash,
            translation_input_hash=segment.translation_input_hash,
            status=TranslationStatus.MANUAL,
            translated_text=value,
            provider_id="caller",
        )
    if value.source_hash and value.source_hash != segment.source_hash:
        raise LinguaError(
            ErrorCode.SOURCE_MISMATCH,
            "Existing translation does not match the current Segment source",
            {"segment_id": segment.segment_id},
        )
    if (
        value.status is TranslationStatus.SUCCEEDED
        and value.translation_input_hash != segment.translation_input_hash
    ):
        raise LinguaError(
            ErrorCode.SOURCE_MISMATCH,
            "Existing translation does not match the current translation policy",
            {"segment_id": segment.segment_id},
        )
    if (
        value.status in {TranslationStatus.SUCCEEDED, TranslationStatus.MANUAL}
        and value.translated_text is None
    ):
        raise LinguaError(
            ErrorCode.INVALID_FORMAT,
            "Successful existing translation has no translated text",
            {"segment_id": segment.segment_id},
        )
    return TranslationRecord(
        segment_id=segment.segment_id,
        order=segment.order,
        source_hash=segment.source_hash,
        translation_input_hash=segment.translation_input_hash,
        status=value.status,
        translated_text=value.translated_text,
        provider_id=value.provider_id,
        model=value.model,
        attempts=value.attempts,
        usage=value.usage,
        error=value.error,
    )


def _source_record(segment: Segment) -> TranslationRecord:
    return TranslationRecord(
        segment_id=segment.segment_id,
        order=segment.order,
        source_hash=segment.source_hash,
        translation_input_hash=segment.translation_input_hash,
        status=TranslationStatus.SOURCE,
    )


def _translate_one(
    segment: Segment,
    provider: TranslationProvider,
    options: TranslationOptions,
    token: CancellationToken,
    sensitive_values: Sequence[str],
    on_event: EventHandler | None,
    total: int,
) -> TranslationRecord:
    provider_id = redact_text(
        str(getattr(provider, "id", type(provider).__name__)), sensitive_values
    )
    for attempt in range(1, options.max_retries + 2):
        if token.cancelled:
            record = TranslationRecord(
                segment_id=segment.segment_id,
                order=segment.order,
                source_hash=segment.source_hash,
                translation_input_hash=segment.translation_input_hash,
                status=TranslationStatus.CANCELLED,
                provider_id=provider_id,
                attempts=attempt - 1,
                error=ErrorRecord(ErrorCode.CANCELLED, "Translation was cancelled"),
            )
            _emit(
                on_event,
                TranslationEvent(
                    EventKind.CANCELLED,
                    0,
                    total,
                    segment_id=segment.segment_id,
                    attempt=attempt - 1,
                    error=record.error,
                ),
            )
            return record
        request = TranslationRequest(
            text=segment.source_text,
            source_language=options.source_language,
            target_language=options.target_language,
            style=options.style,
            prompt_template=options.prompt_template,
            prompt_version=options.prompt_version,
            model_parameters=dict(options.model_parameters),
        )
        try:
            response = provider.translate(request)
            if not isinstance(response, TranslationResult):
                text = getattr(response, "text", None)
                model = getattr(response, "model", provider_id)
                usage = getattr(response, "usage", None)
            else:
                text, model, usage = response.text, response.model, response.usage
            if not isinstance(text, str) or not text.strip():
                raise LinguaError(
                    ErrorCode.OUTPUT_MISSING,
                    "Translation Provider returned no translation",
                    retryable=True,
                )
            model_text = str(model)
            response_values = [text, model_text]
            if isinstance(usage, Mapping):
                response_values.extend(str(key) for key in usage)
            if any(
                secret and any(secret in value for value in response_values)
                for secret in sensitive_values
            ):
                raise LinguaError(
                    ErrorCode.MODEL_API,
                    "Translation Provider response contained a protected runtime value",
                    retryable=False,
                )
            normalized_usage = (
                {
                    str(key): int(value)
                    for key, value in cast(Mapping[str, object], usage).items()
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0
                }
                if isinstance(usage, Mapping)
                else None
            )
            record = TranslationRecord(
                segment_id=segment.segment_id,
                order=segment.order,
                source_hash=segment.source_hash,
                translation_input_hash=segment.translation_input_hash,
                status=TranslationStatus.SUCCEEDED,
                translated_text=text,
                provider_id=provider_id,
                model=model_text,
                attempts=attempt,
                usage=normalized_usage or None,
            )
        except Exception as exc:  # Provider implementations are untrusted extension code
            error = _normalize_error(exc, sensitive_values)
            if not error.retryable or attempt > options.max_retries:
                record = _failed_record(segment, error, attempt, provider_id)
                _emit(
                    on_event,
                    TranslationEvent(
                        EventKind.FAILED,
                        0,
                        total,
                        segment_id=segment.segment_id,
                        attempt=attempt,
                        error=error,
                    ),
                )
                return record
            _emit(
                on_event,
                TranslationEvent(
                    EventKind.RETRY,
                    0,
                    total,
                    segment_id=segment.segment_id,
                    attempt=attempt,
                    error=error,
                ),
            )
            if token.cancelled:
                continue
            if options.retry_backoff_seconds:
                time.sleep(min(options.retry_backoff_seconds * (2 ** (attempt - 1)), 10.0))
            continue
        _emit(
            on_event,
            TranslationEvent(
                EventKind.SUCCEEDED,
                0,
                total,
                segment_id=segment.segment_id,
                attempt=attempt,
            ),
        )
        return record
    raise AssertionError("unreachable")


def _normalize_error(exc: Exception, sensitive_values: Sequence[str]) -> ErrorRecord:
    if isinstance(exc, LinguaError):
        details = normalize_json_object(redact(exc.details or {}, sensitive_values))
        return ErrorRecord(
            code=exc.code,
            message=redact_text(exc.message, sensitive_values),
            details=details,
            retryable=exc.retryable,
        )
    return ErrorRecord(
        ErrorCode.UNKNOWN,
        "Translation Provider failed unexpectedly",
        {"exception_type": type(exc).__name__},
        retryable=False,
    )


def _failed_record(
    segment: Segment,
    error: ErrorRecord,
    attempts: int,
    provider_id: str | None = None,
) -> TranslationRecord:
    return TranslationRecord(
        segment_id=segment.segment_id,
        order=segment.order,
        source_hash=segment.source_hash,
        translation_input_hash=segment.translation_input_hash,
        status=TranslationStatus.FAILED,
        provider_id=provider_id,
        attempts=attempts,
        error=error,
    )


def _batch_status(records: Sequence[TranslationRecord]) -> BatchStatus:
    if any(record.status is TranslationStatus.CANCELLED for record in records):
        successful = any(
            record.status in {TranslationStatus.SUCCEEDED, TranslationStatus.MANUAL}
            for record in records
        )
        return BatchStatus.PARTIALLY_SUCCEEDED if successful else BatchStatus.CANCELLED
    failures = sum(record.status is TranslationStatus.FAILED for record in records)
    if not failures:
        return BatchStatus.SUCCEEDED
    if failures == len(records):
        return BatchStatus.FAILED
    return BatchStatus.PARTIALLY_SUCCEEDED


def _emit(handler: EventHandler | None, event: TranslationEvent) -> None:
    if handler is not None:
        handler(event)


__all__ = ["EventHandler", "translate_segments"]
