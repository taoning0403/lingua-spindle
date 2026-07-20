# LinguaSpindle

LinguaSpindle is an open-source translation orchestration engine for novels and manga. It keeps
imported sources immutable, runs restart-safe ordered Pipelines, and exposes the same application
core through a no-login Web GUI, the `linguaspindle` CLI, and an asynchronous HTTP API.

v0.1.0 provides two complete paths:

- TXT → paragraph-aware segments → Mock or OpenAI-compatible translation → QA → TXT/JSON; and
- image/CBZ → capability-selected manga Adapter → translated pages/raw output → CBZ.

The built-in mocks make the complete core demonstrable offline. The first real manga integration
is a protocol-only Adapter for a separately operated
[`manga-image-translator`](https://github.com/zyddnys/manga-image-translator) HTTP service. Its
GPL code, models, fonts, and GPU stack are not copied, installed, or redistributed by this project.

[简体中文说明](README.zh-CN.md)

## Trust boundary

LinguaSpindle is a single-instance tool. It has no registration, login, account, role,
permission, tenant, owner, or collaboration model. Anyone who can reach the HTTP port can operate
the instance.

The non-container server binds to `127.0.0.1` by default. Docker Compose publishes only on the
host's `127.0.0.1` by default. **Do not expose LinguaSpindle directly to the public Internet.** Use
a private network, VPN/Tailscale, Cloudflare Access, or a deliberately configured reverse proxy
as an outer perimeter when remote access is needed.

## Quick start

Python 3.11 or newer is required.

### Linux, macOS, or WSL

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
linguaspindle doctor
linguaspindle serve
```

Open <http://127.0.0.1:8765>. No login page is expected.

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
linguaspindle doctor
linguaspindle serve
```

If script execution is restricted, invoke `.venv\Scripts\linguaspindle.exe` directly. Mutable
data defaults to the platform application-data directory; use `--data-dir PATH` or
`LINGUASPINDLE_DATA_DIR` to make it explicit.

More details: [local installation](docs/installation.md).

## Docker Compose

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
```

Open <http://127.0.0.1:8765>. The named `linguaspindle-data` volume contains SQLite state and all
Artifact payloads. The core image runs as UID/GID 10001, has a read-only root filesystem under
Compose, and contains no external manga tool or heavyweight model.

See [Docker deployment](docs/docker.md) before changing the loopback port mapping.

## CLI examples

```bash
linguaspindle projects create \
  --name "Sample novel" \
  --kind novel \
  --source-language en \
  --target-language zh-CN \
  --source ./sample.txt

linguaspindle projects list
linguaspindle run PROJECT_ID --provider mock
linguaspindle jobs show JOB_ID
linguaspindle artifacts list PROJECT_ID
linguaspindle export PROJECT_ID --format txt
```

`linguaspindle run` waits by default. The Web/API background worker claims queued Jobs
asynchronously. Pause and cancel requests take effect at safe segment/page boundaries; an
external Adapter that cannot interrupt immediately remains `cancelling` until that boundary.

Run `linguaspindle --help` and each subcommand's `--help` for the complete command surface.

## HTTP API example

Create a Project with multipart input, then queue a Job:

```bash
curl -sS -X POST http://127.0.0.1:8765/api/projects \
  -F 'name=API sample' \
  -F 'kind=novel' \
  -F 'source_language=en' \
  -F 'target_language=fr' \
  -F 'source=@sample.txt;type=text/plain'

curl -sS -X POST http://127.0.0.1:8765/api/projects/PROJECT_ID/jobs \
  -H 'Content-Type: application/json' \
  -d '{"provider_id":"mock"}'

curl -sS http://127.0.0.1:8765/api/jobs/JOB_ID
```

Interactive OpenAPI documentation is at <http://127.0.0.1:8765/docs>. See the
[API guide](docs/api.md) for lifecycle and error semantics.

## Providers and secrets

The Mock Provider is always ready and never uses a paid service. Configure an OpenAI-compatible
endpoint only through the process environment:

```bash
export LINGUASPINDLE_OPENAI_BASE_URL=https://api.openai.com/v1
export LINGUASPINDLE_OPENAI_API_KEY='set-this-outside-version-control'
export LINGUASPINDLE_OPENAI_MODEL=gpt-4.1-mini
linguaspindle serve
```

PowerShell uses `$env:LINGUASPINDLE_OPENAI_API_KEY = '...'`. The API key is not accepted by the
HTTP API and is never intentionally persisted in configuration, Job snapshots, database views,
logs, Artifacts, or exports. Keep populated `.env` files out of version control.

## External manga Adapter

Operate and license `zyddnys/manga-image-translator` separately, enable its HTTP API, then set:

```bash
export LINGUASPINDLE_MIT_BASE_URL=http://127.0.0.1:5003
export LINGUASPINDLE_MIT_CONFIG_JSON='{}'
linguaspindle adapters doctor
```

The Adapter calls `/translate/with-form/image`; it does not download or start the upstream. The
inspected upstream snapshot did not provide a complete per-model and per-font redistribution
inventory, so production operators must review those assets for their selected configuration.
See [Adapter development and operations](docs/adapter-development.md) and the
[tool research](docs/research/translation-tools.md).

## Development and verification

```bash
python -m pip install -c constraints-v010.txt -e '.[dev]'
ruff format --check src tests
ruff check src tests
mypy src
python -m compileall -q src tests
pytest -q
```

Browser acceptance uses Playwright and is opt-in because it needs a separately installed browser:

```bash
playwright install chromium
LINGUASPINDLE_RUN_BROWSER_TESTS=1 pytest -q -m browser
```

See [CONTRIBUTING.md](CONTRIBUTING.md), the factual
[v0.1.0 acceptance archive](acceptance/v0.1.0/README.md), and the current
[project state](docs/PROJECT_STATE.md).

## Architecture and licensing

- [Architecture](docs/architecture.md)
- [Data model](docs/data-model.md)
- [Decision records](docs/DECISIONS.md)
- [Structured third-party inventory](third-party-components.toml)
- [Third-party notices](THIRD_PARTY_NOTICES.md)
- [Security policy](SECURITY.md)

LinguaSpindle core is licensed under [Apache-2.0](LICENSE). External services and Python
dependencies retain their own licenses; no external project's license is replaced by the core
license.
