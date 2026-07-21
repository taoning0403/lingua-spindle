"""Pure single-image and CBZ manga translation pipeline."""

from __future__ import annotations

import hashlib
import io
import re
import stat
import time
import unicodedata
import zipfile
import zlib
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import cast

from ..adapters.base import AdapterHealth, MangaAdapterResult, MangaTranslationAdapter
from ..errors import ErrorCode, LinguaError
from ..json_types import normalize_json_object
from ..limits import ArchiveLimits
from ..security import redact, redact_text
from .io import OutputTarget, SourceInput, read_source_bytes, source_filename, write_output
from .models import (
    BatchStatus,
    BuildResult,
    CancellationToken,
    ErrorRecord,
    EventKind,
    MangaManifest,
    MangaPage,
    MangaPageTranslation,
    MangaTranslationResult,
    SourceFormat,
    TranslationEvent,
    TranslationOptions,
    TranslationStatus,
)

MangaEventHandler = Callable[[TranslationEvent], None]
_IMAGE_SUFFIXES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
_ARCHIVE_SUFFIXES = {".cbz", ".zip"}


def inspect_manga(
    source: SourceInput,
    *,
    filename: str | None = None,
    archive_limits: ArchiveLimits | None = None,
    maximum_bytes: int = 100 * 1024 * 1024,
) -> MangaManifest:
    """Inspect a valid image or bounded CBZ/ZIP into stable page identities."""

    payload = read_source_bytes(source, maximum_bytes=maximum_bytes)
    name = source_filename(source, filename)
    source_sha256 = hashlib.sha256(payload).hexdigest()
    suffix = Path(name or "").suffix.casefold()
    if suffix in _ARCHIVE_SUFFIXES and not payload.startswith(b"PK\x03\x04"):
        raise LinguaError(
            ErrorCode.INVALID_FORMAT,
            "Manga archive filename does not contain a ZIP archive",
        )
    if suffix in _IMAGE_SUFFIXES or not payload.startswith(b"PK\x03\x04"):
        media_type = _validate_image(payload, suffix=suffix or None)
        page_name = name or f"page{_suffix_for_media(media_type)}"
        page_hash = hashlib.sha256(payload).hexdigest()
        page_id = _page_id(source_sha256, page_name, page_hash)
        return MangaManifest(
            source_format=SourceFormat.IMAGE,
            source_sha256=source_sha256,
            source_size=len(payload),
            filename=name,
            pages=(
                MangaPage(
                    page_id=page_id,
                    order=0,
                    name=page_name,
                    media_type=media_type,
                    source_sha256=page_hash,
                    source_size=len(payload),
                ),
            ),
        )

    limits = archive_limits or ArchiveLimits()
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload), "r")
    except zipfile.BadZipFile as exc:
        raise LinguaError(ErrorCode.INVALID_FORMAT, "Manga archive is not a valid ZIP") from exc
    pages: list[MangaPage] = []
    with archive:
        members = archive.infolist()
        if not members:
            raise LinguaError(ErrorCode.INVALID_FORMAT, "Manga archive is empty")
        if len(members) > limits.max_files:
            raise LinguaError(
                ErrorCode.ARCHIVE_LIMIT_EXCEEDED,
                "Manga archive contains too many members",
                {"member_count": len(members), "limit": limits.max_files},
            )
        total = 0
        portable_names: set[str] = set()
        candidates: list[tuple[zipfile.ZipInfo, str, str]] = []
        for member in members:
            safe_name = _safe_member_name(member.filename, limits.max_path_depth)
            portable = unicodedata.normalize("NFC", safe_name).casefold()
            if portable in portable_names:
                raise LinguaError(
                    ErrorCode.ARCHIVE_UNSAFE,
                    "Manga archive contains duplicate or ambiguous paths",
                    {"member": member.filename},
                )
            portable_names.add(portable)
            if member.flag_bits & 0x41:
                raise LinguaError(
                    ErrorCode.INVALID_FORMAT,
                    "Encrypted manga archives are not supported",
                    {"member": member.filename},
                )
            unix_mode = member.external_attr >> 16
            if member.create_system == 3 and stat.S_IFMT(unix_mode) == stat.S_IFLNK:
                raise LinguaError(
                    ErrorCode.ARCHIVE_UNSAFE,
                    "Manga archive cannot contain symbolic links",
                    {"member": member.filename},
                )
            if member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise LinguaError(
                    ErrorCode.INVALID_FORMAT,
                    "Manga archive uses an unsupported compression method",
                    {"member": member.filename},
                )
            if member.file_size > limits.max_member_bytes:
                raise LinguaError(
                    ErrorCode.ARCHIVE_LIMIT_EXCEEDED,
                    "Manga archive member exceeds the configured size limit",
                    {"member": member.filename, "limit": limits.max_member_bytes},
                )
            total += member.file_size
            if total > limits.max_uncompressed_bytes:
                raise LinguaError(
                    ErrorCode.ARCHIVE_LIMIT_EXCEEDED,
                    "Manga archive expands beyond the configured limit",
                    {"expanded_bytes": total, "limit": limits.max_uncompressed_bytes},
                )
            ratio = (
                member.file_size / member.compress_size
                if member.compress_size > 0
                else (float("inf") if member.file_size else 0.0)
            )
            if ratio > limits.max_compression_ratio:
                raise LinguaError(
                    ErrorCode.ARCHIVE_LIMIT_EXCEEDED,
                    "Manga archive member exceeds the configured compression ratio",
                    {"member": member.filename, "limit": limits.max_compression_ratio},
                )
            suffix = PurePosixPath(safe_name).suffix.casefold()
            if not member.is_dir() and suffix in _IMAGE_SUFFIXES:
                candidates.append((member, safe_name, suffix))
        if not candidates:
            raise LinguaError(ErrorCode.INVALID_FORMAT, "Manga archive contains no images")
        candidates.sort(key=lambda item: _natural_key(item[1]))
        for order, (member, safe_name, suffix) in enumerate(candidates):
            try:
                image = archive.read(member)
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise LinguaError(
                    ErrorCode.INVALID_FORMAT,
                    "Manga archive member could not be read",
                    {"member": safe_name, "reason": type(exc).__name__},
                ) from exc
            if len(image) != member.file_size:
                raise LinguaError(
                    ErrorCode.INVALID_FORMAT,
                    "Manga archive member size is inconsistent",
                    {"member": member.filename},
                )
            media_type = _validate_image(image, suffix=suffix)
            page_hash = hashlib.sha256(image).hexdigest()
            pages.append(
                MangaPage(
                    page_id=_page_id(source_sha256, safe_name, page_hash),
                    order=order,
                    name=PurePosixPath(safe_name).name,
                    media_type=media_type,
                    source_sha256=page_hash,
                    source_size=len(image),
                    archive_member=safe_name,
                )
            )
    return MangaManifest(
        source_format=SourceFormat.CBZ,
        source_sha256=source_sha256,
        source_size=len(payload),
        filename=name,
        pages=tuple(pages),
    )


