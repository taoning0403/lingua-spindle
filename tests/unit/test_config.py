from __future__ import annotations

import pytest

from linguaspindle.config import ConfigurationError, Settings


def test_defaults_are_loopback_local_and_runtime_secret_is_not_repr(tmp_path) -> None:
    settings = Settings.from_env(tmp_path / "data")
    assert settings.host == "127.0.0.1"
    assert settings.port == 8765
    assert settings.openai_api_key is None
    assert settings.data_dir == (tmp_path / "data").resolve()

    settings.openai_api_key = "sk-repr-secret"
    assert "sk-repr-secret" not in repr(settings)
    settings.ensure_directories()
    assert settings.database_dir.is_dir()
    assert settings.artifacts_dir.is_dir()
    assert settings.exports_dir.is_dir()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("LINGUASPINDLE_PORT", "0"),
        ("LINGUASPINDLE_PORT", "65536"),
        ("LINGUASPINDLE_OPENAI_CONCURRENCY", "not-an-int"),
        ("LINGUASPINDLE_WORKER_POLL_SECONDS", "nan"),
        ("LINGUASPINDLE_OPENAI_TIMEOUT_SECONDS", "inf"),
        ("LINGUASPINDLE_LOG_LEVEL", "verbose"),
        ("LINGUASPINDLE_OPENAI_MODEL", "   "),
    ],
)
def test_invalid_scalar_configuration_is_rejected(
    tmp_path, monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigurationError):
        Settings.from_env(tmp_path / "data")


@pytest.mark.parametrize(
    "value",
    [
        "provider.example/v1",
        "ftp://provider.example/v1",
        "https://name:password@provider.example/v1",
        "https://provider.example/v1?api_key=secret",
        "https://provider.example/v1#fragment",
        "http://provider.example:99999/v1",
    ],
)
def test_unsafe_or_invalid_provider_urls_are_rejected(
    tmp_path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("LINGUASPINDLE_OPENAI_BASE_URL", value)
    with pytest.raises(ConfigurationError):
        Settings.from_env(tmp_path / "data")


@pytest.mark.parametrize("value", ["not-json", "[]", '"string"'])
def test_adapter_config_must_be_a_json_object(
    tmp_path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("LINGUASPINDLE_MIT_CONFIG_JSON", value)
    with pytest.raises(ConfigurationError):
        Settings.from_env(tmp_path / "data")


def test_valid_local_provider_and_adapter_urls_are_normalized(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LINGUASPINDLE_OPENAI_BASE_URL", "http://127.0.0.1:8080/v1/")
    monkeypatch.setenv("LINGUASPINDLE_MIT_BASE_URL", "http://localhost:5003/")
    settings = Settings.from_env(tmp_path / "data")
    assert settings.openai_base_url == "http://127.0.0.1:8080/v1"
    assert settings.mit_base_url == "http://localhost:5003"
