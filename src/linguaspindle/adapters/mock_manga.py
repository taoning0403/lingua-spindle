"""Offline manga Adapter used by demos and contract tests."""

from __future__ import annotations

from .base import Adapter, AdapterHealth, AdapterManifest, MangaAdapterResult


class MockMangaAdapter(Adapter):
    manifest = AdapterManifest(
        id="mock-manga",
        display_name="Mock Manga Adapter",
        adapter_version="1.0.0",
        upstream_version="built-in",
        invocation_type="in_process_mock",
        capabilities=("manga_full_pipeline",),
        input_formats=("png", "jpeg", "webp"),
        output_formats=("png", "jpeg", "webp"),
        languages=("*",),
        requires_gpu=False,
        supports_cancel=False,
        supports_progress=False,
        health_check="built-in",
        configuration_help="No configuration required. For demos and tests only.",
        upstream_url="",
        upstream_license="Apache-2.0",
        modified=False,
    )

    def health(self) -> AdapterHealth:
        return AdapterHealth(True, "Built-in deterministic mock is ready", "built-in")

    def translate_image(
        self,
        *,
        image: bytes,
        filename: str,
        source_language: str,
        target_language: str,
    ) -> MangaAdapterResult:
        suffix = filename.lower().rsplit(".", maxsplit=1)[-1] if "." in filename else ""
        media_type = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
        }.get(suffix, "application/octet-stream")
        return MangaAdapterResult(
            image=image,
            media_type=media_type,
            raw_metadata={
                "mock": True,
                "filename": filename,
                "source_language": source_language,
                "target_language": target_language,
                "bytes": len(image),
            },
        )
