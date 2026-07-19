"""Deterministic offline Provider used by demos and automation."""

from __future__ import annotations

from typing import Any

from ..errors import ErrorCode, LinguaError
from .base import TranslationProvider, TranslationRequest, TranslationResult


class MockProvider(TranslationProvider):
    id = "mock"
    display_name = "Mock Provider"

    def configured(self) -> bool:
        return True

    def public_status(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "configured": True,
            "model": "mock-v1",
            "offline": True,
        }

    def translate(self, request: TranslationRequest) -> TranslationResult:
        if "[[MOCK_FAIL]]" in request.text:
            raise LinguaError(
                ErrorCode.MODEL_API,
                "Mock Provider was instructed to fail this segment",
                retryable=True,
            )
        translated = f"[{request.target_language}] {request.text}"
        return TranslationResult(text=translated, model="mock-v1")
