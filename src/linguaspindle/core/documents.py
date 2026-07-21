"""Public TXT/EPUB inspection, translation, and reconstruction API."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import cast

from ..epub import (
    build_translated_epub as _build_translated_epub_package,
)
from ..epub import (
    inspect_epub as _inspect_epub_package,
)
from ..errors import ErrorCode, LinguaError
from ..limits import ArchiveLimits
from ..providers.base import TranslationProvider
from .io import (
    OutputTarget,
    SourceInput,
    materialized_path,
    read_source_bytes,
    source_filename,
    source_output_alias,
    write_output,
)
from .models import (
    BuildResult,
    CancellationToken,
    DocumentManifest,
    DocumentTranslationResult,
    JsonValue,
    Segment,
    SegmentLocator,
    SourceFormat,
    TranslationBatchResult,
    TranslationOptions,
    TranslationRecord,
    TranslationStatus,
)
from .orchestration import EventHandler, ExistingTranslation, translate_segments
from .txt import decode_txt, inspect_txt_payload, rebuild_txt


def inspect_document(
    source: SourceInput,
    *,
    filename: str | None = None,
    format_hint: SourceFormat | str | None = None,
    options: TranslationOptions | None = None,
    archive_limits: ArchiveLimits | None = None,
) -> DocumentManifest:
    """Inspect TXT or common unencrypted EPUB 2/3 without runtime state."""

    configured = options or TranslationOptions()
    payload = read_source_bytes(source, maximum_bytes=configured.max_source_bytes)
    name = source_filename(source, filename)
    source_sha256 = hashlib.sha256(payload).hexdigest()
    selected_format = _document_format(payload, name, format_hint)
    requested_epub_format: SourceFormat | None = None
    if format_hint is not None:
        hint_value = (
            format_hint.value if isinstance(format_hint, SourceFormat) else str(format_hint).lower()
        )
        if hint_value in {SourceFormat.EPUB2.value, SourceFormat.EPUB3.value}:
            requested_epub_format = SourceFormat(hint_value)
    if selected_format is SourceFormat.TXT:
        return inspect_txt_payload(
            payload,
            source_sha256=source_sha256,
            filename=name,
            options=configured,
        )

    with materialized_path(payload, suffix=".epub") as source_path:
        raw = _inspect_epub_package(source_path, archive_limits or ArchiveLimits())
    version = str(raw["epub_version"])
    actual_format = SourceFormat.EPUB2 if version.startswith("2") else SourceFormat.EPUB3
    if requested_epub_format is not None and requested_epub_format != actual_format:
        raise LinguaError(
            ErrorCode.INVALID_FORMAT,
            "EPUB version does not match the requested format",
            {"requested": requested_epub_format.value, "actual": actual_format.value},
        )
    segments = _epub_segments(raw, source_sha256, actual_format, configured)
    metadata_source = raw.get("metadata")
    metadata: dict[str, JsonValue] = {
        "epub_version": version,
        "package_document": str(raw["package_document"]),
        "segment_count": len(segments),
        "structure_contract": "epub-inspection.v1-opaque",
    }
    if isinstance(metadata_source, dict):
        metadata["package_metadata"] = cast(JsonValue, metadata_source)
    return DocumentManifest(
        source_format=actual_format,
        source_sha256=source_sha256,
        source_size=len(payload),
        filename=name,
        segments=segments,
        segmentation_version="epub-visible-text.v1",
        metadata=metadata,
        # The complete package graph is an explicitly versioned compatibility
        # payload consumed by the already accepted EPUB rebuilder. Stable
        # Segment locators and the typed summary above remain the public API.
        structure=cast(dict[str, JsonValue], raw),
    )


def inspect_epub(
    source: SourceInput,
    *,
    filename: str | None = None,
    options: TranslationOptions | None = None,
    archive_limits: ArchiveLimits | None = None,
) -> DocumentManifest:
    """Inspect an EPUB 2/3 into the stable typed Document manifest."""

    return inspect_document(
        source,
        filename=filename,
        format_hint="epub",
        options=options,
        archive_limits=archive_limits,
    )


def extract_segments(
    source: SourceInput,
    manifest: DocumentManifest | None = None,
    *,
    filename: str | None = None,
    format_hint: SourceFormat | str | None = None,
    options: TranslationOptions | None = None,
    archive_limits: ArchiveLimits | None = None,
) -> tuple[Segment, ...]:
    """Return deterministic Segments, validating an optional saved manifest."""

    inspected = inspect_document(
        source,
        filename=filename,
        format_hint=format_hint,
        options=options,
        archive_limits=archive_limits,
    )
    if manifest is not None and manifest.source_sha256 != inspected.source_sha256:
        raise LinguaError(
            ErrorCode.SOURCE_MISMATCH,
            "Source does not match the supplied Document manifest",
        )
    if manifest is not None:
        expected = [segment.segment_id for segment in manifest.segments]
        actual = [segment.segment_id for segment in inspected.segments]
        if expected != actual:
            raise LinguaError(
                ErrorCode.SOURCE_MISMATCH,
                "Source Segments do not match the supplied Document manifest",
            )
    return inspected.segments


def rebuild_document(
    source: SourceInput,
    manifest: DocumentManifest,
    translations: TranslationBatchResult
    | Mapping[str, str | TranslationRecord]
    | Iterable[TranslationRecord],
    output: OutputTarget,
    *,
    target_language: str | None = None,
    overwrite: bool = False,
    archive_limits: ArchiveLimits | None = None,
) -> BuildResult:
    """Rebuild from the immutable source, preserving untranslated content."""

    if source_output_alias(source, output):
        raise LinguaError(
            ErrorCode.INVALID_STATE,
            "Document output must not overwrite the immutable source",
        )
    maximum = max(manifest.source_size + 1, 1)
    try:
        payload = read_source_bytes(source, maximum_bytes=maximum)
    except LinguaError as exc:
        if exc.code is ErrorCode.UPLOAD_TOO_LARGE:
            raise LinguaError(
                ErrorCode.SOURCE_MISMATCH,
                "Source does not match the supplied Document manifest",
            ) from exc
        raise
    source_sha256 = hashlib.sha256(payload).hexdigest()
    if source_sha256 != manifest.source_sha256 or len(payload) != manifest.source_size:
        raise LinguaError(
            ErrorCode.SOURCE_MISMATCH,
            "Source does not match the supplied Document manifest",
        )
    canonical_manifest = _validated_document_manifest(
        payload,
        manifest,
        archive_limits=archive_limits,
    )
    values = _translation_values(manifest, translations)

    if canonical_manifest.source_format is SourceFormat.TXT:
        decoded = decode_txt(payload)
        built = rebuild_txt(decoded, canonical_manifest, values)
        write_output(output, built, overwrite=overwrite)
        return BuildResult(
            source_format=SourceFormat.TXT,
            output_sha256=hashlib.sha256(built).hexdigest(),
            output_size=len(built),
            translated_count=len(values),
            preserved_count=len(canonical_manifest.segments) - len(values),
            details={"encoding": "utf-8", "newline": "lf"},
        )

    if canonical_manifest.structure is None:
        raise LinguaError(ErrorCode.INVALID_FORMAT, "EPUB manifest has no package structure")
    language = (target_language or "").strip()
    if not language:
        raise LinguaError(ErrorCode.INVALID_FORMAT, "EPUB rebuild requires a target language")
    by_sequence = {
        segment.locator.unit_sequence: values[segment.segment_id]
        for segment in canonical_manifest.segments
        if segment.segment_id in values and segment.locator.unit_sequence is not None
    }
    limits = archive_limits or ArchiveLimits()
    with materialized_path(payload, suffix=".epub") as source_path:
        descriptor, name = tempfile.mkstemp(prefix="linguaspindle-build-", suffix=".epub")
        os.close(descriptor)
        built_path = Path(name)
        try:
            details = _build_translated_epub_package(
                source_path,
                built_path,
                cast(dict[str, object], canonical_manifest.structure),
                cast(Mapping[object, object], by_sequence),
                language,
                limits,
            )
            built = built_path.read_bytes()
        finally:
            built_path.unlink(missing_ok=True)
    write_output(output, built, overwrite=overwrite)
    return BuildResult(
        source_format=canonical_manifest.source_format,
        output_sha256=hashlib.sha256(built).hexdigest(),
        output_size=len(built),
        translated_count=int(details.get("translated_unit_count", len(values))),
        preserved_count=int(
            details.get("preserved_unit_count", len(canonical_manifest.segments) - len(values))
        ),
        details=cast(dict[str, JsonValue], details),
    )


def build_translated_epub(
    source: SourceInput,
    output: OutputTarget,
    manifest: DocumentManifest,
    translations: TranslationBatchResult
    | Mapping[str, str | TranslationRecord]
    | Iterable[TranslationRecord],
    target_language: str,
    *,
    overwrite: bool = False,
    archive_limits: ArchiveLimits | None = None,
) -> BuildResult:
    """Rebuild an EPUB through the stable typed core contract."""

    if manifest.source_format not in {SourceFormat.EPUB2, SourceFormat.EPUB3}:
        raise LinguaError(
            ErrorCode.INVALID_FORMAT,
            "EPUB rebuild requires an EPUB Document manifest",
        )
    return rebuild_document(
        source,
        manifest,
        translations,
        output,
        target_language=target_language,
        overwrite=overwrite,
        archive_limits=archive_limits,
    )


def translate_document(
    source: SourceInput,
    output: OutputTarget,
    provider: TranslationProvider,
    options: TranslationOptions,
    *,
    filename: str | None = None,
    format_hint: SourceFormat | str | None = None,
    selected_segment_ids: Iterable[str] | None = None,
    existing_translations: Mapping[str, ExistingTranslation] | Iterable[TranslationRecord] = (),
    archive_limits: ArchiveLimits | None = None,
    overwrite: bool = False,
    cancellation: CancellationToken | None = None,
    on_event: EventHandler | None = None,
    sensitive_values: tuple[str, ...] = (),
) -> DocumentTranslationResult:
    if source_output_alias(source, output):
        raise LinguaError(
            ErrorCode.INVALID_STATE,
            "Document output must not overwrite the immutable source",
        )
    effective_filename = source_filename(source, filename)
    payload = read_source_bytes(source, maximum_bytes=options.max_source_bytes)
    manifest = inspect_document(
        payload,
        filename=effective_filename,
        format_hint=format_hint,
        options=options,
        archive_limits=archive_limits,
    )
    translated = translate_segments(
        manifest,
        provider,
        options,
        selected_segment_ids=selected_segment_ids,
        existing_translations=existing_translations,
        cancellation=cancellation,
        on_event=on_event,
        sensitive_values=sensitive_values,
    )
    built = rebuild_document(
        payload,
        manifest,
        translated,
        output,
        target_language=options.target_language,
        overwrite=overwrite,
        archive_limits=archive_limits,
    )
    return DocumentTranslationResult(manifest=manifest, translations=translated, build=built)


def _document_format(
    payload: bytes,
    filename: str | None,
    hint: SourceFormat | str | None,
) -> SourceFormat:
    if hint is not None:
        value = str(hint).lower()
        if value == "epub":
            value = SourceFormat.EPUB3.value
        try:
            selected = SourceFormat(value)
        except ValueError as exc:
            raise LinguaError(ErrorCode.INVALID_FORMAT, "Unknown document format hint") from exc
        if selected not in {SourceFormat.TXT, SourceFormat.EPUB2, SourceFormat.EPUB3}:
            raise LinguaError(ErrorCode.INVALID_FORMAT, "Format hint is not a novel format")
        return selected
    suffix = Path(filename or "").suffix.casefold()
    if suffix == ".epub" or _looks_like_epub(payload):
        # The inspector determines the precise EPUB major version.
        return SourceFormat.EPUB3
    if payload.startswith(b"PK\x03\x04"):
        raise LinguaError(ErrorCode.INVALID_FORMAT, "ZIP source is not a recognized EPUB")
    return SourceFormat.TXT


def _looks_like_epub(payload: bytes) -> bool:
    return payload.startswith(b"PK\x03\x04") and b"application/epub+zip" in payload[:512]


def _epub_segments(
    raw: dict[str, object],
    source_sha256: str,
    source_format: SourceFormat,
    options: TranslationOptions,
) -> tuple[Segment, ...]:
    units = raw.get("text_units", [])
    if not isinstance(units, list):
        raise LinguaError(ErrorCode.EPUB_INVALID, "EPUB text-unit manifest is invalid")
    segments: list[Segment] = []
    for fallback_order, unit in enumerate(units):
        if not isinstance(unit, dict):
            raise LinguaError(ErrorCode.EPUB_INVALID, "EPUB text unit is invalid")
        locator = unit.get("locator")
        if not isinstance(locator, dict):
            raise LinguaError(ErrorCode.EPUB_INVALID, "EPUB text-unit locator is invalid")
        order = int(unit.get("sequence", fallback_order))
        source_text = str(unit["source_text"])
        source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        locator_key = str(unit.get("locator_key") or json.dumps(locator, sort_keys=True))
        segment_id = hashlib.sha256(
            (
                f"{source_format.value}\0epub-visible-text.v1\0{source_sha256}"
                f"\0{locator_key}\0{source_hash}"
            ).encode()
        ).hexdigest()
        input_hash = hashlib.sha256(
            json.dumps(
                {
                    "segment_id": segment_id,
                    "source_hash": source_hash,
                    "source_language": options.source_language,
                    "target_language": options.target_language,
                    "style": options.style,
                    "prompt_template": options.prompt_template,
                    "prompt_version": options.prompt_version,
                    "model_parameters": options.model_parameters,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        document_path = str(locator.get("document_path", ""))
        role = str(locator.get("document_type", "body"))
        if locator.get("slot") == "attribute":
            role = str(locator.get("attribute") or role)
        segments.append(
            Segment(
                segment_id=segment_id,
                order=order,
                source_format=source_format,
                source_document=document_path,
                source_text=source_text,
                content_role=role,
                locator=SegmentLocator(
                    kind="epub-xml-slot",
                    document_path=document_path,
                    unit_sequence=order,
                    element_index=int(locator.get("element_index", 0)),
                    slot=str(locator.get("slot", "text")),
                    attribute=(
                        str(locator["attribute"]) if locator.get("attribute") is not None else None
                    ),
                    part_index=int(locator.get("part_index", 0)),
                    part_count=int(locator.get("part_count", 1)),
                    document_order=int(locator.get("document_order", 0)),
                    document_type=str(locator.get("document_type", "body")),
                ),
                source_hash=source_hash,
                translation_input_hash=input_hash,
                joiner=str(unit.get("joiner", "")),
            )
        )
    if not segments:
        raise LinguaError(ErrorCode.EPUB_INVALID, "EPUB contains no translatable text")
    return tuple(sorted(segments, key=lambda item: item.order))


def _translation_values(
    manifest: DocumentManifest,
    translations: TranslationBatchResult
    | Mapping[str, str | TranslationRecord]
    | Iterable[TranslationRecord],
) -> dict[str, str]:
    if isinstance(translations, TranslationBatchResult):
        if (
            translations.source_sha256 is not None
            and translations.source_sha256 != manifest.source_sha256
        ):
            raise LinguaError(
                ErrorCode.SOURCE_MISMATCH,
                "Translation batch does not match the immutable source",
            )
        records: Mapping[str, str | TranslationRecord] = {
            record.segment_id: record for record in translations.records
        }
    elif isinstance(translations, Mapping):
        records = translations
    else:
        records = {record.segment_id: record for record in translations}
    known = {segment.segment_id for segment in manifest.segments}
    unknown = sorted(set(records) - known)
    if unknown:
        raise LinguaError(
            ErrorCode.SEGMENT_NOT_FOUND,
            "Translation references an unknown Segment ID",
            {"unknown_segment_ids": unknown},
        )
    values: dict[str, str] = {}
    segments_by_id = {segment.segment_id: segment for segment in manifest.segments}
    for segment_id, value in records.items():
        if isinstance(value, str):
            values[segment_id] = value
        elif value.status in {TranslationStatus.SUCCEEDED, TranslationStatus.MANUAL}:
            segment = segments_by_id[segment_id]
            if value.source_hash and value.source_hash != segment.source_hash:
                raise LinguaError(
                    ErrorCode.SOURCE_MISMATCH,
                    "Translation does not match the current Segment source",
                    {"segment_id": segment_id},
                )
            if (
                value.status is TranslationStatus.SUCCEEDED
                and value.translation_input_hash != segment.translation_input_hash
            ):
                raise LinguaError(
                    ErrorCode.SOURCE_MISMATCH,
                    "Translation does not match the current translation policy",
                    {"segment_id": segment_id},
                )
            if value.translated_text is None:
                raise LinguaError(
                    ErrorCode.INVALID_FORMAT,
                    "Successful translation has no translated text",
                    {"segment_id": segment_id},
                )
            values[segment_id] = value.translated_text
    return values


def _validated_document_manifest(
    payload: bytes,
    supplied: DocumentManifest,
    *,
    archive_limits: ArchiveLimits | None,
) -> DocumentManifest:
    raw_maximum = supplied.metadata.get("max_segment_chars", 1_800)
    if isinstance(raw_maximum, bool) or not isinstance(raw_maximum, (int, str)):
        raise LinguaError(ErrorCode.SOURCE_MISMATCH, "Document manifest policy is invalid")
    try:
        maximum = int(raw_maximum)
        options = TranslationOptions(
            max_segment_chars=maximum,
            max_source_bytes=max(len(payload), 1),
        )
    except (TypeError, ValueError) as exc:
        raise LinguaError(
            ErrorCode.SOURCE_MISMATCH,
            "Document manifest policy is invalid",
        ) from exc
    canonical = inspect_document(
        payload,
        filename=supplied.filename,
        format_hint=supplied.source_format,
        options=options,
        archive_limits=archive_limits,
    )
    supplied_identity = [
        (
            segment.schema_version,
            segment.segment_id,
            segment.order,
            segment.source_format,
            segment.source_document,
            segment.source_text,
            segment.content_role,
            segment.locator,
            segment.source_hash,
            segment.joiner,
        )
        for segment in supplied.segments
    ]
    canonical_identity = [
        (
            segment.schema_version,
            segment.segment_id,
            segment.order,
            segment.source_format,
            segment.source_document,
            segment.source_text,
            segment.content_role,
            segment.locator,
            segment.source_hash,
            segment.joiner,
        )
        for segment in canonical.segments
    ]
    if (
        supplied.schema_version != canonical.schema_version
        or supplied.source_format is not canonical.source_format
        or supplied.segmentation_version != canonical.segmentation_version
        or supplied_identity != canonical_identity
    ):
        raise LinguaError(
            ErrorCode.SOURCE_MISMATCH,
            "Document manifest Segments do not match the immutable source",
        )
    return canonical


__all__ = [
    "build_translated_epub",
    "extract_segments",
    "inspect_document",
    "inspect_epub",
    "rebuild_document",
    "translate_document",
]
