# Adapter development and operation

Adapters isolate external-tool details from application and Pipeline code. A Pipeline requests a
capability; only the Adapter knows an upstream's HTTP paths, process arguments, directories, raw
responses, progress, and cancellation limitations.

## Manifest contract

Every Adapter declares:

- stable ID and display name;
- Adapter and pinned/researched upstream version;
- invocation type (`http_service`, future subprocess/container, or explicit mock);
- capabilities;
- input/output formats and supported languages;
- GPU requirement;
- immediate cancel/progress support;
- health-check method and configuration guidance;
- upstream URL and license; and
- whether LinguaSpindle modifies the upstream.

The current Python contract is `AdapterManifest` and `Adapter` in
`src/linguaspindle/adapters/base.py`. `AdapterRegistry.get(id, capability)` validates capability;
business code must not branch on a product name.

## Payload contract

Pipeline and application code exchange Artifact IDs. The runtime may resolve a private local path
or bytes only at the Adapter boundary. An Adapter returns normalized output bytes, media type, and
structured raw metadata. The orchestration Step creates:

- a final/intermediate output Artifact;
- a redacted raw-output Artifact for diagnostics;
- Step logs and a stable error when invocation fails; and
- provenance pointing to Project, Job, Step, and source Artifact.

Never let an upstream overwrite an imported Source. Never expose a private storage key or rely on
a caller's machine-specific absolute path as the contract.

## Error and control behavior

Map expected failures to `LinguaError` and stable `ErrorCode` values:

- missing service/dependency → `ADAPTER_UNAVAILABLE`;
- upstream exit/HTTP rejection → `EXTERNAL_COMMAND_FAILED`;
- timeout → `TIMEOUT`;
- absent/wrong output → `OUTPUT_MISSING`;
- invalid operator configuration → `CONFIGURATION_ERROR`.

Set `retryable` only when repeating later is meaningful. Preserve useful status/type details after
redaction, not secrets or entire unbounded bodies.

Declare cancellation and progress truthfully. If an upstream call cannot stop, keep the Job
`cancelling` while it finishes and checkpoint immediately afterward. Never fabricate percentage
progress or terminal cancellation.

## Tests

An Adapter contribution needs:

1. manifest and health tests;
2. input/output and language/config mapping tests;
3. timeout, unavailable, HTTP/process failure, invalid output, and redaction tests;
4. cancellation/progress declaration tests;
5. orchestration tests proving raw/output Artifact and log creation; and
6. an offline fake or mock with no paid key, model download, GPU, or Internet dependency.

Live heavyweight validation is a separate, explicitly enabled acceptance step. A passing fake
contract must not be described as a live upstream run.

## Licensing checklist

Before accepting an Adapter:

- record upstream repository, exact release/commit, maintenance evidence, and integration method;
- identify the code license and whether process separation is required;
- inventory every downloaded/bundled model and its source/license;
- inventory every font and its source/license/embedding terms;
- state whether anything is copied, modified, built, installed, or redistributed;
- update `third-party-components.toml`, `THIRD_PARTY_NOTICES.md`, and research; and
- never silently download or execute Internet code during core installation.

An external process boundary does not erase an operator's upstream obligations.

## v0.1.0 manga-image-translator Adapter

`MangaImageTranslatorHttpAdapter` targets the separately operated
`zyddnys/manga-image-translator` HTTP service researched at commit
`efdc229de8aa0f3d4051ad97664adc62dd5ac605`.

Configuration:

```bash
export LINGUASPINDLE_MIT_BASE_URL=http://127.0.0.1:5003
export LINGUASPINDLE_MIT_TIMEOUT_SECONDS=600
export LINGUASPINDLE_MIT_CONFIG_JSON='{}'
linguaspindle adapters doctor
```

Health requests `/openapi.json`. Translation posts an image and JSON `config` to
`/translate/with-form/image`; common target-language labels are mapped to upstream codes. The
Adapter validates non-empty `image/*` output. Each page produces a translated-image Artifact and
raw-metadata Artifact; a page failure produces a raw error Artifact and may yield partial success.

The manifest deliberately declares no immediate cancellation or streaming progress in v0.1.0.
The core checkpoints between pages. The upstream is GPL-3.0-only and its inspected model/font
inventory was incomplete, so none of it is distributed here. Operators must follow upstream
installation and license documentation themselves.
