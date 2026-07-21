"""Typed, JSON-versioned contracts for the embeddable translation core."""

from __future__ import annotations

import base64
import math
import threading
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from ..errors import ErrorCode, LinguaError
from ..json_types import JsonValue, normalize_json_object


def _mapping(value: object) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        return {}
    return normalize_json_object(value)


def _require_schema(value: dict[str, object], expected: str) -> None:
    actual = value.get("schema_version")
    if actual != expected:
        raise ValueError(f"Unsupported schema_version: expected {expected}, got {actual!r}")


class SourceFormat(StrEnum):
    TXT = "txt"
    EPUB2 = "epub2"
    EPUB3 = "epub3"
    IMAGE = "image"
    CBZ = "cbz"


class TranslationStatus(StrEnum):
    SOURCE = "source"
    SUCCEEDED = "succeeded"
    MANUAL = "manual"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BatchStatus(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NOOP = "noop"


class EventKind(StrEnum):
    STARTED = "started"
    PROGRESS = "progress"
    RETRY = "retry"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class SegmentLocator:
    """Stable location of a translatable source span or EPUB XML slot."""

    kind: str
    document_path: str
    start: int | None = None
    end: int | None = None
    unit_sequence: int | None = None
    element_index: int | None = None
    slot: str | None = None
    attribute: str | None = None
    part_index: int | None = None
    part_count: int | None = None
    document_order: int | None = None
    document_type: str | None = None

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "kind": self.kind,
            "document_path": self.document_path,
            "start": self.start,
            "end": self.end,
            "unit_sequence": self.unit_sequence,
            "element_index": self.element_index,
            "slot": self.slot,
            "attribute": self.attribute,
            "part_index": self.part_index,
            "part_count": self.part_count,
            "document_order": self.document_order,
            "document_type": self.document_type,
        }

    def to_epub_dict(self) -> dict[str, JsonValue]:
        if self.kind != "epub-xml-slot":
            raise ValueError("Only EPUB locators have an XML-slot representation")
        return {
            "document_path": self.document_path,
            "element_index": self.element_index,
            "slot": self.slot,
            "attribute": self.attribute,
            "part_index": self.part_index,
            "part_count": self.part_count,
            "document_order": self.document_order,
            "document_type": self.document_type,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> SegmentLocator:
        start = value.get("start")
        end = value.get("end")
        unit_sequence = value.get("unit_sequence")
        element_index = value.get("element_index")
        part_index = value.get("part_index")
        part_count = value.get("part_count")
        document_order = value.get("document_order")
        return cls(
            kind=str(value.get("kind", "unknown")),
            document_path=str(value.get("document_path", "")),
            start=int(start) if isinstance(start, (int, str)) and str(start) else None,
            end=int(end) if isinstance(end, (int, str)) and str(end) else None,
            unit_sequence=(
                int(unit_sequence)
                if isinstance(unit_sequence, (int, str)) and str(unit_sequence)
                else None
            ),
            element_index=(
                int(element_index)
                if isinstance(element_index, (int, str)) and str(element_index)
                else None
            ),
            slot=str(value["slot"]) if value.get("slot") is not None else None,
            attribute=(str(value["attribute"]) if value.get("attribute") is not None else None),
            part_index=(
                int(part_index) if isinstance(part_index, (int, str)) and str(part_index) else None
            ),
            part_count=(
                int(part_count) if isinstance(part_count, (int, str)) and str(part_count) else None
            ),
            document_order=(
                int(document_order)
                if isinstance(document_order, (int, str)) and str(document_order)
                else None
            ),
            document_type=(
                str(value["document_type"]) if value.get("document_type") is not None else None
            ),
        )


@dataclass(frozen=True, slots=True)
class Segment:
    """One deterministic novel translation unit."""

    segment_id: str
    order: int
    source_format: SourceFormat
    source_document: str
    source_text: str
    content_role: str
    locator: SegmentLocator
    source_hash: str
    translation_input_hash: str
    joiner: str = ""
    schema_version: str = "segment.v1"

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "segment_id": self.segment_id,
            "order": self.order,
            "source_format": self.source_format.value,
            "source_document": self.source_document,
            "source_text": self.source_text,
            "content_role": self.content_role,
            "locator": self.locator.to_dict(),
            "source_hash": self.source_hash,
            "translation_input_hash": self.translation_input_hash,
            "joiner": self.joiner,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> Segment:
        _require_schema(value, "segment.v1")
        locator = value.get("locator")
        if not isinstance(locator, dict):
            raise ValueError("Segment locator must be an object")
        return cls(
            schema_version="segment.v1",
            segment_id=str(value["segment_id"]),
            order=int(cast(int | str, value["order"])),
            source_format=SourceFormat(str(value["source_format"])),
            source_document=str(value.get("source_document", "")),
            source_text=str(value.get("source_text", "")),
            content_role=str(value.get("content_role", "body")),
            locator=SegmentLocator.from_dict(locator),
            source_hash=str(value.get("source_hash", "")),
            translation_input_hash=str(value.get("translation_input_hash", "")),
            joiner=str(value.get("joiner", "")),
        )


@dataclass(frozen=True, slots=True)
class DocumentManifest:
    """Serializable inspection result for TXT or EPUB input."""

    source_format: SourceFormat
    source_sha256: str
    source_size: int
    segments: tuple[Segment, ...]
    filename: str | None = None
    encoding: str | None = None
    encoding_confidence: float | None = None
    newline: str | None = None
    segmentation_version: str = "txt-segmentation.v1"
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    structure: dict[str, JsonValue] | None = None
    schema_version: str = "document-manifest.v1"

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "source_format": self.source_format.value,
            "source_sha256": self.source_sha256,
            "source_size": self.source_size,
            "filename": self.filename,
            "encoding": self.encoding,
            "encoding_confidence": self.encoding_confidence,
            "newline": self.newline,
            "segmentation_version": self.segmentation_version,
            "metadata": self.metadata,
            "structure": self.structure,
            "segments": [segment.to_dict() for segment in self.segments],
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> DocumentManifest:
        _require_schema(value, "document-manifest.v1")
        raw_segments = value.get("segments", [])
        if not isinstance(raw_segments, list):
            raise ValueError("Document manifest segments must be a list")
        if any(not isinstance(item, dict) for item in raw_segments):
            raise ValueError("Every Document manifest Segment must be an object")
        structure = value.get("structure")
        return cls(
            schema_version="document-manifest.v1",
            source_format=SourceFormat(str(value["source_format"])),
            source_sha256=str(value["source_sha256"]),
            source_size=int(cast(int | str, value["source_size"])),
            filename=str(value["filename"]) if value.get("filename") is not None else None,
            encoding=str(value["encoding"]) if value.get("encoding") is not None else None,
            encoding_confidence=(
                float(cast(float | int | str, value["encoding_confidence"]))
                if value.get("encoding_confidence") is not None
                else None
            ),
            newline=str(value["newline"]) if value.get("newline") is not None else None,
            segmentation_version=str(value.get("segmentation_version", "txt-segmentation.v1")),
            metadata=_mapping(value.get("metadata")),
            structure=_mapping(structure) if isinstance(structure, dict) else None,
            segments=tuple(Segment.from_dict(item) for item in raw_segments),
        )


@dataclass(frozen=True, slots=True)
class TranslationOptions:
    """Explicit per-operation translation policy; contains no credential fields."""

    source_language: str = "auto"
    target_language: str = "en"
    style: str = ""
    prompt_template: str = (
        "Translate from {source_language} to {target_language}. "
        "Style: {style}. Return only the translation.\n\n{text}"
    )
    prompt_version: str = "v1"
    model_parameters: dict[str, JsonValue] = field(default_factory=dict)
    max_segment_chars: int = 1_800
    concurrency: int = 1
    max_retries: int = 2
    retry_backoff_seconds: float = 0.25
    max_source_bytes: int = 100 * 1024 * 1024

    def __post_init__(self) -> None:
        if not self.target_language.strip():
            raise ValueError("target_language cannot be empty")
        if self.max_segment_chars <= 0:
            raise ValueError("max_segment_chars must be positive")
        if not 1 <= self.concurrency <= 32:
            raise ValueError("concurrency must be between 1 and 32")
        if not 0 <= self.max_retries <= 20:
            raise ValueError("max_retries must be between 0 and 20")
        if not math.isfinite(self.retry_backoff_seconds) or self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be finite and non-negative")
        if self.max_source_bytes <= 0:
            raise ValueError("max_source_bytes must be positive")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "source_language": self.source_language,
            "target_language": self.target_language,
            "style": self.style,
            "prompt_template": self.prompt_template,
            "prompt_version": self.prompt_version,
            "model_parameters": self.model_parameters,
            "max_segment_chars": self.max_segment_chars,
            "concurrency": self.concurrency,
            "max_retries": self.max_retries,
            "retry_backoff_seconds": self.retry_backoff_seconds,
            "max_source_bytes": self.max_source_bytes,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> TranslationOptions:
        return cls(
            source_language=str(value.get("source_language", "auto")),
            target_language=str(value.get("target_language", "en")),
            style=str(value.get("style", "")),
            prompt_template=str(
                value.get(
                    "prompt_template",
                    cls.__dataclass_fields__["prompt_template"].default,
                )
            ),
            prompt_version=str(value.get("prompt_version", "v1")),
            model_parameters=_mapping(value.get("model_parameters")),
            max_segment_chars=int(cast(int | str, value.get("max_segment_chars", 1_800))),
            concurrency=int(cast(int | str, value.get("concurrency", 1))),
            max_retries=int(cast(int | str, value.get("max_retries", 2))),
            retry_backoff_seconds=float(
                cast(float | int | str, value.get("retry_backoff_seconds", 0.25))
            ),
            max_source_bytes=int(cast(int | str, value.get("max_source_bytes", 100 * 1024 * 1024))),
        )


@dataclass(frozen=True, slots=True)
class ErrorRecord:
    code: ErrorCode
    message: str
    details: dict[str, JsonValue] = field(default_factory=dict)
    retryable: bool = False

    @classmethod
    def from_error(cls, error: LinguaError) -> ErrorRecord:
        return cls(
            code=error.code,
            message=error.message,
            details=_mapping(error.details or {}),
            retryable=error.retryable,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
            "retryable": self.retryable,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> ErrorRecord:
        return cls(
            code=ErrorCode(str(value["code"])),
            message=str(value.get("message", "")),
            details=_mapping(value.get("details")),
            retryable=bool(value.get("retryable", False)),
        )


@dataclass(frozen=True, slots=True)
class TranslationRecord:
    segment_id: str
    order: int
    source_hash: str
    translation_input_hash: str
    status: TranslationStatus
    translated_text: str | None = None
    provider_id: str | None = None
    model: str | None = None
    attempts: int = 0
    usage: dict[str, int] | None = None
    error: ErrorRecord | None = None
    schema_version: str = "translation-record.v1"

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "segment_id": self.segment_id,
            "order": self.order,
            "source_hash": self.source_hash,
            "translation_input_hash": self.translation_input_hash,
            "status": self.status.value,
            "translated_text": self.translated_text,
            "provider_id": self.provider_id,
            "model": self.model,
            "attempts": self.attempts,
            "usage": cast(JsonValue, self.usage),
            "error": self.error.to_dict() if self.error else None,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> TranslationRecord:
        _require_schema(value, "translation-record.v1")
        raw_error = value.get("error")
        raw_usage = value.get("usage")
        return cls(
            schema_version="translation-record.v1",
            segment_id=str(value["segment_id"]),
            order=int(cast(int | str, value["order"])),
            source_hash=str(value.get("source_hash", "")),
            translation_input_hash=str(value.get("translation_input_hash", "")),
            status=TranslationStatus(str(value["status"])),
            translated_text=(
                str(value["translated_text"]) if value.get("translated_text") is not None else None
            ),
            provider_id=str(value["provider_id"]) if value.get("provider_id") else None,
            model=str(value["model"]) if value.get("model") else None,
            attempts=int(cast(int | str, value.get("attempts", 0))),
            usage=(
                {str(key): int(item) for key, item in raw_usage.items()}
                if isinstance(raw_usage, dict)
                else None
            ),
            error=ErrorRecord.from_dict(raw_error) if isinstance(raw_error, dict) else None,
        )


@dataclass(frozen=True, slots=True)
class TranslationBatchResult:
    records: tuple[TranslationRecord, ...]
    status: BatchStatus
    selected_segment_ids: tuple[str, ...]
    source_sha256: str | None = None
    schema_version: str = "translation-batch.v1"

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "source_sha256": self.source_sha256,
            "selected_segment_ids": list(self.selected_segment_ids),
            "records": [record.to_dict() for record in self.records],
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> TranslationBatchResult:
        _require_schema(value, "translation-batch.v1")
        records = value.get("records", [])
        selected = value.get("selected_segment_ids", [])
        if not isinstance(records, list) or not isinstance(selected, list):
            raise ValueError("Translation batch lists are invalid")
        if any(not isinstance(item, dict) for item in records):
            raise ValueError("Every translation record must be an object")
        return cls(
            schema_version="translation-batch.v1",
            status=BatchStatus(str(value["status"])),
            source_sha256=(
                str(value["source_sha256"]) if value.get("source_sha256") is not None else None
            ),
            selected_segment_ids=tuple(str(item) for item in selected),
            records=tuple(TranslationRecord.from_dict(item) for item in records),
        )


@dataclass(frozen=True, slots=True)
class TranslationEvent:
    kind: EventKind
    completed: int
    total: int
    segment_id: str | None = None
    page_id: str | None = None
    attempt: int | None = None
    message: str | None = None
    error: ErrorRecord | None = None

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "kind": self.kind.value,
            "completed": self.completed,
            "total": self.total,
            "segment_id": self.segment_id,
            "page_id": self.page_id,
            "attempt": self.attempt,
            "message": self.message,
            "error": self.error.to_dict() if self.error else None,
        }


class CancellationToken:
    """Caller-owned cooperative cancellation flag; it starts no worker thread."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise LinguaError(ErrorCode.CANCELLED, "Translation was cancelled")


@dataclass(frozen=True, slots=True)
class BuildResult:
    source_format: SourceFormat
    output_sha256: str
    output_size: int
    translated_count: int
    preserved_count: int
    details: dict[str, JsonValue] = field(default_factory=dict)
    schema_version: str = "build-result.v1"

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "source_format": self.source_format.value,
            "output_sha256": self.output_sha256,
            "output_size": self.output_size,
            "translated_count": self.translated_count,
            "preserved_count": self.preserved_count,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> BuildResult:
        _require_schema(value, "build-result.v1")
        return cls(
            schema_version="build-result.v1",
            source_format=SourceFormat(str(value["source_format"])),
            output_sha256=str(value["output_sha256"]),
            output_size=int(cast(int | str, value["output_size"])),
            translated_count=int(cast(int | str, value["translated_count"])),
            preserved_count=int(cast(int | str, value["preserved_count"])),
            details=_mapping(value.get("details")),
        )


@dataclass(frozen=True, slots=True)
class MangaPage:
    page_id: str
    order: int
    name: str
    media_type: str
    source_sha256: str
    source_size: int
    archive_member: str | None = None

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "page_id": self.page_id,
            "order": self.order,
            "name": self.name,
            "media_type": self.media_type,
            "source_sha256": self.source_sha256,
            "source_size": self.source_size,
            "archive_member": self.archive_member,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> MangaPage:
        return cls(
            page_id=str(value["page_id"]),
            order=int(cast(int | str, value["order"])),
            name=str(value["name"]),
            media_type=str(value["media_type"]),
            source_sha256=str(value["source_sha256"]),
            source_size=int(cast(int | str, value["source_size"])),
            archive_member=(
                str(value["archive_member"]) if value.get("archive_member") is not None else None
            ),
        )


@dataclass(frozen=True, slots=True)
class MangaManifest:
    source_format: SourceFormat
    source_sha256: str
    source_size: int
    pages: tuple[MangaPage, ...]
    filename: str | None = None
    schema_version: str = "manga-manifest.v1"

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "source_format": self.source_format.value,
            "source_sha256": self.source_sha256,
            "source_size": self.source_size,
            "filename": self.filename,
            "pages": [page.to_dict() for page in self.pages],
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> MangaManifest:
        _require_schema(value, "manga-manifest.v1")
        pages = value.get("pages", [])
        if not isinstance(pages, list):
            raise ValueError("Manga manifest pages must be a list")
        if any(not isinstance(item, dict) for item in pages):
            raise ValueError("Every Manga manifest page must be an object")
        return cls(
            schema_version="manga-manifest.v1",
            source_format=SourceFormat(str(value["source_format"])),
            source_sha256=str(value["source_sha256"]),
            source_size=int(cast(int | str, value["source_size"])),
            filename=str(value["filename"]) if value.get("filename") is not None else None,
            pages=tuple(MangaPage.from_dict(item) for item in pages),
        )


@dataclass(frozen=True, slots=True)
class MangaPageTranslation:
    page_id: str
    order: int
    name: str
    status: TranslationStatus
    media_type: str | None = None
    image: bytes | None = None
    attempts: int = 0
    raw_result: dict[str, JsonValue] = field(default_factory=dict)
    logs: tuple[str, ...] = ()
    error: ErrorRecord | None = None

    def to_dict(self, *, include_binary: bool = True) -> dict[str, JsonValue]:
        return {
            "page_id": self.page_id,
            "order": self.order,
            "name": self.name,
            "status": self.status.value,
            "media_type": self.media_type,
            "image_base64": (
                base64.b64encode(self.image).decode("ascii")
                if include_binary and self.image is not None
                else None
            ),
            "image_size": len(self.image) if self.image is not None else None,
            "attempts": self.attempts,
            "raw_result": self.raw_result,
            "logs": list(self.logs),
            "error": self.error.to_dict() if self.error else None,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> MangaPageTranslation:
        encoded = value.get("image_base64")
        raw_error = value.get("error")
        logs = value.get("logs", [])
        return cls(
            page_id=str(value["page_id"]),
            order=int(cast(int | str, value["order"])),
            name=str(value["name"]),
            status=TranslationStatus(str(value["status"])),
            media_type=str(value["media_type"]) if value.get("media_type") else None,
            image=base64.b64decode(str(encoded), validate=True) if encoded else None,
            attempts=int(cast(int | str, value.get("attempts", 0))),
            raw_result=_mapping(value.get("raw_result")),
            logs=tuple(str(item) for item in logs) if isinstance(logs, list) else (),
            error=ErrorRecord.from_dict(raw_error) if isinstance(raw_error, dict) else None,
        )


@dataclass(frozen=True, slots=True)
class MangaTranslationResult:
    manifest: MangaManifest
    pages: tuple[MangaPageTranslation, ...]
    status: BatchStatus
    adapter_id: str
    schema_version: str = "manga-translation.v1"

    def to_dict(self, *, include_binary: bool = True) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "adapter_id": self.adapter_id,
            "manifest": self.manifest.to_dict(),
            "pages": [page.to_dict(include_binary=include_binary) for page in self.pages],
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> MangaTranslationResult:
        _require_schema(value, "manga-translation.v1")
        manifest = value.get("manifest")
        pages = value.get("pages", [])
        if not isinstance(manifest, dict) or not isinstance(pages, list):
            raise ValueError("Manga translation payload is invalid")
        if any(not isinstance(item, dict) for item in pages):
            raise ValueError("Every Manga page result must be an object")
        return cls(
            schema_version="manga-translation.v1",
            status=BatchStatus(str(value["status"])),
            adapter_id=str(value["adapter_id"]),
            manifest=MangaManifest.from_dict(manifest),
            pages=tuple(MangaPageTranslation.from_dict(item) for item in pages),
        )


@dataclass(frozen=True, slots=True)
class DocumentTranslationResult:
    manifest: DocumentManifest
    translations: TranslationBatchResult
    build: BuildResult
    schema_version: str = "document-translation.v1"

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "manifest": self.manifest.to_dict(),
            "translations": self.translations.to_dict(),
            "build": self.build.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> DocumentTranslationResult:
        _require_schema(value, "document-translation.v1")
        manifest = value.get("manifest")
        translations = value.get("translations")
        build = value.get("build")
        if (
            not isinstance(manifest, dict)
            or not isinstance(translations, dict)
            or not isinstance(build, dict)
        ):
            raise ValueError("Document translation payload is invalid")
        return cls(
            schema_version="document-translation.v1",
            manifest=DocumentManifest.from_dict(manifest),
            translations=TranslationBatchResult.from_dict(translations),
            build=BuildResult.from_dict(build),
        )


__all__ = [
    "BatchStatus",
    "BuildResult",
    "CancellationToken",
    "DocumentManifest",
    "DocumentTranslationResult",
    "ErrorRecord",
    "EventKind",
    "JsonValue",
    "MangaManifest",
    "MangaPage",
    "MangaPageTranslation",
    "MangaTranslationResult",
    "Segment",
    "SegmentLocator",
    "SourceFormat",
    "TranslationBatchResult",
    "TranslationEvent",
    "TranslationOptions",
    "TranslationRecord",
    "TranslationStatus",
]
