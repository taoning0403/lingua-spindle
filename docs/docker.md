# Docker deployment

Docker is an optional headless server/runtime deployment. It is not required for the default
Python library and it serves no GUI.

```bash
cp .env.example .env
docker compose build
docker compose up -d
docker compose ps
curl -fsS http://127.0.0.1:8765/health
curl -fsS http://127.0.0.1:8765/
```

The second response is a small JSON descriptor. OpenAPI is at
<http://127.0.0.1:8765/docs>.

## Network trust boundary

The process binds `0.0.0.0` only inside its isolated container so port forwarding works. Compose
publishes host `127.0.0.1:${LINGUASPINDLE_PORT:-8765}:8765`.

Do not change this to an all-interface host mapping on an untrusted network. LinguaSpindle has no
login or permission system; anyone who can reach the port can read/control the instance. Remote
use needs an explicit private network, VPN/Tailscale, Cloudflare Access, or access-controlling
reverse proxy. Outer identity remains outside LinguaSpindle.

## Image contents and runtime properties

- Base image: `python:3.12-slim`.
- Installs `.[all]` because the image supplies CLI, JSON server, persistent runtime, and optional
  HTTP clients; the default non-container Wheel remains minimal.
- Runs as UID/GID 10001 with no home/login shell.
- Compose root filesystem is read-only with `no-new-privileges`.
- `/tmp` is a bounded 512 MiB tmpfs for multipart spooling and temporary core output work.
- `/data` is the only persistent mutable root, backed by `linguaspindle-data`.
- Health checks use `http://127.0.0.1:8765/health` inside the container.
- No static Web GUI, browser, Playwright, external EPUB validator, upstream manga source/container,
  model, font, CUDA/GPU runtime, or paid Provider key is baked in.

The image includes HTTP clients for optional integrations but does not start or download their
services/assets.

## Resource limits

Compose passes:

| Variable | Default |
| --- | ---: |
| `LINGUASPINDLE_MAX_UPLOAD_BYTES` | `104857600` |
| `LINGUASPINDLE_MAX_ARCHIVE_FILES` | `2000` |
| `LINGUASPINDLE_MAX_ARCHIVE_BYTES` | `1048576000` |
| `LINGUASPINDLE_MAX_ARCHIVE_MEMBER_BYTES` | `104857600` |
| `LINGUASPINDLE_MAX_ARCHIVE_COMPRESSION_RATIO` | `100` |
| `LINGUASPINDLE_MAX_ARCHIVE_PATH_DEPTH` | `20` |

The 512 MiB `/tmp` budget leaves room for the default 100 MiB multipart source, request framing,
and simultaneous source/output temporary files. It is an operational default, not proof that
every allowed archive or Adapter output fits: raising upload/member limits or processing unusually
large outputs requires coordinated `/tmp`, `/data`, host-memory, reverse-proxy request,
processing-time, and Provider-cost budgets. An archive expansion bound is likewise not a memory
guarantee; parsing can buffer one already bounded member.

See [EPUB support](epub.md) for archive/path/reference guards.

## Inspect operation

```bash
docker compose ps
docker compose logs --tail=100 linguaspindle
docker compose exec linguaspindle linguaspindle doctor
docker compose exec linguaspindle linguaspindle adapters doctor
```

Managed Provider credentials are redacted, but logs can contain document-level diagnostics and
must still be treated as sensitive.

## Provider secret

A local ignored `.env` can set `LINGUASPINDLE_OPENAI_API_KEY`. On a controlled server, prefer the
deployment platform's secret injection. Docker inspection access is privileged because container
environment variables can be visible to operators.

Never add a key to Dockerfile `ARG`/`ENV`, an image layer, source control, API request, Job
snapshot, or Artifact. It must be supplied again after recreation.

## Persistent data, backup, and restore

The Volume contains SQLite plus every immutable/generated Artifact. Stop writes and archive the
whole Volume:

```bash
docker compose stop linguaspindle
docker run --rm \
  -v lingua-spindle_linguaspindle-data:/source:ro \
  -v "$PWD":/backup \
  alpine:3.22 tar -C /source -czf /backup/linguaspindle-data.tar.gz .
docker compose start linguaspindle
```

The actual Volume prefix can differ; confirm with `docker volume ls`. Restore into an empty Volume
while the service is stopped. Never combine a database from one snapshot with Artifact bytes from
another.

## External manga service

The Compose file deliberately does not run `manga-image-translator`. Operate/license it separately
and set a URL reachable from the LinguaSpindle container:

- Docker Desktop host: commonly `http://host.docker.internal:5003`;
- another Compose service: its DNS name on an explicit shared network;
- Linux host: a deliberate bridge/gateway or extra-host configuration.

```bash
export LINGUASPINDLE_MIT_BASE_URL=http://host.docker.internal:5003
docker compose up -d --force-recreate linguaspindle
docker compose exec linguaspindle linguaspindle adapters doctor
```

Do not expose the upstream API publicly either. Its source is GPL-3.0-only and the inspected
snapshot lacked a complete model/font redistribution inventory.

## Reverse proxy

An unauthenticated public reverse proxy is not sufficient. The outer layer must restrict
reachability/authenticate operators, terminate TLS as needed, and keep upload/time limits bounded.
It must not pass an identity into LinguaSpindle's domain.

## Upgrade from v0.2.0

1. Stop the service and back up the complete Volume.
2. Select/review the intended source and `CHANGELOG.md`.
3. Run `docker compose build --pull`.
4. Run `docker compose up -d`.
5. Check health, `doctor`, existing novel/manga Projects/Artifacts, and a representative download.

First v0.3.0 runtime startup applies additive migration `0003_headless_core.sql`, adding a nullable
stable Segment key/index without deleting existing v0.2.0 data. GUI removal has no data-deletion
step. See [migration guide](migrations/v0.2-to-v0.3.md).

There is no in-place downgrade. To return to v0.2.0, stop v0.3.0, restore the complete pre-upgrade
Volume, select the v0.2.0 image/source, and start only against that restored copy. Never run
v0.2.0 against schema version 3.
