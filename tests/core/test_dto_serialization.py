from __future__ import annotations

import json
from io import BytesIO
from typing import Any

import pytest

from linguaspindle import (
    AdapterHealth,
    AdapterManifest,
    BuildResult,
    DocumentManifest,
    DocumentTranslationResult,
    ErrorCode,
    LinguaError,
    MangaAdapterResult,
    MangaManifest,
    MangaTranslationResult,
    MockMangaAdapter,
    MockProvider,
    Segment,
    TranslationBatchResult,
    TranslationOptions,
    TranslationRecord,
    build_manga_output,
    inspect_manga,
    translate_document,
    translate_manga,
)

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02"
    "0000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082"
)


def _through_json(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False))


def test_document_dtos_round_trip_through_json() -> None:
    source = "第一章\r\n\r\nHello.\r\n".encode()
    output = BytesIO()
    options = TranslationOptions(
        source_language="auto",
        target_language="fr",
        concurrency=2,
        max_retries=0,
        retry_backoff_seconds=0,
    )
    result = translate_document(
        source,
        output,
        MockProvider(),
        options,
        filename="round-trip.txt",
    )

    assert TranslationOptions.from_dict(_through_json(options.to_dict())) == options
    assert (
        Segment.from_dict(_through_json(result.manifest.segments[0].to_dict()))
        == (result.manifest.segments[0])
    )
    assert DocumentManifest.from_dict(_through_json(result.manifest.to_dict())) == result.manifest
    assert (
        TranslationRecord.from_dict(_through_json(result.translations.records[0].to_dict()))
        == result.translations.records[0]
    )
    assert (
        TranslationBatchResult.from_dict(_through_json(result.translations.to_dict()))
        == result.translations
    )
    assert BuildResult.from_dict(_through_json(result.build.to_dict())) == result.build
    assert DocumentTranslationResult.from_dict(_through_json(result.to_dict())) == result


def test_manga_dtos_round_trip_through_json_with_binary_payload() -> None:
    manifest = inspect_manga(PNG_1X1, filename="round-trip.png")
    translated = translate_manga(
        PNG_1X1,
        MockMangaAdapter(),
        TranslationOptions(target_language="zh", max_retries=0),
        manifest=manifest,
    )
    output = BytesIO()
    build = build_manga_output(translated, output)

    assert MangaManifest.from_dict(_through_json(manifest.to_dict())) == manifest
    assert (
        MangaTranslationResult.from_dict(_through_json(translated.to_dict(include_binary=True)))
        == translated
    )
    assert BuildResult.from_dict(_through_json(build.to_dict())) == build
    binary_free = _through_json(translated.to_dict(include_binary=False))
    assert binary_free["pages"][0]["image_base64"] is None
    assert binary_free["pages"][0]["image_size"] == len(PNG_1X1)


def test_versioned_dtos_reject_missing_and_unknown_schema_versions() -> None:
    document = translate_document(
        b"one\n\ntwo\n",
        BytesIO(),
        MockProvider(),
        TranslationOptions(max_retries=0),
        filename="schema.txt",
    )
    manga = translate_manga(
        PNG_1X1,
        MockMangaAdapter(),
        TranslationOptions(max_retries=0),
        filename="schema.png",
    )
    cases = (
        (Segment, document.manifest.segments[0].to_dict()),
        (DocumentManifest, document.manifest.to_dict()),
        (TranslationRecord, document.translations.records[0].to_dict()),
        (TranslationBatchResult, document.translations.to_dict()),
        (BuildResult, document.build.to_dict()),
        (MangaManifest, manga.manifest.to_dict()),
        (MangaTranslationResult, manga.to_dict()),
        (DocumentTranslationResult, document.to_dict()),
    )

    for dto_type, valid_payload in cases:
        missing = dict(valid_payload)
        missing.pop("schema_version")
        with pytest.raises(ValueError, match="Unsupported schema_version"):
            dto_type.from_dict(_through_json(missing))

        future = dict(valid_payload)
        future["schema_version"] = "future.v999"
        with pytest.raises(ValueError, match="Unsupported schema_version"):
            dto_type.from_dict(_through_json(future))


