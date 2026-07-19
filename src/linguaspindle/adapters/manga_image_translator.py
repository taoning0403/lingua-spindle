"""HTTP Adapter for the separately operated manga-image-translator service."""

from __future__ import annotations

import json
from typing import Any

import httpx

from ..config import Settings
from ..errors import ErrorCode, LinguaError
from ..security import redact
from .base import Adapter, AdapterHealth, AdapterManifest, MangaAdapterResult

_LANGUAGE_CODES = {
    "en": "ENG",
    "en-us": "ENG",
    "english": "ENG",
    "zh": "CHS",
    "zh-cn": "CHS",
    "chinese": "CHS",
    "zh-tw": "CHT",
    "ja": "JPN",
    "japanese": "JPN",
    "ko": "KOR",
    "korean": "KOR",
    "fr": "FRA",
    "de": "DEU",
    "es": "ESP",
    "it": "ITA",
    "ru": "RUS",
}


class MangaImageTranslatorHttpAdapter(Adapter):
    manifest = AdapterManifest(
        id="manga-image-translator-http",
        display_name="manga-image-translator HTTP",
        adapter_version="1.0.0",
        upstream_version="efdc229d (researched)",
        invocation_type="http_service",
        capabilities=(
            "manga_detect",
            "manga_ocr",
            "manga_inpaint",
            "manga_render",
            "manga_full_pipeline",
        ),
        input_formats=("png", "jpeg", "webp"),
        output_formats=("png",),
        languages=("multi-language",),
        requires_gpu=False,
        supports_cancel=False,
        supports_progress=False,
        health_check="GET /openapi.json",
        configuration_help=(
            "Operate the GPL-3.0-only upstream service separately and set "
            "LINGUASPINDLE_MIT_BASE_URL. LinguaSpindle does not install its models or fonts."
        ),
        upstream_url="https://github.com/zyddnys/manga-image-translator",
        upstream_license="GPL-3.0-only; model/font redistribution not verified",
        modified=False,
    )

    def __init__(self, settings: Settings):
        self.settings = settings

    def health(self) -> AdapterHealth:
        if not self.settings.mit_base_url:
            return AdapterHealth(
                False,
                "External service URL is not configured",
                details={"required_setting": "LINGUASPINDLE_MIT_BASE_URL"},
            )
        try:
            response = httpx.get(
                f"{self.settings.mit_base_url}/openapi.json",
                timeout=min(self.settings.mit_timeout_seconds, 3.0),
            )
            if response.status_code >= 400:
                return AdapterHealth(
                    False,
                    f"Health endpoint returned HTTP {response.status_code}",
                    details={"base_url": self.settings.mit_base_url},
                )
            body = response.json()
            return AdapterHealth(
                True,
                "External service is reachable",
                str(body.get("info", {}).get("version") or "unknown"),
                {"base_url": self.settings.mit_base_url},
            )
        except (httpx.HTTPError, ValueError) as exc:
            return AdapterHealth(
                False,
                "External service is not reachable",
                details={"reason": type(exc).__name__},
            )

    def _config(self, target_language: str) -> dict[str, Any]:
        try:
            config = json.loads(self.settings.mit_config_json)
        except json.JSONDecodeError as exc:
            raise LinguaError(
                ErrorCode.CONFIGURATION,
                "LINGUASPINDLE_MIT_CONFIG_JSON is not valid JSON",
            ) from exc
        if not isinstance(config, dict):
            raise LinguaError(
                ErrorCode.CONFIGURATION, "Manga Adapter configuration must be a JSON object"
            )
        translator = config.setdefault("translator", {})
        if not isinstance(translator, dict):
            raise LinguaError(
                ErrorCode.CONFIGURATION, "Manga Adapter translator configuration is invalid"
            )
        target = _LANGUAGE_CODES.get(target_language.lower(), target_language.upper())
        translator.setdefault("target_lang", target)
        return config

    def translate_image(
        self,
        *,
        image: bytes,
        filename: str,
        source_language: str,
        target_language: str,
    ) -> MangaAdapterResult:
        if not self.settings.mit_base_url:
            raise LinguaError(
                ErrorCode.ADAPTER_UNAVAILABLE,
                "manga-image-translator service URL is not configured",
            )
        config = self._config(target_language)
        try:
            response = httpx.post(
                f"{self.settings.mit_base_url}/translate/with-form/image",
                files={"image": (filename, image, "application/octet-stream")},
                data={"config": json.dumps(config)},
                timeout=self.settings.mit_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise LinguaError(
                ErrorCode.TIMEOUT,
                "Manga Adapter request timed out",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise LinguaError(
                ErrorCode.ADAPTER_UNAVAILABLE,
                "Manga Adapter service could not be reached",
                {"reason": type(exc).__name__},
                retryable=True,
            ) from exc
        if response.status_code >= 400:
            raise LinguaError(
                ErrorCode.EXTERNAL_COMMAND,
                "Manga Adapter service returned an error",
                redact({"status_code": response.status_code, "body": response.text[:500]}),
                retryable=response.status_code >= 500,
            )
        if not response.content:
            raise LinguaError(
                ErrorCode.OUTPUT_MISSING,
                "Manga Adapter returned an empty image",
                retryable=True,
            )
        media_type = response.headers.get("content-type", "image/png").split(";", maxsplit=1)[0]
        if not media_type.startswith("image/"):
            raise LinguaError(
                ErrorCode.OUTPUT_MISSING,
                "Manga Adapter response is not an image",
                {"content_type": media_type},
            )
        return MangaAdapterResult(
            image=response.content,
            media_type=media_type,
            raw_metadata={
                "status_code": response.status_code,
                "content_type": media_type,
                "bytes": len(response.content),
                "source_language": source_language,
                "target_language": target_language,
                "config": config,
            },
        )
