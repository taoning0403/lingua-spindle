# Module map

Use this map to choose a narrow inspection path, then verify behavior against implementation,
migration, tests, generated OpenAPI, and runtime evidence.

## Product and repository context

| Path | Responsibility |
| --- | --- |
| `AGENTS.md`, `.agents/skills/repo-context/` | Required context-first workflow and refresh rules. |
| `docs/PRODUCT_SPEC.md` | Durable v0.1.0 product and acceptance contract. |
| `docs/PROJECT_STATE.md` | Actual capabilities, verification, limits, and environment blockers. |
| `docs/architecture.md`, `docs/data-model.md` | Consolidated implemented boundaries and invariants. |
| `docs/DECISIONS.md`, `docs/adr/` | Durable decisions and rationale. |
| `docs/research/` | Name/tool/license evidence captured before selection. |
| `acceptance-v010.md` | Commands and factual v0.1.0 acceptance outcomes. |
| `acceptance-v010-supplement.*`, `acceptance-v010-command-log.txt` | Docker/WSL supplemental matrix, machine-readable outcome, and executed-command transcript. |
| `docs/releases/v0.1.0.md` | Technical Preview highlights, verified surface, limitations, security, and installation notes. |
| `artifacts/acceptance-v010/` | Browser screenshots/trace/downloads plus persistence, recovery, deletion, and checksum evidence. |

## Application modules

| Path | Responsibility | Primary verification |
| --- | --- | --- |
| `src/linguaspindle/config.py` | Environment validation, loopback default, data paths, runtime-only key. | `tests/unit/test_config.py` |
| `database.py`, `migrations/` | SQLite WAL/foreign keys, sessions, forward-only schema migration. | recovery/pipeline integration tests |
| `models.py` | Instance-scoped relational records with no identity model. | migration, boundary scans |
| `storage.py` | Safe filename/key resolution, atomic immutable payload write/read/removal. | `test_artifacts_and_secrets.py` |
| `security.py`, `errors.py` | Recursive redaction and stable error vocabulary. | security/provider/Adapter tests |
| `application.py` | Shared Project/Profile/Job/Artifact use cases, lifecycle, diagnostics. | all integration tests |
| `orchestration/state.py` | Explicit Job and Step transitions. | `tests/unit/test_state.py` |
| `orchestration/pipelines.py` | Versioned TXT and manga ordered Presets. | pipeline catalog/integration tests |
| `orchestration/engine.py` | Claim/execute/recover and all v0.1.0 Step handlers. | job-control, recovery, pipeline tests |
| `providers/` | Mock and OpenAI-compatible Provider contracts/implementations. | `test_provider.py`, novel tests |
| `adapters/` | Manifest/registry, Mock Manga, manga-image-translator HTTP Adapter. | Adapter unit/orchestration tests |
| `interfaces/api.py` | FastAPI lifespan/routes/errors/OpenAPI/static asset delivery. | `test_api_cli_shared.py` |
| `interfaces/cli.py` | Typer commands over ApplicationService/JobRunner. | cross-interface tests |
| `web/` | No-login polling GUI for dashboard, Projects, Jobs, results, downloads, capabilities. | `tests/browser/test_gui_flow.py` |

## Tests

