# LinguaSpindle v0.2.0 acceptance report

> **Final status: Pass / release pending.** All required executable gates available on this host
> passed for source candidate `f662c4844bd7990b3197f39314841b9c903deae1`. No v0.2.0 tag,
> remote push, or GitHub Release was performed.

- Report date: 2026-07-20 (Asia/Shanghai)
- Branch: `codex/v0.2.0-epub`
- Source candidate: `f662c4844bd7990b3197f39314841b9c903deae1`
- Host: macOS Darwin 25.4.0, arm64
- Container runtime: Linux/arm64 Docker 29.6.1, Compose 5.3.0
- Package version: `0.2.0`
- Test policy: offline Mock Provider/Adapter by default; no paid key or external model required

The commit containing this archive adds reports and retained evidence only. The source candidate
above is the exact runtime revision used for the final static, Python, browser, Wheel, image, and
Compose checks.

## Conclusion

LinguaSpindle v0.2.0 adds a bounded, structure-preserving EPUB 2/3 path without changing the
standalone, no-user, shared-core architecture. Common valid and unencrypted EPUBs can be imported,
segmented through stable document/XML locators, translated through the existing Provider layer,
rebuilt from the immutable source archive, independently validated, downloaded, and re-imported.
TXT and manga flows remain operational.

The candidate passed 149 automated tests with 83% branch-aware coverage. Both real-Chromium tests
passed when browser tests were enabled. The retained EPUB3 sample completed the full Mock Pipeline,
translated all 26 selected text units, preserved six unchanged archive members byte-for-byte, and
reopened with its four-item spine, navigation, resources, internal references, and target language
intact. EPUB2 behavior is established by separate unit and integration fixtures rather than being
inferred from that EPUB3 sample.

An installable Wheel and a non-root Docker image were built. The Wheel contains Web assets and both
schema migrations. An isolated Compose deployment bound only to `127.0.0.1`, ran with a read-only
root and UID/GID 10001, completed an offline Mock Job, returned an HTTP Artifact with its recorded
SHA-256, and retained the Project, Job, and eight Artifacts across restart. The test-only container,
network, and named volume were then deleted; the local image was retained.