def translate_manga(
    source: SourceInput,
    adapter: MangaTranslationAdapter,
    options: TranslationOptions,
    *,
    manifest: MangaManifest | None = None,
    filename: str | None = None,
    archive_limits: ArchiveLimits | None = None,
    cancellation: CancellationToken | None = None,
    on_event: MangaEventHandler | None = None,
    sensitive_values: Sequence[str] = (),
) -> MangaTranslationResult:
    """Translate pages synchronously, retaining page-level partial results."""

    payload, inspected = _validated_manga_source(
        source,
        manifest,
        filename=filename,
        archive_limits=archive_limits,
        maximum_bytes=options.max_source_bytes,
    )
    adapter_id = redact_text(adapter.manifest.id, sensitive_values)
    token = cancellation or CancellationToken()
    total = len(inspected.pages)
    _emit(on_event, TranslationEvent(EventKind.STARTED, 0, total, message="manga"))
    if token.cancelled:
        error = ErrorRecord(ErrorCode.CANCELLED, "Translation was cancelled")
        cancelled = tuple(
            MangaPageTranslation(
                page_id=page.page_id,
                order=page.order,
                name=page.name,
                status=TranslationStatus.CANCELLED,
                error=error,
            )
            for page in inspected.pages
        )
        for completed, page in enumerate(inspected.pages, start=1):
            _emit(
                on_event,
                TranslationEvent(
                    EventKind.CANCELLED,
                    completed,
                    total,
                    page_id=page.page_id,
                    error=error,
                ),
            )
        _emit(
            on_event,
            TranslationEvent(
                EventKind.COMPLETED,
                total,
                total,
                message=BatchStatus.CANCELLED.value,
            ),
        )
        return MangaTranslationResult(
            manifest=inspected,
            pages=cancelled,
            status=BatchStatus.CANCELLED,
            adapter_id=adapter_id,
        )
    try:
        health = adapter.health()
        if not isinstance(health, AdapterHealth):
            raise TypeError("Manga Adapter health() returned an invalid result")
    except Exception as exc:
        error = _manga_error(exc, sensitive_values)
        raise LinguaError(
            ErrorCode.ADAPTER_UNAVAILABLE,
            "Manga Adapter health check failed",
            {
                "adapter_id": adapter_id,
                "cause_code": error.code.value,
                **error.details,
            },
            retryable=True,
        ) from exc
    if not health.available:
        details = normalize_json_object(redact(health.details or {}, sensitive_values))
        raise LinguaError(
            ErrorCode.ADAPTER_UNAVAILABLE,
            redact_text(health.message, sensitive_values),
            details,
            retryable=True,
        )
    page_payloads = _page_payloads(payload, inspected)
    results: list[MangaPageTranslation] = []
    for page, image in zip(inspected.pages, page_payloads, strict=True):
        if token.cancelled:
            error = ErrorRecord(ErrorCode.CANCELLED, "Translation was cancelled")
            results.append(
                MangaPageTranslation(
                    page_id=page.page_id,
                    order=page.order,
                    name=page.name,
                    status=TranslationStatus.CANCELLED,
                    error=error,
                )
            )
            _emit(
                on_event,
                TranslationEvent(
                    EventKind.CANCELLED,
                    len(results),
                    total,
                    page_id=page.page_id,
                    error=error,
                ),
            )
            continue
        translated = _translate_page(
            page,
            image,
            adapter,
            options,
            token,
            sensitive_values,
            on_event,
            total,
        )
        results.append(translated)
        _emit(
            on_event,
            TranslationEvent(
                EventKind.PROGRESS,
                len(results),
                total,
                page_id=page.page_id,
            ),
        )
        # Cancellation is deliberately observed only at page boundaries. The
        # core does not claim streaming progress or mid-image interruption.
    status = _manga_status(results)
    _emit(on_event, TranslationEvent(EventKind.COMPLETED, total, total, message=status.value))
    return MangaTranslationResult(
        manifest=inspected,
        pages=tuple(results),
        status=status,
        adapter_id=adapter_id,
    )


