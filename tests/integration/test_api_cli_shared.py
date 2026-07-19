from __future__ import annotations

import asyncio
import json

import httpx
from typer.testing import CliRunner

from linguaspindle.config import Settings
from linguaspindle.interfaces.api import create_app
from linguaspindle.interfaces.cli import app as cli_app


async def _wait_for_terminal(client: httpx.AsyncClient, job_id: str) -> dict:
    for _ in range(100):
        job = (await client.get(f"/api/jobs/{job_id}")).json()
        if job["status"] in {"succeeded", "failed", "partially_succeeded", "cancelled"}:
            return job
        await asyncio.sleep(0.02)
    raise AssertionError("Job did not reach a terminal status")


async def _api_cli_flow(data_dir) -> str:
    application = create_app(Settings.from_env(data_dir))
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/health")
            assert health.status_code == 200
            assert health.json()["database"] == "ok"

            created = await client.post(
                "/api/projects",
                data={
                    "name": "API novel",
                    "kind": "novel",
                    "source_language": "en",
                    "target_language": "de",
                },
                files={"source": ("api.txt", b"First.\n\nSecond.", "text/plain")},
            )
            assert created.status_code == 201
            project_id = created.json()["id"]

            queued = await client.post(
                f"/api/projects/{project_id}/jobs",
                json={"provider_id": "mock"},
            )
            assert queued.status_code == 202
            assert queued.json()["id"]
            completed = await _wait_for_terminal(client, queued.json()["id"])
            assert completed["status"] == "succeeded"

            exports = await client.post(f"/api/projects/{project_id}/exports")
            assert exports.status_code == 200
            assert {item["kind"] for item in exports.json()} == {
                "novel_export_txt",
                "novel_export_json",
            }
            download = await client.get(exports.json()[0]["download_url"])
            assert download.status_code == 200
            assert download.content
    return project_id


def test_async_api_and_cli_share_one_data_store(tmp_path) -> None:
    data_dir = tmp_path / "shared-data"
    project_id = asyncio.run(_api_cli_flow(data_dir))

    result = CliRunner().invoke(cli_app, ["projects", "list", "--data-dir", str(data_dir)])
    assert result.exit_code == 0, result.output
    listed = json.loads(result.output)
    assert listed[0]["id"] == project_id


async def _openapi_flow(data_dir) -> None:
    application = create_app(Settings.from_env(data_dir), start_worker=False)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            document = (await client.get("/openapi.json")).json()
            paths = set(document["paths"])
            assert {
                "/health",
                "/api/projects",
                "/api/projects/{project_id}/jobs",
                "/api/jobs/{job_id}/pause",
                "/api/jobs/{job_id}/resume",
                "/api/jobs/{job_id}/cancel",
                "/api/jobs/{job_id}/retry",
                "/api/artifacts/{artifact_id}/download",
            } <= paths
            prohibited = ("/api/users", "/api/me", "/api/auth")
            assert not any(path.startswith(prohibited) for path in paths)
            download_content = document["paths"]["/api/artifacts/{artifact_id}/download"]["get"][
                "responses"
            ]["200"]["content"]
            assert "application/octet-stream" in download_content

            response = await client.get("/")
            assert response.status_code == 200
            assert "LinguaSpindle" in response.text
            assert "No login" in response.text
            assert (await client.get("/app.js")).status_code == 200
            assert (await client.get("/styles.css")).status_code == 200


def test_openapi_and_web_gui_surface(tmp_path) -> None:
    asyncio.run(_openapi_flow(tmp_path / "data"))


async def _read_cli_data_through_api(data_dir, project_id: str) -> None:
    application = create_app(Settings.from_env(data_dir), start_worker=False)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            project = await client.get(f"/api/projects/{project_id}")
            assert project.status_code == 200
            assert project.json()["latest_job"]["status"] == "succeeded"
            artifacts = await client.get(f"/api/projects/{project_id}/artifacts")
            assert {item["kind"] for item in artifacts.json()} >= {
                "source_original",
                "novel_export_txt",
                "novel_export_json",
            }


def test_cli_create_and_run_are_immediately_visible_to_api(tmp_path) -> None:
    data_dir = tmp_path / "cli-shared-data"
    source = tmp_path / "cli-source.txt"
    source.write_text("CLI first.\n\nCLI second.", encoding="utf-8")
    runner = CliRunner()
    created = runner.invoke(
        cli_app,
        [
            "projects",
            "create",
            "--name",
            "CLI novel",
            "--kind",
            "novel",
            "--source-language",
            "en",
            "--target-language",
            "es",
            "--source",
            str(source),
            "--data-dir",
            str(data_dir),
        ],
    )
    assert created.exit_code == 0, created.output
    project_id = json.loads(created.output)["id"]

    completed = runner.invoke(
        cli_app,
        ["run", project_id, "--provider", "mock", "--data-dir", str(data_dir)],
    )
    assert completed.exit_code == 0, completed.output
    assert json.loads(completed.output)["status"] == "succeeded"
    asyncio.run(_read_cli_data_through_api(data_dir, project_id))


async def _validation_redaction_flow(data_dir) -> None:
    runtime_value = "sk-" + "validation-response-secret"
    settings = Settings(data_dir=data_dir, openai_api_key=runtime_value)
    application = create_app(settings, start_worker=False)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            invalid = await client.post(
                "/api/profiles",
                json={
                    "name": "Profile",
                    "source_language": "en",
                    "target_language": "fr",
                    "api_key": runtime_value,
                },
            )
            assert invalid.status_code == 422
            assert invalid.json()["error"]["code"] == "CONFIGURATION_ERROR"
            assert runtime_value not in invalid.text

            document = await client.get("/openapi.json")
            serialized = json.dumps(document.json()).lower()
            for prohibited in (
                "user_id",
                "owner_id",
                "tenant_id",
                "created_by",
                '"/api/users',
                '"/api/me"',
                '"/api/auth',
            ):
                assert prohibited not in serialized


def test_validation_errors_redact_input_and_openapi_has_no_identity_contract(tmp_path) -> None:
    asyncio.run(_validation_redaction_flow(tmp_path / "secure-api-data"))


def test_cli_reports_invalid_environment_as_stable_configuration_error() -> None:
    result = CliRunner().invoke(
        cli_app,
        ["doctor"],
        env={"LINGUASPINDLE_PORT": "70000"},
    )
    assert result.exit_code == 2
    error = json.loads(result.output)["error"]
    assert error["code"] == "CONFIGURATION_ERROR"
    assert "at most 65535" in error["message"]
