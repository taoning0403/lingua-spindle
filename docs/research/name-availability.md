# Name availability research

Checked on 2026-07-19. Registry state can change at any time; repeat these checks immediately
before publishing the repository or packages. A successful lookup is evidence of current public
use, not a trademark clearance.

At release time, the owner-scoped repository was created and verified as
`taoning0403/lingua-spindle`. No package or image registry publication is part of v0.1.0.

## Results

| Surface | Queries | Result |
| --- | --- | --- |
| GitHub repositories | `LinguaSpindle`, `lingua-spindle`, `linguaspindle` | GitHub repository search returned no matches. |
| GitHub account/organization handles | `github.com/linguaspindle`, `github.com/lingua-spindle` | Both returned HTTP 404. Repository names remain owner-scoped. |
| PyPI JSON API | `linguaspindle`, `lingua-spindle` | Both returned HTTP 404. |
| npm registry | `linguaspindle`, `lingua-spindle` | Both returned HTTP 404. |
| Docker Hub search | `linguaspindle` | Search returned zero repositories; both `library/linguaspindle` and `library/lingua-spindle` returned HTTP 404. |
| Quay search | `linguaspindle` | Search returned zero repositories. |
| GHCR | account-scoped package name | No global package reservation exists independently of a GitHub owner. |

## Decision

Proceed with **LinguaSpindle**, repository `lingua-spindle`, Python distribution and CLI
`linguaspindle`. The verified source repository is `taoning0403/lingua-spindle`; an owner-scoped
image would use that owner if a later release explicitly publishes one. Do not claim that package
or image names are reserved until they are actually registered.

## Evidence URLs

- [GitHub repository search](https://github.com/search?q=LinguaSpindle&type=repositories)
- [PyPI `linguaspindle` JSON](https://pypi.org/pypi/linguaspindle/json)
- [PyPI `lingua-spindle` JSON](https://pypi.org/pypi/lingua-spindle/json)
- [npm `linguaspindle`](https://registry.npmjs.org/linguaspindle)
- [npm `lingua-spindle`](https://registry.npmjs.org/lingua-spindle)
- [Docker Hub search](https://hub.docker.com/v2/search/repositories/?query=linguaspindle)
- [Quay search](https://quay.io/api/v1/find/repositories?query=linguaspindle)
