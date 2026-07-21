"""Stable Translation Provider contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..errors import ErrorCode, LinguaError
from ..json_types import JsonValue


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    text: str
    source_language: str
    target_language: str
    style: str = ""
    prompt_template: str = "{text}"
    prompt_version: str = "v1"
    model_parameters: dict[str, JsonValue] | None = None

    def prompt(self) -> str:
        return self.prompt_template.format(
            source_language=self.source_language,
            target_language=self.target_language,
            style=self.style,
            text=self.text,
        )


@dataclass(frozen=True, slots=True)
class TranslationResult:
    text: str
    model: str
    usage: dict[str, int] | None = None


@runtime_checkable
class TranslationProvider(Protocol):
    """Minimal caller-implementable text translation contract."""

    id: str

    def translate(self, request: TranslationRequest) -> TranslationResult: ...


class ProviderRegistry:
    def __init__(self, providers: list[TranslationProvider]):
        self._providers = {provider.id: provider for provider in providers}

    def get(self, provider_id: str) -> TranslationProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise LinguaError(
                ErrorCode.CONFIGURATION, f"Unknown Translation Provider: {provider_id}"
            ) from exc

    def statuses(self) -> list[dict[str, Any]]:
        statuses: list[dict[str, Any]] = []
        for provider in self._providers.values():
            public_status = getattr(provider, "public_status", None)
            if callable(public_status):
                statuses.append(dict(public_status()))
            else:
                statuses.append(
                    {
                        "id": provider.id,
                        "display_name": getattr(provider, "display_name", provider.id),
                        "configured": True,
                    }
                )
        return statuses