def extract_manga_pages(
    source: SourceInput,
    manifest: MangaManifest,
    *,
    archive_limits: ArchiveLimits | None = None,
    maximum_bytes: int = 100 * 1024 * 1024,
) -> tuple[tuple[MangaPage, bytes], ...]:
    """Read and checksum-verify pages declared by a saved Manga manifest."""

    payload, inspected = _validated_manga_source(
        source,
        manifest,
        filename=manifest.filename,
        archive_limits=archive_limits,
        maximum_bytes=maximum_bytes,
    )
    return tuple(zip(inspected.pages, _page_payloads(payload, inspected), strict=True))


def build_manga_output(
    result: MangaTranslationResult,
    output: OutputTarget,
    *,
    overwrite: bool = False,
) -> BuildResult:
    """Write a translated image or ordered CBZ from successful page results."""

    pages = [
        page
        for page in sorted(result.pages, key=lambda item: item.order)
        if page.status is TranslationStatus.SUCCEEDED and page.image is not None
    ]
    if not pages:
        raise LinguaError(ErrorCode.OUTPUT_MISSING, "No translated manga pages are available")
    if result.manifest.source_format is SourceFormat.IMAGE:
        payload = cast(bytes, pages[0].image)
    else:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for index, page in enumerate(pages, start=1):
                archive.writestr(
                    f"{index:04d}{_suffix_for_media(page.media_type or 'image/png')}",
                    cast(bytes, page.image),
                )
        payload = buffer.getvalue()
    write_output(output, payload, overwrite=overwrite)
    return BuildResult(
        source_format=result.manifest.source_format,
        output_sha256=hashlib.sha256(payload).hexdigest(),
        output_size=len(payload),
        translated_count=len(pages),
        preserved_count=0,
        details={
            "adapter_id": result.adapter_id,
            "batch_status": result.status.value,
            "omitted_count": len(result.pages) - len(pages),
        },
    )


