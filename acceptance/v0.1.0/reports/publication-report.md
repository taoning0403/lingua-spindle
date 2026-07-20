# LinguaSpindle v0.1.0 final release report

- Result: **Published**
- Scope: v0.1.0 only; v0.2.0 was not started
- Release commit and tag target: `90439f66d2d2ddf656174bc33a34ffdacee2b41d`
- Annotated tag object: `4aa155e91ef1465e3ba8d5813b8b0d0db7477d10`
- Remote: `git@github.com:taoning0403/lingua-spindle.git`
- GitHub Release: <https://github.com/taoning0403/lingua-spindle/releases/tag/v0.1.0>
- Release state: prerelease `true`, draft `false`; published `2026-07-19T11:54:18Z`

## Real Provider result

The OpenAI-compatible DeepSeek Provider at the sanitized origin `https://api.deepseek.com` passed
the minimal Docker GUI end-to-end flow with model `deepseek-v4-flash`.

| Field | Result |
| --- | --- |
| Project | `a76cc19f-41c2-4229-8a47-5b41d3f14a7f` |
| Job | `fd04c94c-71ea-4000-b118-6f8aa7526e54` |
| Final status | `succeeded` |
| Steps | 6 succeeded, attempt 1 |
| Segments | 3 succeeded with corresponding non-Mock translations |
| Usage | prompt 133, completion 937, total 1,070 tokens |
| TXT SHA-256 | `d699035ae69e5e47bec144217e0873b3ce56657c30cee867b3bc2cfcf50d24f2` |
| JSON SHA-256 | `0699a8917c9cbfee6fb5295345fe6cd48132ebb20298fea9d25195503a57dc30` |

The final browser verification reused this persisted successful Job and made no additional paid
Provider call.

## Release assets

| Asset | Bytes | SHA-256 |
| --- | ---: | --- |
| `linguaspindle-0.1.0-py3-none-any.whl` | 67,319 | `8256ec41e189f3a9abad235d09843d09f4f2faaaa5a871e79fef75674ef70f28` |
| `linguaspindle-0.1.0.tar.gz` | 62,610 | `7af799d02754a63fc05781d182732f8d4442df1c260c9bd5dea450f9a3a1a24a` |
| `SHA256SUMS` | 206 | `f82e14be9fb972640cdada7db826ff676461df6197a6c8a44c202444da578c68` |
| `acceptance-v010-supplement.md` | 20,714 | `50122c6f837d34cda19502156a20ef2705762644315e4f4e4f08b0b9d868e499` |

All four GitHub assets were downloaded to a fresh temporary directory and compared byte-for-byte
with the local verified files. The downloaded wheel and sdist hashes match `SHA256SUMS`. The
manifest intentionally uses repository-root `dist/...` paths from the recorded generation
command, so flat Release downloads were rehashed by filename rather than using a direct flat
`sha256sum -c` invocation.

Twine metadata checks passed. A fresh isolated install returned `0.1.0` from
`linguaspindle --version`; required doctor checks passed; packaged Web assets and migration were
present; and wheel/sdist scans found no `.env`, tests, runtime data, model, font, or local-path
payload.

## Regression, Docker, browser, and security

- Ruff format/check, strict mypy, compileall, and Node syntax: Pass.
- Default pytest: 69 passed, 2 explicit browser skips, 108 upstream FastAPI deprecation warnings.
- Branch-aware coverage: 82%.
- Final Docker image:
  `sha256:36b7db00ce6feab9da36f033b41d89b690f5d34ced0a9cfc1673b12e9ff4ea37`,
  60,423,794 bytes, linux/amd64, UID/GID 10001, healthy, loopback-published, Volume retained.
- Final Docker container `linguaspindle --version`: `0.1.0`.
- Final Headless Chromium Mock flow: 1 passed, 70 deselected.
- Final existing-real-Job browser replay: 1 passed, 70 deselected; no Provider call.
- Original post-call scan: Docker `/data` 43 files / 3,019,776 bytes and browser evidence 33 files
  / 9,092,891 bytes; exact key and Authorization/Bearer hits were both zero.
- Final candidate scan: Docker `/data` 115 files / 4,925,531 bytes and 267 evidence/report/Release
  archive scan units / 7,147,792 bytes; exact key and Authorization/Bearer hits were both zero.
- Final staged scans also found zero exact-key, credential-token, and private-key-header hits.

## Git and modified surface

At publication, the remote default branch `main` and the peeled annotated `v0.1.0` tag both
resolved to `90439f66d2d2ddf656174bc33a34ffdacee2b41d`. The tag remains immutable; later maintenance
commits advanced `main`. No force push, tag overwrite, registry publish, or Docker Volume deletion
occurred during publication.

Because the repository began on an unborn `main`, the first audited baseline established 87
publishable files. The exact tag tree is preserved in
[`../evidence/publication-report.json`](../evidence/publication-report.json), originally named
`release-v010-report.json`. Changes made after
that baseline were limited to:

- `CHANGELOG.md`
- `acceptance-v010-command-log.txt`
- `acceptance-v010-supplement.json`
- `acceptance-v010-supplement.md`
- `docs/MODULE_MAP.md`
- `docs/PROJECT_STATE.md`
- `src/linguaspindle/interfaces/cli.py`
- `tests/integration/test_api_cli_shared.py`
- this post-release Markdown/JSON audit report

Before adding this post-release report, `git status --porcelain` was empty. Only explicitly ignored
local `.env`, virtual environment, caches, browser evidence, build output, and runtime data were
present. The report is committed after the immutable release tag so it can record the actual URL
and publication metadata without moving the tag.

## Remaining limits

- Real `manga-image-translator`: **Blocked**; no live model/font/runtime acceptance is claimed.
- Native Windows: **Not in scope**.
- Long documents, concurrency, rate-limit behavior, and long-term stability remain unvalidated.
- Direct Docker Hub OAuth access remained host-network dependent; the final build itself passed.
- This is a single-host Technical Preview with loopback-first deployment, not a production-stable
  or publicly exposed service.

## Final conclusion

```text
LinguaSpindle v0.1.0 has been published as a WSL2/Linux Technical Preview.
The real OpenAI-compatible Provider passed a minimal end-to-end validation.
Long-document scale, concurrency, rate-limit behavior, long-term stability,
native Windows, and the real manga model runtime remain outside this release acceptance.
```