| Path | Coverage |
| --- | --- |
| `tests/unit/test_state.py` | Job/Step state-machine valid and invalid transitions. |
| `test_config.py`, `test_security.py` | Scalar/URL/JSON configuration and redaction. |
| `test_provider.py` | Auth contract, usage normalization, bounded retry, rate-limit/server/timeout/output errors. |
| `test_manga_adapter.py` | Manifest, health, HTTP mapping, timeout/error/output/config contract. |
| `test_doctor.py` | Real Docker-engine probe semantics and diagnostic redaction. |
| `tests/integration/test_novel_pipeline.py` | Offline TXT end-to-end, exports, persistence, latest results. |
| `test_manga_pipeline.py` | Offline CBZ end-to-end and traversal rejection. |
| `test_job_controls.py` | Active pause/resume/cancel, segment retry, attempt/log preservation. |
| `test_recovery.py` | Persisted running-state recovery and completed-Step reuse. |
| `test_adapter_orchestration.py` | Page-boundary cancellation, partial pages/raw logs, unavailable real Adapter. |
| `test_artifacts_and_secrets.py` | Provenance, atomicity, deletion, traversal, whole-data-root key scan. |
| `test_api_cli_shared.py` | Async API, OpenAPI/no-identity contract, CLI↔API shared data. |
| `tests/browser/test_gui_flow.py` | Local or externally targeted Chromium flow covering TXT/JSON, Mock manga/CBZ, failures, capability status, console/network checks, optional evidence capture, and an explicit-cost real Provider opt-in with existing-Job replay. |

## Deployment and open-source surface

| Path | Responsibility |
| --- | --- |
| `pyproject.toml`, `constraints-v010.txt` | Package metadata, direct dependencies, scripts, gates, tested direct versions. |
| `Dockerfile`, `compose.yaml`, `.dockerignore`, `.env.example` | Non-root core image, loopback host publish, Volume/health, runtime configuration. |
| `README.md`, `README.zh-CN.md` | Quick start, examples, trust and integration overview. |
| `docs/installation.md`, `docs/docker.md`, `docs/api.md` | Local/Windows operation, container deployment, HTTP lifecycle. |
| `docs/adapter-development.md` | Adapter contract, tests, license checklist, real Adapter operation. |
| `third-party-components.toml`, `THIRD_PARTY_NOTICES.md` | Structured inventory and license/integration notices. |
| `LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CHANGELOG.md` | Open-source policy and release surface. |

## Verification commands

```bash
.venv/bin/ruff format --check src tests
.venv/bin/ruff check src tests
.venv/bin/mypy src
.venv/bin/python -m compileall -q src tests
.venv/bin/pytest -q
node --check src/linguaspindle/web/app.js
LINGUASPINDLE_RUN_BROWSER_TESTS=1 .venv/bin/pytest -q -m browser
LINGUASPINDLE_RUN_BROWSER_TESTS=1 \
  LINGUASPINDLE_BROWSER_BASE_URL=http://127.0.0.1:8765 \
  LINGUASPINDLE_BROWSER_EVIDENCE_DIR=artifacts/acceptance-v010 \
  .venv/bin/pytest -q -m browser
LINGUASPINDLE_RUN_BROWSER_TESTS=1 \
  LINGUASPINDLE_RUN_REAL_PROVIDER_TESTS=1 \
  LINGUASPINDLE_BROWSER_BASE_URL=http://127.0.0.1:8765 \
  .venv/bin/pytest -q -m browser -k real_provider_minimal_translation
.venv/bin/pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/linguaspindle-wheel-v010 .
docker compose config
docker compose up --build -d
```

The last two commands require a functional Docker Engine. Browser acceptance requires installed
Playwright Chromium and loopback socket/browser permissions.

## Task routing

| Change | Start with | Then verify/update |
| --- | --- | --- |
| Product scope/acceptance | `PRODUCT_SPEC.md` + user request | `PROJECT_STATE.md`; ADR if durable |
| Job/Step lifecycle | architecture + state/application/engine | controls/recovery tests, data model |
| Artifact/import/export | architecture + storage/application | atomicity/traversal/pipeline tests |
| Provider/secrets | ADR 0005 + config/security/providers | Provider and whole-root secret tests |
| External Adapter | ADR 0003/0006 + research | contract/orchestration/license inventory |
| Web/CLI/API | shared-core ADR + interface module | cross-interface/OpenAPI/browser tests |
| Deployment/networking | ADR 0001 + Docker docs | loopback, health, persistence, real commands |
| Persistent schema | data model + migration | fresh migration, recovery, model/map refresh |
