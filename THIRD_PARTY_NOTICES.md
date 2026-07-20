# Third-party notices

LinguaSpindle core is Apache-2.0. That license does not replace the licenses of dependencies or
external services. The machine-readable/human-reviewable source of record is
[`third-party-components.toml`](third-party-components.toml).

## Runtime libraries

The tested v0.2.0 direct runtime libraries use permissive licenses compatible with an Apache-2.0
core: FastAPI (MIT), Uvicorn (BSD-3-Clause), Typer (MIT), SQLAlchemy (MIT), HTTPX
(BSD-3-Clause), Pydantic (MIT), charset-normalizer (MIT), python-multipart (Apache-2.0), and
platformdirs (MIT). Their transitive dependencies remain under their own notices included in the
installed distributions. `constraints-v020.txt` records the current direct versions;
`constraints-v010.txt` remains as the historical v0.1.0 acceptance constraint.

Development-only tools include pytest/pytest-cov, Ruff, mypy, and Playwright for Python. They are
not imported by the production package. Playwright browser binaries are installed separately for
browser acceptance and are not committed to this repository.

## External manga service

The Adapter named `manga-image-translator-http` implements an HTTP protocol for
[`zyddnys/manga-image-translator`](https://github.com/zyddnys/manga-image-translator), inspected
at commit `efdc229de8aa0f3d4051ad97664adc62dd5ac605` (GPL-3.0-only).

LinguaSpindle:

- does not vendor, import, modify, build, download, or redistribute that upstream source;
- does not include its container, models, GPU dependencies, or fonts in the core image;
- requires the operator to install and operate the service separately; and
- communicates only over the configured HTTP boundary.

The inspected upstream snapshot did not provide a complete per-weight and per-font license
inventory. Absence from this repository is not a finding that those assets are unrestricted.
Operators must identify and satisfy the terms of every selected model and font before production
deployment or redistribution.

## Research candidates

`comic-translate`, `BallonsTranslator`, Ebook-Translator-Calibre-Plugin, and `docutranslate` were
evaluated but are not runtime components of v0.2.0. Their mention in research documentation does
not bundle, depend on, or relicense them.

If the inventory and an installed package's license disagree, the upstream package license
controls. Please report the discrepancy as described in `SECURITY.md` or through an ordinary issue
when no vulnerability is involved.
