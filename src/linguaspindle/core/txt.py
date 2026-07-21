"""Pure TXT inspection, deterministic segmentation, and reconstruction helpers."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from charset_normalizer import from_bytes

from ..errors import ErrorCode, LinguaError
from .models import (
    DocumentManifest,
    Segment,
    SegmentLocator,
    SourceFormat,
    TranslationOptions,
)

SEGMENTATION_VERSION = "txt-segmentation.v1"
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n+")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？.!?；;])\s+")
_BINARY_SIGNATURES = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"%PDF-",
    b"PK\x03\x04",
    b"\x1f\x8b",
    b"BM",
    b"II*\x00",
    b"MM\x00*",
    b"7z\xbc\xaf\x27\x1c",
    b"Rar!\x1a\x07",
    b"\x7fELF",
)


@dataclass(frozen=True, slots=True)
class DecodedText:
    text: str
    encoding: str
    confidence: float
    newline: str


def decode_txt(payload: bytes) -> DecodedText:
    """Detect and strictly decode text without consulting process configuration."""

    if not payload:
        raise LinguaError(ErrorCode.INVALID_FORMAT, "TXT source is empty")
    if payload.startswith(_BINARY_SIGNATURES) or (
        payload.startswith(b"RIFF") and payload[8:12] == b"WEBP"
    ):
        raise LinguaError(ErrorCode.INVALID_FORMAT, "TXT source appears to contain binary data")

    encoding: str
    confidence: float
    if payload.startswith(b"\xef\xbb\xbf"):
        encoding, confidence = "utf-8-sig", 1.0
    elif payload.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        encoding, confidence = "utf-32", 1.0
    elif payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding, confidence = "utf-16", 1.0
    else:
        try:
            payload.decode("utf-8", errors="strict")
            encoding, confidence = "utf-8", 1.0
        except UnicodeDecodeError:
            match = from_bytes(payload).best()
            if match is None or not match.encoding:
                raise LinguaError(
                    ErrorCode.INVALID_FORMAT,
                    "TXT source encoding could not be identified",
                ) from None
            encoding = match.encoding
            confidence = max(0.0, min(float(match.percent_coherence) / 100.0, 1.0))

    try:
        decoded = payload.decode(encoding, errors="strict")
    except (LookupError, UnicodeDecodeError) as exc:
        raise LinguaError(
            ErrorCode.INVALID_FORMAT,
            "TXT source could not be decoded with the detected encoding",
            {"encoding": encoding},
        ) from exc

    text = decoded.lstrip("\ufeff")
    disallowed = [
        character
        for character in text
        if (ord(character) < 0x20 and character not in "\n\r\t") or ord(character) == 0x7F
    ]
    if "\x00" in text or len(disallowed) > max(8, len(text) // 100):
        raise LinguaError(
            ErrorCode.INVALID_FORMAT,
            "TXT source appears to contain binary data",
        )
    if not text.strip():
        raise LinguaError(ErrorCode.INVALID_FORMAT, "TXT source contains no text")

    newline = _newline_style(text)
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return DecodedText(normalized, encoding, confidence, newline)


def _newline_style(text: str) -> str:
    crlf = text.count("\r\n")
    without_crlf = text.replace("\r\n", "")
    cr = without_crlf.count("\r")
    lf = without_crlf.count("\n")
    used = sum(value > 0 for value in (crlf, cr, lf))
    if used > 1:
        return "mixed"
    if crlf:
        return "crlf"
    if cr:
        return "cr"
    if lf:
        return "lf"
    return "none"


def inspect_txt_payload(
    payload: bytes,
    *,
    source_sha256: str,
    filename: str | None,
    options: TranslationOptions,
) -> DocumentManifest:
    decoded = decode_txt(payload)
    spans = _segment_spans(decoded.text, options.max_segment_chars)
    if not spans:
        raise LinguaError(ErrorCode.INVALID_FORMAT, "No translatable TXT segments were found")

    segments: list[Segment] = []
    for order, (start, end) in enumerate(spans):
        source_text = decoded.text[start:end]
        next_start = spans[order + 1][0] if order + 1 < len(spans) else len(decoded.text)
        joiner = decoded.text[end:next_start]
        source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        id_payload = (
            f"{SourceFormat.TXT.value}\0{SEGMENTATION_VERSION}\0{source_sha256}"
            f"\0{start}:{end}\0{source_hash}"
        )
        segment_id = hashlib.sha256(id_payload.encode("utf-8")).hexdigest()
        input_payload = {
            "segment_id": segment_id,
            "source_hash": source_hash,
            "source_language": options.source_language,
            "target_language": options.target_language,
            "style": options.style,
            "prompt_template": options.prompt_template,
            "prompt_version": options.prompt_version,
            "model_parameters": options.model_parameters,
        }
        translation_input_hash = hashlib.sha256(
            json.dumps(
                input_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        segments.append(
            Segment(
                segment_id=segment_id,
                order=order,
                source_format=SourceFormat.TXT,
                source_document="text",
                source_text=source_text,
                content_role=_content_role(source_text),
                locator=SegmentLocator(
                    kind="txt-span",
                    document_path="text",
                    start=start,
                    end=end,
                ),
                source_hash=source_hash,
                translation_input_hash=translation_input_hash,
                joiner=joiner,
            )
        )

    return DocumentManifest(
        source_format=SourceFormat.TXT,
        source_sha256=source_sha256,
        source_size=len(payload),
        filename=filename,
        encoding=decoded.encoding,
        encoding_confidence=decoded.confidence,
        newline=decoded.newline,
        segmentation_version=SEGMENTATION_VERSION,
        segments=tuple(segments),
        metadata={
            "normalized_characters": len(decoded.text),
            "segment_count": len(segments),
            "max_segment_chars": options.max_segment_chars,
            "output_encoding": "utf-8",
            "output_newline": "lf",
            "segmentation_rules": SEGMENTATION_VERSION,
        },
    )


def _content_role(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith(("“", "‘", '"', "「", "『", "—")):
        return "dialogue"
    if "\n" not in stripped and len(stripped) <= 100 and not re.search(r"[。！？.!?]$", stripped):
        return "heading"
    return "paragraph"


def _segment_spans(text: str, maximum_chars: int) -> list[tuple[int, int]]:
    blocks: list[tuple[int, int]] = []
    cursor = 0
    for separator in _PARAGRAPH_BREAK.finditer(text):
        blocks.extend(_split_block(text, cursor, separator.start(), maximum_chars))
        cursor = separator.end()
    blocks.extend(_split_block(text, cursor, len(text), maximum_chars))
    return blocks


def _split_block(text: str, start: int, end: int, maximum_chars: int) -> list[tuple[int, int]]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    spans: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        remaining = end - cursor
        if remaining <= maximum_chars:
            spans.append((cursor, end))
            break
        limit = cursor + maximum_chars
        window = text[cursor:limit]
        boundaries = list(_SENTENCE_BOUNDARY.finditer(window))
        cut = cursor + boundaries[-1].start() if boundaries else -1
        if cut <= cursor:
            whitespace = [match.start() for match in re.finditer(r"\s+", window)]
            cut = cursor + whitespace[-1] if whitespace else limit
        if cut <= cursor:
            cut = limit
        while cut > cursor and text[cut - 1].isspace():
            cut -= 1
        if cut <= cursor:
            cut = limit
        spans.append((cursor, cut))
        cursor = cut
        while cursor < end and text[cursor].isspace():
            cursor += 1
    return spans


def rebuild_txt(decoded: DecodedText, manifest: DocumentManifest, values: dict[str, str]) -> bytes:
    if manifest.source_format is not SourceFormat.TXT:
        raise LinguaError(ErrorCode.INVALID_FORMAT, "Manifest is not for TXT input")
    rebuilt = decoded.text
    replacements: list[tuple[int, int, str]] = []
    for segment in manifest.segments:
        start, end = segment.locator.start, segment.locator.end
        if start is None or end is None or start < 0 or end < start or end > len(rebuilt):
            raise LinguaError(ErrorCode.SOURCE_MISMATCH, "TXT Segment locator is invalid")
        if rebuilt[start:end] != segment.source_text:
            raise LinguaError(
                ErrorCode.SOURCE_MISMATCH,
                "TXT source no longer matches the inspected Segment manifest",
                {"segment_id": segment.segment_id},
            )
        translated = values.get(segment.segment_id)
        if translated is not None:
            replacements.append((start, end, translated))
    for start, end, translated in reversed(replacements):
        rebuilt = f"{rebuilt[:start]}{translated}{rebuilt[end:]}"
    return rebuilt.encode("utf-8")


__all__ = [
    "DecodedText",
    "SEGMENTATION_VERSION",
    "decode_txt",
    "inspect_txt_payload",
    "rebuild_txt",
]
