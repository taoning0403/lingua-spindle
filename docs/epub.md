# EPUB 2/3 support

LinguaSpindle supports a structure-preserving translation round trip for common valid,
unencrypted EPUB 2 and EPUB 3 packages. It does not flatten a book to TXT, synthesize a generic
replacement EPUB, run book JavaScript, or bypass protection.

EPUB inspection/rebuild is part of the default pure library. It requires no Project, Job,
database, Artifact store, server, or global Settings. The optional local runtime maps the same
public manifests/Segments/results into its persistent Job and Artifact model.

## Public use

```python
from linguaspindle import (
    ArchiveLimits,
    MockProvider,
    TranslationOptions,
    inspect_document,
    translate_document,
)

options = TranslationOptions(source_language="en", target_language="zh-CN")
manifest = inspect_document("book.epub", options=options)

result = translate_document(
    "book.epub",
    "book.zh-CN.epub",
    MockProvider(),
    options,
    archive_limits=ArchiveLimits(),
)
```

Lower-level selected/manual translation and caller-controlled reconstruction are covered in the
[Python library API](library-api.md).

## Package inspection

The inspector requires:

- a ZIP whose first member is the uncompressed `mimetype` entry containing
  `application/epub+zip`;
- `META-INF/container.xml` and its referenced OPF package document;
- an EPUB 2.x or 3.x package version, manifest, and spine;
- one EPUB 3 XHTML navigation item containing a `nav` whose `epub:type` includes `toc`, or an EPUB
  2 NCX selected by the spine;
- unique safe portable member paths and valid manifest/spine targets;
- parseable XML/XHTML package, navigation, and content documents; and
- local XHTML/navigation/CSS/image/media/resource references that resolve inside the archive.

The returned `DocumentManifest` records source checksum/size, precise EPUB major version, package
metadata summary, and ordered typed Segments. Its `structure` value is an explicitly versioned
opaque compatibility payload containing the package/resource graph consumed by the rebuilder; it
must be serialized with the manifest rather than edited by callers.

Any `META-INF/encryption.xml` is treated as protected content and rejected. LinguaSpindle does not
decrypt, remove DRM, or de-obfuscate fonts. Common EPUB 2 external PUBLIC/SYSTEM doctypes are
accepted without fetching DTDs; internal DTD subsets and ENTITY declarations are rejected before
XML parsing.

## Text selection and stable locators

Segments have stable source-document/XML-slot locators and are ordered as follows:

1. OPF package metadata;
2. XHTML content in spine order;
3. remaining XHTML manifest documents in manifest order; and
4. EPUB 2 NCX navigation text.

One XML text slot beyond the fixed 1,800-source-character EPUB safety bound is split
deterministically at a sentence/whitespace boundary when possible, otherwise at the hard limit.
Each part retains its exact separator for reconstruction. This is a Segment bound, not a
book/member limit; `TranslationOptions.max_segment_chars` configures TXT segmentation only.

| Content | Policy |
| --- | --- |
| Visible XHTML `body`/`nav` text and tails | Translate in document order. |
| EPUB 3 navigation labels and EPUB 2 NCX text | Translate. |
| OPF title, description, and subject | Translate. |
| OPF creator/author and identifier | Expose as metadata; do not translate. |
| Image `alt` and `title` attributes | Translate. |
| Ruby base text | Translate normally. |
| Ruby `rt` and `rp` pronunciation/fallback | Preserve. |
| Script, style, code, and SVG content | Preserve. |
| CSS, JavaScript, URLs, paths, anchors, IDs, names, and non-image attributes | Never translate. |
| Leading/trailing whitespace and inter-part separators | Preserve per XML slot. |

Uploaded XHTML is parsed as data and is not rendered by LinguaSpindle. v0.3.0 ships no browser
GUI or reader.

Each public Segment includes the source format/document, role, typed locator, source hash,
translation-input hash, joiner, stable ID, and order. Repeated inspection of unchanged bytes with
the same options returns the same IDs/order. The optional runtime also persists the stable ID in
the migration-0003 Segment key for new rows; existing v0.2 rows remain compatible.

## Selection, manual text, and source fallback

