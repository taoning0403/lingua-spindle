"""Capability-based external Adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any

from ..errors import ErrorCode, LinguaError


@dataclass(frozen=True, slots=True)
class AdapterManifest:
    id: str
    display_name: str
    adapter_version: str
    upstream_version: str
    invocation_type: str
    capabilities: tuple[str, ...]
    input_formats: tuple[str, ...]
    output_formats: tuple[str, ...]
    languages: tuple[str, ...]
    requires_gpu: bool
    supports_cancel: bool
    supports_progress: bool
    health_check: str
    configuration_help: str
    upstream_url: str
    upstream_license: str
    modified: bool

    def public(self) -> dict[str, Any]:
        value = asdict(self)
        value["capabilities"] = list(self.capabilities)
        value["input_formats"] = list(self.input_formats)
        value["output_formats"] = list(self.output_formats)
        value["languages"] = list(self.languages)
        return value


@dataclass(frozen=True, slots=True)
class AdapterHealth:
    available: bool
    message: str
    external_version: str | None = None
    details: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class MangaAdapterResult:
    image: bytes
    media_type: str
    raw_metadata: dict[str, Any]


class Adapter(ABC):
    manifest: AdapterManifest

    @abstractmethod
    def health(self) -> AdapterHealth:
        raise NotImplementedError

    @abstractmethod
    def translate_image(
        self,
        *,
        image: bytes,
        filename: str,
        source_language: str,
        target_language: str,
    ) -> MangaAdapterResult:
        raise NotImplementedError


class AdapterRegistry:
    def __init__(self, adapters: list[Adapter]):
        self._adapters = {adapter.manifest.id: adapter for adapter in adapters}

    def get(self, adapter_id: str, capability: str | None = None) -> Adapter:
        try:
            adapter = self._adapters[adapter_id]
        except KeyError as exc:
            raise LinguaError(ErrorCode.CONFIGURATION, f"Unknown Adapter: {adapter_id}") from exc
        if capability and capability not in adapter.manifest.capabilities:
            raise LinguaError(
                ErrorCode.CONFIGURATION,
                f"Adapter {adapter_id} does not declare capability {capability}",
            )
        return adapter

    def select(self, capability: str) -> Adapter:
        for adapter in self._adapters.values():
            if capability in adapter.manifest.capabilities and adapter.health().available:
                return adapter
        raise LinguaError(
            ErrorCode.ADAPTER_UNAVAILABLE,
            f"No available Adapter declares capability {capability}",
        )

    def statuses(self) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for adapter in self._adapters.values():
            health = adapter.health()
            values.append(
                {
                    **adapter.manifest.public(),
                    "health": {
                        "available": health.available,
                        "message": health.message,
                        "external_version": health.external_version,
                        "details": health.details or {},
                    },
                }
            )
        return values