def _translate_page(
    page: MangaPage,
    image: bytes,
    adapter: MangaTranslationAdapter,
    options: TranslationOptions,
    token: CancellationToken,
    sensitive_values: Sequence[str],
    on_event: MangaEventHandler | None,
    total: int,
) -> MangaPageTranslation:
    logs: list[str] = []
    for attempt in range(1, options.max_retries + 2):
        if token.cancelled:
            error = ErrorRecord(ErrorCode.CANCELLED, "Translation was cancelled")
            logs.append(f"page cancelled after {attempt - 1} attempt(s)")
            _emit(
                on_event,
                TranslationEvent(
                    EventKind.CANCELLED,
                    0,
                    total,
                    page_id=page.page_id,
                    attempt=attempt - 1,
                    error=error,
                ),
            )
            return MangaPageTranslation(
                page_id=page.page_id,
                order=page.order,
                name=page.name,
                status=TranslationStatus.CANCELLED,
                attempts=attempt - 1,
                logs=tuple(logs),
                error=error,
            )
        try:
            response = adapter.translate_image(
                image=image,
                filename=page.name,
                source_language=options.source_language,
                target_language=options.target_language,
            )
            if not isinstance(response, MangaAdapterResult):
                response = cast(MangaAdapterResult, response)
            media_type = _validate_image(response.image, media_type=response.media_type)
            sanitized = normalize_json_object(redact(response.raw_metadata, sensitive_values))
            adapter_logs = tuple(
                redact_text(item, sensitive_values)
                if isinstance(item, str)
                else f"<{type(item).__name__}>"
                for item in response.logs
            )
            logs.extend(adapter_logs)
            logs.append(f"page translated on attempt {attempt}")
            translated = MangaPageTranslation(
                page_id=page.page_id,
                order=page.order,
                name=page.name,
                status=TranslationStatus.SUCCEEDED,
                media_type=media_type,
                image=response.image,
                attempts=attempt,
                raw_result=sanitized,
                logs=tuple(logs),
            )
        except Exception as exc:
            error = _manga_error(exc, sensitive_values)
            if not error.retryable or attempt > options.max_retries:
                logs.append(f"page failed on attempt {attempt}: {error.code.value}")
                _emit(
                    on_event,
                    TranslationEvent(
                        EventKind.FAILED,
                        0,
                        total,
                        page_id=page.page_id,
                        attempt=attempt,
                        error=error,
                    ),
                )
                return MangaPageTranslation(
                    page_id=page.page_id,
                    order=page.order,
                    name=page.name,
                    status=TranslationStatus.FAILED,
                    attempts=attempt,
                    logs=tuple(logs),
                    error=error,
                )
            logs.append(f"page retry after {error.code.value}")
            _emit(
                on_event,
                TranslationEvent(
                    EventKind.RETRY,
                    0,
                    total,
                    page_id=page.page_id,
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
                page_id=page.page_id,
                attempt=attempt,
            ),
        )
        return translated
    raise AssertionError("unreachable")


def _validated_manga_source(
    source: SourceInput,
    manifest: MangaManifest | None,
    *,
    filename: str | None,
    archive_limits: ArchiveLimits | None,
    maximum_bytes: int,
) -> tuple[bytes, MangaManifest]:
    payload = read_source_bytes(source, maximum_bytes=maximum_bytes)
    inspected = inspect_manga(
        payload,
        filename=filename or (manifest.filename if manifest else None),
        archive_limits=archive_limits,
        maximum_bytes=maximum_bytes,
    )
    if manifest is not None and (
        manifest.schema_version != inspected.schema_version
        or manifest.source_format is not inspected.source_format
        or manifest.source_sha256 != inspected.source_sha256
        or manifest.source_size != inspected.source_size
        or manifest.pages != inspected.pages
    ):
        raise LinguaError(
            ErrorCode.SOURCE_MISMATCH,
            "Manga source does not match the supplied canonical manifest",
        )
    return payload, inspected


