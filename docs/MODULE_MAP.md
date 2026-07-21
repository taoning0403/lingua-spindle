# Module map

Use this map to choose a narrow inspection path, then verify current behavior against code,
migrations, tests, generated contracts, and runtime evidence.

## Product and repository context

| Path | Responsibility |
| --- | --- |
| `AGENTS.md`, `.agents/skills/repo-context/` | Required context-first workflow and refresh rules. |
| `docs/PRODUCT_SPEC.md` | Durable v0.3.0 product and acceptance contract. |
| `docs/PROJECT_STATE.md` | Actual milestone, implemented candidate surface, verification ownership, and known limits. |
| `docs/architecture.md`, `docs/data-model.md` | Consolidated pure-core, optional-runtime, and persistence boundaries. |
| `docs/DECISIONS.md`, `docs/adr/` | Durable decisions; ADR 0008 owns headless/library-first layering. |
| `docs/library-api.md` | Stable Python API examples, selection/manual mapping, extension protocols, events, errors, and serialization. |
| `docs/migrations/v0.2-to-v0.3.md` | Full-data-root backup, additive migration 0003, verification, and restore rollback. |
| `docs/epub.md` | EPUB 2/3 subset, visible-text/locator policy, reconstruction, validation, and archive guards. |
| `docs/adapter-development.md` | Provider/Manga Adapter separation, manifest contract, tests, and external service operation. |
| `docs/releases/v0.1.0.md`, `v0.2.0.md`, `v0.3.0.md` | Versioned highlights, security, upgrade, and limitations. |
| `acceptance/v0.1.0/`, `acceptance/v0.2.0/` | Immutable historical reports, evidence, checksums, and samples. |
| `acceptance/v0.3.0/` *(planned until evidence is generated)* | Required headless core/extras/migration/sample acceptance archive; never contains GUI screenshots or browser traces. |
| `tools/generate_v030_acceptance.py` | Deterministic TXT/EPUB2/EPUB3/image/CBZ core samples, manifests, results, output validation, import-boundary evidence, and checksums. |
| `tools/verify_v030_extras.py` | Enforces the exact clean source commit and v0.3.0 Wheel identity, then installs and smoke-tests every dependency extra in isolation. |

## Pure public core

| Path | Responsibility | Primary verification |
| --- | --- | --- |
| `src/linguaspindle/__init__.py`, `core/__init__.py` | Side-effect-free stable exports and version. | `tests/core/test_import_and_public_api.py` |
| `core/models.py`, `json_types.py` | Typed/versioned manifests, Segments, pages, events, cancellation, records, and results. | `test_dto_serialization.py`, public API tests |
| `errors.py`, `security.py` | Stable errors plus sensitive-value redaction. | core partial/error tests, `test_security.py` |
| `limits.py` | Explicit immutable archive limits shared by EPUB and manga operations. | EPUB/manga limit tests |
| `core/io.py` | Bounded path/bytes/binary-stream reads and caller-targeted atomic output writes. | document/manga core tests |
| `core/txt.py` | TXT decode/inspection, source-span segmentation, stable IDs, and UTF-8/LF rebuild. | `tests/core/test_documents.py`, segmentation tests |
| `core/documents.py` | TXT/EPUB inspect, extract, rebuild, and high-level translate APIs. | `test_documents.py`, EPUB unit/integration tests |
| `core/orchestration.py` | Synchronous selected Segment translation, existing/manual precedence, retry, events, cancellation, and deterministic order. | `test_documents.py`, DTO/error tests |
| `epub.py` | Dependency-light safe EPUB package inspection and source-based reconstruction/validation implementation. | `tests/unit/test_epub.py`, EPUB pipeline tests |
| `core/manga.py` | Image/CBZ inspection, page extraction, Adapter orchestration, partial results, and image/CBZ build. | `tests/core/test_manga.py`, manga integration tests |
| `providers/base.py`, `providers/mock.py` | Minimal text Provider Protocol/request/result and deterministic offline Mock. | core Provider tests, `tests/unit/test_provider.py` |
| `adapters/base.py`, `adapters/mock_manga.py` | Distinct Manga Adapter manifest/health/result Protocol and offline Mock. | core manga tests, `test_manga_adapter.py` |

The pure core must never import `runtime`, `interfaces`, FastAPI, Uvicorn, Typer, SQLAlchemy, or
Playwright. It accepts no global `Settings`.

## Optional integrations and runtime

| Path | Responsibility | Extra / verification |
| --- | --- | --- |
| `providers/openai_compatible.py` | Caller-keyed OpenAI-compatible Chat Completions transport; core owns retries. | `[openai]`; Provider fake-HTTP tests |
| `adapters/manga_image_translator.py` | Protocol-only client for the separately operated real manga service. | `[manga]`; fake-HTTP Adapter tests |
| `runtime/__init__.py` | `LocalRuntime` facade and explicit `JobRunner`; construction does not start a worker. | `[runtime]`; migration/recovery tests |
| `config.py` | Optional interface/runtime environment resolution and validation. | config tests |
| `database.py`, `migrations/` | SQLite and atomic forward-only migrations 0001–0003. | `test_database_migrations.py` |
| `models.py` | Private SQLAlchemy records; migration 0003 adds nullable `segment_key`. | migration/runtime tests |
| `storage.py` | Private safe immutable Artifact payload store and atomic publication/copy. | storage/Artifact tests |
| `application.py` | Optional Project/Profile/Job/Artifact use cases and core DTO mapping. | integration/interface tests |
| `orchestration/state.py`, `pipelines.py` | Persisted state machine and versioned TXT/EPUB/manga runtime Presets. | state/control tests |
| `orchestration/engine.py` | Durable claim/recover/checkpoint runner delegating format work to public core. | recovery/control/pipeline tests |

