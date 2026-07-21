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


def redact(
    value: Any,
    known_secrets: Sequence[str] = (),
    *,
    _seen: set[int] | None = None,
) -> Any:
    if isinstance(value, str):
        return redact_text(value, known_secrets)
    seen = _seen if _seen is not None else set()
    identity = id(value)
    if identity in seen:
        return "<recursive-reference>"
    if isinstance(value, Mapping):
        seen.add(identity)
        try:
            result: dict[str, Any] = {}
            for key, item in value.items():
                normalized_key = key if isinstance(key, str) else f"<{type(key).__name__}>"
                result[normalized_key] = (
                    "[REDACTED]"
                    if _SENSITIVE_KEY.search(normalized_key)
                    else redact(item, known_secrets, _seen=seen)
                )
            return result
        except Exception:
            return {"unsupported_type": type(value).__name__}
        finally:
            seen.discard(identity)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        seen.add(identity)
        try:
            return [redact(item, known_secrets, _seen=seen) for item in value]
        except Exception:
            return [{"unsupported_type": type(value).__name__}]
        finally:
            seen.discard(identity)
    return value


def collect_sensitive_values(value: Any, *, _seen: set[int] | None = None) -> tuple[str, ...]:
    """Collect string values stored beneath secret-shaped mapping keys."""

    seen = _seen if _seen is not None else set()
    identity = id(value)
    if identity in seen:
        return ()
    if isinstance(value, Mapping):
        seen.add(identity)
        try:
            collected: list[str] = []
            for key, item in value.items():
                key_text = key if isinstance(key, str) else f"<{type(key).__name__}>"
                if _SENSITIVE_KEY.search(key_text):
                    collected.extend(_string_leaves(item, seen))
                else:
                    collected.extend(collect_sensitive_values(item, _seen=seen))
            return tuple(dict.fromkeys(collected))
        finally:
            seen.discard(identity)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        seen.add(identity)
        try:
            collected = [
                item for nested in value for item in collect_sensitive_values(nested, _seen=seen)
            ]
            return tuple(dict.fromkeys(collected))
        finally:
            seen.discard(identity)
    return ()


def _string_leaves(value: Any, seen: set[int]) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    identity = id(value)
    if identity in seen:
        return []
    if isinstance(value, Mapping):
        seen.add(identity)
        try:
            return [item for nested in value.values() for item in _string_leaves(nested, seen)]
        finally:
            seen.discard(identity)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        seen.add(identity)
        try:
            return [item for nested in value for item in _string_leaves(nested, seen)]
        finally:
            seen.discard(identity)
    return []


__all__ = ["collect_sensitive_values", "redact", "redact_text"]
