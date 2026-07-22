from __future__ import annotations

import asyncio

import httpx

from linguaspindle.config import Settings
from linguaspindle.interfaces.api import create_app

ERROR_STATUSES = {"400", "404", "409", "413", "422"}
ERROR_REF = "#/components/schemas/ErrorEnvelope"


def _assert_error_envelope(response: httpx.Response, status_code: int) -> None:
    assert response.status_code == status_code
    error = response.json()["error"]
    assert set(error) == {"code", "message", "details", "retryable"}
    assert isinstance(error["code"], str)
    assert isinstance(error["message"], str)
    assert isinstance(error["details"], dict)
    assert isinstance(error["retryable"], bool)


def _assert_documented_errors(operation: dict) -> None:
    responses = operation["responses"]
    assert ERROR_STATUSES <= set(responses)
    for status in ERROR_STATUSES:
        assert responses[status]["content"]["application/json"]["schema"] == {"$ref": ERROR_REF}


async def _contract_flow(data_dir) -> None:
    settings = Settings.from_env(data_dir)
    settings.max_upload_bytes = 8
    application = create_app(settings, start_worker=False)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            document = (await client.get("/openapi.json")).json()
            schemas = document["components"]["schemas"]

            assert schemas["JobStatus"]["enum"] == [
                "queued",
                "running",
                "paused",
                "cancelling",
                "cancelled",
                "succeeded",
                "failed",
                "partially_succeeded",
            ]
            assert schemas["ErrorEnvelope"]["properties"]["error"] == {
                "$ref": "#/components/schemas/ErrorResponse"
            }
            assert schemas["ErrorResponse"]["properties"]["code"] == {
                "$ref": "#/components/schemas/ErrorCode"
            }

            project_upload = document["paths"]["/api/projects"]["post"]
            assert project_upload["responses"]["201"]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ProjectResponse"
            }
            _assert_documented_errors(project_upload)
            project_list_schema = document["paths"]["/api/projects"]["get"]["responses"]["200"][
                "content"
            ]["application/json"]["schema"]
            assert project_list_schema["items"] == {
                "$ref": "#/components/schemas/ProjectSummaryResponse"
            }
            project_detail = document["paths"]["/api/projects/{project_id}"]["get"]
            assert project_detail["responses"]["200"]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ProjectResponse"
            }

            job_create = document["paths"]["/api/projects/{project_id}/jobs"]["post"]
            assert job_create["responses"]["202"]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/JobResponse"
            }
            _assert_documented_errors(job_create)
            job_list_schema = document["paths"]["/api/jobs"]["get"]["responses"]["200"]
            job_list_schema = job_list_schema["content"]["application/json"]["schema"]
            assert job_list_schema["items"] == {"$ref": "#/components/schemas/JobSummaryResponse"}

            for path in (
                "/api/jobs/{job_id}",
                "/api/jobs/{job_id}/pause",
                "/api/jobs/{job_id}/resume",
                "/api/jobs/{job_id}/cancel",
                "/api/jobs/{job_id}/retry",
            ):
                method = "get" if path == "/api/jobs/{job_id}" else "post"
                operation = document["paths"][path][method]
                assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
                    "$ref": "#/components/schemas/JobResponse"
                }
                _assert_documented_errors(operation)

            export_operation = document["paths"]["/api/projects/{project_id}/exports"]["post"]
            export_schema = export_operation["responses"]["200"]["content"]["application/json"][
                "schema"
            ]
            assert export_schema["type"] == "array"
            assert export_schema["items"] == {"$ref": "#/components/schemas/ArtifactResponse"}
            _assert_documented_errors(export_operation)

            metadata_operation = document["paths"]["/api/artifacts/{artifact_id}"]["get"]
            assert metadata_operation["responses"]["200"]["content"]["application/json"][
                "schema"
            ] == {"$ref": "#/components/schemas/ArtifactResponse"}
            _assert_documented_errors(metadata_operation)

            download_operation = document["paths"]["/api/artifacts/{artifact_id}/download"]["get"]
            download_ok = download_operation["responses"]["200"]
            assert download_ok["content"]["application/octet-stream"]["schema"] == {
                "type": "string",
                "format": "binary",
            }
            assert set(download_ok["headers"]) == {
                "Content-Disposition",
                "X-Content-Type-Options",
                "X-Request-ID",
            }
            _assert_documented_errors(download_operation)

            missing_job = await client.get("/api/jobs/missing")
            _assert_error_envelope(missing_job, 404)
            assert missing_job.json()["error"]["code"] == "NOT_FOUND"

            invalid_request = await client.post("/api/projects", data={"name": "Incomplete"})
            _assert_error_envelope(invalid_request, 422)
            assert invalid_request.json()["error"]["code"] == "CONFIGURATION_ERROR"

            invalid_format = await client.post(
                "/api/projects",
                data={
                    "name": "Wrong format",
                    "kind": "novel",
                    "source_language": "en",
                    "target_language": "fr",
                },
                files={"source": ("source.pdf", b"pdf", "application/pdf")},
            )
            _assert_error_envelope(invalid_format, 400)
            assert invalid_format.json()["error"]["code"] == "INVALID_FORMAT"

            too_large = await client.post(
                "/api/projects",
                data={
                    "name": "Too large",
                    "kind": "novel",
                    "source_language": "en",
                    "target_language": "fr",
                },
                files={"source": ("source.txt", b"x" * 9, "text/plain")},
            )
            _assert_error_envelope(too_large, 413)
            assert too_large.json()["error"]["code"] == "UPLOAD_TOO_LARGE"

            created = await client.post(
                "/api/projects",
                data={
                    "name": "Typed project",
                    "kind": "novel",
                    "source_language": "en",
                    "target_language": "fr",
                },
                files={"source": ("source.txt", b"hello", "text/plain")},
            )
            assert created.status_code == 201
            project_id = created.json()["id"]

            queued = await client.post(
                f"/api/projects/{project_id}/jobs", json={"provider_id": "mock"}
            )
            assert queued.status_code == 202
            assert queued.json()["status"] == "queued"

            conflict = await client.delete(f"/api/projects/{project_id}")
            _assert_error_envelope(conflict, 409)
            assert conflict.json()["error"]["code"] == "INVALID_STATE"


def test_openapi_uses_typed_workflow_responses_and_stable_errors(tmp_path) -> None:
    asyncio.run(_contract_flow(tmp_path / "api-contract"))
