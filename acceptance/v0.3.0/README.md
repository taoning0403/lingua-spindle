# LinguaSpindle v0.3.0 acceptance archive

Final status: **Pass / release pending**.

This archive binds the v0.3.0 headless/library-first acceptance run to source candidate
`84270dec38b5f92fcc044b36c170f4230c15170f`. The later commit containing this directory adds
retained evidence and maintained release-state text only.

- Human report: [`reports/acceptance-report.md`](reports/acceptance-report.md)
- Machine report: [`evidence/acceptance-report.json`](evidence/acceptance-report.json)
- Command transcript: [`evidence/command-log.txt`](evidence/command-log.txt)
- Environment: [`evidence/environment.txt`](evidence/environment.txt)
- Extras matrix: [`evidence/extras-report.json`](evidence/extras-report.json)
- Wheel inspection: [`evidence/wheel-report.json`](evidence/wheel-report.json)
- Container inspection: [`evidence/container-report.json`](evidence/container-report.json)
- Archive checksums: [`evidence/checksums.sha256`](evidence/checksums.sha256)

The retained artifacts contain deterministic offline TXT, EPUB 2, EPUB 3, image, and CBZ
samples plus the exact default Wheel. There are no GUI screenshots or browser traces.

Verify from this directory with:

```bash
shasum -a 256 -c evidence/checksums.sha256
```

No remote branch push, v0.3.0 tag, GitHub Release, deployment, paid Provider request, or real
external manga-model execution was performed.
