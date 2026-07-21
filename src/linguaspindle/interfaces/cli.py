"""Dependency-light console entry point for the optional CLI.

Importing this module never imports Typer, the local SQLite runtime, or the
FastAPI server unconditionally.  Installed CLI environments still expose the
historical Typer ``app`` object for test and embedding compatibility.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from .. import __version__


def _missing_cli() -> int:
    if any(argument in {"--version", "version"} for argument in sys.argv[1:]):
        print(__version__)
        return 0
    print(
        "LinguaSpindle command-line support is not installed. "
        "Install the optional [cli] extra: pip install 'linguaspindle[cli]'",
        file=sys.stderr,
    )
    return 2


try:
    import typer as _typer  # noqa: F401
except ModuleNotFoundError:
    app: Callable[[], int | None] = _missing_cli
else:
    from ._typer_cli import app


if __name__ == "__main__":
    raise SystemExit(app())
