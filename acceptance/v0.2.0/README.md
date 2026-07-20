# LinguaSpindle v0.2.0 acceptance archive

**Final status: Pass / release pending.** The accepted source candidate is
`f662c4844bd7990b3197f39314841b9c903deae1` on branch `codex/v0.2.0-epub`.

This directory contains the v0.2.0-only acceptance record. The later commit that contains this
archive adds reports and evidence but does not change the tested runtime source candidate. No
v0.2.0 tag, remote push, or GitHub Release was performed.

## Evidence index

- [Human-readable acceptance report](reports/acceptance-report.md)
- [Machine-readable acceptance report](evidence/acceptance-report.json)
- [Executed command log](evidence/command-log.txt)
- [Sanitized environment record](evidence/environment.txt)
- [Tracked-file checksums](evidence/checksums.sha256)
- [Deterministic sample-run inventory](artifacts/sample-run-summary.json)
- [Representative EPUB validation](artifacts/samples/epub/validation-report.json)
- [Browser evidence](artifacts/browser/browser-evidence.json)
- [Large-file resource measurement](evidence/resource-measurements.json)
- [Installable Wheel](artifacts/wheel/linguaspindle-0.2.0-py3-none-any.whl)

## Retention policy

The tracked fixtures, generated outputs, screenshots, and Wheel are small, synthetic, and scanned
for the active Provider key. Runtime databases and paid-Provider outputs are not retained.

Two larger temporary products are checksum-only evidence:

- Browser trace: 1,439,086 bytes, SHA-256
  `0b11037e3e1becbfa3610b4b7a43932769b5aba65059d4ea273c51a79cb6c16a`; removed after the
  successful Chromium run.
- Synthetic large EPUB: 25,307,593 bytes, SHA-256
  `5bede6bd858a4b0f60e47b49185713e0aad0e3164adf63ce5a4c790c51147088`; generated in a temporary
  directory and removed after measurement.

The browser screenshots record the synthetic TXT/manga GUI flow. EPUB GUI coverage is proven by
the separate real-Chromium `test_web_epub_gui.py` browser test; the screenshots are not presented
as EPUB screenshots.
