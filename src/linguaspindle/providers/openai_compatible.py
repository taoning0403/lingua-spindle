"""Optional HTTPX OpenAI-compatible Chat Completions Provider."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

try:
    import httpx
except ModuleNotFoundError as exc:  # pragma: no cover - exercised in isolated Wheel checks
    raise ModuleNotFoundError(
        "OpenAI-compatible support is optional; install 'linguaspindle[openai]'",
        name="httpx",
    ) from exc

from ..errors import ErrorCode, LinguaError
from ..security import redact
from .base import TranslationProvider, TranslationRequest, TranslationResult


class _LegacyOpenAISettings(Protocol):
    openai_base_url: str
    openai_model: str
    openai_timeout_seconds: float
    openai_api_key: str | None


@dataclass(frozen=True, slots=True)
class OpenAIProviderConfig:
    """Explicit endpoint policy and caller-supplied key source."""

    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4.1-mini"
    timeout_seconds: float = 60.0
    api_key: str | None = field(default=None, repr=False)
    api_key_resolver: Callable[[], str | None] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        candidate = self.base_url.strip().rstrip("/")
        parsed = urlsplit(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("OpenAI-compatible base_url must be an HTTP(S) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("OpenAI-compatible base_url cannot contain credentials or query data")
        if not self.model.strip():
            raise ValueError("OpenAI-compatible model cannot be empty")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("OpenAI-compatible timeout must be positive")
        if self.api_key is not None and self.api_key_resolver is not None:
            raise ValueError("Pass api_key or api_key_resolver, not both")

    def resolve_key(self) -> str | None:
        return self.api_key_resolver() if self.api_key_resolver is not None else self.api_key


class OpenAICompatibleProvider(TranslationProvider):
    id = "openai-compatible"
    display_name = "OpenAI-compatible Provider"

    def __init__(self, config: OpenAIProviderConfig | object):
        if isinstance(config, OpenAIProviderConfig):
            self.config = config
        else:
            # Forward-compatible v0.2 runtime bridge. The optional Provider
            # does not import or expose the former global Settings type.
            legacy = cast(_LegacyOpenAISettings, config)
            self.config = OpenAIProviderConfig(
                base_url=legacy.openai_base_url,
                model=legacy.openai_model,
                timeout_seconds=legacy.openai_timeout_seconds,
                api_key=legacy.openai_api_key,
            )

    def configured(self) -> bool:
        return bool(self.config.resolve_key() and self.config.base_url)

    def public_status(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "configured": self.configured(),
            "base_url": self.config.base_url,
            "model": self.config.model,
            "timeout_seconds": self.config.timeout_seconds,
            "secret_source": "caller_runtime",
        }

    def translate(self, request: TranslationRequest) -> TranslationResult:
        api_key = self.config.resolve_key()
        if not api_key:
            raise LinguaError(
                ErrorCode.CONFIGURATION,
                "OpenAI-compatible Provider is not configured; set the runtime API key",
            )
        model_parameters = request.model_parameters or {}
        reserved = sorted({"messages", "model"} & set(model_parameters))
        if reserved:
            raise LinguaError(
                ErrorCode.CONFIGURATION,
                "OpenAI-compatible model parameters contain reserved fields",
                {"reserved_fields": reserved},
            )
        payload = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a literary translator. Return only the translation.",
                },
                {"role": "user", "content": request.prompt()},
            ],
            **model_parameters,
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        endpoint = f"{self.config.base_url.rstrip('/')}/chat/completions"
        try:
            with httpx.Client(timeout=self.config.timeout_seconds) as client:
                response = client.post(endpoint, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LinguaError(
                ErrorCode.TIMEOUT,
                "Translation Provider request timed out",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise LinguaError(
                ErrorCode.MODEL_API,
                "Translation Provider could not be reached",
                {"reason": type(exc).__name__},
                retryable=True,
            ) from exc
        if response.status_code == 429:
            raise LinguaError(
                ErrorCode.RATE_LIMIT,
                "Translation Provider rate limit reached",
                {"status_code": 429},
                retryable=True,
            )
        if response.status_code >= 500:
            raise LinguaError(
                ErrorCode.MODEL_API,
                "Translation Provider returned a server error",
                {"status_code": response.status_code},
                retryable=True,
            )
        if response.status_code >= 400:
            details = redact(
                {"status_code": response.status_code, "body": response.text[:500]},
                [api_key or ""],
            )
            raise LinguaError(
                ErrorCode.MODEL_API,
                "Translation Provider rejected the request",
                details,
                retryable=False,
            )
        try:
            body = response.json()
            text = body["choices"][0]["message"]["content"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("empty translation")
            model = str(body.get("model") or self.config.model)
            raw_usage = body.get("usage")
            usage = None
            if isinstance(raw_usage, dict):
                normalized_usage = {
                    name: value
                    for name in ("prompt_tokens", "completion_tokens", "total_tokens")
                    if isinstance((value := raw_usage.get(name)), int)
                    and not isinstance(value, bool)
                    and value >= 0
                }
                usage = normalized_usage or None
            return TranslationResult(text=text.strip(), model=model, usage=usage)
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise LinguaError(
                ErrorCode.OUTPUT_MISSING,
                "Translation Provider returned an invalid response",
                retryable=True,
            ) from exc


__all__ = ["OpenAICompatibleProvider", "OpenAIProviderConfig"]
