# LinguaSpindle

LinguaSpindle is a headless, embeddable translation orchestration engine for novels and manga.
The default Python package is a side-effect-free library: it does not need a GUI, database,
server, account, API key, or worker.

It supports:

- TXT inspection, stable segmentation, selected translation, and UTF-8/LF reconstruction;
- structure-preserving common unencrypted EPUB 2/3 translation;
- PNG/JPEG/WebP and CBZ/ZIP manga translation;
- caller-implementable text Providers and distinct Manga Adapters;
- deterministic Mock Provider and Mock Manga Adapter for offline use;
- bounded retry/concurrency, progress events, cooperative cancellation, partial results, and
  stable errors; and
- optional SQLite/Artifact/Job recovery, CLI, OpenAI-compatible transport, real manga HTTP
  Adapter, and headless FastAPI server.

Imported input remains immutable. Every output path or stream is supplied explicitly by the
caller. Readers, proofreading UI, revision/approval history, bookshelves, and calling-product
state belong to the embedding application.

[简体中文说明](README.zh-CN.md)

## Install the core

Python 3.11 or newer is required.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

The default dependency set contains only core TXT/EPUB needs. It does not install FastAPI,
Uvicorn, Typer, SQLAlchemy, HTTPX, Pydantic, Playwright, a browser, an external manga tool, models,
fonts, or a GPU runtime.

## Translate TXT or EPUB

```python
from pathlib import Path

from linguaspindle import MockProvider, TranslationOptions, translate_document

result = translate_document(
    Path("book.epub"),  # .txt works through the same API
    Path("book.zh-CN.epub"),
    MockProvider(),
    TranslationOptions(source_language="en", target_language="zh-CN"),
)

print(result.translations.status)
print(result.build.output_sha256)
```

EPUB output preserves reading order, navigation, links, anchors, cover, images, CSS, fonts, and
other non-text resources. The core rebuilds from the immutable source, retains source text for
unmapped/failed Segments, updates target language, then reopens and validates the output.

See [EPUB support](docs/epub.md) for visible-text, locator, archive-limit, and validation rules.

## Selected translation and caller edits

```python
from linguaspindle import (
    MockProvider,
    TranslationOptions,
    inspect_document,
    rebuild_document,
    translate_segments,
)

options = TranslationOptions(source_language="en", target_language="fr")
manifest = inspect_document("novel.txt", options=options)
selected = [manifest.segments[0].segment_id]

batch = translate_segments(
    manifest,
    MockProvider(),
    options,
    selected_segment_ids=selected,
)

# A caller can rebuild with reviewed text and no Provider call.
rebuild_document(
    "novel.txt",
    manifest,
    {selected[0]: "A human-edited first paragraph."},
    "novel.reviewed.txt",
    target_language="fr",
)
```

`selected_segment_ids=None` means all; an explicit empty list means none. Unknown IDs fail before
Provider calls. Existing/manual text wins and is never silently overwritten. Result records stay
in source order under concurrency and can be serialized for later retry/rebuild.

## Translate image or CBZ manga

```python
from linguaspindle import (
    MockMangaAdapter,
    TranslationOptions,
    build_manga_output,
    translate_manga,
)

translated = translate_manga(
    "chapter.cbz",
    MockMangaAdapter(),
    TranslationOptions(source_language="ja", target_language="en"),
)
build_manga_output(translated, "chapter.en.cbz")
```

The Mock returns input image bytes for deterministic offline tests; it is not real OCR,
translation, inpainting, or typesetting. Real whole-page output is provided by an optional,
separately operated Adapter.

## Optional extras

```bash
python -m pip install -e '.[openai]'   # OpenAI-compatible HTTP Provider
python -m pip install -e '.[manga]'    # real manga HTTP Adapter client
python -m pip install -e '.[runtime]'  # SQLite + Artifacts + persistent Jobs
python -m pip install -e '.[cli]'      # headless Typer CLI
python -m pip install -e '.[server]'   # FastAPI/Uvicorn JSON server + runtime
python -m pip install -e '.[all]'      # all supported optional layers
```

Missing optional features return an actionable extra-install message. More detail:
[Installation](docs/installation.md).

## Headless CLI

