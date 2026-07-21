"""Small recursive JSON type aliases shared without importing public packages."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def normalize_json(value: object, *, _seen: set[int] | None = None) -> JsonValue:
    """Bound untrusted extension metadata to a strict, non-leaking JSON value."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else "<non-finite-float>"
    if isinstance(value, Enum):
        return normalize_json(value.value, _seen=_seen)
    if isinstance(value, (bytes, bytearray)):
        payload = bytes(value)
        return {
            "binary_size": len(payload),
            "binary_sha256": hashlib.sha256(payload).hexdigest(),
        }

    seen = _seen if _seen is not None else set()
    identity = id(value)
    if identity in seen:
        return "<recursive-reference>"
    if isinstance(value, Mapping):
        seen.add(identity)
        try:
            normalized: dict[str, JsonValue] = {}
            for key, item in value.items():
                normalized_key = key if isinstance(key, str) else f"<{type(key).__name__}>"
                normalized[normalized_key] = normalize_json(item, _seen=seen)
            return normalized
        except Exception:
            return {"unsupported_type": type(value).__name__}
        finally:
            seen.discard(identity)
    if isinstance(value, Sequence):
        seen.add(identity)
        try:
            return [normalize_json(item, _seen=seen) for item in value]
        except Exception:
            return [{"unsupported_type": type(value).__name__}]
        finally:
            seen.discard(identity)
    return {"unsupported_type": type(value).__name__}


def normalize_json_object(value: object) -> dict[str, JsonValue]:
    normalized = normalize_json(value)
    if isinstance(normalized, dict):
        return normalized
    return {"value": normalized}


__all__ = ["JsonScalar", "JsonValue", "normalize_json", "normalize_json_object"]
