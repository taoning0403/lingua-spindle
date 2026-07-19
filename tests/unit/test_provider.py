from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from linguaspindle.config import Settings
from linguaspindle.errors import ErrorCode, LinguaError
from linguaspindle.providers.base import TranslationRequest
from linguaspindle.providers.openai_compatible import OpenAICompatibleProvider


def _request() -> TranslationRequest:
    return TranslationRequest(
        text="Hello",
        source_language="en",
        target_language="fr",
        style="literary",
        prompt_template="Translate {source_language} to {target_language}: {text} ({style})",
        prompt_version="v1",
        model_parameters={"temperature": 0},
    )


def _provider(tmp_path, **changes) -> OpenAICompatibleProvider:
    settings = Settings(
        data_dir=tmp_path / "data",
        openai_api_key="sk-runtime-secret",
        openai_base_url="https://provider.example/v1",
        openai_model="model-v1",
        openai_max_retries=changes.pop("openai_max_retries", 2),
        **changes,
    )
    return OpenAICompatibleProvider(settings)


def _mock_client(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    real_client = httpx.Client

    def factory(*, timeout: float) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr(httpx, "Client", factory)


def test_rate_limit_and_server_errors_retry_before_success(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses = [429, 503, 200]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        status = responses.pop(0)
        if status == 200:
            return httpx.Response(
                200,
                json={
                    "model": "model-v2",
                    "choices": [{"message": {"content": "Bonjour"}}],
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 3,
                        "total_tokens": 15,
                    },
                },
            )
        return httpx.Response(status, text="retry later")

    _mock_client(monkeypatch, handler)
    monkeypatch.setattr("linguaspindle.providers.openai_compatible.time.sleep", lambda _: None)
    result = _provider(tmp_path).translate(_request())

    assert result.text == "Bonjour"
    assert result.model == "model-v2"
    assert result.usage == {
        "prompt_tokens": 12,
        "completion_tokens": 3,
        "total_tokens": 15,
    }
    assert len(requests) == 3
    assert all(
        request.headers["authorization"] == "Bearer sk-runtime-secret" for request in requests
    )
    assert requests[-1].url == "https://provider.example/v1/chat/completions"


def test_timeout_is_normalized_after_bounded_retries(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    _mock_client(monkeypatch, handler)
    monkeypatch.setattr("linguaspindle.providers.openai_compatible.time.sleep", lambda _: None)
    with pytest.raises(LinguaError) as caught:
        _provider(tmp_path, openai_max_retries=1).translate(_request())
    assert caught.value.code == ErrorCode.TIMEOUT
    assert caught.value.retryable is True
    assert attempts == 2


def test_rejected_response_redacts_runtime_key(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="api_key=sk-runtime-secret rejected")

    _mock_client(monkeypatch, handler)
    with pytest.raises(LinguaError) as caught:
        _provider(tmp_path).translate(_request())
    assert caught.value.code == ErrorCode.MODEL_API
    assert caught.value.retryable is False
    assert "sk-runtime-secret" not in str(caught.value.details)
    assert "[REDACTED]" in str(caught.value.details)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {"content": ""}}]},
    ],
)
def test_invalid_provider_output_is_normalized(
    tmp_path, monkeypatch: pytest.MonkeyPatch, body: dict
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    _mock_client(monkeypatch, handler)
    monkeypatch.setattr("linguaspindle.providers.openai_compatible.time.sleep", lambda _: None)
    with pytest.raises(LinguaError) as caught:
        _provider(tmp_path, openai_max_retries=0).translate(_request())
    assert caught.value.code == ErrorCode.OUTPUT_MISSING


def test_missing_runtime_key_fails_without_an_http_request(tmp_path) -> None:
    provider = OpenAICompatibleProvider(
        Settings(
            data_dir=tmp_path / "data",
            openai_api_key=None,
            openai_base_url="https://provider.example/v1",
        )
    )
    with pytest.raises(LinguaError) as caught:
        provider.translate(_request())
    assert caught.value.code == ErrorCode.CONFIGURATION
