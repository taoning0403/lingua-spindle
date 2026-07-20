# EPUB 2/3 support

LinguaSpindle v0.2.0 supports common, valid, unencrypted EPUB 2 and EPUB 3 files. EPUB uses the
same instance-scoped Project, Job, Step, TranslationSegment, Artifact, Provider, QA, control,
retry, and restart-recovery implementation as TXT. It does not introduce an EPUB-only task
system, an account model, or a second storage root.

The goal is a structure-preserving translation round trip. LinguaSpindle does not flatten the
book to TXT and synthesize a new generic EPUB.

## Import and package validation

Import streams the uploaded source into an immutable source Artifact, then inspects the stored
file before publishing the Project. A rejected import removes the staged payload and does not
leave a usable half-created Project.

The built-in inspector requires:

- a ZIP package whose first member is the uncompressed `mimetype` entry containing
  `application/epub+zip`;
- `META-INF/container.xml` and a referenced OPF package document;
- an EPUB 2.x or 3.x package version, manifest, and spine;
- exactly one EPUB 3 XHTML navigation item containing a `nav` whose `epub:type` includes `toc`,
  or an EPUB 2 NCX selected by the spine;
- unique, safe, portable member paths and valid manifest/spine targets;
- parseable XML/XHTML package, navigation, and content documents; and
- internal XHTML, navigation, CSS, image, media, and other local references that resolve to
  archive members.

The manifest records package metadata, cover, manifest resources, spine/reading order,
navigation documents, document order, resource references, ZIP entry facts, validation summary,
source archive checksum, and every translatable text locator. It is a generated intermediate
Artifact; callers continue to identify payloads by Artifact ID.

Any `META-INF/encryption.xml` is treated as protected content and rejected. LinguaSpindle does not
attempt DRM removal, decryption, or font de-obfuscation. Common vendor-specific packages that do
not satisfy the rules above are rejected instead of being silently rewritten.

Common EPUB 2 XHTML external PUBLIC/SYSTEM doctypes are accepted without fetching their DTDs.
Internal DTD subsets and ENTITY declarations remain rejected before XML parsing.

## Text selection and order

Text units have a stable source document and XML-slot locator. They are ordered as follows:

1. OPF package metadata;
2. XHTML content in spine reading order;
3. remaining XHTML manifest documents in manifest order; and
4. EPUB 2 NCX navigation text.

One XML text slot longer than 1,800 source characters is split deterministically at a sentence or
whitespace boundary where possible, otherwise at the hard limit. Each part retains its exact
inter-part separator so reconstruction remains stable. This is a segmentation bound, not an
upload or chapter-size limit.

The following table is the v0.2.0 translation policy:

| Content | Policy |
| --- | --- |
| Visible XHTML `body`/`nav` text and tails | Translate in document order. |
| EPUB 3 navigation labels and EPUB 2 NCX text | Translate. |
| OPF title, description, and subject | Translate. |
| OPF creator/author and identifier | Display/import as metadata, but do not translate. |
| Image `alt` and `title` attributes | Translate. |
| Ruby base text | Translate normally. |
| Ruby `rt` and `rp` pronunciation/fallback nodes | Preserve without translation. |
| Script, style, code, and SVG element content | Preserve without translation. |
| CSS, JavaScript, URLs, paths, anchors, IDs, element names, and non-image attributes | Never translate. |
| Leading/trailing whitespace and inter-part separators | Preserve exactly within each XML slot. |

Uploaded XHTML is parsed as book data. It is never injected into the LinguaSpindle GUI as live
HTML, so embedded script content is not executed by the result view.

## Segment lineage and reuse

Each EPUB TranslationSegment records the immutable source Artifact ID, source document, content
role, JSON locator, source-text hash, translation-input hash, and optional reused Segment ID. The
translation-input hash covers the source archive/content locator and the effective non-secret
translation policy, including language pair, Provider/model, style, prompt version/contents,
model parameters, and context strategy.

An identical successful input from an earlier Job in the same Project can be reused. A changed
source location, source text, language, Provider/model, prompt, style, or model policy produces a
different hash and is translated again. This is scoped deterministic reuse, not a general
translation-memory or fuzzy-match system.

Pause, cancel, retry, progress, Provider errors, process-interruption classification, Step reuse,
and QA use the existing orchestration state machine. Active controls are cooperative at Segment
boundaries. A process interruption remains explicit `PROCESS_INTERRUPTED`; retry then reuses
durable successful work.

