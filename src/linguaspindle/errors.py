"""Stable error vocabulary shared by every interface."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .json_types import normalize_json_object


class ErrorCode(StrEnum):
    CONFIGURATION = "CONFIGURATION_ERROR"
    UPLOAD_TOO_LARGE = "UPLOAD_TOO_LARGE"
    ARCHIVE_UNSAFE = "ARCHIVE_UNSAFE"
    ARCHIVE_LIMIT_EXCEEDED = "ARCHIVE_LIMIT_EXCEEDED"
    EPUB_INVALID = "EPUB_INVALID"
    EPUB_UNSUPPORTED = "EPUB_UNSUPPORTED"
    EPUB_PROTECTED = "EPUB_PROTECTED"
    EPUB_VALIDATION_FAILED = "EPUB_VALIDATION_FAILED"
    SOURCE_MISMATCH = "SOURCE_MISMATCH"
    SEGMENT_NOT_FOUND = "SEGMENT_NOT_FOUND"
    IDEMPOTENCY_KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"
    IDEMPOTENCY_KEY_INVALID = "IDEMPOTENCY_KEY_INVALID"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    IDEMPOTENCY_IN_PROGRESS = "IDEMPOTENCY_IN_PROGRESS"
    IDEMPOTENCY_INDETERMINATE = "IDEMPOTENCY_INDETERMINATE"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    ADAPTER_UNAVAILABLE = "ADAPTER_UNAVAILABLE"
    EXTERNAL_COMMAND = "EXTERNAL_COMMAND_FAILED"
    TIMEOUT = "TIMEOUT"
    INVALID_FORMAT = "INVALID_FORMAT"
    MODEL_API = "MODEL_API_ERROR"
    RATE_LIMIT = "RATE_LIMITED"
    CANCELLED = "TASK_CANCELLED"
    OUTPUT_MISSING = "OUTPUT_MISSING"
    NOT_FOUND = "NOT_FOUND"
    INVALID_STATE = "INVALID_STATE"
    PROCESS_INTERRUPTED = "PROCESS_INTERRUPTED"
    STORAGE = "STORAGE_ERROR"
    UNKNOWN = "UNKNOWN_ERROR"


@dataclass(slots=True)
class LinguaError(Exception):
    code: ErrorCode
    message: str
    details: dict[str, Any] | None = None
    retryable: bool = False

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, Any]:
        """Return the stable, JSON-compatible public error envelope."""

        return {
            "code": self.code.value,
            "message": self.message,
            "details": normalize_json_object(self.details or {}),
            "retryable": self.retryable,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> LinguaError:
        return cls(
            code=ErrorCode(str(value["code"])),
            message=str(value.get("message", "")),
            details=dict(value.get("details") or {}),
            retryable=bool(value.get("retryable", False)),
        )
