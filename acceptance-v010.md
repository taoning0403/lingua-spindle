# LinguaSpindle v0.1.0 acceptance report

> Supplemental Docker/WSL runtime evidence from the same date is recorded in
> `acceptance-v010-supplement.md`. It supersedes this report's original Docker environment blocker
> while preserving the original command history and other findings.

- Report date: 2026-07-19 (Asia/Shanghai)
- Version: `0.1.0`
- Tested host: WSL2 Linux, x86_64
- Runtime: Python 3.14.4; Node 18.20.7 (JavaScript syntax check only)
- Scope: v0.1.0 only; no v0.2.0 implementation was started

This report records commands actually executed in the supplied environment. “Blocked” means the
required external runtime was unavailable; it is not reported as a pass.

## Delivered result

LinguaSpindle now runs as a standalone, single-instance translation orchestrator with no login or
identity model. Web GUI, CLI, and HTTP API call one `ApplicationService` and one persistent ordered
Job engine over SQLite plus immutable local Artifacts.

Implemented end-to-end paths:

1. TXT import → encoding detection → normalized extraction → paragraph-aware segmentation → Mock
   or OpenAI-compatible Provider → persisted segments → basic QA → TXT/JSON.
2. CBZ/image-directory/single-image import → capability-selected Mock or separately operated
   manga HTTP Adapter → translated/raw per-page Artifacts → CBZ.

Jobs expose queued/running/paused/cancelling/cancelled/succeeded/failed/partial states, weighted
progress, Step inputs/outputs, attempts, append-only logs, stable errors, active safe-boundary
pause/cancel, failed-work retry, and restart recovery. Completed Steps and successful segments are
reused.

## Final technology stack

| Area | Selection |
| --- | --- |
| Language/package | Python 3.11+, setuptools, `src/` package |
| HTTP/OpenAPI | FastAPI 0.115.14, Uvicorn 0.34.3, multipart uploads |
| CLI | Typer 0.15.4 |
| Persistence | SQLAlchemy 2.0.51, SQLite WAL/foreign keys, package SQL migration |
| Background work | Durable in-process polling runner with conditional SQLite claim |
| Payloads | Atomic file-backed Artifact store, UUID/SHA-256/provenance |
| Providers | Built-in Mock; OpenAI-compatible Chat Completions via HTTPX |
| Manga Adapters | Built-in Mock; process-separated manga-image-translator HTTP contract |
| GUI | Server-served HTML/CSS/ES module; polling only, no Node production runtime |
| Tests/gates | pytest, coverage, Ruff, strict mypy, compileall, Playwright Chromium |
| Deployment | Local Python; non-root Dockerfile; loopback-published Compose/Volume/health |

Direct tested versions are pinned in `constraints-v010.txt`; third-party integration/license
records are in `third-party-components.toml` and `THIRD_PARTY_NOTICES.md`.

## Directory structure

```text
src/linguaspindle/
  adapters/          capability manifests, registry, Mock and real HTTP Adapter
  interfaces/        FastAPI and Typer adapters
  migrations/        forward-only SQLite SQL
  orchestration/     state machines, Pipeline Presets, durable runner/Steps
  providers/         Provider contract, Mock, OpenAI-compatible implementation
  web/               no-login polling GUI
  application.py     shared use-case boundary
  config.py          validated environment/runtime-only secret
  database.py        migration/session/WAL setup
  models.py          instance-scoped SQLAlchemy records
  security.py        recursive redaction
  storage.py         immutable atomic Artifact payloads
tests/
  unit/              state/config/security/Provider/Adapter/doctor contracts
  integration/       novel/manga/control/recovery/storage/API↔CLI flows
  browser/           live Uvicorn + Chromium GUI acceptance
docs/                product/context/architecture/data/ADRs/research/operations
```

## Architecture decisions

