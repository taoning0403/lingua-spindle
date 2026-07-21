"""External capability Adapter implementations."""

from .base import (
    Adapter,
    AdapterHealth,
    AdapterManifest,
    AdapterRegistry,
    MangaAdapterResult,
    MangaTranslationAdapter,
)
from .mock_manga import MockMangaAdapter

__all__ = [
    "Adapter",
    "AdapterHealth",
    "AdapterManifest",
    "AdapterRegistry",
    "MangaAdapterResult",
    "MockMangaAdapter",
    "MangaTranslationAdapter",
]