def _page_payloads(payload: bytes, manifest: MangaManifest) -> tuple[bytes, ...]:
    pages: tuple[bytes, ...]
    if manifest.source_format is SourceFormat.IMAGE:
        pages = (payload,)
    else:
        try:
            with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
                pages = tuple(
                    archive.read(cast(str, page.archive_member)) for page in manifest.pages
                )
        except (KeyError, zipfile.BadZipFile) as exc:
            raise LinguaError(
                ErrorCode.SOURCE_MISMATCH,
                "Manga source no longer matches its page manifest",
            ) from exc
    for page, image in zip(manifest.pages, pages, strict=True):
        if hashlib.sha256(image).hexdigest() != page.source_sha256:
            raise LinguaError(
                ErrorCode.SOURCE_MISMATCH,
                "Manga page no longer matches its manifest",
                {"page_id": page.page_id},
            )
    return pages


def _safe_member_name(name: str, maximum_depth: int) -> str:
    if not name or "\x00" in name or "\\" in name:
        raise LinguaError(ErrorCode.ARCHIVE_UNSAFE, "Manga archive has an unsafe member path")
    parts = name.rstrip("/").split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise LinguaError(ErrorCode.ARCHIVE_UNSAFE, "Manga archive has an unsafe member path")
    path = PurePosixPath(name)
    if len(parts) > maximum_depth:
        raise LinguaError(
            ErrorCode.ARCHIVE_LIMIT_EXCEEDED,
            "Manga archive member exceeds the configured path depth",
            {"member": name, "depth": len(parts), "limit": maximum_depth},
        )
    if path.is_absolute() or ":" in parts[0]:
        raise LinguaError(ErrorCode.ARCHIVE_UNSAFE, "Manga archive has an unsafe member path")
    if any(any(ord(character) < 0x20 for character in part) for part in parts):
        raise LinguaError(ErrorCode.ARCHIVE_UNSAFE, "Manga archive has an unsafe member path")
    return str(path)


def _validate_image(
    payload: bytes,
    *,
    suffix: str | None = None,
    media_type: str | None = None,
) -> str:
    detected: str | None = None
    if _is_valid_png(payload):
        detected = "image/png"
    elif _is_valid_jpeg(payload):
        detected = "image/jpeg"
    elif _is_valid_webp(payload):
        detected = "image/webp"
    if detected is None:
        raise LinguaError(ErrorCode.INVALID_FORMAT, "Manga page is not a supported valid image")
    expected = media_type.split(";", 1)[0].casefold() if media_type else None
    if expected and expected not in {detected, "application/octet-stream"}:
        raise LinguaError(
            ErrorCode.OUTPUT_MISSING,
            "Manga Adapter media type does not match its image output",
        )
    if suffix and suffix in _IMAGE_SUFFIXES and _IMAGE_SUFFIXES[suffix] != detected:
        raise LinguaError(ErrorCode.INVALID_FORMAT, "Manga image extension does not match content")
    return detected


