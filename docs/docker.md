# Docker deployment

## Core Compose deployment

The supplied Compose file builds the same Python application used outside Docker. It persists all
mutable state in one named volume and publishes the host port only on loopback.

```bash
cp .env.example .env
docker compose build
docker compose up -d
docker compose ps
curl -fsS http://127.0.0.1:8765/health
```

The application listens on `0.0.0.0` *inside* its isolated container so container port forwarding
works. Compose maps it as `127.0.0.1:8765:8765`, preserving the host trust boundary. Do not change
that to `8765:8765` or `0.0.0.0:8765:8765` on an untrusted host without a private network or an
access-controlling reverse proxy in front.

## Runtime properties

- Base: `python:3.12-slim`.
- Application UID/GID: `10001`, with no login shell or home directory.
- Compose root filesystem: read-only, with a bounded `/tmp` tmpfs.
- Mutable root: `/data`, backed by `linguaspindle-data`.
- Health endpoint: `http://127.0.0.1:8765/health` inside the container.
- No manga upstream, model, font, CUDA runtime, browser, or development dependency in the image.

Inspect status and logs:

```bash
docker compose ps
docker compose logs --tail=100 linguaspindle
docker compose exec linguaspindle linguaspindle doctor
```

Logs may contain document-level diagnostics even though managed Provider secrets are redacted.
Treat them as sensitive.

## Provider secret

For local development, a populated `.env` can supply `LINGUASPINDLE_OPENAI_API_KEY`; `.env` is
ignored by Git. For a controlled server, prefer the deployment platform's environment/secret
injection. Compose environment variables are visible to users allowed to inspect the container,
so Docker access remains privileged access.

Never add the key as a Dockerfile `ARG`/`ENV`, bake it into an image, or commit it. It is read at
runtime and must be supplied again after recreation.

## Data backup and restore

Stop writes before taking a filesystem-level archive:

```bash
docker compose stop linguaspindle
docker run --rm \
  -v lingua-spindle_linguaspindle-data:/source:ro \
  -v "$PWD":/backup \
  alpine:3.22 tar -C /source -czf /backup/linguaspindle-data.tar.gz .
docker compose start linguaspindle
```

The actual volume name may include a different Compose project prefix; confirm it with
`docker volume ls`. Restore into an empty volume while the service is stopped. Keep SQLite and
Artifact payloads together.

## External manga service

The core Compose file deliberately does not start `manga-image-translator`. Operate it under its
own license and resource policy. Configure a URL reachable *from the core container*:

- Docker Desktop host service: commonly `http://host.docker.internal:5003`;
- another Compose service: use its service DNS name on a shared network;
- Linux host service: use a deliberate bridge/gateway configuration or an extra host mapping.

Set `LINGUASPINDLE_MIT_BASE_URL` in `.env`, recreate the core, then run:

```bash
docker compose up -d --force-recreate linguaspindle
docker compose exec linguaspindle linguaspindle adapters doctor
```

Do not expose the upstream manga API publicly either. Its code is GPL-3.0-only, and the inspected
snapshot lacked a complete per-model/per-font redistribution inventory.

## Reverse proxy and remote access

LinguaSpindle has no sessions or built-in authentication. A reverse proxy that merely forwards a
public port is insufficient. Use an outer mechanism that restricts reachability and, when needed,
authenticates operators—such as a private VPN/Tailscale network, Cloudflare Access, or an
identity-aware proxy. Terminate TLS and enforce upload/time limits there.

The outer identity is not passed into or stored by LinguaSpindle.

## Upgrade

1. Back up the entire volume.
2. Pull the intended source/tag and review `CHANGELOG.md`.
3. Run `docker compose build --pull`.
4. Run `docker compose up -d`.
5. Check health, `linguaspindle doctor`, and recent Jobs.

Forward-only database migrations run on startup. An active Step interrupted during replacement is
marked failed and remains explicitly retryable; completed Steps are reused.
