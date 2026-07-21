# Python library API

The default `linguaspindle` installation is a synchronous, side-effect-free translation library.
Importing it does not read environment variables, create a data directory, open a database, or
start a worker. Public functions accept `Path`/path-like values, binary streams, and bytes; output
is always a caller-supplied path or binary stream.

```bash
python -m pip install linguaspindle
```

The default package contains TXT/EPUB processing, the public Provider and Manga Adapter
protocols, `MockProvider`, and `MockMangaAdapter`. Optional integrations are described in
[Installation](installation.md).

## TXT translation

The high-level function inspects, translates, and rebuilds through the same lower-level core:

```python
from pathlib import Path

from linguaspindle import MockProvider, TranslationOptions, translate_document

result = translate_document(
    Path("novel.txt"),
    Path("novel.zh-CN.txt"),
    MockProvider(),
    TranslationOptions(source_language="en", target_language="zh-CN"),
)

print(result.translations.status)
print(result.build.output_sha256)
```

TXT inspection exposes detected encoding, confidence, newline style, segmentation version,
stable Segment IDs, source offsets, content roles, hashes, and joiners. Reconstruction starts
from the immutable source, substitutes only provided translations, and preserves all other source
spans. The v0.3 TXT output contract is UTF-8 with LF newlines; `BuildResult.details` records both.

Empty input, binary content disguised as text, unrecognized encoding, and input beyond
`TranslationOptions.max_source_bytes` return a `LinguaError` with a stable code.

## EPUB translation

The same entry point recognizes `.epub` input and preserves the EPUB package structure:

```python
from pathlib import Path

from linguaspindle import ArchiveLimits, MockProvider, TranslationOptions, translate_document

result = translate_document(
    Path("book.epub"),
    Path("book.fr.epub"),
    MockProvider(),
    TranslationOptions(source_language="en", target_language="fr"),
    archive_limits=ArchiveLimits(max_files=2_000),
)
```

Common valid, unencrypted EPUB 2 and EPUB 3 packages are supported. The output is rebuilt from
the original archive, re-inspected, and checked for package/reference consistency and unchanged
resource payloads. It updates target-language metadata without flattening chapters, navigation,
links, anchors, images, CSS, or fonts. See [EPUB rules](epub.md) for the exact visible-text and
resource policy.

`ArchiveLimits` is explicit per operation. The core never reads global `Settings`. A path output
cannot be the same path as the source, and an existing destination requires `overwrite=True`.

The top-level `inspect_epub` and `build_translated_epub` names are typed, format-specific
conveniences over the same document core. They return `DocumentManifest` and `BuildResult`, not
the private package dictionaries used by the implementation module:

```python
from linguaspindle import TranslationOptions, build_translated_epub, inspect_epub

options = TranslationOptions(source_language="en", target_language="de")
manifest = inspect_epub("book.epub", options=options)
build = build_translated_epub(
    "book.epub",
    "book.reviewed.de.epub",
    manifest,
    {manifest.segments[0].segment_id: "Reviewed text"},
    target_language="de",
)
```

## Inspect, select, translate, and rebuild

Use the lower-level calls when a caller owns a review or partial-retranslation workflow:

```python
from pathlib import Path

from linguaspindle import (
    MockProvider,
    TranslationOptions,
    inspect_document,
    rebuild_document,
    translate_segments,
)

source = Path("book.epub")
options = TranslationOptions(source_language="en", target_language="de")
manifest = inspect_document(source, options=options)

selected = [manifest.segments[1].segment_id, manifest.segments[4].segment_id]
batch = translate_segments(
    manifest,
    MockProvider(),
    options,
    selected_segment_ids=selected,
)

build = rebuild_document(
    source,
    manifest,
    batch,
    Path("book.partial.de.epub"),
    target_language=options.target_language,
)
```

