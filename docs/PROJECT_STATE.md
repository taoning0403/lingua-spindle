# Project state

Last reviewed against the founding requirements and repository on 2026-07-19. The active and only
implemented milestone is v0.1.0; no v0.2.0 work has begun.

## Current milestone outcome

LinguaSpindle v0.1.0 implements a persistent, restart-aware translation orchestration engine for
TXT novels and CBZ/image manga. One ApplicationService and sequential orchestration core are
exposed through a no-login Web GUI, Typer CLI, and FastAPI asynchronous Job API.

The product remains a single-instance standalone tool. It has no account/identity/tenant/
permission/ownership model, has no `novel-platform` dependency, binds non-container operation to
loopback by default, preserves imported Sources, and uses Artifact identities across core
boundaries.

## Implemented capabilities

- Python 3.11+ modular monolith with FastAPI/Uvicorn, Typer, SQLAlchemy, SQLite WAL, package SQL
  migration, and an atomic local Artifact store below one configurable data root.
- Durable ordered Job/Step state, weighted progress, logs, normalized errors, partial success,
  cooperative pause/resume/cancel, failed-work retry, conditional Job claim, and restart recovery.
- Completed-Step and successful-segment reuse; interrupted active work becomes explicit
  `PROCESS_INTERRUPTED` failure with retry rather than silent success/rerun.
- TXT encoding detection, normalized extraction, paragraph/dialogue-preserving segmentation,
  persisted source/translation rows, basic QA, and TXT/JSON export.
- Deterministic offline Mock Provider and real OpenAI-compatible Chat Completions Provider with
  runtime-only key, concurrency bound, timeout, retry, rate-limit/error normalization, standard
  token-usage audit logs, and redaction.
- CBZ/ZIP or single-image manga import with traversal/member/expanded-size limits, Mock Manga
  end-to-end flow, per-page/raw Artifacts, and CBZ export.
- Protocol-only HTTP Adapter for separately operated `zyddnys/manga-image-translator` at researched
  commit `efdc229d`; capability manifest, health, target mapping, output validation, and contract
  tests. No upstream code/model/font distribution.
- Web dashboard, Project create/list/detail/delete, Job detail/controls/logs/Artifact links,
  latest novel result/QA view, downloads, and Adapter/Provider/Pipeline status using polling only.
- CLI commands required by the product contract, explicit `--version`, doctor diagnostics, async
  HTTP resources, downloads, stable error envelopes, and generated OpenAPI with no identity-shaped
  contract.
- Non-root core Dockerfile, loopback-published Compose, persistent volume, health check, read-only
  Compose root filesystem, environment example, bilingual README, operational/developer docs,
  project policies, and structured third-party inventory.

## Verification state

Executed in WSL2 Linux with Python 3.14.4 and Node 18.20.7:

- Ruff format/check, strict mypy, compileall, and the full default pytest suite pass.
- Unit/integration/contract coverage includes active controls, restart, retry, atomicity, deletion,
  archive safety, Provider/Adapter failure mapping, CLI↔API shared data, OpenAPI boundary, and a
  byte scan proving the synthetic runtime key is absent from every database/WAL/Artifact/export
  file.
- Playwright 1.61.0 with Headless Chromium 149.0.7827.55 passes both live local Uvicorn and Docker
  Compose GUI flows. The expanded flow covers no-login/loopback messaging, TXT and JSON export,
  Mock manga/CBZ, normalized failure display, unavailable external Adapter display, screenshots,
  trace capture, console errors, and unexpected external network requests.
- An explicit-cost opt-in Playwright flow passes against the Docker GUI and a real DeepSeek
  OpenAI-compatible endpoint using `deepseek-v4-flash`: one three-Segment novel Job completed all
  six Steps, persisted translations/QA/usage, exported TXT/JSON, and made no browser-side request
  to the Provider origin. The opt-in is excluded from default pytest.
- The wheel builds, installs into an isolated target, and contains GUI plus migration resources.
- `linguaspindle doctor` passes required local checks. Docker probing is execution-context-sensitive:
  the ordinary WSL Linux CLI reaches Docker Desktop, while the current Codex sandbox is denied
  access to its Unix socket.
- Docker Desktop 4.82.0 Engine 29.6.1 (Linux containers) and Compose 5.3.0 build and run the
  60,423,794-byte Linux/amd64 image with container Python 3.12.13. Compose is healthy, publishes
  only `127.0.0.1:8765`, runs as UID/GID 10001 with a read-only root, and retains real GUI-created
  Projects, Jobs, Steps, logs, Segments, and Artifact bytes across restart, down/up, rebuild, and
  force-recreate.
