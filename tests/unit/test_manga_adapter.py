from __future__ import annotations

import json

import httpx
import pytest

from linguaspindle.adapters.manga_image_translator import MangaImageTranslatorHttpAdapter
from linguaspindle.config import Settings
from linguaspindle.errors import ErrorCode, LinguaError


def _adapter(tmp_path, *, base_url: str | None = "http://manga.test"):
    return MangaImageTranslatorHttpAdapter(
        Settings(
            data_dir=tmp_path / "data",
            mit_base_url=base_url,
            mit_timeout_seconds=12,
            mit_config_json=json.dumps({"detector": {"detector": "default"}}),
        )
    )


def test_manifest_declares_automation_and_safe_boundary_limits(tmp_path) -> None:
    manifest = _adapter(tmp_path).manifest
    assert manifest.id == "manga-image-translator-http"
    assert "manga_full_pipeline" in manifest.capabilities
    assert manifest.invocation_type == "http_service"
    assert manifest.supports_cancel is False
    assert manifest.supports_progress is False
    assert manifest.upstream_license.startswith("GPL-3.0-only")
    assert manifest.modified is False


def test_health_reports_missing_and_unreachable_service(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = _adapter(tmp_path, base_url=None).health()
    assert missing.available is False
    assert missing.details == {"required_setting": "LINGUASPINDLE_MIT_BASE_URL"}

    def unavailable(_url: str, *, timeout: float) -> httpx.Response:
        raise httpx.ConnectError(
            f"unreachable after {timeout}", request=httpx.Request("GET", "http://manga.test")
        )

    monkeypatch.setattr(httpx, "get", unavailable)
    health = _adapter(tmp_path).health()
    assert health.available is False
    assert health.details == {"reason": "ConnectError"}


def test_health_and_translation_follow_upstream_http_contract(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}

    def health(_url: str, *, timeout: float) -> httpx.Response:
        assert timeout == 3.0
        return httpx.Response(200, json={"info": {"version": "1.7.0"}})

    def translate(
        url: str,
        *,
        files: dict,
        data: dict,
        timeout: float,
    ) -> httpx.Response:
        captured.update(url=url, files=files, data=data, timeout=timeout)
        return httpx.Response(
            200,
            content=b"translated-png",
            headers={"content-type": "image/png; charset=binary"},
        )

    monkeypatch.setattr(httpx, "get", health)
    monkeypatch.setattr(httpx, "post", translate)
    adapter = _adapter(tmp_path)
    status = adapter.health()
    assert status.available is True
    assert status.external_version == "1.7.0"

    result = adapter.translate_image(
        image=b"source-image",
        filename="page.png",
        source_language="ja",
        target_language="zh-CN",
    )
    assert result.image == b"translated-png"
    assert result.media_type == "image/png"
    assert captured["url"].endswith("/translate/with-form/image")
    assert captured["files"]["image"] == (
        "page.png",
        b"source-image",
        "application/octet-stream",
    )
    assert json.loads(captured["data"]["config"])["translator"]["target_lang"] == "CHS"
    assert captured["timeout"] == 12


def test_timeout_and_invalid_output_are_normalized(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _adapter(tmp_path)

    def timeout(*_args, **_kwargs) -> httpx.Response:
        raise httpx.ReadTimeout(
            "synthetic timeout", request=httpx.Request("POST", "http://manga.test")
        )

    monkeypatch.setattr(httpx, "post", timeout)
    with pytest.raises(LinguaError) as caught:
        adapter.translate_image(
            image=b"source", filename="page.png", source_language="ja", target_language="en"
        )
    assert caught.value.code == ErrorCode.TIMEOUT
    assert caught.value.retryable is True

    monkeypatch.setattr(
        httpx,
        "post",
        lambda *_args, **_kwargs: httpx.Response(
            200, content=b"{}", headers={"content-type": "application/json"}
        ),
    )
    with pytest.raises(LinguaError) as caught:
        adapter.translate_image(
            image=b"source", filename="page.png", source_language="ja", target_language="en"
        )
    assert caught.value.code == ErrorCode.OUTPUT_MISSING


def test_http_failure_is_redacted_and_retryable_only_for_server_errors(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _adapter(tmp_path)
    statuses = iter([400, 503])

    def failure(*_args, **_kwargs) -> httpx.Response:
        status = next(statuses)
        return httpx.Response(status, text="api_key=not-for-logs")

    monkeypatch.setattr(httpx, "post", failure)
    with pytest.raises(LinguaError) as client_error:
        adapter.translate_image(
            image=b"source", filename="page.png", source_language="ja", target_language="en"
        )
    assert client_error.value.code == ErrorCode.EXTERNAL_COMMAND
    assert client_error.value.retryable is False
    assert "not-for-logs" not in str(client_error.value.details)

    with pytest.raises(LinguaError) as server_error:
        adapter.translate_image(
            image=b"source", filename="page.png", source_language="ja", target_language="en"
        )
    assert server_error.value.code == ErrorCode.EXTERNAL_COMMAND
    assert server_error.value.retryable is True


def test_invalid_adapter_configuration_is_rejected(tmp_path) -> None:
    adapter = MangaImageTranslatorHttpAdapter(
        Settings(
            data_dir=tmp_path / "data",
            mit_base_url="http://manga.test",
            mit_config_json='{"translator": []}',
        )
    )
    with pytest.raises(LinguaError) as caught:
        adapter.translate_image(
            image=b"source", filename="page.png", source_language="ja", target_language="en"
        )
    assert caught.value.code == ErrorCode.CONFIGURATION
