from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from linguaspindle.application import ApplicationService
from linguaspindle.config import Settings


@pytest.fixture(autouse=True)
def isolated_runtime_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        if name.startswith("LINGUASPINDLE_"):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture
def service(tmp_path) -> Iterator[ApplicationService]:
    instance = ApplicationService(Settings.from_env(tmp_path / "data"))
    try:
        yield instance
    finally:
        instance.close()