## Optional interfaces

| Path | Responsibility | Extra / verification |
| --- | --- | --- |
| `interfaces/cli.py` | Dependency-light console entry and actionable missing-extra message. | core/CLI isolation tests |
| `interfaces/_typer_cli.py` | Headless core commands plus lazy optional runtime/server commands. | `[cli]`; interface tests |
| `interfaces/api.py` | JSON/OpenAPI-only persistent API, bounded upload/download, errors, and headless root. | `[server]`; OpenAPI/API tests |
| `docs/cli.md`, `docs/api.md` | Command and HTTP contracts without GUI behavior. | examples checked against implementations |

`src/linguaspindle/web/` and v0.3.0 GUI/browser tests do not exist. Historical v0.2.0 browser
artifacts remain only in the immutable acceptance archive.

## Test routing

| Path | Coverage |
| --- | --- |
| `tests/core/test_import_and_public_api.py` | Import side effects, optional-dependency boundary, and stable exports. |
| `tests/core/test_dto_serialization.py` | Versioned JSON-compatible manifest/result round trips. |
| `tests/core/test_documents.py` | TXT/EPUB stable IDs, selection/manual mapping, rebuild, partial/errors, events, and immutability. |
| `tests/core/test_manga.py` | Image/CBZ inspect/translate/build, archive guards, partial pages, and cancellation. |
| `tests/unit/test_epub.py` | EPUB package/text/locator rules, rejection codes, reconstruction, and limits. |
| `tests/unit/test_provider.py`, `test_manga_adapter.py` | Optional HTTP mapping, timeout/error/output/config behavior. |
| `tests/integration/test_database_migrations.py` | Fresh and v0.1/v0.2-compatible forward migration through schema 0003. |
| `test_novel_pipeline.py`, `test_epub_pipeline.py`, `test_manga_pipeline.py` | Optional runtime regression for all accepted formats and exports. |
| `test_job_controls.py`, `test_epub_controls.py`, `test_recovery.py` | Durable controls, retry, checkpoints, lineage, and process recovery. |
| `test_adapter_orchestration.py` | Runtime page-boundary cancellation, partial/raw Artifacts, unavailable real Adapter. |
| `test_artifacts_and_secrets.py` | Provenance, atomicity, deletion guard, redaction, and root/archive secret scans. |
| `test_api_cli_shared.py`, `test_headless_document_api.py`, `test_openapi_contract.py` | Optional headless interface sharing, selected Segment/rebuild APIs, typed responses, downloads, and no identity/GUI routes. |

## Packaging, deployment, and open-source surface

| Path | Responsibility |
| --- | --- |
| `pyproject.toml`, `constraints-v030.txt` | Minimal default dependency, extras, entry point, static gates, and accepted direct-version constraints. |
| `.github/workflows/ci.yml` | Python 3.11–3.14 tests, Windows core smoke, static checks, Wheel contents, and isolated extras. |
| `Dockerfile`, `compose.yaml`, `.dockerignore`, `.env.example` | Optional headless server image, loopback host publishing, persistent runtime data, and limits/secrets. |
| `README.md`, `README.zh-CN.md` | Library-first quick start, extras, trust boundary, and integration overview. |
| `docs/installation.md`, `docs/docker.md`, `docs/api.md`, `docs/cli.md` | Environment-specific core/runtime/server operation. |
| `third-party-components.toml`, `THIRD_PARTY_NOTICES.md` | Default/optional dependency inventory and external manga separation. |
| `LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CHANGELOG.md` | Open-source and release policy. |

## Verification commands

```bash
python -m pip install -c constraints-v030.txt -e '.[dev]'
python -m ruff format --check src tests tools
python -m ruff check --no-cache src tests tools
python -m mypy src tools/generate_v020_acceptance.py tools/generate_v030_acceptance.py \
  tools/verify_v030_extras.py
python -m compileall -q src tests tools
python -m pytest -q
python -m pytest --cov=linguaspindle --cov-branch --cov-report=term-missing
python -m build --wheel
python -m pip check
docker compose --env-file /dev/null config
```

The acceptance matrix additionally installs the built Wheel into isolated environments for core,
openai, manga, runtime, cli, server, and all. Docker start requires a working engine. The v0.3.0
default suite neither installs a browser nor accesses paid/network/model services.

## Task routing

| Change | Start with | Then verify/update |
| --- | --- | --- |
| Product scope/acceptance | `PRODUCT_SPEC.md` + user request | `PROJECT_STATE.md`; ADR if durable |
| Public API/DTO | ADR 0008 + `library-api.md` + `core/` | core isolation/serialization tests, map/docs |
| TXT/select/manual | core documents/txt/orchestration | core document tests and runtime regression |
| EPUB package/text/rebuild | ADR 0007 + `epub.md` + `epub.py` | core/EPUB/runtime structure/security tests |
| Manga core/Adapter | ADRs 0003/0006/0008 + Adapter docs | core manga, fake HTTP, runtime Artifact tests |
| Provider/secrets | ADRs 0005/0008 + providers/security | fake HTTP, core redaction, full-root scans |
| Persistent runtime/schema | data model + migration guide | migration/recovery/controls/Artifact tests |
| CLI/API | public core + optional runtime | isolation, shared interface, OpenAPI/no-GUI tests |
| Packaging/extras | pyproject + notices | isolated Wheels, `pip check`, resource/dependency scans |
| Deployment/network | ADR 0001 + Docker docs | loopback, health, persistence, non-root/read-only checks |