def test_error_details_normalize_non_json_values_without_repr_or_nan() -> None:
    sensitive_marker = "private-value-in-object-repr"

    class UnsafeObject:
        def __repr__(self) -> str:
            return sensitive_marker

    recursive: list[object] = []
    recursive.append(recursive)
    error = LinguaError(
        ErrorCode.MODEL_API,
        "bad metadata",
        {
            7: "non-string-key",  # type: ignore[dict-item]
            "binary": b"private bytes",
            "infinite": float("inf"),
            "nan": float("nan"),
            "recursive": recursive,
            "unsupported": UnsafeObject(),
        },
    )

    payload = error.to_dict()
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)

    assert payload["details"]["<int>"] == "non-string-key"
    assert payload["details"]["binary"]["binary_size"] == len(b"private bytes")
    assert payload["details"]["infinite"] == "<non-finite-float>"
    assert payload["details"]["nan"] == "<non-finite-float>"
    assert payload["details"]["recursive"] == ["<recursive-reference>"]
    assert payload["details"]["unsupported"] == {"unsupported_type": "UnsafeObject"}
    assert sensitive_marker not in encoded


def test_untrusted_adapter_metadata_is_json_safe_without_using_object_repr() -> None:
    sensitive_marker = "private-adapter-object-repr"

    class UnsafeObject:
        def __repr__(self) -> str:
            return sensitive_marker

    class MetadataAdapter:
        manifest = AdapterManifest(
            id="metadata",
            display_name="Metadata",
            adapter_version="1",
            upstream_version="test",
            invocation_type="in_process",
            capabilities=("manga_full_pipeline",),
            input_formats=("png",),
            output_formats=("png",),
            languages=("*",),
            requires_gpu=False,
            supports_cancel=False,
            supports_progress=False,
            health_check="call",
            configuration_help="none",
            upstream_url="",
            upstream_license="Apache-2.0",
            modified=False,
        )

        def health(self) -> AdapterHealth:
            return AdapterHealth(True, "ready")

        def translate_image(
            self,
            *,
            image: bytes,
            filename: str,
            source_language: str,
            target_language: str,
        ) -> MangaAdapterResult:
            metadata: dict[object, object] = {
                7: "non-string-key",
                "binary": b"private bytes",
                "nan": float("nan"),
                "unsupported": UnsafeObject(),
            }
            return MangaAdapterResult(  # type: ignore[arg-type]
                image=image,
                media_type="image/png",
                raw_metadata=metadata,
            )

    result = translate_manga(
        PNG_1X1,
        MetadataAdapter(),
        TranslationOptions(max_retries=0),
        filename="metadata.png",
    )
    raw_result = result.pages[0].raw_result
    encoded = json.dumps(result.to_dict(), allow_nan=False, sort_keys=True)

    assert "non-string-key" in raw_result.values()
    assert all(isinstance(key, str) for key in raw_result)
    assert raw_result["binary"]["binary_size"] == len(b"private bytes")
    assert raw_result["nan"] == "<non-finite-float>"
    assert raw_result["unsupported"] == {"unsupported_type": "UnsafeObject"}
    assert sensitive_marker not in encoded


def test_untrusted_adapter_metadata_normalizes_recursive_values() -> None:
    recursive: list[object] = []
    recursive.append(recursive)

    class RecursiveMetadataAdapter:
        manifest = AdapterManifest(
            id="recursive-metadata",
            display_name="Recursive metadata",
            adapter_version="1",
            upstream_version="test",
            invocation_type="in_process",
            capabilities=("manga_full_pipeline",),
            input_formats=("png",),
            output_formats=("png",),
            languages=("*",),
            requires_gpu=False,
            supports_cancel=False,
            supports_progress=False,
            health_check="call",
            configuration_help="none",
            upstream_url="",
            upstream_license="Apache-2.0",
            modified=False,
        )

        def health(self) -> AdapterHealth:
            return AdapterHealth(True, "ready")

        def translate_image(
            self,
            *,
            image: bytes,
            filename: str,
            source_language: str,
            target_language: str,
        ) -> MangaAdapterResult:
            return MangaAdapterResult(  # type: ignore[arg-type]
                image=image,
                media_type="image/png",
                raw_metadata={"recursive": recursive},
            )

    result = translate_manga(
        PNG_1X1,
        RecursiveMetadataAdapter(),
        TranslationOptions(max_retries=0),
        filename="recursive-metadata.png",
    )

    assert result.pages[0].status.value == "succeeded"
    assert result.pages[0].raw_result["recursive"] == ["<recursive-reference>"]
    json.dumps(result.to_dict(), allow_nan=False, sort_keys=True)
