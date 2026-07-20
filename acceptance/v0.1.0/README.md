# LinguaSpindle v0.1.0 acceptance index

## Final conclusion

**Pass — accepted and published as a WSL2/Linux Technical Preview.** The first local acceptance
run could not reach Docker and recorded that item as `Blocked`. A later supplemental run used the
ordinary WSL Linux Docker CLI and produced real build, Compose, persistence, browser, recovery,
and security evidence, so Docker's final v0.1.0 result is `Pass`. The original blocker remains in
the main report as execution history and is not a competing final status.

- Version position: first technical preview; TXT and image/CBZ translation orchestration.
- Git tag: [`v0.1.0`](https://github.com/taoning0403/lingua-spindle/releases/tag/v0.1.0), targeting
  commit `90439f66d2d2ddf656174bc33a34ffdacee2b41d`.
- GitHub Release: `LinguaSpindle v0.1.0 — Technical Preview`, published
  `2026-07-19T11:54:18Z`, prerelease.
- Release notes: [docs/releases/v0.1.0.md](../../docs/releases/v0.1.0.md).
- Release publication report: [reports/publication-report.md](reports/publication-report.md).

## Reports and evidence

- [Main acceptance report](reports/acceptance-report.md) — initial local execution and the complete
  v0.1.0 implementation surface.
- [Docker/WSL supplemental report](reports/supplemental-docker-wsl-report.md) — superseding Docker
  evidence and the final WSL2/Linux decision.
- [Supplemental JSON](evidence/supplemental-docker-wsl-report.json) and
  [command transcript](evidence/command-log.txt).
- [Publication evidence](evidence/publication-report.json).
- [Archive checksums](evidence/checksums.sha256).

## Test environment

- Host: Ubuntu 26.04 LTS on WSL2, x86_64; Python 3.14.4; Node 18.20.7 for JavaScript syntax.
- Container: Python 3.12.13; Docker Desktop Engine 29.6.1; Compose 5.3.0.
- Browser: Playwright 1.61.0 with Headless Chromium 149.0.7827.55.
- Current Codex restricted sandbox could not access `/var/run/docker.sock`; the same ordinary WSL
  Linux CLI passed outside that sandbox.

## Verified capabilities

- TXT → segmentation → Mock/OpenAI-compatible translation → QA → TXT/JSON.
- Image/CBZ → Mock manga Adapter → per-page/raw Artifacts → CBZ.
- Shared GUI, CLI, and asynchronous API over one application and Job core.
- Pause, resume, cancel, retry, process-interruption recovery, completed-Step and Segment reuse.
- SQLite/Artifact persistence across restart, Compose down/up, rebuild, and force-recreate.
- Loopback-only Compose publication, non-root/read-only container properties, wheel resources,
  OpenAPI boundary, and whole-data-root Provider-secret scans.
- One explicit-cost, three-Segment real OpenAI-compatible Provider run.

## Limited, blocked, or not executed

- **Blocked optional external test:** live `manga-image-translator` model execution; no service,
  model/font assets, hardware, or complete per-asset license inventory was supplied. Contract and
  unavailable-status tests passed, but they are not a live model run.
- **Not executed:** native Windows PowerShell/Python runtime and a Python-version matrix.
- **Limited:** the real Provider run was intentionally tiny; long documents, concurrency,
  rate-limit behavior, and long-term stability were not accepted.
- **Environment limitation:** direct Docker Hub OAuth timed out; the exact official image digest
  was obtained from AWS Public ECR before the unchanged Dockerfile build passed.

No product acceptance item finished as `Fail`.

## Release artifacts

Release binaries stay on GitHub rather than being duplicated in Git. The Release page displays
six downloadable source/assets in total: the four uploaded assets below plus GitHub's two
automatically generated source-code archives.

| Asset | Bytes | SHA-256 |
| --- | ---: | --- |
| `acceptance-v010-supplement.md` | 20,714 | `50122c6f837d34cda19502156a20ef2705762644315e4f4e4f08b0b9d868e499` |
| `linguaspindle-0.1.0-py3-none-any.whl` | 67,319 | `8256ec41e189f3a9abad235d09843d09f4f2faaaa5a871e79fef75674ef70f28` |
| `linguaspindle-0.1.0.tar.gz` | 62,610 | `7af799d02754a63fc05781d182732f8d4442df1c260c9bd5dea450f9a3a1a24a` |
| `SHA256SUMS` | 206 | `f82e14be9fb972640cdada7db826ff676461df6197a6c8a44c202444da578c68` |

The supplemental report also names screenshots, traces, downloads, recovery evidence, and helper
scripts produced in the original acceptance workspace. Those files were deliberately excluded
from Git and the Release because they may contain runtime or source data; this checkout does not
silently claim to contain them. See [artifacts/README.md](artifacts/README.md).

## Known limitations

v0.1.0 supports TXT novels and image/CBZ manga only, uses one host/data root and an in-process
worker, exposes polling rather than streaming progress, provides basic read-only QA rather than an
editor, and reads Artifact HTTP downloads into memory. These are historical v0.1.0 limits; later
version work must preserve this accepted baseline while extending it.