Callers can translate all, an explicit ID set, or an explicit empty set. Unknown IDs fail before
Provider calls. Existing successful/manual records take precedence. `rebuild_document` also
accepts a direct `{segment_id: text}` mapping and calls no Provider.

Rebuild applies only supplied successful/manual values. Missing, failed, cancelled, malformed, or
unmapped Segments keep source text. Mixed successful/failed parts within one split XML slot retain
the original inter-part separators.

## Reconstruction and validation

Output is always a new caller-supplied path or binary stream. A source and path output resolving
to the same file is rejected. Existing path output requires explicit `overwrite=True`.

The rebuilder:

- starts from the immutable original ZIP;
- retains original entry order, timestamps, compression choice, comments, and attributes;
- keeps `mimetype` first and uncompressed;
- modifies only XML containing selected text slots or target-language metadata;
- preserves spine, manifest, navigation, cover, links, anchors, CSS, fonts, images, audio/video,
  and other resources;
- replaces/creates OPF `dc:language` with the target language;
- sets matching `lang` and `xml:lang` on XHTML/navigation `html` roots; and
- records output checksum/size, translated/preserved counts, and validation details.

The target must be a structurally plausible BCP 47 tag such as `en`, `fr`, or `zh-CN`, not a
display label such as `English`.

Modified XML is parsed/serialized, so namespace prefixes, declarations, attribute order, or
insignificant formatting can change. The validation boundary is semantic package/reference
integrity plus byte equality for archive members not intentionally modified.

Before publication, the temporary output is independently reopened, re-inspected, and checked for
package structure, required files, manifest/spine targets, XML/XHTML parsing, internal references,
target language, and unchanged resources. External `epubcheck` is optional acceptance evidence,
not a default/runtime dependency.

## Resource and archive limits

The pure core receives an explicit `ArchiveLimits`:

| Field | Default | Guard |
| --- | ---: | --- |
| `max_files` | 2,000 | ZIP member count. |
| `max_uncompressed_bytes` | 1,048,576,000 | Total expanded bytes (1,000 MiB). |
| `max_member_bytes` | 104,857,600 | One expanded member (100 MiB). |
| `max_compression_ratio` | 100 | Per-member expanded/compressed ratio. |
| `max_path_depth` | 20 | Member-path components. |

`TranslationOptions.max_source_bytes` defaults to 104,857,600 (100 MiB) and bounds the source
payload before archive inspection. The optional runtime maps corresponding environment variables
to these explicit values:

```text
LINGUASPINDLE_MAX_UPLOAD_BYTES
LINGUASPINDLE_MAX_ARCHIVE_FILES
LINGUASPINDLE_MAX_ARCHIVE_BYTES
LINGUASPINDLE_MAX_ARCHIVE_MEMBER_BYTES
LINGUASPINDLE_MAX_ARCHIVE_COMPRESSION_RATIO
LINGUASPINDLE_MAX_ARCHIVE_PATH_DEPTH
```

The archive rejects absolute/traversal/backslash/control/drive-like paths, symlinks, duplicate or
Unicode/case-conflicting portable names, unsupported compression, announced/observed size excess,
too many members, excessive ratio, or path depth. Input is never extracted to a caller-controlled
member path. Hashing/reference checks use bounded reads; XML processing can buffer at most one
already bounded member.

Stable errors include `UPLOAD_TOO_LARGE`, `ARCHIVE_LIMIT_EXCEEDED`, `ARCHIVE_UNSAFE`,
`EPUB_INVALID`, `EPUB_UNSUPPORTED`, `EPUB_PROTECTED`, `EPUB_VALIDATION_FAILED`,
`SOURCE_MISMATCH`, and `SEGMENT_NOT_FOUND`.

Limits bound work; they do not promise that every allowed book fits every host or Provider budget.
Operators raising optional server limits must also budget disk, temporary storage, reverse-proxy
body limits, processing time, and paid-model cost.

## Known limits

- No PDF, DOCX, MOBI, AZW3, DRM bypass, store download, or dynamic browser-layout text discovery.
- CSS must be UTF-8 for built-in reference validation.
- Validation is structural/reference-oriented; reader-specific CSS/font/layout behavior can still
  require testing in the caller's target reader.
- LinguaSpindle does not provide an EPUB reader, per-sentence editor, CAT workflow, or approval
  state.
