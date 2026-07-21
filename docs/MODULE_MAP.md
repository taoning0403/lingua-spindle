# Module map

Use this map to choose a narrow inspection path, then verify behavior against implementation,
migration, tests, generated OpenAPI, and runtime evidence.

## Product and repository context

| Path | Responsibility |
| --- | --- |
| `AGENTS.md`, `.agents/skills/repo-context/` | Required context-first workflow and refresh rules. |
| `docs/PRODUCT_SPEC.md` | Durable v0.2.0 product and acceptance contract. |
| `docs/PROJECT_STATE.md` | Actual capabilities, verification, limits, and environment blockers. |
| `docs/architecture.md`, `docs/data-model.md` | Consolidated implemented boundaries and invariants. |
| `docs/DECISIONS.md`, `docs/adr/` | Durable decisions and rationale. |
| `docs/research/` | Name/tool/license evidence captured before selection. |
| `acceptance/v0.1.0/` | Indexed v0.1.0 reports, Docker/WSL supplemental matrix, machine-readable evidence, command transcript, and Release checksums. |
| `acceptance/v0.2.0/` | v0.2.0 acceptance report, machine-readable evidence, command/environment logs, checksums, and generated EPUB/TXT/manga/build/browser artifacts. |
| `tools/generate_v020_acceptance.py` | Deterministic Mock EPUB/TXT/manga sample generation, output verification, and measured temporary large-EPUB evidence. |
| `docs/releases/v0.1.0.md`, `docs/releases/v0.2.0.md` | Versioned Technical Preview highlights, verified surface, limitations, security, upgrade, and installation notes. |
| `docs/epub.md` | EPUB 2/3 subset, text-node rules, lineage/reuse, reconstruction, validation, resource guards, and limitations. |
| `acceptance/*/artifacts/` | Versioned acceptance fixtures and generated outputs; large/private runtime artifacts remain Release-only or checksum-only. |

## Application modules

| Path | Responsibility | Primary verification |
| --- | --- | --- |
| `src/linguaspindle/config.py` | Environment validation, loopback default, data paths, runtime-only key. | `tests/unit/test_config.py` |
| `database.py`, `migrations/` | SQLite WAL/foreign keys, sessions, atomic forward-only schema migration; 0002 adds EPUB Source/Segment fields. | `test_database_migrations.py`, recovery tests |
| `models.py` | Instance-scoped relational records, EPUB source metadata and Segment lineage/reuse, with no identity model. | migration, EPUB pipeline, boundary scans |
| `storage.py` | Safe filename/key resolution, bounded streamed/atomic immutable payload write/read/copy/removal. | `test_storage.py`, `test_artifacts_and_secrets.py` |
| `security.py`, `errors.py` | Recursive redaction and stable error vocabulary. | security/provider/Adapter tests |
| `application.py` | Shared Project/Profile/Job/Artifact use cases, lifecycle, diagnostics. | all integration tests |
| `epub.py` | Dependency-light safe EPUB inspection, text-unit manifests, reconstruction, output validation, and resource equality. | `test_epub.py`, `test_epub_pipeline.py` |
| `orchestration/state.py` | Explicit Job and Step transitions. | `tests/unit/test_state.py` |
| `orchestration/pipelines.py` | Versioned TXT, EPUB, and manga ordered Presets selected by Project/Source kind. | pipeline catalog/integration tests |
| `orchestration/engine.py` | Claim/execute/recover plus TXT, EPUB, and manga Step handlers. | job-control, recovery, pipeline tests |
| `providers/` | Mock and OpenAI-compatible Provider contracts/implementations. | `test_provider.py`, novel tests |
| `adapters/` | Manifest/registry, Mock Manga, manga-image-translator HTTP Adapter. | Adapter unit/orchestration tests |
| `interfaces/api.py` | FastAPI lifespan/routes/errors/OpenAPI, bounded multipart upload, streamed Artifact download, and static asset delivery. | `test_api_cli_shared.py`, `test_openapi_contract.py`, `test_epub_pipeline.py` |
| `interfaces/cli.py` | Typer commands over ApplicationService/JobRunner, including explicit Pipeline and streamed output copy. | cross-interface tests |
| `web/` | No-login polling GUI for TXT/EPUB/manga Projects, Jobs, results, downloads, and capabilities. | `test_web_epub_gui.py`, `tests/browser/test_gui_flow.py` |

## Tests

