# Installation and operation

LinguaSpindle requires Python 3.11 or newer. The default installation is a pure headless library;
it needs no data directory, API key, server, database, Docker, browser, GPU, model, or external
service.

## Choose an installation

| Command | Adds |
| --- | --- |
| `pip install linguaspindle` | TXT/EPUB/manga core contracts, archive processing, Mock Provider, Mock Manga Adapter. |
| `pip install 'linguaspindle[openai]'` | HTTPX OpenAI-compatible Provider. |
| `pip install 'linguaspindle[manga]'` | HTTPX client for the separately operated real manga service. |
| `pip install 'linguaspindle[runtime]'` | SQLite, Artifact store, persistent Projects/Jobs/recovery. |
| `pip install 'linguaspindle[cli]'` | Typer headless CLI and pure core commands. |
| `pip install 'linguaspindle[server]'` | FastAPI/Uvicorn JSON server and persistent runtime. |
| `pip install 'linguaspindle[all]'` | Every supported optional layer. |

Use `[server,cli]` when starting the server through the `linguaspindle serve` command. The default
Wheel does not install FastAPI, Uvicorn, Typer, SQLAlchemy, Pydantic, python-multipart,
platformdirs, HTTPX, or Playwright.

## Create an environment

Linux, macOS, or WSL:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install linguaspindle
python -m pip check
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install linguaspindle
python -m pip check
```

If policy blocks script activation, use `.venv\Scripts\python.exe` and the explicit
`.venv\Scripts\linguaspindle.exe` path.

## First core-only run

```python
from pathlib import Path

from linguaspindle import MockProvider, TranslationOptions, translate_document

translate_document(
    Path("sample.txt"),
    Path("sample.fr.txt"),
    MockProvider(),
    TranslationOptions(source_language="en", target_language="fr"),
)
```

The same high-level function handles `.epub`. Image/CBZ examples, selected translation, manual
rebuild, custom extensions, events, and serialization are in the
[Python library API](library-api.md).

## Headless CLI

```bash
python -m pip install 'linguaspindle[cli]'
linguaspindle --version
linguaspindle document inspect sample.txt --target-language fr
linguaspindle document translate sample.txt --target-language fr --output sample.fr.txt
linguaspindle manga inspect chapter.cbz
linguaspindle manga translate chapter.cbz --target-language en --output chapter.en.cbz
linguaspindle validate sample.fr.txt
```

These commands use deterministic Mock implementations and need no runtime database. Persistent
Project/Job/Artifact commands additionally need `[runtime]`. See [CLI reference](cli.md).

## Optional local runtime

```bash
python -m pip install 'linguaspindle[runtime,cli]'
linguaspindle doctor --data-dir ./data
```

The runtime data root contains SQLite metadata and private Artifact payloads. The platform default
is resolved only when runtime configuration is constructed; for predictable backup, set it:

```bash
export LINGUASPINDLE_DATA_DIR="$PWD/data"
linguaspindle doctor
```

PowerShell:

```powershell
$env:LINGUASPINDLE_DATA_DIR = "$PWD\data"
linguaspindle doctor
```

Use a local filesystem for SQLite WAL and atomic Artifact publication. Back up/move the whole
stopped root, never only SQLite or only Artifacts. Constructing `LocalRuntime` does not start a
background worker; callers explicitly run/start `JobRunner`.

## Optional headless server

```bash
python -m pip install 'linguaspindle[server,cli]'
linguaspindle serve
```

Open <http://127.0.0.1:8765/docs> for OpenAPI. The root is JSON, not a GUI. Stop with Ctrl-C.
Default loopback binding is a security boundary; read [HTTP API](api.md) before remote operation.

## Configuration for optional interfaces/runtime

The pure library receives explicit options and never reads these variables. CLI/server/runtime
configuration may resolve:

| Variable | Default | Meaning |
| --- | --- | --- |
| `LINGUASPINDLE_DATA_DIR` | platform application-data path | Optional runtime root. |
| `LINGUASPINDLE_HOST` | `127.0.0.1` | Server bind; non-loopback needs an outer perimeter. |
| `LINGUASPINDLE_PORT` | `8765` | Server port. |
| `LINGUASPINDLE_LOG_LEVEL` | `INFO` | Uvicorn log level. |
| `LINGUASPINDLE_WORKER_POLL_SECONDS` | `0.25` | Explicitly started durable worker poll interval. |
| `LINGUASPINDLE_MAX_UPLOAD_BYTES` | `104857600` | Runtime/server source bound. |
| `LINGUASPINDLE_MAX_ARCHIVE_FILES` | `2000` | ZIP member bound. |
| `LINGUASPINDLE_MAX_ARCHIVE_BYTES` | `1048576000` | Total expanded archive bytes. |
| `LINGUASPINDLE_MAX_ARCHIVE_MEMBER_BYTES` | `104857600` | One expanded member. |
| `LINGUASPINDLE_MAX_ARCHIVE_COMPRESSION_RATIO` | `100` | Per-member expansion ratio. |
| `LINGUASPINDLE_MAX_ARCHIVE_PATH_DEPTH` | `20` | ZIP path depth. |
| `LINGUASPINDLE_OPENAI_BASE_URL` | `https://api.openai.com/v1` | Optional compatible endpoint. |
| `LINGUASPINDLE_OPENAI_API_KEY` | unset | Runtime-only Provider secret. |
| `LINGUASPINDLE_OPENAI_MODEL` | `gpt-4.1-mini` | Optional Provider model. |
| `LINGUASPINDLE_OPENAI_TIMEOUT_SECONDS` | `60` | One transport call timeout. |
| `LINGUASPINDLE_OPENAI_CONCURRENCY` | `2` | Runtime process concurrency policy. |
| `LINGUASPINDLE_OPENAI_MAX_RETRIES` | `3` | Runtime orchestration retry policy. |
| `LINGUASPINDLE_MIT_BASE_URL` | unset | Separately operated manga service. |
| `LINGUASPINDLE_MIT_TIMEOUT_SECONDS` | `600` | One image call timeout. |
| `LINGUASPINDLE_MIT_CONFIG_JSON` | `{}` | Upstream form configuration object. |