- ADR 0001: no user system, permanently; loopback-default trust boundary.
- ADR 0002: standalone modular monolith and one shared application core.
- ADR 0003: capability-driven Adapters and Artifact-identity data flow.
- ADR 0004: Python/FastAPI/Typer/SQLAlchemy/SQLite/local Artifacts, durable in-process runner,
  static ES-module GUI, polling only.
- ADR 0005: Provider key from runtime environment only; no key API/database field.
- ADR 0006: `manga-image-translator` only as an operator-managed HTTP service; no upstream
  redistribution.

The implemented architecture and schema are consolidated in `docs/architecture.md` and
`docs/data-model.md`.

## Tool and name research

Name checks on 2026-07-19 found no matching GitHub repository/account, PyPI project, npm package,
Docker Hub result, or Quay result for the checked `LinguaSpindle`, `lingua-spindle`, and
`linguaspindle` variants. Availability is observational; a name is not reserved until registered.
Evidence and endpoints are recorded in `docs/research/name-availability.md`.

Manga candidates:

- selected: `zyddnys/manga-image-translator`, commit
  `efdc229de8aa0f3d4051ad97664adc62dd5ac605`, GPL-3.0-only;
- alternatives: `ogkalu2/comic-translate` (Apache-2.0) and `dmMaze/BallonsTranslator`
  (GPL-3.0), with weaker v0.1.0 headless/service contracts for this use; and
- novel research: Ebook-Translator-Calibre-Plugin (GPL-3.0) and docutranslate (MPL-2.0), while the
  mandatory TXT path remained internal.

The selected upstream has a maintained batch/API/Docker surface and CPU/GPU modes. LinguaSpindle
uses only its HTTP protocol and saves image plus raw-response Artifacts. The inspected upstream
snapshot did not contain a complete per-model/per-font redistribution inventory. Therefore the
core ships none of its source, image, weights, fonts, or GPU stack; live production operators must
revalidate their chosen assets. Full research is in `docs/research/translation-tools.md`.

## Startup and use

Local installation:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
linguaspindle doctor
linguaspindle serve
```

Docker (files delivered; runtime blocked on this host):

```bash
cp .env.example .env
docker compose up --build -d
```

CLI:

```bash
linguaspindle projects create --name Sample --kind novel \
  --source-language en --target-language fr --source sample.txt
linguaspindle run PROJECT_ID --provider mock
linguaspindle jobs show JOB_ID
linguaspindle export PROJECT_ID
```

API:

```bash
curl -X POST http://127.0.0.1:8765/api/projects \
  -F name=Sample -F kind=novel -F source_language=en -F target_language=fr \
  -F source=@sample.txt
curl -X POST http://127.0.0.1:8765/api/projects/PROJECT_ID/jobs \
  -H 'Content-Type: application/json' -d '{"provider_id":"mock"}'
curl http://127.0.0.1:8765/api/jobs/JOB_ID
```

GUI pages delivered and browser-tested: dashboard, Project list/create/detail/delete, Job
detail/progress/Steps/logs/errors/input-output Artifact IDs/controls, latest source↔translation/QA
results, downloads, and Adapter/Provider/Pipeline status. The GUI opens directly without a login.

## Actual verification evidence

### Static, type, compile, and automated suite

The final gate commands are:

```bash
.venv/bin/ruff format --check src tests
.venv/bin/ruff check src tests
.venv/bin/mypy src
.venv/bin/python -m compileall -q src tests
.venv/bin/pytest -q
```

Final outcome: all format, lint, strict type, and compile gates passed; `68 passed, 1 skipped`. The
single default skip is the explicitly opt-in real browser test. FastAPI 0.115 emits upstream
deprecation warnings under Python 3.14 but no test failure.

Coverage command:

```bash
.venv/bin/pytest --cov=linguaspindle --cov-report=term-missing -q
```

Final outcome: `68 passed, 1 skipped` and 82% total statement/branch-combined report coverage.
Coverage was recorded as evidence rather than enforced as a threshold.

The suite proves state transitions, active pause/resume/cancel, page-boundary cancellation,
partial work, segment retry, process recovery, completed-Step reuse, Provider retry/rate-limit/
timeout/output errors, Adapter manifest/health/HTTP/errors, archive/path safety, Artifact
provenance/atomicity/deletion, API↔CLI shared data, and OpenAPI identity exclusions. A security test
scans every file below its data root and finds the synthetic runtime key in none of SQLite/WAL,
logs, Artifacts, or exports.

### Browser

Sandboxed execution first failed with the expected `PermissionError: Operation not permitted`
when creating a socket. It was rerun with loopback/browser permission:

```bash
LINGUASPINDLE_RUN_BROWSER_TESTS=1 .venv/bin/pytest -q -m browser
```

Outcome: `1 passed, 68 deselected` (real installed Chromium). It exercised a live Uvicorn server, no-login
dashboard, TXT upload, Mock async Job, polling to success, source/translation view, TXT download,
and a Mock failure with normalized error/log display.

### Live CLI server

Executed:

```bash
.venv/bin/linguaspindle serve \
  --data-dir /tmp/linguaspindle-v010-live --host 127.0.0.1 --port 18765
