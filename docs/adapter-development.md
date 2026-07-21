# Provider and Manga Adapter development

LinguaSpindle has two extension contracts because novel text translation and whole-page manga
translation have different inputs, outputs, health, and capability requirements.

- `TranslationProvider` translates one `TranslationRequest` into text/model/usage.
- `MangaTranslationAdapter` declares a manifest and health, then translates one image into an
  image plus structured raw metadata.

Do not combine them into a vendor-shaped generic plugin. The pure core supplies ordering, bounded
retry, events, cancellation, partial results, and error normalization around both contracts.

## Translation Provider

The structurally typed contract in `providers/base.py` is intentionally minimal:

```python
class TranslationProvider(Protocol):
    id: str

    def translate(self, request: TranslationRequest) -> TranslationResult: ...
```

A custom Provider receives explicit text, source/target language, style, prompt/version, and model
parameters. It must return non-empty text and a model label. It may return non-negative token usage.

Provider rules:

- accept credentials/transport configuration through the constructor or caller-owned resolver;
- never read the core's global environment/Settings;
- never put a key/header/secret derivative in `repr`, serialization, results, exceptions, or logs;
- make one logical transport attempt and let core orchestration own retry;
- raise `LinguaError` with a stable code for expected failure; and
- set `retryable=True` only for a condition that may succeed later.

`MockProvider` is the default offline implementation. `OpenAICompatibleProvider` is installed by
`linguaspindle[openai]` and takes `OpenAIProviderConfig(api_key=... | api_key_resolver=...)`.
Environment lookup belongs to optional CLI/server configuration only.

## Manga Adapter manifest

Every `MangaTranslationAdapter` declares:

- stable Adapter ID/display name and Adapter/upstream versions;
- invocation type (`http_service`, future subprocess/container, or explicit mock);
- capabilities, input/output formats, and languages;
- GPU requirement;
- immediate cancel and internal progress support;
- health-check/configuration guidance;
- upstream URL/license; and
- whether LinguaSpindle modifies the upstream.

`AdapterRegistry.get(id, capability)` validates declared capability. Application/Pipeline code
must not branch on an upstream product name.

## Manga call contract

```python
class MangaTranslationAdapter(Protocol):
    manifest: AdapterManifest

    def health(self) -> AdapterHealth: ...

    def translate_image(
        self,
        *,
        image: bytes,
        filename: str,
        source_language: str,
        target_language: str,
    ) -> MangaAdapterResult: ...
```

Return a valid image, matching `image/*` media type, and bounded JSON-compatible raw metadata.
Never overwrite input. Redact secrets and avoid unbounded response bodies.

The pure core accepts caller paths/streams/bytes and returns typed page results; it has no Project,
Job, database, or Artifact requirement. The optional runtime maps immutable source/page input,
translated images, raw results, logs/errors, and final CBZ to Artifacts with provenance.

## Errors, retry, progress, and cancellation

Map expected failure to stable codes:

| Failure | Code |
| --- | --- |
| Missing/unreachable service or dependency | `ADAPTER_UNAVAILABLE` |
| Upstream HTTP/process rejection | `EXTERNAL_COMMAND_FAILED` |
| Timeout | `TIMEOUT` |
| Missing or invalid image output | `OUTPUT_MISSING` or `INVALID_FORMAT` |
| Invalid caller/operator configuration | `CONFIGURATION_ERROR` |

Core orchestration performs bounded retries only for retryable errors and keeps page-level partial
results. Adapter methods should not implement a second conflicting retry policy.

Declare progress/cancellation truthfully. If a call cannot stop, do not claim immediate cancel.
The core observes cancellation before the next page and emits no fabricated inside-page percentage.
An optional persistent Job stays `cancelling` until the current Adapter call returns or times out.

## Tests required for an extension

1. Protocol/manifest and health behavior.
2. Input/output, media signature, language, and configuration mapping.
3. Timeout, unavailable, upstream rejection, invalid/empty output, and redaction.
4. Accurate cancellation/progress declarations.
5. Pure-core orchestration with partial result and page-boundary cancellation.
6. Optional-runtime output/raw/log Artifact provenance when applicable.
7. An offline fake/mock with no paid key, Internet, model download, font, or GPU.

Live service/model validation is an explicit optional external acceptance step. A passing fake
HTTP contract is not a live upstream model run.

## Licensing checklist

Before accepting an external Adapter:

- record upstream repository, exact release/commit, maintenance evidence, and integration method;
- identify code license and whether process separation is required;
- inventory each downloaded/bundled model and its source/license;
- inventory each font and its source/license/embedding terms;
- state what is copied, modified, built, installed, downloaded, or redistributed;
- update `third-party-components.toml`, `THIRD_PARTY_NOTICES.md`, and research; and
- never silently download or execute network code during core installation.

An external process boundary preserves the core's package boundary; it does not remove the
operator's upstream obligations.

## manga-image-translator HTTP Adapter

Install the protocol client only:

```bash
python -m pip install 'linguaspindle[manga]'
```

Programmatic configuration is explicit:

```python
from linguaspindle.adapters.manga_image_translator import (
    MangaImageTranslatorConfig,
    MangaImageTranslatorHttpAdapter,
)

adapter = MangaImageTranslatorHttpAdapter(
    MangaImageTranslatorConfig(
        base_url="http://127.0.0.1:5003",
        timeout_seconds=600,
        request_config={},
    )
)
```

The optional CLI/server environment adapter supports:

```bash
export LINGUASPINDLE_MIT_BASE_URL=http://127.0.0.1:5003
export LINGUASPINDLE_MIT_TIMEOUT_SECONDS=600
export LINGUASPINDLE_MIT_CONFIG_JSON='{}'
linguaspindle adapters doctor
```

Health requests `/openapi.json`. Translation posts one image and JSON `config` to
`/translate/with-form/image`; common target labels map to upstream codes. The Adapter validates
image output and returns redacted raw metadata.

It targets the separately operated `zyddnys/manga-image-translator` service researched at commit
`efdc229de8aa0f3d4051ad97664adc62dd5ac605`. It declares no immediate cancellation or streaming
progress. Upstream is GPL-3.0-only and the inspected model/font inventory was incomplete, so
LinguaSpindle distributes none of its source, container, weights, fonts, or GPU runtime. Operators
install, license, run, and secure it independently.
