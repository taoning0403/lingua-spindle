# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versioning follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

The v0.2.0 tag and GitHub Release remain pending acceptance-report review.

## 0.2.0 - 2026-07-20

### Added

- Common unencrypted EPUB 2/3 inspection with package metadata, manifest, spine, navigation,
  reference, cover, document, and visible-text manifests.
- Structure-preserving EPUB translation Pipeline using the existing Project, Job, Step, Segment,
  Artifact, Provider, QA, control, retry, and recovery mechanisms.
- Stable per-slot text locators, source/input hashes, source-document lineage, and cross-Job reuse
  of successful unchanged translation inputs.
- EPUB reconstruction with source-text fallback for failed/missing translations, target-language
  metadata, a fresh validation/re-import pass, and byte comparison for unmodified resources.
- EPUB Project/upload/run/export coverage through the same Web GUI, CLI, and HTTP application
  core; CLI export can copy one Artifact to an explicit output path.
- Configurable archive member-size, total expanded-size, file-count, compression-ratio, and path-
  depth limits, plus stable EPUB/archive rejection codes.

### Changed

- Source uploads are published from streams with a hard source-byte bound; failed imports do not
  publish a usable Project. Artifact HTTP downloads and CLI copies avoid whole-file buffering.
- Pipeline selection now considers the immutable Source kind so TXT, EPUB, and manga inputs choose
  compatible Presets deterministically.
- Forward-only schema migration `0002_epub.sql` adds Source inspection metadata and EPUB Segment
  lineage/reuse fields while retaining existing v0.1.0 Projects, Jobs, and Artifacts.
- The Compose upload temporary filesystem is 128 MiB and all archive resource limits are exposed
  as runtime environment settings.
- OpenAPI now describes typed Project/Job/Artifact responses and the stable application error
  envelope; Projects with active Jobs require terminal cancellation before deletion.

### Security

- Reject encrypted/protected, malformed, unsupported, duplicate/case-conflicting, traversal,
  symlink, over-deep, oversized, over-member, and excessive-ratio EPUB archives before Project
  publication.
- Uploaded XHTML is parsed as data and is never injected as executable GUI markup; scripts,
  styles, code, SVG, Ruby pronunciation/fallback text, paths, URLs, anchors, and structural IDs are
  excluded from translation.
- Raw and bounded expanded archive members are scanned for the active runtime Provider key before
  publication. User-authored prose preserves ordinary secret-shaped words while diagnostic and
  configuration payloads retain strict redaction. The no-user/no-auth/no-tenant boundary remains.

### Known limitations

- EPUB support targets common, valid, unencrypted EPUB 2 and EPUB 3 packages; DRM bypass and
  vendor-specific encrypted content are explicitly unsupported.
- Reconstruction preserves source structure instead of normalizing arbitrary invalid publisher
  markup. External `epubcheck` evidence is optional; the default path uses independent built-in
  validation and re-import.
- EPUB results are inspectable and downloadable, but v0.2.0 does not add a professional sentence
  editor, translation memory, collaboration, or distributed workers.

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
- Shared no-login Web GUI, Typer CLI with an explicit `--version` release check, FastAPI
  asynchronous Job API, OpenAPI, health, and doctor diagnostics.
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
