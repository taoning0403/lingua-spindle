# Translation-tool research

Research snapshot: 2026-07-19. Commit dates and licenses were checked against public repository
metadata and the named source snapshots. Runtime behavior must be revalidated before pinning a
new upstream version.

## Manga candidates

| Candidate | Maintenance evidence | Automation surface | Runtime profile | License finding | Outcome |
| --- | --- | --- | --- | --- | --- |
| [`zyddnys/manga-image-translator`](https://github.com/zyddnys/manga-image-translator) | `efdc229d`, 2026-07-01; repository not archived | Folder/file batch CLI, FastAPI HTTP endpoints, streaming progress protocol, batch endpoints, Docker image | CPU supported; GPU optional; upstream image is documented at about 15 GB; models download at runtime | Code declares GPL-3.0-only. The inspected snapshot has one top-level GPL license but no complete separate inventory for downloaded weights or bundled fonts. | **Selected**, only as a separately installed HTTP service or command. |
| [`ogkalu2/comic-translate`](https://github.com/ogkalu2/comic-translate) | `010048b3`, 2026-07-09; repository not archived | Primarily a PySide desktop application/browser extension; no stable headless HTTP or Docker contract documented | CPU supported, NVIDIA GPU recommended; several model families | Code reports Apache-2.0; model licenses remain component-specific | Not selected because the automation boundary is less stable. |
| [`dmMaze/BallonsTranslator`](https://github.com/dmMaze/BallonsTranslator) | `2a20211c`, 2026-07-17; repository not archived | Headless folder CLI and rich desktop workflow; no documented stable HTTP API or supported Docker service | CPU/GPU paths and many optional models | Code reports GPL-3.0; model licenses remain component-specific | Strong alternative for a future subprocess Adapter. |

### Selected Adapter boundary

The v0.1.0 Adapter targets manga-image-translator's external HTTP service and its
`/translate/with-form/image` contract. LinguaSpindle sends an Artifact payload at the Adapter
boundary, records the redacted request configuration, stores the returned image and raw response
metadata as new Artifacts, and never imports or vendors upstream Python modules.

The upstream service documents batch and streaming APIs, but LinguaSpindle v0.1.0 deliberately
uses one image per request. Its Adapter declares progress and immediate cancellation unsupported:
closing an HTTP request is not evidence that model execution stopped. A cancelled Job therefore
stops only at the next safe image boundary.

### Code, model, and font licenses

- Upstream code is GPL-3.0-only. Process-separated HTTP interoperability avoids copying or
  linking upstream code into this Apache-2.0 repository. Operators must still comply with the
  upstream license for their deployment.
- Model mappings in the inspected snapshot download detector, OCR, inpainting, colorization,
  upscaling, and translation weights from upstream release assets. The snapshot supplies hashes
  but no complete per-weight license inventory. Weight redistribution is therefore **not
  approved** by LinguaSpindle.
- The snapshot contains Noto-derived, comic, Arial-compatible, and Microsoft-named font files but
  no complete per-font notice set. Some names strongly imply materially different redistribution
  terms. Font redistribution is therefore **not approved** by LinguaSpindle.
- The core image and repository contain none of those weights or fonts. The Adapter health output
  explains that the operator must install and license the external service separately.

This unresolved upstream inventory is a distribution blocker for bundling the tool, not a blocker
for a protocol-only Adapter or its mock contract tests.

## Novel and document candidates

| Candidate | Finding | v0.1.0 decision |
| --- | --- | --- |
| [`bookfere/Ebook-Translator-Calibre-Plugin`](https://github.com/bookfere/Ebook-Translator-Calibre-Plugin) | Active through 2026-01-01, GPL-3.0, Calibre-hosted EPUB workflow | Do not require Calibre or a GUI plugin for the mandatory TXT flow. Reconsider for EPUB after the core is stable. |
| [`xunbu/docutranslate`](https://github.com/xunbu/docutranslate) | Active through 2026-07-10, MPL-2.0, broad document/EPUB/PDF scope | Useful future reference, but its scope overlaps rather than supplies one narrow capability boundary. |
| Internal TXT parser/segmenter | UTF-8 normalized Artifacts, paragraph-aware deterministic segmentation, no heavyweight dependency | Selected for v0.1.0 because TXT is mandatory and its invariants need direct orchestration tests. |

EPUB remains deferred. This prevents an external document suite from becoming a prerequisite for
the required offline TXT + Mock Provider acceptance path.

## Revalidation checklist

Before changing the pinned upstream commit or recommending a production deployment, recheck:

- repository activity and security issues;
- HTTP/CLI request and output compatibility;
- model download URLs and hashes;
- every selected weight's license and acceptable use terms;
- every rendering font's license;
- CPU/GPU and disk requirements; and
- whether cancellation actually terminates active inference.