def _is_valid_png(payload: bytes) -> bool:
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    offset = 8
    seen_ihdr = False
    seen_idat = False
    while offset + 12 <= len(payload):
        length = int.from_bytes(payload[offset : offset + 4], "big")
        kind = payload[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if data_end < data_start or crc_end > len(payload):
            return False
        expected_crc = int.from_bytes(payload[data_end:crc_end], "big")
        if zlib.crc32(kind + payload[data_start:data_end]) & 0xFFFFFFFF != expected_crc:
            return False
        if not seen_ihdr:
            if kind != b"IHDR" or length != 13:
                return False
            width = int.from_bytes(payload[data_start : data_start + 4], "big")
            height = int.from_bytes(payload[data_start + 4 : data_start + 8], "big")
            bit_depth = payload[data_start + 8]
            color_type = payload[data_start + 9]
            if (
                width == 0
                or height == 0
                or bit_depth not in {1, 2, 4, 8, 16}
                or color_type not in {0, 2, 3, 4, 6}
                or payload[data_start + 10 : data_start + 12] != b"\x00\x00"
                or payload[data_start + 12] not in {0, 1}
            ):
                return False
            seen_ihdr = True
        elif kind == b"IHDR":
            return False
        elif kind == b"IDAT":
            seen_idat = True
        elif kind == b"IEND":
            return length == 0 and seen_idat and crc_end == len(payload)
        offset = crc_end
    return False


def _is_valid_jpeg(payload: bytes) -> bool:
    if len(payload) < 12 or not payload.startswith(b"\xff\xd8"):
        return False
    position = 2
    saw_frame = False
    saw_scan = False
    frame_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    while position < len(payload):
        if payload[position] != 0xFF:
            if not saw_scan:
                return False
            next_marker = payload.find(b"\xff", position)
            if next_marker < 0:
                return False
            position = next_marker
        while position < len(payload) and payload[position] == 0xFF:
            position += 1
        if position >= len(payload):
            return False
        marker = payload[position]
        position += 1
        if marker == 0x00:
            if not saw_scan:
                return False
            continue
        if marker == 0xD9:
            return saw_frame and saw_scan and position == len(payload)
        if marker in range(0xD0, 0xD8):
            if not saw_scan:
                return False
            continue
        if marker in {0x01, 0xD8}:
            continue
        if position + 2 > len(payload):
            return False
        length = int.from_bytes(payload[position : position + 2], "big")
        if length < 2 or position + length > len(payload):
            return False
        segment_start = position + 2
        segment_end = position + length
        if marker in frame_markers:
            if length < 8:
                return False
            height = int.from_bytes(payload[segment_start + 1 : segment_start + 3], "big")
            width = int.from_bytes(payload[segment_start + 3 : segment_start + 5], "big")
            if width == 0 or height == 0:
                return False
            saw_frame = True
        elif marker == 0xDA:
            if length < 6 or not saw_frame:
                return False
            saw_scan = True
        position = segment_end
    return False


def _is_valid_webp(payload: bytes) -> bool:
    if (
        len(payload) < 20
        or not payload.startswith(b"RIFF")
        or payload[8:12] != b"WEBP"
        or int.from_bytes(payload[4:8], "little") != len(payload) - 8
    ):
        return False
    position = 12
    saw_image = False
    while position + 8 <= len(payload):
        kind = payload[position : position + 4]
        length = int.from_bytes(payload[position + 4 : position + 8], "little")
        data_start = position + 8
        data_end = data_start + length
        padded_end = data_end + (length % 2)
        if data_end < data_start or padded_end > len(payload):
            return False
        chunk = payload[data_start:data_end]
        if kind == b"VP8 ":
            if length < 10 or chunk[3:6] != b"\x9d\x01\x2a":
                return False
            saw_image = True
        elif kind == b"VP8L":
            if length < 5 or chunk[0] != 0x2F:
                return False
            saw_image = True
        elif kind == b"ANMF":
            if length < 16:
                return False
            saw_image = True
        position = padded_end
    return saw_image and position == len(payload)


def _page_id(source_sha256: str, name: str, page_sha256: str) -> str:
    return hashlib.sha256(
        f"manga-page.v1\0{source_sha256}\0{name}\0{page_sha256}".encode()
    ).hexdigest()


def _natural_key(value: str) -> tuple[object, ...]:
    return tuple(
        int(part) if part.isdigit() else unicodedata.normalize("NFC", part).casefold()
        for part in re.split(r"(\d+)", value)
    )


def _suffix_for_media(media_type: str) -> str:
    return {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(
        media_type.casefold(), ".img"
    )


def _manga_error(exc: Exception, sensitive_values: Sequence[str]) -> ErrorRecord:
    if isinstance(exc, LinguaError):
        details = normalize_json_object(redact(exc.details or {}, sensitive_values))
        return ErrorRecord(
            exc.code,
            redact_text(exc.message, sensitive_values),
            details,
            exc.retryable,
        )
    return ErrorRecord(
        ErrorCode.UNKNOWN,
        "Manga Adapter failed unexpectedly",
        {"exception_type": type(exc).__name__},
    )


def _manga_status(results: Sequence[MangaPageTranslation]) -> BatchStatus:
    succeeded = sum(page.status is TranslationStatus.SUCCEEDED for page in results)
    cancelled = sum(page.status is TranslationStatus.CANCELLED for page in results)
    failed = sum(page.status is TranslationStatus.FAILED for page in results)
    if succeeded == len(results):
        return BatchStatus.SUCCEEDED
    if succeeded:
        return BatchStatus.PARTIALLY_SUCCEEDED
    if cancelled and not failed:
        return BatchStatus.CANCELLED
    return BatchStatus.FAILED


def _emit(handler: MangaEventHandler | None, event: TranslationEvent) -> None:
    if handler is not None:
        handler(event)


__all__ = [
    "build_manga_output",
    "extract_manga_pages",
    "inspect_manga",
    "translate_manga",
]
