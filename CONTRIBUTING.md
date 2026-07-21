# Contributing to LinguaSpindle

Thank you for helping improve LinguaSpindle. Contributions should keep the project understandable,
local-first, testable without paid services, and safe to operate as a single-instance tool.

## Before changing code

Read `AGENTS.md`, `docs/PROJECT_STATE.md`, and `docs/MODULE_MAP.md`, then follow the relevant ADRs.
The following boundaries are permanent:

- Do not add users, accounts, authentication, sessions, roles, permissions, tenants, ownership,
  memberships, quotas, or identity-shaped fields/routes.
- Keep LinguaSpindle independent from `novel-platform`.
- Keep the side-effect-free Python core as the shared implementation boundary. Optional CLI,
  HTTP, and persistent-runtime layers may call it; an interface must not duplicate pipelines.
- Keep the default non-container bind on loopback.
- Preserve source bytes. Pure-core calls use caller-owned paths/streams/bytes plus typed
  manifests/results; the optional runtime uses private Artifact identities rather than exposing
  machine-specific storage paths as durable contracts.
- Select Adapters by declared capability, never by upstream-name conditionals.
- Never serialize runtime API keys.

Open an issue before proposing a durable boundary reversal, a new persistent concept, or a new
external integration. Such changes need an ADR and license review.

## Development setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -c constraints-v030.txt -e '.[dev]'
```

On Windows PowerShell use `.venv\Scripts\Activate.ps1`. The supported Python range begins at
3.11. Tests use temporary data roots and require no API key or model download.

## Quality gates

Run the checks relevant to your change; before a pull request, run all of these:

```bash
ruff format --check src tests tools
ruff check src tests tools
mypy src tools/generate_v020_acceptance.py tools/generate_v030_acceptance.py \
  tools/verify_v030_extras.py
python -m compileall -q src tests tools
pytest -q --cov=linguaspindle --cov-branch --cov-report=term-missing
```

The v0.3.0 contract has no GUI, static Web assets, Playwright dependency, or browser gate. Changes
to the optional server must retain its JSON/OpenAPI-only surface and no-GUI route tests.

Never weaken an assertion or skip a required check merely to produce a green result. Record real
environment blockers.

## Change design

- Put reusable TXT/EPUB/manga behavior and orchestration in the public core. Keep optional
  `ApplicationService`, `JobRunner`, CLI, and HTTP handlers thin adapters over core/runtime calls.
- Add a forward-only SQL migration for persistent schema changes. Do not rewrite an applied
  migration.
- In the optional runtime, publish Artifact payloads atomically and keep all private paths under
  the configured data root. Core callers continue to own their input/output paths or streams.
- Normalize third-party errors into stable `ErrorCode` values and redact diagnostics before
  persistence.
- Adapter tests must use fakes or protocol fixtures rather than downloading heavyweight models.
- Update `third-party-components.toml` and `THIRD_PARTY_NOTICES.md` when adding a dependency or
  integration. Confirm code, model, and font terms separately.

## Documentation and commits

Update only maintained context whose facts changed, following `AGENTS.md`. Keep pull requests
focused and describe verification commands and outcomes. Do not commit `.env`, database files,
runtime Artifact payloads, model weights, fonts, virtual environments, or ad hoc generated
downloads. Compact versioned acceptance fixtures/evidence follow `acceptance/README.md` instead.

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md) and certify that
you have the right to submit your contribution under Apache-2.0.
