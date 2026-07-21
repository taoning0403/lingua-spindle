"""Explicit resource limits shared by pure archive processors.

The defaults match the v0.2 runtime limits, but the core never reads process
configuration.  Callers that need different bounds pass an ``ArchiveLimits``
instance for the current operation.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    """Bounds applied while reading EPUB and comic archives."""

    max_files: int = 2_000
    max_uncompressed_bytes: int = 1_000 * 1024 * 1024
    max_member_bytes: int = 100 * 1024 * 1024
    max_compression_ratio: float = 100.0
    max_path_depth: int = 20

    def __post_init__(self) -> None:
        values = {
            "max_files": self.max_files,
            "max_uncompressed_bytes": self.max_uncompressed_bytes,
            "max_member_bytes": self.max_member_bytes,
            "max_compression_ratio": self.max_compression_ratio,
            "max_path_depth": self.max_path_depth,
        }
        invalid = [
            name
            for name, value in values.items()
            if value <= 0 or (isinstance(value, float) and not math.isfinite(value))
        ]
        if invalid:
            names = ", ".join(sorted(invalid))
            raise ValueError(f"Archive limits must be positive: {names}")

    def to_dict(self) -> dict[str, int | float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, int | float]) -> ArchiveLimits:
        return cls(
            max_files=int(value.get("max_files", 2_000)),
            max_uncompressed_bytes=int(value.get("max_uncompressed_bytes", 1_000 * 1024 * 1024)),
            max_member_bytes=int(value.get("max_member_bytes", 100 * 1024 * 1024)),
            max_compression_ratio=float(value.get("max_compression_ratio", 100.0)),
            max_path_depth=int(value.get("max_path_depth", 20)),
        )


__all__ = ["ArchiveLimits"]
