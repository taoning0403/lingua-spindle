"""Canonical request fingerprints and secret-safe idempotency metadata.

This module belongs to the optional service/runtime layer.  It intentionally has no
FastAPI, SQLAlchemy, environment, filesystem, or pure-core dependency.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any

from .errors import ErrorCode, LinguaError
from .json_types import normalize_json

_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass(frozen=True, slots=True)
class IdempotencyContext:
    """A validated request identity with the caller key irreversibly hashed."""

    key_hash: str
    request_id: str


@dataclass(frozen=True, slots=True)
class ServiceOperationResult:
    """Application result metadata needed by HTTP without changing direct-call payloads."""

    value: dict[str, Any]
    replayed: bool = False
    coalesced: bool = False


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    """A durable processing record owned by the current operation."""

    record_id: str
    scope: str
    request_fingerprint: str
    request_id: str


@dataclass(frozen=True, slots=True)
class IdempotencyReplay:
    """Safe resource reference retained by a completed idempotency record."""

    record_id: str
    resource_type: str
    resource_id: str
    response_status: int
    result_reference: dict[str, Any]


def normalize_request_id(value: str | None) -> str:
    """Return a log-safe caller request ID or a generated UUID."""

    if value is not None:
        candidate = value.strip()
        if _REQUEST_ID.fullmatch(candidate):
            return candidate
    return str(uuid.uuid4())


def idempotency_context(
    key: str | None,
    *,
    request_id: str,
    required: bool,
) -> IdempotencyContext | None:
    """Validate the HTTP key and discard its raw value after hashing."""

    if key is None or key == "":
        if required:
            raise LinguaError(
                ErrorCode.IDEMPOTENCY_KEY_REQUIRED,
                "A valid Idempotency-Key header is required for this operation",
            )
        return None
    if not _IDEMPOTENCY_KEY.fullmatch(key):
        raise LinguaError(
            ErrorCode.IDEMPOTENCY_KEY_INVALID,
            "Idempotency-Key must be 8-128 characters using letters, numbers, dot, "
            "underscore, colon, or hyphen",
        )
    return IdempotencyContext(
        key_hash=hashlib.sha256(key.encode("utf-8")).hexdigest(),
        request_id=request_id,
    )


def _canonicalize(value: Any) -> Any:
    normalized = normalize_json(value)
    if isinstance(normalized, str):
        normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
        return unicodedata.normalize("NFC", normalized)
    if isinstance(normalized, list):
        return [_canonicalize(item) for item in normalized]
    if isinstance(normalized, dict):
        return {str(key): _canonicalize(item) for key, item in normalized.items()}
    return normalized


def canonical_json(value: Any) -> str:
    """Serialize normalized JSON deterministically for versioned fingerprints."""

    return json.dumps(
        _canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def request_fingerprint(namespace: str, payload: Any, *, version: int = 1) -> str:
    """Return a versioned SHA-256 fingerprint without retaining request content."""

    canonical = canonical_json(
        {
            "fingerprint_schema": f"{namespace}.v{version}",
            "payload": payload,
        }
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{namespace}.v{version}:{digest}"


def normalized_text(value: str, *, strip: bool = False) -> str:
    candidate = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    return candidate.strip() if strip else candidate


def normalized_text_mapping_hash(values: dict[str, str]) -> str:
    """Hash caller text without storing the text in the idempotency table."""

    canonical = canonical_json(
        {str(key): normalized_text(value) for key, value in sorted(values.items())}
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
