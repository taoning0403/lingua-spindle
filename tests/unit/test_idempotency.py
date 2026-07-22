from __future__ import annotations

import hashlib

import pytest

from linguaspindle.config import ConfigurationError, Settings
from linguaspindle.errors import ErrorCode, LinguaError
from linguaspindle.idempotency import (
    canonical_json,
    idempotency_context,
    normalize_request_id,
    request_fingerprint,
)


def test_idempotency_key_is_validated_then_discarded_after_hashing() -> None:
    raw_key = "novel-platform:high-entropy-key-0001"
    context = idempotency_context(raw_key, request_id="request-0001", required=True)

    assert context is not None
    assert context.key_hash == hashlib.sha256(raw_key.encode()).hexdigest()
    assert raw_key not in repr(context)

    with pytest.raises(LinguaError) as invalid:
        idempotency_context("bad key!", request_id="request-0001", required=False)
    assert invalid.value.code == ErrorCode.IDEMPOTENCY_KEY_INVALID

    with pytest.raises(LinguaError) as required:
        idempotency_context(None, request_id="request-0001", required=True)
    assert required.value.code == ErrorCode.IDEMPOTENCY_KEY_REQUIRED
    assert idempotency_context(None, request_id="request-0001", required=False) is None


def test_request_fingerprint_is_canonical_versioned_and_secret_opaque() -> None:
    first = request_fingerprint(
        "example",
        {"b": None, "a": "Cafe\u0301\r\n", "default": 2},
    )
    second = request_fingerprint(
        "example",
        {"default": 2, "a": "Café\n", "b": None},
    )

    assert first == second
    assert first.startswith("example.v1:")
    assert "Café" not in first
    assert canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'


def test_request_id_rejects_unsafe_values_without_echoing_them() -> None:
    assert normalize_request_id("caller-request_01") == "caller-request_01"
    generated = normalize_request_id("unsafe request value!")
    assert generated != "unsafe request value!"
    assert len(generated) == 36


def test_require_idempotency_environment_is_strict_boolean(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LINGUASPINDLE_REQUIRE_IDEMPOTENCY_KEY", "true")
    assert Settings.from_env(tmp_path / "required").require_idempotency_key is True

    monkeypatch.setenv("LINGUASPINDLE_REQUIRE_IDEMPOTENCY_KEY", "false")
    assert Settings.from_env(tmp_path / "optional").require_idempotency_key is False

    monkeypatch.setenv("LINGUASPINDLE_REQUIRE_IDEMPOTENCY_KEY", "sometimes")
    with pytest.raises(ConfigurationError):
        Settings.from_env(tmp_path / "invalid")