## Required acceptance matrix

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| A01 | v0.1.0 acceptance archived without rewriting its tag | Pass | Six archived checksums verify; `v0.1.0` still resolves to `90439f66d2d2ddf656174bc33a34ffdacee2b41d`. |
| A02 | Forward-only EPUB schema upgrade preserves existing rows | Pass | Migration tests execute `0001_initial.sql` then `0002_epub.sql` and verify retained Project, Source, Job, Step, Segment, QA, and Artifact data. |
| A03 | Common valid EPUB 2/3 import and package/navigation inspection | Pass | EPUB2/3 unit and integration fixtures cover container/OPF/manifest/spine, EPUB3 nav, EPUB2 NCX, metadata, cover, resources, references, and external DOCTYPE compatibility. |
| A04 | Explicit visible-text selection, bounded splitting, and stable locators | Pass | Tests cover XHTML/nav/NCX/metadata text, Ruby handling, skipped script/style/code/SVG content, nested exclusions, exact joiners, 1,800-character parts, source document, locator, and hashes. |
| A05 | Mock EPUB Pipeline and Artifact lineage | Pass | `novel_epub_v1` sample Job succeeded; all five Steps and seven Artifacts have recorded inputs/outputs and source/job/manifest lineage. |
| A06 | Structure-preserving export, reopen, and re-import | Pass | Retained EPUB3 output is valid, all 26 selected units translated, six untouched members byte-equal, four-item reading order stable, nine resources retained, and language changed to `en`. Separate EPUB2 round-trip tests pass. |
| A07 | Imported Source remains immutable | Pass | Unit/integration assertions compare original bytes before and after export, reject source overwrite/stale manifests, and verify source Artifact checksums. |
| A08 | Pause, resume, cancel, retry, interruption recovery, and Segment reuse | Pass | EPUB-specific controls tests plus retained v0.1 controls/recovery tests pass; completed Segments are not retransmitted and durable document/locator lineage survives retry. |
| A09 | Provider failure, partial output, normalized error, and logs | Pass | Deterministic Mock failure fixtures preserve source text for failed/missing translations, produce partial status/QA evidence, retain prior successes, and exercise stable Provider error/redaction paths. |
| A10 | Reject malformed, protected, unsafe, or ambiguous archives | Pass | Tests reject non-ZIP, malformed XML, encryption, internal entity subsets, traversal, duplicates, unsafe flags, control characters, casefold/NFC conflicts, and invalid EPUB navigation/language declarations. |
| A11 | Enforce upload and archive resource limits | Pass | Tests cover upload bytes, member count, total/per-member expansion, compression ratio, path depth, chunked requests, and compressed-key inspection. The synthetic large-file measurement remains within every default limit. |
| A12 | Bounded file transfer | Pass | Storage/API/CLI tests prove chunked upload publication, outer multipart guarding, file-based HTTP downloads, and atomic streamed CLI copies without whole-payload helper reads. |
| A13 | GUI, CLI, and HTTP API share one application core and data store | Pass | Integration tests create/read the same durable Project through API and CLI; typed OpenAPI models and stable 400/404/409/413/422 envelopes pass. Interfaces do not invoke Pipelines or third-party tools directly. |
| A14 | TXT regression | Pass | Deterministic TXT sample and browser flow complete Mock translation, QA, TXT/JSON export, checksum verification, and HTTP download. |
| A15 | Manga regression | Pass | Deterministic CBZ sample and Chromium GUI flow complete the built-in Mock path; unsafe/bounded archive and unconfigured external Adapter behavior pass. |
| A16 | Runtime Provider key never enters persistent/public data | Pass | Security tests scan every file under a test data root after deliberate leaky Provider/error inputs; no synthetic runtime key appears in SQLite/WAL, logs, Artifacts, exports, or API state. Raw, UTF-16/32, and compressed EPUB imports containing the active key are rejected. Generated acceptance files are also scanned against the locally configured active key. |
| A17 | Installed Wheel contains runtime resources | Pass | Wheel SHA-256 `6f0a6abb6333f8c842edc76d453e283c60d578e1f2acc8ab66721437244bba42`; installed-package smoke finds Web `index.html`, migrations 0001/0002, serves `/`, and reports version `0.2.0`. |
| A18 | Real-browser GUI acceptance | Pass | Chromium 149.0.7827.55: 2 passed, 1 paid-Provider test skipped, 149 deselected. One test covers EPUB import/inspect/Mock Job/result/failure; the retained screenshots separately document TXT/manga flows. |
| A19 | Representative large-file measurement | Pass | A temporary 25,307,593-byte EPUB with 505 members and a 24 MiB resource inspected successfully in 0.028224 s with 65,355,776-byte process peak RSS on this host. See limitations below. |
| A20 | Docker image and isolated Compose deployment | Pass | Image `sha256:db74fc61608b9899a8c48414adefd4cf246f4cfff3ec941cd62baab92c6113c0`, Linux/arm64, 60,771,978 bytes; version `0.2.0`, UID/GID 10001, read-only root, `no-new-privileges`, loopback-only port. Health, Mock Job, download hash, restart persistence, and cleanup passed. |
| A21 | Static, type, compile, and JavaScript gates | Pass | Ruff format/check, strict mypy, Python compileall, and `node --check` all pass. |
| A22 | Complete automated suite and coverage | Pass | `149 passed, 3 skipped`; 83% total branch-aware coverage. Default skips are the two opt-in browser tests and the opt-in paid Provider test, all explicitly rerouted below. |
| A23 | Product/security boundaries and maintained documentation | Pass | Repository tests and final diff preserve no users/auth/tenancy, standalone operation, capability-based Adapters, immutable Sources, Artifact identity flow, loopback default, runtime-only keys, and updated EPUB/operations/upgrade documentation. |

