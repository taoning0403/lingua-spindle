"""Stable Translation Provider contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ..errors import ErrorCode, LinguaError


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    text: str
    source_language: str
    target_language: str
    style: str
    prompt_template: str
    prompt_version: str
    model_parameters: dict[str, Any]

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


class TranslationProvider(ABC):
    id: str
    display_name: str

    @abstractmethod
    def configured(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def public_status(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def translate(self, request: TranslationRequest) -> TranslationResult:
        raise NotImplementedError


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
        return [provider.public_status() for provider in self._providers.values()]