Base URLs must be HTTP(S) without credentials, query strings, or fragments. Numeric limits are
positive/bounded. Raising archive/upload limits requires matching disk, `/tmp`, reverse-proxy,
time, and Provider-cost budgets.

## OpenAI-compatible Provider

Install `[openai]`. Library callers pass the key directly or through a resolver:

```python
from linguaspindle.providers.openai_compatible import (
    OpenAICompatibleProvider,
    OpenAIProviderConfig,
)

provider = OpenAICompatibleProvider(
    OpenAIProviderConfig(
        base_url="https://api.example.test/v1",
        model="example-model",
        api_key_resolver=read_from_your_secret_store,
    )
)
```

For CLI/server, environment injection is supported:

```bash
export LINGUASPINDLE_OPENAI_API_KEY='set-outside-version-control'
export LINGUASPINDLE_OPENAI_MODEL='example-model'
```

Never commit a populated `.env`. Keys are not API fields and are excluded from managed
serialization, errors, logs, Artifacts, and output.

## Real manga HTTP Adapter

Install `[manga]`, then independently install/license/run
`zyddnys/manga-image-translator`. LinguaSpindle downloads or starts none of its GPL source,
models, fonts, containers, or GPU runtime.

```bash
export LINGUASPINDLE_MIT_BASE_URL=http://127.0.0.1:5003
export LINGUASPINDLE_MIT_CONFIG_JSON='{}'
linguaspindle adapters doctor
```

The Mock Manga Adapter remains available without this extra. See
[Provider and Manga Adapter development](adapter-development.md).

## Upgrade from v0.2.0

Core-only use has no managed database. To retain the optional v0.2.0 runtime, stop all writers,
back up the complete data root, install `[runtime]`, and run `doctor` against the same root.
Migration 0003 is additive and retains old novel/manga rows/Artifacts. Follow the
[v0.2-to-v0.3 migration guide](migrations/v0.2-to-v0.3.md); rollback restores the whole backup.

## Development checkout

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -c constraints-v030.txt -e '.[dev]'
python -m ruff format --check src tests tools
python -m ruff check --no-cache src tests tools
python -m mypy src tools/generate_v020_acceptance.py tools/generate_v030_acceptance.py \
  tools/verify_v030_extras.py
python -m compileall -q src tests tools
python -m pytest -q
```

The v0.3.0 default test contract installs no browser and accesses no paid/network/model service.
Exact candidate outcomes belong in `acceptance/v0.3.0/` after they are captured.

## Troubleshooting

- CLI commands and optional facades normalize a missing feature as `DEPENDENCY_MISSING` and name
  the extra to install. Importing an optional implementation module directly follows ordinary
  Python behavior and raises an actionable `ModuleNotFoundError` when its dependency is absent.
- `linguaspindle doctor` checks optional runtime storage/database and configured Provider/Adapter
  status; an absent real manga service is optional for Mock/core use.
- `SOURCE_MISMATCH` means a saved manifest/result does not bind to the current source bytes.
- `SEGMENT_NOT_FOUND` means a selected/manual mapping used an ID outside the current manifest.
- Archive/EPUB error meanings and limits are in [EPUB support](epub.md).

Do not paste keys, source content, databases, or private Artifact payloads into public reports.
