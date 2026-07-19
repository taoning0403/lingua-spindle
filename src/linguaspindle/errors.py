"""Stable error vocabulary shared by every interface."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    CONFIGURATION = "CONFIGURATION_ERROR"
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
