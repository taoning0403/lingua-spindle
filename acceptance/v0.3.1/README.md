# LinguaSpindle v0.3.1 acceptance archive

Final status: **Pass / release pending**.

This archive binds the v0.3.1 service-call hardening acceptance run to clean source candidate
`1d5949437bbbbd0bdbeb1a86d407832dd2d28c3c`. The later local commit containing this directory
adds retained evidence and the final maintained project-state conclusion only.

- Human report: [`reports/acceptance-report.md`](reports/acceptance-report.md)
- Machine report: [`evidence/acceptance-report.json`](evidence/acceptance-report.json)
- Command transcript: [`evidence/command-log.txt`](evidence/command-log.txt)
- Environment: [`evidence/environment.txt`](evidence/environment.txt)
- Extras matrix: [`evidence/extras-report.json`](evidence/extras-report.json)
- Wheel inspection: [`evidence/wheel-report.json`](evidence/wheel-report.json)
- Migration evidence: [`evidence/migration-report.json`](evidence/migration-report.json)
- Security/leak evidence: [`evidence/security-report.json`](evidence/security-report.json)
- Compose evidence: [`evidence/compose-report.json`](evidence/compose-report.json)
- Container inspection: [`evidence/container-report.json`](evidence/container-report.json)
- Archive checksums: [`evidence/checksums.sha256`](evidence/checksums.sha256)

The retained artifacts contain deterministic offline TXT, EPUB 2, EPUB 3, image, and CBZ samples
plus the exact default Wheel. There are no GUI screenshots, browser traces, paid Provider outputs,
runtime databases, raw Provider keys, or raw Idempotency-Keys.

Verify from this directory with:

```bash
shasum -a 256 -c evidence/checksums.sha256
```

No remote branch push, v0.3.1 tag, GitHub Release, Wheel/image publication, or server deployment
was performed. Those actions require separate authorization.
