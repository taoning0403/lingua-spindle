# Headless CLI reference

Install Typer support separately:

```bash
python -m pip install 'linguaspindle[cli]'
```

Without `[cli]`, `linguaspindle --version` remains available and other invocations print an
actionable missing-extra message. CLI modules load optional runtime/server dependencies only when
the corresponding command is used.

## Core-only commands

```text
linguaspindle --version
linguaspindle version
linguaspindle document inspect SOURCE
linguaspindle document translate SOURCE --output OUTPUT
linguaspindle manga inspect SOURCE
linguaspindle manga translate SOURCE --output OUTPUT
linguaspindle validate SOURCE
```

### Inspect TXT or EPUB

```bash
linguaspindle document inspect book.epub \
  --source-language en \
  --target-language zh-CN \
  --max-segment-chars 1800
```

Output is the versioned `DocumentManifest` JSON with stable Segments/locators. `--format` can be
`txt`, `epub`, `epub2`, or `epub3`; normal path/signature detection is preferred. An explicit EPUB
major version must match the package.

### Translate TXT or EPUB with the Mock Provider

```bash
linguaspindle document translate novel.txt \
  --source-language en \
  --target-language fr \
  --output novel.fr.txt

linguaspindle document translate book.epub \
  --source-language en \
  --target-language fr \
  --output book.fr.epub
```

This command always uses the deterministic offline `MockProvider`; it prints the versioned
manifest, translation batch, and build result. It refuses an existing destination unless
`--overwrite` is supplied. Additional options set format, max Segment characters, concurrency,
and retry count.

Selected/manual translation is available through the
[Python library API](library-api.md) and [headless HTTP API](api.md); the CLI does not invent a
separate editing workflow.

### Inspect or Mock-translate manga

```bash
linguaspindle manga inspect chapter.cbz
linguaspindle manga translate chapter.cbz \
  --source-language ja \
  --target-language en \
  --output chapter.en.cbz
```

Input is PNG/JPEG/WebP or CBZ/ZIP. Translation uses `MockMangaAdapter`, which returns input image
bytes unchanged for deterministic offline verification; it is not a real OCR/model run. Inspect
supports an explicit source-byte maximum. Translate supports retries and explicit overwrite.

### Validate generated output

```bash
linguaspindle validate book.fr.epub
linguaspindle validate chapter.en.cbz --kind manga
```

`--kind` is `auto`, `document`, or `manga`. Validation reopens/inspects TXT/EPUB/image/CBZ and
prints a manifest; EPUB uses the same structural/reference checks as the library.

## Optional persistent runtime commands

Install both extras:

```bash
python -m pip install 'linguaspindle[runtime,cli]'
```

```text
linguaspindle doctor
linguaspindle projects list
linguaspindle projects create
linguaspindle projects show PROJECT_ID
linguaspindle projects delete PROJECT_ID
linguaspindle run PROJECT_ID
linguaspindle jobs list
linguaspindle jobs show JOB_ID
linguaspindle jobs pause|resume|cancel|retry JOB_ID
linguaspindle artifacts list PROJECT_ID
linguaspindle export PROJECT_ID
linguaspindle adapters list
linguaspindle adapters doctor
```

All accept `--data-dir` where applicable; otherwise the optional runtime resolves
`LINGUASPINDLE_DATA_DIR`/platform default.

Create and run an offline persistent Project:

```bash
linguaspindle projects create \
  --name "Sample novel" \
  --kind novel \
  --source-language en \
  --target-language fr \
  --source sample.txt

linguaspindle run PROJECT_ID --provider mock
linguaspindle jobs show JOB_ID
linguaspindle artifacts list PROJECT_ID
linguaspindle export PROJECT_ID --format txt --output sample.runtime.fr.txt
```

`run` creates a persistent Job. With the default `--wait`, it constructs a `JobRunner` and
executes in the current process; `--no-wait` only queues work for an explicitly running worker.
Source kind chooses TXT, EPUB, or manga Preset unless `--pipeline` is supplied. Export requires
exactly one matching Artifact before `--output` can be used and refuses overwrite by default.

Pause/cancel take effect at safe Segment/page boundaries. The current real manga Adapter cannot
stop mid-image; the Job remains `cancelling` until that call returns or times out.

## Optional server command

```bash
python -m pip install 'linguaspindle[server,cli]'
linguaspindle serve --host 127.0.0.1 --port 8765
```

This starts the JSON/OpenAPI server and its explicit persistent worker. No GUI is served. A non-
loopback bind prints a warning because LinguaSpindle has no login; use an outer private/access
perimeter. See [HTTP API](api.md).

## Provider and real manga diagnostics

The runtime/server can configure an OpenAI-compatible Provider from process environment after the
`[openai]` extra is installed. The key is never a command argument or serialized output.

The `[manga]` extra supplies the real HTTP Adapter client. Configure its separate service and run:

```bash
linguaspindle adapters list
linguaspindle adapters doctor
```

The command reports declared health/capabilities. It neither downloads nor starts the upstream.

## Output and exit behavior

- Successful commands exit `0`.
- Failed health/availability diagnostics exit `1`.
- With `[cli]` installed, missing command-specific extras, configuration failures, and stable
  core/application errors print a JSON error envelope and exit `2`.
- Without `[cli]`, the dependency-light entry wrapper keeps `--version` available; other
  invocations print a plain actionable install message to stderr and exit `2` because Typer/JSON
  command handling is not installed yet.
- Versioned manifests/results use UTF-8 JSON with non-ASCII characters preserved.
- Use each command's `--help` as the definitive option list.
