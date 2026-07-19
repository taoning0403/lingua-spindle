"""OpenAI-compatible Chat Completions Provider."""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from ..config import Settings
from ..errors import ErrorCode, LinguaError
from ..security import redact
from .base import TranslationProvider, TranslationRequest, TranslationResult


class OpenAICompatibleProvider(TranslationProvider):
    id = "openai-compatible"
    display_name = "OpenAI-compatible Provider"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._semaphore = threading.BoundedSemaphore(settings.openai_concurrency_limit)

    def configured(self) -> bool:
        return bool(self.settings.openai_api_key and self.settings.openai_base_url)

    def public_status(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "configured": self.configured(),
            "base_url": self.settings.openai_base_url,
            "model": self.settings.openai_model,
            "timeout_seconds": self.settings.openai_timeout_seconds,
            "concurrency_limit": self.settings.openai_concurrency_limit,
            "max_retries": self.settings.openai_max_retries,
            "secret_source": "runtime_environment",
        }

    def translate(self, request: TranslationRequest) -> TranslationResult:
        if not self.configured():
            raise LinguaError(
                ErrorCode.CONFIGURATION,
                "OpenAI-compatible Provider is not configured; set the runtime API key",
            )
        payload = {
            "model": self.settings.openai_model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a literary translator. Return only the translation.",
                },
                {"role": "user", "content": request.prompt()},
            ],
            **request.model_parameters,
        }
        headers = {"Authorization": f"Bearer {self.settings.openai_api_key}"}
        endpoint = f"{self.settings.openai_base_url}/chat/completions"
        last_error: LinguaError | None = None
        with self._semaphore:
            for attempt in range(self.settings.openai_max_retries + 1):
                try:
                    with httpx.Client(timeout=self.settings.openai_timeout_seconds) as client:
                        response = client.post(endpoint, headers=headers, json=payload)
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
                            [self.settings.openai_api_key or ""],
                        )
                        raise LinguaError(
                            ErrorCode.MODEL_API,
                            "Translation Provider rejected the request",
                            details,
                            retryable=False,
                        )
                    body = response.json()
                    text = body["choices"][0]["message"]["content"]
                    if not isinstance(text, str) or not text.strip():
                        raise LinguaError(
                            ErrorCode.OUTPUT_MISSING,
                            "Translation Provider returned no translation",
                            retryable=True,
                        )
                    model = str(body.get("model") or self.settings.openai_model)
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
                except httpx.TimeoutException as exc:
                    last_error = LinguaError(
                        ErrorCode.TIMEOUT,
                        "Translation Provider request timed out",
                        retryable=True,
                    )
                    if attempt >= self.settings.openai_max_retries:
                        raise last_error from exc
                except httpx.RequestError as exc:
                    last_error = LinguaError(
                        ErrorCode.MODEL_API,
                        "Translation Provider could not be reached",
                        {"reason": type(exc).__name__},
                        retryable=True,
                    )
                    if attempt >= self.settings.openai_max_retries:
                        raise last_error from exc
                except (IndexError, KeyError, TypeError, ValueError) as exc:
                    raise LinguaError(
                        ErrorCode.OUTPUT_MISSING,
                        "Translation Provider returned an invalid response",
                        retryable=True,
                    ) from exc
                except LinguaError as exc:
                    last_error = exc
                    if not exc.retryable or attempt >= self.settings.openai_max_retries:
                        raise
                time.sleep(min(0.25 * (2**attempt), 2.0))
        raise last_error or LinguaError(ErrorCode.UNKNOWN, "Translation failed")