```bash
python -m pip install -e '.[cli]'

linguaspindle document inspect sample.txt --target-language fr
linguaspindle document translate sample.txt --target-language fr --output sample.fr.txt
linguaspindle manga inspect chapter.cbz
linguaspindle manga translate chapter.cbz --target-language en --output chapter.en.cbz
linguaspindle validate sample.fr.txt
```

These core commands use offline mocks and need no database. Persistent Project/Job/Artifact
commands require `[runtime,cli]`. See [CLI reference](docs/cli.md).

## Headless HTTP server

```bash
python -m pip install -e '.[server,cli]'
linguaspindle serve
```

Open <http://127.0.0.1:8765/docs> for OpenAPI. `/` returns JSON; there is no Web GUI or reader.
The API retains asynchronous Project/Job/Artifact flows and adds stable novel Segment listing,
explicit selected translation, and Provider-free caller-mapping rebuild.

See [HTTP API](docs/api.md) and [Docker deployment](docs/docker.md).

## Trust boundary

LinguaSpindle is a single-instance engine. It has no registration, login, account, role,
permission, tenant, owner, or collaboration model. Anyone who can reach the optional HTTP port
can operate it.

Server startup and Compose publish on `127.0.0.1` by default. **Do not expose LinguaSpindle
directly to the public Internet.** Use an explicit private network, VPN/Tailscale, Cloudflare
Access, or access-controlling reverse proxy for remote use. That outer identity is not copied into
LinguaSpindle.

## Providers and secrets

Library callers inject credentials directly or through a key resolver. The pure core never reads
a fixed environment variable. Optional CLI/server configuration can resolve:

```bash
export LINGUASPINDLE_OPENAI_BASE_URL=https://api.example.test/v1
export LINGUASPINDLE_OPENAI_API_KEY='set-outside-version-control'
export LINGUASPINDLE_OPENAI_MODEL=example-model
```

The key is not accepted by the HTTP API and is excluded from serialized models, database views,
events, errors, logs, Artifacts, and exports. Keep populated `.env` files out of version control.

## External manga Adapter

The optional protocol client targets a separately operated
[`manga-image-translator`](https://github.com/zyddnys/manga-image-translator) HTTP service:

```bash
python -m pip install -e '.[manga,runtime,cli]'
export LINGUASPINDLE_MIT_BASE_URL=http://127.0.0.1:5003
export LINGUASPINDLE_MIT_CONFIG_JSON='{}'
linguaspindle adapters doctor
```

LinguaSpindle does not vendor, install, download, start, or redistribute its GPL source, models,
fonts, container, or GPU stack. Operators must license and secure that service independently. The
current Adapter reports no streaming progress or immediate mid-image cancellation; cancellation
is observed between pages.

See [Provider and Manga Adapter development](docs/adapter-development.md) and
[third-party notices](THIRD_PARTY_NOTICES.md).

## v0.2.0 runtime migration

The core-only library owns no data root. Optional runtime users can retain all v0.2.0 TXT/EPUB/
manga Projects, Jobs, Segments, and Artifacts through additive migration 0003. Stop writes and
back up the complete data root first. Rollback restores that full backup; it is not an in-place
schema downgrade.

Read [v0.2-to-v0.3 migration](docs/migrations/v0.2-to-v0.3.md).

## Development

```bash
python -m pip install -c constraints-v030.txt -e '.[dev]'
python -m ruff format --check src tests tools
python -m ruff check --no-cache src tests tools
python -m mypy src tools/generate_v020_acceptance.py tools/generate_v030_acceptance.py \
  tools/verify_v030_extras.py
python -m compileall -q src tests tools
python -m pytest -q
```

Default tests access no paid service/network/model and install no browser. Exact release-candidate
results belong in the versioned [acceptance archive](acceptance/README.md).

## Documentation and licensing

- [Python library API](docs/library-api.md)
- [Architecture](docs/architecture.md)
- [Data model](docs/data-model.md)
- [Decision records](docs/DECISIONS.md)
- [Current project state](docs/PROJECT_STATE.md)
- [v0.3.0 release notes](docs/releases/v0.3.0.md)
- [Structured third-party inventory](third-party-components.toml)
- [Security policy](SECURITY.md)

LinguaSpindle core is [Apache-2.0](LICENSE). Dependencies and external services retain their own
licenses; the core license does not replace them.