`selected_segment_ids=None` means all Segments. An explicitly empty iterable means none; it
returns a `noop` batch and never calls the Provider. Unknown IDs return `SEGMENT_NOT_FOUND` before
translation begins. Records always follow source Segment order, even when `concurrency` is greater
than one. A partial failure preserves successful records and records one normalized error per
failed Segment.

An unchanged source and the same inspection options produce the same Segment IDs and order.
Changing source bytes or a translation-input policy may change the corresponding identity/hash.
Saved manifests are checksum-validated before extraction or reconstruction.

`extract_segments(source, manifest, options=options)` returns the ordered `tuple[Segment, ...]`
without translating anything. Supplying a saved manifest makes extraction verify both the
immutable source checksum and the deterministic Segment IDs; repeat the original inspection
options so the operation policy also matches. Omit the manifest to inspect and return the current
Segments in one call.

## Rebuild with human-authored text

LinguaSpindle deliberately has no proofreader or approval workflow. A caller can supply its own
text directly, without a Provider call:

```python
manifest = inspect_document("novel.txt", options=options)
manual = {
    manifest.segments[0].segment_id: "A carefully edited first paragraph.",
}

rebuild_document(
    "novel.txt",
    manifest,
    manual,
    "novel.edited.txt",
    target_language=options.target_language,
)
```

Unmapped Segments retain their source text. Caller-supplied successful/manual translations passed
to `translate_segments(..., existing_translations=...)` win and are not sent to the Provider or
silently overwritten.

## Manga image and CBZ translation

`inspect_manga` accepts one PNG/JPEG/WebP image or a CBZ/ZIP archive. Archive pages are naturally
ordered and receive stable page IDs. Safe paths, supported compression, member count, per-member
and total expanded bytes, compression ratio, and path depth are checked before Adapter calls.

```python
from linguaspindle import (
    MockMangaAdapter,
    TranslationOptions,
    build_manga_output,
    extract_manga_pages,
    inspect_manga,
    translate_manga,
)

manifest = inspect_manga("chapter.cbz")
pages = extract_manga_pages("chapter.cbz", manifest)
translated = translate_manga(
    "chapter.cbz",
    MockMangaAdapter(),
    TranslationOptions(source_language="ja", target_language="en"),
    manifest=manifest,
)
build = build_manga_output(translated, "chapter.en.cbz")
```

`extract_manga_pages` returns ordered `(MangaPage, bytes)` pairs and re-inspects the source under
the supplied `ArchiveLimits` before reading page payloads, so a caller-supplied manifest cannot
bypass archive or source checks.

Each page result can contain a translated image, normalized logs, a redacted raw result, attempts,
or an error. Successful pages remain available when another page fails. Output includes successful
pages in source order. The built-in Mock Adapter returns the input image unchanged and exists for
deterministic offline tests; it is not evidence of real OCR, translation, inpainting, or
typesetting.

The optional real HTTP Adapter remains a separate integration. Install `linguaspindle[manga]` and
construct `MangaImageTranslatorHttpAdapter` with an explicit
`MangaImageTranslatorConfig`; the library never starts or downloads the upstream service.

## Custom Translation Provider

The Provider contract is structurally typed and intentionally small:

```python
from linguaspindle import TranslationRequest, TranslationResult


class MyProvider:
    id = "my-provider"

    def translate(self, request: TranslationRequest) -> TranslationResult:
        translated = my_translation_call(request.text, request.target_language)
        return TranslationResult(text=translated, model="my-model")
```

The caller owns authentication and transport. Raise `LinguaError` for a known stable failure and
set `retryable=True` only when retry can reasonably succeed. The orchestration core, not a custom
Provider, owns bounded retries and deterministic result ordering.

`linguaspindle[openai]` supplies `OpenAICompatibleProvider`. Pass an API key or key resolver to
`OpenAIProviderConfig`; do not put credentials in serialized options:

```python
from linguaspindle.providers.openai_compatible import (
    OpenAICompatibleProvider,
    OpenAIProviderConfig,
)

provider = OpenAICompatibleProvider(
    OpenAIProviderConfig(
        base_url="https://api.example.test/v1",
        model="example-model",
        api_key_resolver=load_key_from_your_secret_store,
    )
)
```