Required results: **23 Pass, 0 Fail, 0 Blocked.** Optional external tests below do not change the
required conclusion.

## Representative retained artifacts

The deterministic generator ran the EPUB3, TXT, and manga Pipelines twice. Recursive comparison of
`artifacts/**` was identical between runs; only real elapsed/RSS fields in the separately generated
resource measurement can vary.

### EPUB3 round trip

- Source: 4,587 bytes,
  `b37e462e7381a8685481a0c81901f6827a073cb36bebd9954bb3c33ef3db0fae`
- Output: 4,682 bytes,
  `e7f6e5f96cbe1dcd8c9ce749331e7f103ca2c1a90e57bec53fd16b74306face2`
- Validation report: 1,345 bytes,
  `f5c86e2ec145723ee54a7b840de6e1ce03e65b131b6c4e7b00742ff8327fd6a3`
- EPUB version: 3.0; spine documents: 4; documents: 5; resources: 9; members: 12
- Text units: 26 translated, 0 source fallbacks in this successful case
- Modified XML documents: package, nav, cover, notes, and two chapters
- Unchanged member payloads verified byte-for-byte: 6, including binary/style resources

The fixture includes two narrative chapters, cover content/image, navigation, stylesheet, font,
footnote/notes content, and internal links. Built-in validation checks package/reference structure;
it does not claim reader-rendering equivalence or external `epubcheck` certification.

### TXT and manga regressions

The TXT Job succeeded with five Segments and retained TXT/JSON outputs. The manga Job succeeded via
the built-in deterministic Mock Adapter and retained source/output CBZ files. The sample inventory
records every delivered Artifact identity, byte size, checksum, and lineage.

## Automated and browser gates

Final full-suite command:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q -p no:cacheprovider \
  --cov=linguaspindle --cov-branch --cov-report=term-missing
