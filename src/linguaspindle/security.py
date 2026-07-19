"""Redaction helpers for logs, diagnostics, and normalized errors."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_SENSITIVE_KEY = re.compile(
    r"(?:api[-_]?key|authorization|access[-_]?token|secret|password)", re.IGNORECASE
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_KEY_ASSIGNMENT = re.compile(
    r"(?i)(api[-_]?key|authorization|access[-_]?token|secret|password)(\s*[:=]\s*)([^\s,;]+)"
)


def redact_text(value: str, known_secrets: Sequence[str] = ()) -> str:
    redacted = _BEARER.sub("Bearer [REDACTED]", value)
    redacted = _KEY_ASSIGNMENT.sub(r"\1\2[REDACTED]", redacted)
    for secret in known_secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def redact(value: Any, known_secrets: Sequence[str] = ()) -> Any:
    if isinstance(value, str):
        return redact_text(value, known_secrets)
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]"
            if _SENSITIVE_KEY.search(str(key))
            else redact(item, known_secrets)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [redact(item, known_secrets) for item in value]
    return value
