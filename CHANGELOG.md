# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versioning follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

No changes beyond the v0.1.0 delivery are currently planned or implemented.

## [0.1.0] - 2026-07-19

### Added

- Persistent SQLite Project, Source, Job, Step Run, log, segment, QA, Provider-config, and Artifact
  metadata with package-owned migration and a local atomic payload store.
- Restart-aware sequential Job runner with persisted progress, safe-boundary pause/cancel,
  failed-work retry, partial success, normalized errors, and completed-Step reuse.
- TXT import, encoding detection, paragraph-aware segmentation, Mock/OpenAI-compatible Provider,
  basic QA, and TXT/JSON export.
- CBZ/image import, safe archive handling, Mock Manga Adapter, process-separated
  `manga-image-translator` HTTP Adapter, raw response Artifacts, and CBZ export.
- Shared no-login Web GUI, Typer CLI, FastAPI asynchronous Job API, OpenAPI, health, and doctor
  diagnostics.
- Non-root Dockerfile, loopback-published Compose deployment, runtime-only secrets, bilingual
  README, project policies, Adapter/API/install/deployment docs, and structured third-party
  inventory.
- Offline unit/integration/contract/browser acceptance coverage with no paid key or model download.

### Security

- Loopback is the non-container default; public deployment warnings are explicit.
- Imported archive paths and payload storage keys are traversal-safe and bounded.
- Runtime Provider keys are excluded from API configuration and centrally redacted before managed
  persistence.

### Known limitations

- One host, one data root, and an in-process polling worker; no distributed scheduling.
- TXT and CBZ/images only; EPUB is deferred.
- Active work interrupted by process exit is marked failed and explicitly retried rather than
  transparently resumed inside a Provider/Adapter call.
- The real manga Adapter exposes page-boundary cancellation and no streaming progress in v0.1.0.
- Upstream manga model/font redistribution terms require operator revalidation.

[Unreleased]: https://github.com/taoning0403/lingua-spindle/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/taoning0403/lingua-spindle/releases/tag/v0.1.0