```

Outcome: `149 passed, 3 skipped`, 83% total coverage. No coverage threshold was weakened or added
to turn the run green.

Final real-browser command:

```bash
LINGUASPINDLE_RUN_BROWSER_TESTS=1 \
LINGUASPINDLE_BROWSER_EVIDENCE_DIR=acceptance/v0.2.0/artifacts/browser \
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q -p no:cacheprovider -m browser
```

Outcome: `2 passed, 1 skipped, 149 deselected`. The remaining skip is the separately gated real
paid-Provider browser test. The run reported no browser errors, console errors, failed requests, or
unexpected origins. The 1.4 MiB Playwright trace was checksum-recorded and removed rather than
committed.

## Wheel evidence and harness corrections

The 95,860-byte `py3-none-any` Wheel is retained in `artifacts/wheel/`. It was installed with
`--no-deps --target` and then exercised against the already pinned acceptance environment, which
keeps the probe focused on packaged LinguaSpindle content while dependency installation is covered
by the Docker build.

The command transcript preserves test-harness corrections rather than hiding them:

1. An early probe passed a string where `Settings` requires `pathlib.Path`; the corrected probe
   passed.
2. A later bare-system-Python probe could not import FastAPI because the target install deliberately
   used `--no-deps`; it was rerun with the pinned environment dependencies.
3. That rerun initially imported the factory from `linguaspindle.web`; the actual public factory is
   `linguaspindle.interfaces.api.create_app`. The corrected installed-package probe passed.

These were acceptance harness mistakes. No Wheel or product source change was needed.

## Docker and persistence evidence

The final image build succeeded from the source candidate. The initial version probe used
`docker run IMAGE --version`, which replaces an image `CMD` and therefore attempted to execute
`--version`. The corrected explicit command `docker run IMAGE linguaspindle --version` returned
`0.2.0`; this is recorded as a harness correction, not a product failure.

The isolated Compose run used project name `linguaspindle-v020-acceptance`, host port 18765, an
explicitly empty Provider key, and its own named volume. Observed results:

- `/health`: status `ok`, version `0.2.0`, database `ok`;
- container healthy, UID/GID `10001:10001`, read-only root, `no-new-privileges:true`;
- published port: `127.0.0.1:18765` to container port 8765;
- runtime Provider key presence check: `False` (value was never printed);
- offline Mock Job: `succeeded`, one Source, one Job, eight total Artifacts;
- TXT HTTP download SHA-256 before restart:
  `eff82d60199192d8ce2a989954023741ea23781ce7aa11e74d399f73f975c0ad`;
- after container restart, the same Project/Job/Artifacts remained and the same download checksum
  was returned; and
- the test-only container, network, and volume were removed after the proof. Their contents were
  synthetic and are recoverable by rerunning the documented commands.

Two automatic approval reviews timed out before executing their commands (one image-build attempt
and one Compose-up attempt). Each command was retried once unchanged and succeeded. They are
infrastructure authorization timeouts, not product results.

## Resource measurement

The synthetic large fixture was inspected in a fresh subprocess:

| Measurement | Observed | Default limit |
| --- | ---: | ---: |
| Input bytes | 25,307,593 | 104,857,600 upload bytes |
| ZIP members | 505 | 2,000 |
| Expanded bytes | 25,309,480 | 1,048,576,000 |
| Largest expanded member | 25,165,824 | 104,857,600 |
| Maximum compression ratio | 13.032041 | 100 |
| Maximum path depth | 3 | 20 |
| Text units | 523 | not a configured safety limit |
| Elapsed inspection | 0.028224 s | observational only |
| Process peak RSS | 65,355,776 bytes | observational only |

This is one cold-process observation on the recorded host. The 24 MiB member is stored rather than
a compression-bomb payload. Inspection reads and validates the archive but does not measure
Provider translation, reader rendering, publisher CSS, or end-to-end throughput. Safety thresholds
are bounds, not memory/performance guarantees.

## Optional external tests

| Category | Test | Status | Reason/next action |
| --- | --- | --- | --- |
| Optional external test | Real paid OpenAI-compatible Provider | Not executed | No paid credential/cost was authorized. Configure a disposable key and explicitly opt in. |
| Optional external test | Real `manga-image-translator` model/service | Not executed | The external GPU/model/font stack is operator-managed and intentionally not bundled. |
| Optional external test | External `epubcheck` | Not executed | Built-in structural/reference validation passed; external validator remains optional. |
| Optional external test | Native Windows and WSL2 runtime | Not executed | This run covered macOS arm64 and Linux/arm64 Docker; use a supplemental report on those hosts. |

No optional result is represented as a pass, and none is a blocker for the defined v0.2.0 local
candidate because the offline Mock paths and required container deployment passed.

## Security and disclosure notes

- No user/account/auth/tenant/role/ownership model was introduced.
- No Provider key value is present in this report, the command transcript, the retained Artifacts,
  or the machine-readable evidence.
- The Compose key-presence probe logged only a Boolean result.
- Ordinary source prose containing `password: castle` or `secret=plot` remains content, while an
  exact active runtime key is rejected/redacted.
- The heavyweight manga upstream, models, fonts, browser, external validator, and paid key are not
  included in the core image or Wheel.
- Source imports are immutable Artifacts; Pipeline and Adapter boundaries use Artifact identities,
  not machine-specific absolute paths.

## Publication state

- v0.2.0 Git tag: **Not executed by instruction**
- Remote branch push: **Not executed by instruction**
- GitHub Release: **Not executed by instruction**
- Release state: **release pending**

The next publication step, if separately authorized, is to review this archive, create an annotated
`v0.2.0` tag at the accepted source/evidence history, push intentionally, and publish the retained
Wheel plus release notes. This report itself does not grant that authority.
