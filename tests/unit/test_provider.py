from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from linguaspindle.errors import ErrorCode, LinguaError
from linguaspindle.providers.base import TranslationRequest
from linguaspindle.providers.openai_compatible import (
    OpenAICompatibleProvider,
    OpenAIProviderConfig,
)


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


def _provider(**changes) -> OpenAICompatibleProvider:
    config = OpenAIProviderConfig(
        api_key=changes.pop("api_key", "sk-runtime-secret"),
        base_url=changes.pop("base_url", "https://provider.example/v1"),
        model=changes.pop("model", "model-v1"),
        **changes,
    )
    return OpenAICompatibleProvider(config)


def _mock_client(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    real_client = httpx.Client

    def factory(*, timeout: float) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr(httpx, "Client", factory)


def test_success_maps_usage_and_sends_caller_runtime_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
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

    _mock_client(monkeypatch, handler)
    result = _provider().translate(_request())

    assert result.text == "Bonjour"
    assert result.model == "model-v2"
    assert result.usage == {
        "prompt_tokens": 12,
        "completion_tokens": 3,
        "total_tokens": 15,
    }
    assert len(requests) == 1
    assert requests[0].headers["authorization"] == "Bearer sk-runtime-secret"
    assert requests[0].url == "https://provider.example/v1/chat/completions"


def test_rate_limit_is_retryable_without_a_hidden_provider_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, text="retry later")

    _mock_client(monkeypatch, handler)
    with pytest.raises(LinguaError) as caught:
        _provider().translate(_request())
    assert caught.value.code == ErrorCode.RATE_LIMIT
    assert caught.value.retryable is True
    assert attempts == 1


def test_timeout_is_normalized_for_core_owned_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    _mock_client(monkeypatch, handler)
    with pytest.raises(LinguaError) as caught:
        _provider().translate(_request())
    assert caught.value.code == ErrorCode.TIMEOUT
    assert caught.value.retryable is True
    assert attempts == 1


def test_rejected_response_redacts_runtime_key(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="api_key=sk-runtime-secret rejected")

    _mock_client(monkeypatch, handler)
    with pytest.raises(LinguaError) as caught:
        _provider().translate(_request())
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
def test_invalid_provider_output_is_normalized(monkeypatch: pytest.MonkeyPatch, body: dict) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    _mock_client(monkeypatch, handler)
    with pytest.raises(LinguaError) as caught:
        _provider().translate(_request())
    assert caught.value.code == ErrorCode.OUTPUT_MISSING


def test_missing_runtime_key_fails_without_an_http_request() -> None:
    provider = OpenAICompatibleProvider(
        OpenAIProviderConfig(api_key=None, base_url="https://provider.example/v1")
    )
    with pytest.raises(LinguaError) as caught:
        provider.translate(_request())
    assert caught.value.code == ErrorCode.CONFIGURATION


@pytest.mark.parametrize("reserved_field", ["model", "messages"])
def test_reserved_model_parameters_are_rejected_without_an_http_request(
    monkeypatch: pytest.MonkeyPatch,
    reserved_field: str,
) -> None:
    def unexpected_request(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("reserved fields must fail before the HTTP boundary")

    _mock_client(monkeypatch, unexpected_request)
    base = _request()
    request = TranslationRequest(
        text=base.text,
        source_language=base.source_language,
        target_language=base.target_language,
        style=base.style,
        prompt_template=base.prompt_template,
        prompt_version=base.prompt_version,
        model_parameters={reserved_field: "caller-controlled"},
    )

    with pytest.raises(LinguaError) as caught:
        _provider().translate(request)

    assert caught.value.code is ErrorCode.CONFIGURATION
    assert caught.value.details == {"reserved_fields": [reserved_field]}


def test_key_resolver_is_called_once_per_translation(monkeypatch: pytest.MonkeyPatch) -> None:
    resolver_calls = 0

    def resolve_key() -> str:
        nonlocal resolver_calls
        resolver_calls += 1
        return "sk-resolved-once"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk-resolved-once"
        return httpx.Response(
            200,
            json={
                "model": "model-v1",
                "choices": [{"message": {"content": "Bonjour"}}],
            },
        )

    _mock_client(monkeypatch, handler)
    provider = _provider(api_key=None, api_key_resolver=resolve_key)

    assert provider.translate(_request()).text == "Bonjour"
    assert resolver_calls == 1


@pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
def test_provider_config_rejects_non_finite_timeout(non_finite: float) -> None:
    with pytest.raises(ValueError):
        OpenAIProviderConfig(timeout_seconds=non_finite)