curl --fail --silent --show-error http://127.0.0.1:18765/health
curl --fail --silent --show-error http://127.0.0.1:18765/
curl --fail --silent --show-error http://127.0.0.1:18765/openapi.json
```

Observed health: `{"status":"ok","version":"0.1.0","database":"ok"}`. The GUI HTML contained
`No login · loopback first`; OpenAPI contained the required async Job/control/Artifact routes. The
server then completed a clean Ctrl-C shutdown and application lifespan cleanup.

### Diagnostics

Executed:

```bash
.venv/bin/linguaspindle doctor --data-dir /tmp/linguaspindle-v010-doctor
```

Outcome: exit 0 and `"ok": true` for required checks: writable data root, database, Mock Provider,
and Mock Manga Adapter. Optional diagnostics correctly reported:

- the WSL Docker shim path exists but its Engine probe fails;
- sandbox port inspection is unavailable (`PermissionError`);
- OpenAI-compatible Provider has no runtime key; and
- real manga URL/assets are not configured/bundled.

### Package build and installed resources

The initial no-build-isolation wheel attempt failed because this specially bootstrapped virtual
environment lacked setuptools. After installing the declared build backend, executed:

```bash
.venv/bin/pip wheel --no-deps --no-build-isolation \
  --wheel-dir /tmp/linguaspindle-wheel-v010-release .