## Reconstruction and fallback

Export creates a new immutable `novel_export_epub` Artifact. It never writes over the imported
source. Translations are applied only when the persisted Segment is successful and contains a
non-blank string. A missing, failed, malformed, or blank translation keeps that Segment's source
text. In a split XML slot, successful parts are translated and failed parts use source text while
the original separators remain in place.

The exporter:

- copies the original ZIP entry order, timestamps, compression choices, comments, and attributes;
- keeps `mimetype` first and uncompressed;
- modifies only XML documents containing translated slots or target-language metadata;
- preserves the spine, manifest, navigation structure, cover, links, anchors, CSS, fonts, images,
  audio/video, and other resources;
- replaces existing OPF `dc:language` values with the target language, or adds one if absent;
- sets matching `lang` and `xml:lang` on XHTML and navigation `html` roots; and
- records Project, Job, source Artifact, validation, and fallback lineage in generated Artifacts.

An EPUB Project therefore requires a structurally plausible BCP 47 target-language tag such as
`en`, `fr`, or `zh-CN`; a display name such as `English` is not written as package metadata.

Modified XML is parsed and serialized, so namespace prefixes, XML declarations, attribute order,
or insignificant formatting in those modified documents can change. Semantics and validated
references are preserved. Every archive member not intentionally modified is compared byte for
byte with its source counterpart.

Before publication, the temporary output is independently opened, inspected, reference-checked,
and re-imported by the built-in validator. The exporter confirms package structure, required
files, manifest/spine targets, parseable XHTML/XML, internal resource paths, target language, and
unchanged non-text payloads. External `epubcheck` may be recorded as optional acceptance evidence
when available, but is not a runtime dependency.

## Resource and archive limits

The defaults are centralized in runtime Settings and apply to EPUB/ZIP inspection:

| Variable | Default | Guard |
| --- | ---: | --- |
| `LINGUASPINDLE_MAX_UPLOAD_BYTES` | 104,857,600 | Maximum immutable source payload (100 MiB). |
| `LINGUASPINDLE_MAX_ARCHIVE_FILES` | 2,000 | Maximum ZIP members. |
| `LINGUASPINDLE_MAX_ARCHIVE_BYTES` | 1,048,576,000 | Maximum total expanded bytes (1,000 MiB). |
| `LINGUASPINDLE_MAX_ARCHIVE_MEMBER_BYTES` | 104,857,600 | Maximum expanded bytes for one member (100 MiB). |
| `LINGUASPINDLE_MAX_ARCHIVE_COMPRESSION_RATIO` | 100 | Maximum expanded/compressed ratio per member. |
| `LINGUASPINDLE_MAX_ARCHIVE_PATH_DEPTH` | 20 | Maximum member-path components. |

The archive is rejected for absolute/traversal/backslash/control-character paths, drive-like
prefixes, symlinks, duplicate or Unicode/case-conflicting portable names, unsupported compression,
announced or observed expansion beyond a byte limit, too many members, excessive compression
ratio, or excessive path depth. Hashing, expanded-secret scans, and resource validation use
bounded reads. XML parsing/rebuild and unchanged-member comparison may buffer at most one member,
which is capped by the per-member limit; input is never extracted to an attacker-selected path.

`UPLOAD_TOO_LARGE` and `ARCHIVE_LIMIT_EXCEEDED` map to HTTP 413. Other stable codes include
`ARCHIVE_UNSAFE`, `EPUB_INVALID`, `EPUB_UNSUPPORTED`, `EPUB_PROTECTED`, and
`EPUB_VALIDATION_FAILED`. All interfaces return the same normalized error vocabulary.

The numerical defaults are conservative product guardrails, not a promise that every allowed
book fits every host. The v0.2.0 acceptance report records the actual representative-book resource
measurement used for this release candidate; operators who raise a limit must also budget disk,
temporary storage, Provider cost, processing time, reverse-proxy limits, and container `/tmp`.

## Known limits

- Only common EPUB 2/3 is in scope; PDF, DOCX, MOBI, AZW3, DRM bypass, and store downloads are not.
- No JavaScript execution or browser-layout engine is used to infer dynamically generated text.
- CSS must be UTF-8 for built-in reference validation.
- The GUI exposes results and QA but is not a full per-sentence EPUB editor.
- Validation is structural/reference oriented; rendering differences caused by reader-specific
  CSS, fonts, scripting, or invalid publisher markup can still require testing in a target reader.