| Path | Coverage |
| --- | --- |
| `tests/unit/test_state.py` | Job/Step state-machine valid and invalid transitions. |
| `test_config.py`, `test_security.py` | Scalar/URL/JSON configuration and redaction. |
| `test_provider.py` | Auth contract, usage normalization, bounded retry, rate-limit/server/timeout/output errors. |
| `test_manga_adapter.py` | Manifest, health, HTTP mapping, timeout/error/output/config contract. |
| `test_doctor.py` | Real Docker-engine probe semantics and diagnostic redaction. |
| `tests/integration/test_novel_pipeline.py` | Offline TXT end-to-end, exports, persistence, latest results. |
| `test_epub_pipeline.py` | EPUB Project/Job/Mock/export/re-import, source/resource preservation, reuse/fallback, and content/secret separation. |
| `test_epub_controls.py` | EPUB pause/resume/cancel/retry plus process-interruption recovery and Segment reuse/lineage. |
| `test_database_migrations.py` | Fresh and v0.1-to-v0.2 atomic forward migration. |
| `tests/unit/test_epub.py` | EPUB package/text rules, rejection codes, reconstruction, and archive limits. |
| `tests/unit/test_storage.py` | Bounded stream publication and atomic file copy. |
| `test_web_epub_gui.py` | No-login EPUB GUI labels/actions over the shared API surface. |
| `test_manga_pipeline.py` | Offline CBZ end-to-end plus member/size/ratio/path/portable-name guards. |
| `test_job_controls.py` | Active pause/resume/cancel, segment retry, attempt/log preservation. |
| `test_recovery.py` | Persisted running-state recovery, EPUB-style Segment recovery, and runner race resilience. |
| `test_adapter_orchestration.py` | Page-boundary cancellation, partial pages/raw logs, unavailable real Adapter. |
| `test_artifacts_and_secrets.py` | Provenance, atomicity, active-Job deletion guard, content-safe redaction, and raw/expanded whole-root key scans. |
| `test_api_cli_shared.py` | Async/streaming upload and download, CLI↔API shared data, and no-identity contract. |
| `test_openapi_contract.py` | Typed Project/Job/Artifact responses and stable HTTP error envelopes. |
| `tests/browser/test_gui_flow.py` | Local or externally targeted Chromium flow covering TXT/JSON, Mock manga/CBZ, failures, capability status, console/network checks, optional evidence capture, and an explicit-cost real Provider opt-in with existing-Job replay. |

## Deployment and open-source surface

| Path | Responsibility |
| --- | --- |
| `pyproject.toml`, `constraints-v020.txt` | v0.2.0 package metadata, direct dependencies, scripts, gates, and development/acceptance direct versions. |
| `.github/workflows/ci.yml` | Python 3.11–3.14 default tests, static/configuration gates, Chromium tests, and Python 3.12 Wheel/resource verification. |
| `constraints-v010.txt` | Historical v0.1.0 acceptance direct-version constraint retained for reproducibility. |
| `Dockerfile`, `compose.yaml`, `.dockerignore`, `.env.example` | Non-root core image, loopback host publish, Volume/health, runtime configuration. |
| `README.md`, `README.zh-CN.md` | Quick start, examples, trust and integration overview. |
| `docs/installation.md`, `docs/docker.md`, `docs/api.md` | Local/Windows operation, container deployment, HTTP lifecycle. |
| `docs/adapter-development.md` | Adapter contract, tests, license checklist, real Adapter operation. |
| `third-party-components.toml`, `THIRD_PARTY_NOTICES.md` | Structured inventory and license/integration notices. |
| `LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CHANGELOG.md` | Open-source policy and release surface. |

## Verification commands

```bash
.venv/bin/ruff format --check src tests tools
.venv/bin/ruff check src tests tools
.venv/bin/mypy src tools/generate_v020_acceptance.py
.venv/bin/python -m compileall -q src tests tools
.venv/bin/pytest -q
node --check src/linguaspindle/web/app.js
.venv/bin/linguaspindle --version
LINGUASPINDLE_RUN_BROWSER_TESTS=1 .venv/bin/pytest -q -m browser
LINGUASPINDLE_RUN_BROWSER_TESTS=1 \
  LINGUASPINDLE_BROWSER_BASE_URL=http://127.0.0.1:8765 \
  LINGUASPINDLE_BROWSER_EVIDENCE_DIR=acceptance/v0.2.0/artifacts/browser \
  .venv/bin/pytest -q -m browser
LINGUASPINDLE_RUN_BROWSER_TESTS=1 \
  LINGUASPINDLE_RUN_REAL_PROVIDER_TESTS=1 \
  LINGUASPINDLE_BROWSER_BASE_URL=http://127.0.0.1:8765 \
  .venv/bin/pytest -q -m browser -k real_provider_minimal_translation
.venv/bin/python -m pip wheel --no-deps --wheel-dir /tmp/linguaspindle-wheel-v020 .
docker compose config
docker compose up --build -d
```

The image build/start command requires a functional Docker Engine; `docker compose config` does
not. The isolated wheel build may download declared build requirements. Browser acceptance
requires installed Playwright Chromium and loopback socket/browser permissions.

## Task routing

| Change | Start with | Then verify/update |
| --- | --- | --- |
| Product scope/acceptance | `PRODUCT_SPEC.md` + user request | `PROJECT_STATE.md`; ADR if durable |
| Job/Step lifecycle | architecture + state/application/engine | controls/recovery tests, data model |
| Artifact/import/export | architecture + storage/application | atomicity/traversal/pipeline tests |
| EPUB package/text/rebuild | ADR 0007 + `docs/epub.md` + `epub.py` | EPUB unit/integration/interface/browser tests |
| Provider/secrets | ADR 0005 + config/security/providers | Provider and whole-root secret tests |
| External Adapter | ADR 0003/0006 + research | contract/orchestration/license inventory |
| Web/CLI/API | shared-core ADR + interface module | cross-interface/OpenAPI/browser tests |
| Deployment/networking | ADR 0001 + Docker docs | loopback, health, persistence, real commands |
| Persistent schema | data model + migration | fresh migration, recovery, model/map refresh |
