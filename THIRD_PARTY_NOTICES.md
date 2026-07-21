# Third-party notices

LinguaSpindle core is Apache-2.0. That license does not replace the licenses of dependencies or
external services. The structured source of record is
[`third-party-components.toml`](third-party-components.toml); installed distributions and upstream
projects remain authoritative for their complete terms.

## Default core

The default v0.3.0 dependency set has one direct runtime library:

- **charset-normalizer** (MIT), used for bounded TXT charset detection.

The default Wheel includes the LinguaSpindle public core, Mock Provider, Mock Manga Adapter, and
package migrations. It does not include server/database/CLI frameworks, HTTPX, Playwright/browser
binaries, external manga code, models, fonts, containers, or GPU runtime.

## Optional Python dependencies

Optional extras add permissively licensed direct dependencies:

| Extra | Direct components |
| --- | --- |
| `openai` | HTTPX (BSD-3-Clause) |
| `manga` | HTTPX (BSD-3-Clause) |
| `runtime` | SQLAlchemy (MIT), platformdirs (MIT) |
| `cli` | Typer (MIT) |
| `server` | FastAPI (MIT), Uvicorn (BSD-3-Clause), Pydantic (MIT), Starlette (BSD-3-Clause), python-multipart (Apache-2.0), SQLAlchemy (MIT), platformdirs (MIT) |

Their transitive dependencies retain their own licenses/notices in installed distributions.
`constraints-v030.txt` records direct versions used by the development/acceptance environment;
`constraints-v020.txt` and `constraints-v010.txt` remain historical constraints.

Development tools include build/setuptools, pytest/pytest-cov, Ruff, and mypy. v0.3.0 removes
Playwright and browser binaries from the dependency and acceptance contract.

## External manga service

The optional Adapter `manga-image-translator-http` implements an HTTP protocol for
[`zyddnys/manga-image-translator`](https://github.com/zyddnys/manga-image-translator), researched
at commit `efdc229de8aa0f3d4051ad97664adc62dd5ac605` (GPL-3.0-only).

LinguaSpindle:

- does not vendor, import, modify, build, install, start, download, or redistribute the upstream;
- includes only its own optional protocol client;
- includes no upstream container, model/weight, GPU dependency, or font;
- requires the operator to install, operate, license, update, and secure the service separately;
  and
- communicates only over the configured HTTP boundary.

The inspected upstream snapshot did not provide a complete per-weight and per-font redistribution
inventory. Absence from LinguaSpindle is not a finding that those assets are unrestricted.
Operators must identify and satisfy every selected model/font term before production deployment
or redistribution.

The deterministic `MockMangaAdapter` is LinguaSpindle code under Apache-2.0. A fake HTTP contract
test and the Mock are not real upstream model execution.

## Research-only projects

`comic-translate`, `BallonsTranslator`, Ebook-Translator-Calibre-Plugin, and `docutranslate` were
evaluated but are not runtime components. Their mention in research does not bundle, depend on, or
relicense them.

If this inventory and an installed package's license disagree, the upstream package license
controls. Report discrepancies through `SECURITY.md` when security-related or an ordinary issue
otherwise.