## Custom Manga Adapter

A Manga Adapter has a declared manifest, health check, and one whole-image call. It is separate
from the text Provider contract:

```python
from linguaspindle import AdapterHealth, AdapterManifest, MangaAdapterResult


class MyMangaAdapter:
    manifest = AdapterManifest(
        id="my-manga",
        display_name="My manga service",
        adapter_version="1.0.0",
        upstream_version="2026-07",
        invocation_type="http_service",
        capabilities=("manga_full_pipeline",),
        input_formats=("png", "jpeg", "webp"),
        output_formats=("png",),
        languages=("*",),
        requires_gpu=False,
        supports_cancel=False,
        supports_progress=False,
        health_check="GET /health",
        configuration_help="Configure the service URL in the caller.",
        upstream_url="https://example.test/my-service",
        upstream_license="Example license",
        modified=False,
    )

    def health(self) -> AdapterHealth:
        return AdapterHealth(True, "ready")

    def translate_image(
        self,
        *,
        image: bytes,
        filename: str,
        source_language: str,
        target_language: str,
    ) -> MangaAdapterResult:
        output, raw = call_my_service(image, source_language, target_language)
        return MangaAdapterResult(output, "image/png", raw)
```

Do not advertise progress or immediate cancellation unless the implementation can honor that
contract. Core cancellation for the current real Adapter is observed between pages, not during a
single remote image call.

## Events, cancellation, and partial results

Both novel and manga orchestration accept a synchronous `on_event` callback and a caller-owned
`CancellationToken`:

```python
from linguaspindle import CancellationToken

token = CancellationToken()


def report(event):
    print(event.kind, event.completed, event.total)
    if should_stop():
        token.cancel()


batch = translate_segments(
    manifest,
    provider,
    options,
    cancellation=token,
    on_event=report,
)
```

Events report start, retry, success/failure, progress, cancellation, and completion. They are
notifications, not durable storage. Novel cancellation is observed between Provider attempts and
Segments; manga cancellation is observed at page boundaries. Put the synchronous call in the
thread/task system chosen by the embedding application if non-blocking execution is required.

## Errors

Public operations raise `LinguaError`. Branch on `error.code`, not message text:

```python
from linguaspindle import ErrorCode, LinguaError, inspect_document

try:
    manifest = inspect_document("source.epub")
except LinguaError as error:
    if error.code is ErrorCode.EPUB_PROTECTED:
        reject_protected_source()
    else:
        record(error.to_dict())
```

Stable codes include input/archive bounds, unsafe or protected EPUBs, source/manifest mismatch,
unknown Segment IDs, missing optional dependencies, Provider/Adapter failure, timeout,
cancellation, missing output, invalid state, storage, and unknown failures. Pass active credential
values through `sensitive_values` when invoking third-party implementations so normalized details
and events can redact them.

## Serialization and recovery

Long-lived public results use a `schema_version` field and matching `to_dict`/`from_dict` methods:

```python
import json

from linguaspindle import DocumentManifest, TranslationBatchResult

saved_manifest = json.dumps(manifest.to_dict(), ensure_ascii=False)
saved_batch = json.dumps(batch.to_dict(), ensure_ascii=False)

manifest = DocumentManifest.from_dict(json.loads(saved_manifest))
batch = TranslationBatchResult.from_dict(json.loads(saved_batch))
```

`DocumentTranslationResult`, `BuildResult`, `MangaManifest`, and `MangaTranslationResult` support
the same pattern. Manga translation serialization includes page bytes as base64 by default so a
restored result can be built later; use `to_dict(include_binary=False)` only for metadata-only
reporting. Unknown schema versions are rejected instead of being silently interpreted.

Serialization is not an approval database or revision history. The caller chooses where and how
to persist manifests, results, source files, and business state. The optional local runtime is
available when Project/Job/Artifact persistence and restart recovery are desired.
