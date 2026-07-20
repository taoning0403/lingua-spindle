# Contributing to LinguaSpindle

Thank you for helping improve LinguaSpindle. Contributions should keep the project understandable,
local-first, testable without paid services, and safe to operate as a single-instance tool.

## Before changing code

Read `AGENTS.md`, `docs/PROJECT_STATE.md`, and `docs/MODULE_MAP.md`, then follow the relevant ADRs.
The following boundaries are permanent:

- Do not add users, accounts, authentication, sessions, roles, permissions, tenants, ownership,
  memberships, quotas, or identity-shaped fields/routes.
- Keep LinguaSpindle independent from `novel-platform`.
- Make Web, CLI, and API reuse the application/orchestration core.
- Keep the default non-container bind on loopback.
- Preserve imported source bytes and pass data across core boundaries by Artifact identity.
- Select Adapters by declared capability, never by upstream-name conditionals.
- Never serialize runtime API keys.

Open an issue before proposing a durable boundary reversal, a new persistent concept, or a new
external integration. Such changes need an ADR and license review.

## Development setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -c constraints-v020.txt -e '.[dev]'
```

On Windows PowerShell use `.venv\Scripts\Activate.ps1`. The supported Python range begins at
3.11. Tests use temporary data roots and require no API key or model download.

## Quality gates

Run the checks relevant to your change; before a pull request, run all of these:

```bash
ruff format --check src tests tools
ruff check src tests tools
mypy src tools/generate_v020_acceptance.py
python -m compileall -q src tests tools
pytest -q
```

Browser changes also require:

```bash
playwright install chromium
LINGUASPINDLE_RUN_BROWSER_TESTS=1 pytest -q -m browser
```

Never weaken an assertion or skip a required check merely to produce a green result. Record real
environment blockers.

## Change design

- Put use-case behavior in `ApplicationService` and orchestration behavior in the runner; keep
  interface handlers thin.
- Add a forward-only SQL migration for persistent schema changes. Do not rewrite an applied
  migration.
- Publish Artifact payloads atomically and keep all paths under the configured data root.
- Normalize third-party errors into stable `ErrorCode` values and redact diagnostics before
  persistence.
- Adapter tests must use fakes or protocol fixtures rather than downloading heavyweight models.
- Update `third-party-components.toml` and `THIRD_PARTY_NOTICES.md` when adding a dependency or
  integration. Confirm code, model, and font terms separately.

## Documentation and commits

Update only maintained context whose facts changed, following `AGENTS.md`. Keep pull requests
focused and describe verification commands and outcomes. Do not commit `.env`, database files,
runtime Artifact payloads, model weights, fonts, virtual environments, or ad hoc browser
downloads. Compact versioned acceptance fixtures/evidence follow `acceptance/README.md` instead.

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md) and certify that
you have the right to submit your contribution under Apache-2.0.
