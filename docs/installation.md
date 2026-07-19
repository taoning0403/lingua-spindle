# Local installation and operation

## Requirements

- Python 3.11 or newer on Windows, Linux, macOS, or WSL.
- A writable data directory.
- No API key, Docker, GPU, model, or external service for the Mock/TXT path.

The package and CLI use the same implementation in every environment. SQLite and all payloads
live below one data root.

## Linux, macOS, and WSL

```bash
git clone https://github.com/taoning0403/lingua-spindle.git
cd lingua-spindle
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
linguaspindle doctor
linguaspindle serve
```

Open <http://127.0.0.1:8765>. Stop with Ctrl-C.

If the Python distribution omits `venv`/`ensurepip`, install its OS package first (for example,
`python3-venv` on Debian/Ubuntu) or use a standards-compatible virtual-environment tool. Do not
install LinguaSpindle as root merely to bypass a missing virtual environment.

## Windows PowerShell

Install a supported 64-bit Python from python.org or Windows Package Manager, then:

```powershell
git clone https://github.com/taoning0403/lingua-spindle.git
Set-Location lingua-spindle
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
linguaspindle doctor
linguaspindle serve
```

When local policy prevents activation, use explicit executables:

```powershell
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\linguaspindle.exe doctor
.venv\Scripts\linguaspindle.exe serve
```

Paths are handled through `pathlib` and platformdirs. Avoid placing the data root on a network
filesystem: SQLite WAL and atomic Artifact publication are supported on a local filesystem.

## Data location

The default comes from the platform application-data convention. For predictable backups, set it
explicitly:

```bash
export LINGUASPINDLE_DATA_DIR="$PWD/data"
linguaspindle serve
```

PowerShell:

```powershell
$env:LINGUASPINDLE_DATA_DIR = "$PWD\data"
linguaspindle serve
```

The root contains `database/linguaspindle.sqlite3`, `artifacts/`, `exports/`, `logs/`, and
`cache/`. Artifact payloads currently live under `artifacts/projects/<project-id>/...`; callers
use Artifact IDs, never these private paths.

Back up or move the entire root while the service is stopped. Copying only SQLite or only
Artifacts creates an incomplete backup.

## Configuration

All settings are process environment variables; CLI `--data-dir`, `serve --host`, and
`serve --port` can override the most common values.

| Variable | Default | Meaning |
| --- | --- | --- |
| `LINGUASPINDLE_DATA_DIR` | platform data directory | Mutable state root. |
| `LINGUASPINDLE_HOST` | `127.0.0.1` | HTTP bind address. Non-loopback requires an outer perimeter. |
| `LINGUASPINDLE_PORT` | `8765` | HTTP port. |
| `LINGUASPINDLE_LOG_LEVEL` | `INFO` | Uvicorn log level. |
| `LINGUASPINDLE_WORKER_POLL_SECONDS` | `0.25` | Durable queue polling interval. |
| `LINGUASPINDLE_MAX_UPLOAD_BYTES` | `104857600` | Source upload limit. |
| `LINGUASPINDLE_MAX_ARCHIVE_FILES` | `2000` | Maximum CBZ members. |
| `LINGUASPINDLE_MAX_ARCHIVE_BYTES` | `1048576000` | Maximum expanded CBZ bytes. |
| `LINGUASPINDLE_OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible base URL. |
| `LINGUASPINDLE_OPENAI_API_KEY` | unset | Runtime-only Provider secret. |
| `LINGUASPINDLE_OPENAI_MODEL` | `gpt-4.1-mini` | Provider model string. |
| `LINGUASPINDLE_OPENAI_TIMEOUT_SECONDS` | `60` | Per-call timeout. |
| `LINGUASPINDLE_OPENAI_CONCURRENCY` | `2` | Process-local Provider concurrency bound. |
| `LINGUASPINDLE_OPENAI_MAX_RETRIES` | `3` | Retries after the initial call. |
| `LINGUASPINDLE_MIT_BASE_URL` | unset | Separate manga-image-translator service URL. |
| `LINGUASPINDLE_MIT_TIMEOUT_SECONDS` | `600` | Per-image Adapter timeout. |
| `LINGUASPINDLE_MIT_CONFIG_JSON` | `{}` | Upstream form configuration JSON. |

Base URLs must be HTTP(S) and cannot contain credentials, query strings, or fragments. JSON
configuration must be an object. Numeric settings are bounded and reject NaN/infinity.

## First offline run

Create `sample.txt`, then:

```bash
linguaspindle projects create \
  --name "Offline sample" --kind novel \
  --source-language en --target-language fr \
  --source sample.txt
linguaspindle projects list
linguaspindle run PROJECT_ID --provider mock
linguaspindle export PROJECT_ID
```

The last command returns Artifact metadata and download URLs. CLI and Web use the same data root;
the Project appears in the GUI immediately.

## Upgrade and recovery

Back up the full data root before upgrading. Package-owned migrations are forward-only and run at
startup. If the process exits during a running Step, startup marks that Job/Step failed with
`PROCESS_INTERRUPTED`; use the Job retry action. Completed earlier Steps retain their outputs and
attempt counts.

## Troubleshooting

`linguaspindle doctor` checks directories, SQLite, a real Docker Engine probe when the command is
present, port availability, Provider status, Adapter health, and external model/font ownership.
Docker and the real manga Adapter are optional for the offline path and therefore appear as
optional failures when unavailable.

For a clean diagnostic with explicit state:

```bash
linguaspindle doctor --data-dir ./diagnostic-data
linguaspindle adapters doctor --data-dir ./diagnostic-data
```

Do not paste populated keys, source content, database files, or Artifact payloads into public bug
reports.
