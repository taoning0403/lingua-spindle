#!/usr/bin/env python3
"""Verify every LinguaSpindle v0.3.1 Wheel extra in a fresh virtual environment."""

from __future__ import annotations

from collections.abc import Sequence

import verify_v030_extras as _verifier

_verifier.EXPECTED_VERSION = "0.3.1"


def main(argv: Sequence[str] | None = None) -> int:
    return _verifier.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