```

Outcome: built `linguaspindle-0.1.0-py3-none-any.whl` (66,986 bytes), SHA-256
`3a5e7d902d2bc36a47600b9bddf96a8ac3ac4af2e15168df90565e44d696a205`.

The wheel was installed with `--no-deps --target /tmp/linguaspindle-wheel-install-v010-release`; an import
probe printed `0.1.0`, `True` for packaged `web/index.html`, `True` for `0001_initial.sql`, and
`LinguaSpindle API` for the factory title.

### Docker

Executed both:

```bash
docker version
docker compose config
```

Both exited 1 with Docker Desktop's message:

```text
The command 'docker' could not be found in this WSL 2 distro.
We recommend to activate the WSL integration in Docker Desktop settings.
```

The Windows Docker shim is present but the Engine/Compose integration is not functional. A real
image build, Compose health, volume-restart persistence, and container non-root inspection could
not be executed here. Docker acceptance is **blocked**, not passed.

### Windows and Linux

- Linux/WSL2: local CLI, SQLite, Job runner, API, GUI, Chromium, wheel, and automated suite passed.
- Native Windows: no Windows execution host was attached. PowerShell setup and Windows path usage
  are documented; cross-platform Python path handling and CLI tests pass on WSL, but native
  Windows startup is **not executed and not claimed**.

### Real external services

- OpenAI-compatible Provider: real production implementation exists; fake HTTP contract covers
  Authorization, success, 400, 429, 5xx, timeout, retry, missing output, and redaction. No paid key
  was provided, so no live billable call is claimed.
- manga-image-translator: real HTTP Adapter exists; fake HTTP and orchestration contracts cover
  health, config/language mapping, image output, timeout, HTTP failure, raw Artifacts, partial
  pages, logs, and page-boundary cancellation. The heavyweight upstream was not installed and no
  live model run is claimed due environment and asset-license uncertainty.

## Acceptance checklist

| # | Requirement | Result |
| --- | --- | --- |
| 1 | README clean start | Pass for local package/wheel/live server; native clean OS not separately provisioned. |
| 2 | Compose starts GUI/API | **Blocked:** Docker WSL integration unavailable. |
| 3 | GUI without registration/login | Pass, live Chromium. |
| 4 | No user/tenant/permission model | Pass, source/schema/OpenAPI tests and final scan. |
| 5 | GUI creates TXT Project | Pass, live Chromium. |
| 6 | Mock end-to-end translation | Pass through core/API/CLI/GUI. |
| 7 | OpenAI-compatible configuration | Pass implementation/contract; no paid live call. |
| 8 | CLI creates/runs same Project | Pass, CLI→API and API→CLI integration. |
| 9 | HTTP API creates async Job | Pass (`202`, polling). |
| 10 | GUI/CLI/API share services/data | Pass, cross-interface tests. |
| 11 | Pause/resume/cancel/retry | Pass, active segment/page safe-boundary tests. |
| 12 | State survives restart | Pass, new ApplicationService over same data root. |
| 13 | Completed Steps not rerun | Pass, attempt counts unchanged. |
| 14 | TXT and structured JSON export | Pass, payload assertions/download. |
| 15 | One real external manga Adapter | Pass implementation/contract; live heavyweight run limited. |
| 16 | No copied upstream source | Pass; HTTP protocol only. |
| 17 | Missing Adapter clear in GUI/CLI | Pass status/doctor and stable `ADAPTER_UNAVAILABLE`. |
| 18 | Core acceptance without API Key | Pass; all default automation uses mocks. |
| 19 | Logs do not leak key | Pass whole-data-root synthetic-key scan. |
| 20 | Tests/static/build pass | Pass for code/wheel/browser; Docker runtime separately blocked. |
| 21 | License and third-party declarations | Pass repository surface/inventory; upstream asset caveat explicit. |
| 22 | Loopback default | Pass config/live server; Compose host mapping loopback. |
| 23 | Public deployment warning | Pass English/Chinese/install/Docker/security docs. |
| 24 | Windows and Linux basics | Linux/WSL pass; **native Windows not executed**. |

## Known limitations

- One host, one SQLite database, one local Artifact root, and an in-process worker.
- TXT and CBZ/images only; no EPUB in v0.1.0.
- Process interruption fails the active Step and requires explicit retry; no mid-request resume.
- Real manga Adapter has page-boundary cancellation and no streaming progress in v0.1.0.
- Basic QA/result view only, not a professional editor.
- Artifact HTTP responses currently read bounded payloads into application memory.
- Docker and native Windows require execution in a capable external environment before a release
  can claim those two runtime acceptances.
- Real Provider/upstream model runs require operator credentials/assets/license validation.
- Observed project/package/image names remain unreserved until registered.

## Next-version recommendations (not implemented)

1. Run a release matrix on native Windows, Ubuntu, and a functional Docker Engine; capture Compose
   volume/restart/non-root evidence.
2. Revalidate a pinned manga upstream release plus every selected model/font license, then run one
   opt-in live CPU fixture without redistributing assets.
3. Add streamed file responses and measured large-document resource limits.
4. Consider EPUB only after the mandatory TXT/CBZ contracts remain stable.
5. Evaluate manga streaming progress/cancel behind the existing capability contract.
6. Upgrade FastAPI/Starlette after Python 3.14 compatibility tests confirm the ASGI client/runtime
   behavior.

These are recommendations only. The repository stops at the v0.1.0 implementation described
above.
