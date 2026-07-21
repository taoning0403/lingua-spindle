"""HTTP Adapter for the separately operated manga-image-translator service."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import urlsplit

try:
    import httpx
except ModuleNotFoundError as exc:  # pragma: no cover - exercised in isolated Wheel checks
    raise ModuleNotFoundError(
        "manga-image-translator HTTP support is optional; install 'linguaspindle[manga]'",
        name="httpx",
    ) from exc

from ..errors import ErrorCode, LinguaError
from ..json_types import JsonValue
from ..security import collect_sensitive_values, redact
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


@dataclass(frozen=True, slots=True)
class MangaImageTranslatorConfig:
    """Explicit connection policy for the separately operated service."""

    base_url: str | None = None
    timeout_seconds: float = 600.0
    request_config: dict[str, JsonValue] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("Manga Adapter timeout must be positive")
        if self.base_url:
            parsed = urlsplit(self.base_url.strip().rstrip("/"))
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("Manga Adapter base_url must be an HTTP(S) URL")
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("Manga Adapter base_url cannot contain credentials or query data")


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

    def __init__(self, config: MangaImageTranslatorConfig | object):
        if isinstance(config, MangaImageTranslatorConfig):
            self.config = config
        else:
            raw = getattr(config, "mit_config_json", "{}")
            parsed = json.loads(str(raw))
            if not isinstance(parsed, dict):
                raise ValueError("Manga Adapter request configuration must be an object")
            self.config = MangaImageTranslatorConfig(
                base_url=getattr(config, "mit_base_url", None),
                timeout_seconds=float(getattr(config, "mit_timeout_seconds", 600.0)),
                request_config=parsed,
            )

    def health(self) -> AdapterHealth:
        if not self.config.base_url:
            return AdapterHealth(
                False,
                "External service URL is not configured",
                details={"required_setting": "LINGUASPINDLE_MIT_BASE_URL"},
            )
        try:
            response = httpx.get(
                f"{self.config.base_url.rstrip('/')}/openapi.json",
                timeout=min(self.config.timeout_seconds, 3.0),
            )
            if response.status_code >= 400:
                return AdapterHealth(
                    False,
                    f"Health endpoint returned HTTP {response.status_code}",
                    details={"base_url": self.config.base_url},
                )
            body = response.json()
            return AdapterHealth(
                True,
                "External service is reachable",
                str(body.get("info", {}).get("version") or "unknown"),
                {"base_url": self.config.base_url},
            )
        except (httpx.HTTPError, ValueError) as exc:
            return AdapterHealth(
                False,
                "External service is not reachable",
                details={"reason": type(exc).__name__},
            )

    def _config(self, target_language: str) -> dict[str, Any]:
        config = cast(dict[str, Any], json.loads(json.dumps(self.config.request_config)))
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
        if not self.config.base_url:
            raise LinguaError(
                ErrorCode.ADAPTER_UNAVAILABLE,
                "manga-image-translator service URL is not configured",
            )
        config = self._config(target_language)
        try:
            response = httpx.post(
                f"{self.config.base_url.rstrip('/')}/translate/with-form/image",
                files={"image": (filename, image, "application/octet-stream")},
                data={"config": json.dumps(config)},
                timeout=self.config.timeout_seconds,
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
                redact(
                    {"status_code": response.status_code, "body": response.text[:500]},
                    collect_sensitive_values(config),
                ),
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
                "config_keys": cast(JsonValue, sorted(config)),
            },
        )


__all__ = ["MangaImageTranslatorConfig", "MangaImageTranslatorHttpAdapter"]
