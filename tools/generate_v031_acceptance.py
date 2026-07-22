#!/usr/bin/env python3
"""Generate deterministic v0.3.1 core acceptance samples in a caller-owned root."""

from __future__ import annotations

from collections.abc import Sequence

import generate_v030_acceptance as _generator

_generator.EXPECTED_VERSION = "0.3.1"


def main(argv: Sequence[str] | None = None) -> int:
    return _generator.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