- A follow-up ordinary WSL verification uses Linux CLI `/usr/bin/docker`, resolved to
  `/mnt/wsl/docker-desktop/cli-tools/usr/bin/docker`. Client and Server 29.6.1, Compose 5.3.0,
  `compose ps`, application health, and a minimal `compose restart linguaspindle` all pass without
  invoking Windows `docker.exe`.
- A Docker SIGKILL acceptance interrupts an 800-Segment active translation Step, recovers it as
  `PROCESS_INTERRUPTED`, and succeeds after explicit retry. Completed upstream Steps retain their
  attempt counts and Artifact IDs; 28 completed Segment timestamps remain unchanged and all 800
  final sequences are unique.
- Final container data-root scanning found no authorization/key patterns in 35 files
  (2,079,238 bytes), and live schema inspection found no identity-shaped entity/field or Provider
  secret column.
- Post-real-call exact scanning found no runtime key or Authorization/Bearer header in 43 Docker
  `/data` files (3,019,776 bytes) or 33 browser-evidence/report files (9,092,891 bytes), including
  SQLite/WAL, logs, Artifacts, exports, screenshots, and expanded Playwright trace members.

Original acceptance evidence is in `acceptance-v010.md`; the Docker/WSL supplemental run and exact
commands are in `acceptance-v010-supplement.md` and `acceptance-v010-command-log.txt`.

## Environment-limited acceptance

- Ordinary WSL Docker integration passes. In the current Codex `workspace-write`, managed,
  restricted sandbox, the same Linux client can be resolved and executed but Engine-backed
  commands fail with `permission denied while trying to connect to the docker API at
  unix:///var/run/docker.sock`. The socket is visible as mode `0660`, `nobody:nogroup`; the same
  commands pass outside that sandbox. This is a Codex sandbox/session limitation, not a WSL Docker
  integration blocker, and Windows `docker.exe` is not required.
- Two initial `docker compose build --no-cache` attempts could not reach Docker Hub's OAuth endpoint.
  Pulling the same Docker Official Image digest through AWS Public ECR and tagging it locally
  unblocked the exact no-cache Dockerfile build; subsequent normal builds pass. Direct Docker Hub
  clean-host builds therefore remain dependent on host network/proxy configuration.
- No native Windows PowerShell/Python execution host is available. Windows paths/commands are
  documented and path behavior is platform-neutral, but only WSL2 execution is evidenced here.
- Real Provider acceptance is deliberately minimal: three short Segments, concurrency one, and no
  automatic retry. Long-document scale, concurrency, rate-limit behavior, and long-term stability
  remain unvalidated.
- The selected external manga service is not installed because its heavyweight models and
  per-asset license inventory are outside the core environment. The Docker GUI and Job flow show
  its unavailable status and stable `ADAPTER_UNAVAILABLE`; no live model translation is claimed.

These limits do not change the stable architecture or offline v0.1.0 path and must not be reported
as passing runtime checks.

## Deliberate v0.1.0 omissions

- EPUB, broad format/provider/tool coverage, a full editorial translation editor, streaming manga
  progress, and immediate mid-image Adapter cancellation.
- Distributed workers, brokers, external databases/object stores, general DAG editing, and
  multi-host scheduling.
- Any user/account/auth/session/role/permission/tenant/ownership/collaboration surface.
- Scrapers/downloaders, DRM, a reader, mobile clients, plugin marketplace/arbitrary installer,
  OCR training, Photoshop-class editing, and formal `novel-platform` integration.

## Known limitations

- One host and data root are the concurrency/deployment boundary.
- The in-process worker may fail the active Step on process exit; retry resumes at durable
  boundaries, not inside the external call.
- Step attempts use one StepRun plus monotonic count/append-only logs rather than a StepAttempt
  table.
- Artifact downloads are currently read into process memory before the HTTP response, matching the
  bounded v0.1.0 upload model but not ideal for very large future outputs.
- FastAPI 0.115 emits upstream `asyncio.iscoroutinefunction` deprecation warnings on Python 3.14;
  supported behavior passes, while a framework upgrade needs compatibility revalidation.
- The source repository is registered as `taoning0403/lingua-spindle`; Python and container
  package names remain unreserved because v0.1.0 publishes only a GitHub Technical Preview.

## Decisions

ADRs 0001–0006 close the v0.1.0 stack, persistence, secrets, progress transport, and first Adapter
choices. There are no remaining ordinary technology choices blocking the milestone. Any reversal
requires a new superseding ADR.

## Update triggers

Update this file when capability, verification, deployment evidence, limitation, or milestone
state changes. Put exact requirements in `PRODUCT_SPEC.md`, durable rationale in ADRs, navigation
in `MODULE_MAP.md`, and command transcripts in `acceptance-v010.md`.
