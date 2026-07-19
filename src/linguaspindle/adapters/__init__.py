"""External capability Adapter implementations."""

from .base import Adapter, AdapterHealth, AdapterManifest, AdapterRegistry, MangaAdapterResult
from .manga_image_translator import MangaImageTranslatorHttpAdapter
from .mock_manga import MockMangaAdapter

__all__ = [
    "Adapter",
    "AdapterHealth",
    "AdapterManifest",
    "AdapterRegistry",
    "MangaAdapterResult",
    "MangaImageTranslatorHttpAdapter",
    "MockMangaAdapter",
]
