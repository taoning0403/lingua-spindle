# LinguaSpindle v0.1.0 补充发布验收报告

- 验收日期：2026-07-19（Asia/Shanghai）
- 验收范围：仅 v0.1.0
- 宿主：Ubuntu 26.04 LTS on WSL2，x86_64
- 首个 Git 基线 commit：`98682bde47c536d5856e196b03cf8116693dbbaa`
- 代码修改：是；增加 Provider usage 审计、补全 Compose 已有 Provider 配置透传、扩展同一套 Playwright 验收并补齐 CLI `--version` 发布检查；migration 与 schema 未变
- 总体判断：`Pass`

> **LinguaSpindle v0.1.0 is ready for a WSL2/Linux Technical Preview release.**

真实 OpenAI-compatible Provider 最小端到端实跑为 `Pass`；真实
`manga-image-translator` 仍为 `Blocked`。普通 WSL `docker` 已复验为 `Pass`；Docker Hub
直连和 Codex agent 沙箱内的 Docker socket 访问仍有明确的环境限制，见下文。

`Native Windows execution: Not in scope for this supplemental acceptance.`

## 1. 结果矩阵

| 验收项 | 状态 | 实际结果 |
| --- | --- | --- |
| WSL2、发行版与主机 Python | Pass | WSL2 kernel `6.18.33.1-microsoft-standard-WSL2`；Ubuntu 26.04；Python 3.14.4。 |
| 普通 WSL `docker` 命令 | Pass | Linux CLI 为 `/usr/bin/docker`，解析到 `/mnt/wsl/docker-desktop/cli-tools/usr/bin/docker`；`default` context 的 Client/Server 29.6.1 正常。 |
| 当前 Codex agent 沙箱 Docker socket | Blocked | `workspace-write` + managed/restricted 权限下，Engine 命令连接 `unix:///var/run/docker.sock` 返回 `permission denied`；沙箱外同一 Linux CLI 通过，因此不是 WSL integration 故障。 |
| Docker Engine / Linux containers | Pass | 普通 Linux `docker version` 返回 Client/Server 29.6.1，Desktop 4.82.0，Server `linux/amd64`、`OSType=linux`。 |
| Docker Compose | Pass | Compose 5.3.0；普通 `docker compose ps`、health 和最小 restart 复验成功。 |
| 直接 Docker Hub 基础镜像拉取 | Blocked | 两次 `build --no-cache` 均在 `auth.docker.io:443` OAuth 请求处超时。 |
| Docker 镜像构建 | Pass | 通过 AWS Public ECR 的 Docker Official Images 镜像取得相同基础镜像 digest 后，原 Dockerfile 的无缓存构建成功；最终普通 build 成功。 |
| Compose 启动与健康 | Pass | 容器 `healthy`；`/health` 返回 `status=ok`、`database=ok`、`version=0.1.0`。 |
| GUI、API、OpenAPI | Pass | `/` 与 `/openapi.json` 均 200；GUI、异步 API 与静态资源真实可用。 |
| loopback-only | Pass | 宿主映射为 `127.0.0.1:8765->8765/tcp`；`compose port` 返回 `127.0.0.1:8765`。 |
| 非 root 与容器安全 | Pass | UID/GID 10001；非 privileged；只读根；`no-new-privileges`；仅 `/data` 可写 Volume；无 Docker socket。 |
| 镜像运行资源 | Pass | Web `index.html`/`app.js` 与 migration 均存在；`/app` 未发现模型或字体后缀资产；未复制 tests/docs/整个仓库。 |
| 有业务数据的 Volume 持久化 | Pass | GUI 创建的 Project/Job/Step/Segment/日志/Artifact 在所有重建场景保持；下载 SHA-256 不变。 |
| 场景 A：restart | Pass | 同一 ID 和 Step attempt 保持；Artifact 字节完全一致。 |
| 场景 B：down/up 保留 Volume | Pass | 未使用 `down -v`；Volume 在容器删除期间仍存在；数据与字节一致。 |
| 场景 C：build/force-recreate | Pass | 镜像重建与容器替换后数据、状态、日志、Segment 和 Artifact 均保持。 |
| WSL Headless Chromium → Docker GUI | Pass | Playwright 1.61.0 / Chromium 149.0.7827.55；Mock 与真实 Provider opt-in 流程均通过；使用 `--no-sandbox` 和获批的 loopback/browser 权限。 |
| Mock TXT GUI 流程 | Pass | GUI 创建、上传、异步轮询、Steps/日志/源译文/QA、TXT/JSON 下载与内容校验通过。 |
| Mock 失败 GUI 流程 | Pass | `partially_succeeded`、`MODEL_API_ERROR`、消息和 Step 日志正确显示。 |
| Mock Manga GUI 流程 | Pass | 单页 PNG → Mock Adapter → translated/raw Artifacts → CBZ；CBZ 仅含预期 `0001.png`。 |
| 真实 OpenAI-compatible Provider | Pass | Docker GUI 创建 3-Segment novel Job；DeepSeek OpenAI-compatible `deepseek-v4-flash` 后端请求、持久化、QA、TXT/JSON 导出与 usage 记录均通过。 |
| 真实 manga-image-translator | Blocked | 未配置服务 URL，且上游模型/字体/许可证/运行资产未提供；GUI/API 与 Job 正确显示 unavailable / `ADAPTER_UNAVAILABLE`。 |
| SIGKILL 恢复与显式 retry | Pass | 800 Segment Job 在 translate Step 运行时被 SIGKILL；恢复为 `PROCESS_INTERRUPTED`，retry 后完整成功且复用已完成工作。 |
| 密钥与身份边界 | Pass | 真实调用后扫描 Docker `/data` 43 文件、3,019,776 bytes，以及浏览器证据/trace/下载/报告 33 文件、9,092,891 bytes；真实密钥与 Authorization/Bearer 均 0 hit。 |
| Artifact provenance 与删除 | Pass | 7 个 Job Artifact 均有 Step provenance；专用测试 Project 删除后 metadata/download 404 且 payload 目录消失。 |
| 静态检查、测试、coverage | Pass | 41 files formatted；Ruff、mypy、compileall、69 default tests、82% coverage、Mock Docker 浏览器与真实 Provider opt-in 浏览器测试均通过。 |
| 容器内 `ps` | Not in scope | `python:3.12-slim` 最终镜像没有 `ps` 可执行文件；该检查仅在镜像支持时要求。 |
| 原生 Windows | Not in scope | 本轮不测试 PowerShell/Python 原生 Windows 执行。 |
| Python 多版本矩阵 | Not in scope | 按指令仅记录实际主机 3.14.4 和容器 3.12.13。 |

没有产品验收项被标记为 `Failed`。

## 2. 实际环境与版本

| 组件 | 实际值 |
| --- | --- |
| WSL kernel | `6.18.33.1-microsoft-standard-WSL2` |
| Distribution | Ubuntu 26.04 LTS (Resolute Raccoon) |
| Host Python | 3.14.4 |
| Container Python | 3.12.13 |
| Docker Client / Server | 29.6.1 / 29.6.1 |
| Linux Docker CLI | `/usr/bin/docker` |
| Linux Docker CLI resolved path | `/mnt/wsl/docker-desktop/cli-tools/usr/bin/docker` |
| Docker context | `default` |
| Docker Desktop | 4.82.0 (233772) |
| Docker Server OS | Linux/amd64, `OSType=linux` |
| Docker Compose | 5.3.0 |
| Playwright | 1.61.0 |
| Headless Chromium | 149.0.7827.55 |
| Node（JS syntax only） | 18.20.7 |
| Final image | `sha256:36b7db00ce6feab9da36f033b41d89b690f5d34ced0a9cfc1673b12e9ff4ea37` |
| Final image size | 60,423,794 bytes |
| Git | `main`; audited baseline `98682bde47c536d5856e196b03cf8116693dbbaa` |

Docker Desktop Engine 和本发行版的普通 Linux CLI 均实际可用。当前 shell 命中与最终解析路径为：

```text
/usr/bin/docker
/mnt/wsl/docker-desktop/cli-tools/usr/bin/docker
```

Windows `docker.exe` 不再是运行限制或验收前提。早先命令日志中的 `docker.exe` 调用仅保留为
当时已执行命令的历史记录，不表示当前必须使用 Windows CLI。

### 当前 agent 沙箱与普通 WSL 执行上下文

当前 agent 的 Codex 权限模式为 `workspace-write`，permission profile 为 `managed`，
filesystem 为 `restricted`，network access 为 `restricted`。在该沙箱内：

- `command -v docker` 返回 `/usr/bin/docker`，`readlink -f` 返回上述 WSL Linux CLI；
- `WSL_DISTRO_NAME=Ubuntu`，`docker context show` 返回 `default`，`docker compose version`
  返回 `v5.3.0`；
- `docker version`、`docker info --format '{{.OSType}}/{{.Architecture}}'` 和 `docker compose ps`
  均在 Engine 访问处退出 1，具体错误为
  `permission denied while trying to connect to the docker API at unix:///var/run/docker.sock`；
- agent 身份为 `uid=1000(mine) gid=1000(mine)` 且列有 `nogroup`；socket 可见为
  `srw-rw---- 660 nobody:nogroup /var/run/docker.sock`。

在沙箱外的新执行上下文中，使用同一 Linux CLI 执行用户指定的整组命令，全部退出 0：
Client/Server 均为 29.6.1，`docker info` 为 `linux/x86_64`，Compose 为 5.3.0，
`docker compose ps` 显示容器 `healthy`。结合维护者在同一 Ubuntu WSL2 发行版集成终端的
成功结果，沙箱内失败判定为 **Codex 沙箱/会话环境问题**，不是 WSL Docker integration 问题。

## 3. Docker build、Compose 与安全

`docker compose config` 显示：

- `host_ip: 127.0.0.1`，published port `8765`；
- named Volume `lingua-spindle_linguaspindle-data` → `/data`；
- `read_only: true`；
- `no-new-privileges:true`；
- `/tmp` 为 64 MiB tmpfs；
- Provider key 仅由受保护的运行时 `.env` 注入；使用 `docker compose config --quiet` 验证，
  未把展开后的 secret 写入命令日志或报告。

首次和第二次 `docker compose build --no-cache` 在 Docker Hub OAuth endpoint 失败，本地当时只有
`mcp/playwright` 镜像，没有 Python base cache。随后从
`public.ecr.aws/docker/library/python:3.12-slim` 拉取 Docker Official Image digest
`sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de`，本地标记为
`python:3.12-slim`。原 Dockerfile 的无缓存构建随后从该 digest 开始，所有 dependency/wheel/
image export 步骤成功。没有修改 Dockerfile 或 Compose 来绕过构建。

最终运行证据：

- `healthy`，最近日志没有未处理异常；
- `/health`：`{"status":"ok","version":"0.1.0","database":"ok"}`；
- 普通 Linux `docker compose restart linguaspindle` 的最小 Compose 操作成功，重启后
  `docker compose ps` 在 9 秒时显示 `healthy`，`/health` 再次返回上述成功结果；
- `/`：200，1,461 bytes，SHA-256 `da67dc0c...d5ad`；
- `/openapi.json`：200，15,750 bytes，SHA-256 `f864a000...4424`；
- `id`：`uid=10001(linguaspindle) gid=10001(linguaspindle)`；
- inspect：`Privileged=false`、`ReadonlyRootfs=true`、仅一个 rw `/data` Volume、无 bind mount/
  Docker socket；
- 包内 Web 和 SQL migration 资源存在；`/app` 无 `.pt/.pth/.onnx/.safetensors/.ttf/.otf`。

## 4. 真实业务数据持久化

持久化基准由 Docker GUI 创建：

| 实体 | ID / 值 |
| --- | --- |
| Project | `3f1c6f96-4b92-4264-b887-3a023b639e10` |
| Job | `fdf12e53-79e7-4b7e-bfae-554ef0032125`，`succeeded` |
| Steps | 6 个，全部 `succeeded`、attempt 1 |
| Segments | 2 个，全部 `succeeded` |
| TXT Artifact | `2f4c741e-f67a-46d9-b947-745b563662a3` |
| JSON Artifact | `fd69e555-4254-44f5-b38f-36b2edcfed8d` |
| TXT SHA-256 | `7768a62ac0806d25be44daccb653e36b2f060aacf1659fd7c9266fc0827f0f30` |
| JSON SHA-256 | `fb1627806463183d3af0ef154f26d7eb54865ab0faeb8c55fbf772d749bcbc7d` |

| 场景 | 健康 | 同一 Project/Job/Step/Segment/日志 | TXT SHA-256 | 状态 |
| --- | --- | --- | --- | --- |
| A `compose restart` | ok | 是 | `7768...f0f30` | Pass |
| B `compose down` + `up -d` | ok | 是；Volume 明确保留 | `7768...f0f30` | Pass |
| C `compose build` + `up -d --force-recreate` | ok | 是 | `7768...f0f30` | Pass |
| 最终 build/recreate | ok | 是 | `7768...f0f30` | Pass |

验收结束时没有执行 `down -v`，Volume 保留。

## 5. Docker GUI 与浏览器证据

Docker 目标命令：

```bash
LINGUASPINDLE_RUN_BROWSER_TESTS=1 \
LINGUASPINDLE_BROWSER_BASE_URL=http://127.0.0.1:8765 \
LINGUASPINDLE_BROWSER_EVIDENCE_DIR=/home/mine/code/lingua-spindle/artifacts/acceptance-v010 \
.venv/bin/pytest -q -m browser
```

结果：`1 passed, 68 deselected in 7.59s`。

验证内容：无需登录、loopback 提示、TXT Project/上传/Mock Job、轮询成功、Step/attempt/Artifact/
日志、源译文与 QA、TXT/JSON 下载与结构、预期 Mock 失败、Mock Manga 单页/Raw Artifact/CBZ、
真实 Adapter unavailable 状态和 `ADAPTER_UNAVAILABLE`。浏览器 `pageerror`、console error、非预期
request failure、外部 origin 均为空。

主要证据：

- `artifacts/acceptance-v010/01-runtime-capabilities.png`
- `artifacts/acceptance-v010/02-novel-job-succeeded.png`
- `artifacts/acceptance-v010/03-expected-failure.png`
- `artifacts/acceptance-v010/04-mock-manga-project.png`
- `artifacts/acceptance-v010/05-unconfigured-manga-adapter.png`
- `artifacts/acceptance-v010/browser-trace.zip`
- `artifacts/acceptance-v010/browser-evidence.json`
- `artifacts/acceptance-v010/novel-export.txt`
- `artifacts/acceptance-v010/novel-export.json`
- `artifacts/acceptance-v010/mock-manga-export.cbz`

### 真实 Provider opt-in 浏览器流程

唯一真实远端 Job：

| 字段 | 实际值 |
| --- | --- |
| Provider | OpenAI-compatible（DeepSeek） |
| 脱敏 Base URL | `https://api.deepseek.com` |
| Model | `deepseek-v4-flash` |
| Project | `a76cc19f-41c2-4229-8a47-5b41d3f14a7f` |
| Job | `fd04c94c-71ea-4000-b118-6f8aa7526e54`，`succeeded` |
| Steps | 6，全部 `succeeded`、attempt 1 |
| Segments | 3，全部 `succeeded`，逐段语义与源文对应且不是 Mock 固定前缀 |
| usage | prompt 133 / completion 937 / total 1,070 tokens |
| TXT SHA-256 | `d699035ae69e5e47bec144217e0873b3ce56657c30cee867b3bc2cfcf50d24f2` |
| JSON SHA-256 | `0699a8917c9cbfee6fb5295345fe6cd48132ebb20298fea9d25195503a57dc30` |

Headless Chromium 通过 Docker GUI 完成无需登录、Provider available、Project 创建、TXT 上传、
语言方向、Provider 选择、异步 Job、终态查看、Steps/logs/attempt/QA/Artifact、TXT/JSON 下载与
结构校验。浏览器 console error、page error、非预期 request failure 和外部 origin 均为空，远端
Provider 请求仅由后端发出。

第一次测试断言过早匹配到已成功 Step，而 Job 当时仍为 `running`；该同一 Job 随后持久化为
`succeeded`。修复等待逻辑后以 existing-Job 采证模式复查通过，没有创建第二个 Job，也没有再次
调用远端 Provider。脱敏证据位于 `artifacts/acceptance-v010/real-provider-final/`，不进入 Git 或
Release。

## 6. 中断恢复与复用

专用脚本创建 800 个短 Segment，在 `translate_text` progress 2% 时执行：

```text
docker compose kill -s SIGKILL linguaspindle
docker compose up -d
```

重启后的实际状态：

- Job：`failed / PROCESS_INTERRUPTED`；
- `translate_text`：`failed / PROCESS_INTERRUPTED`，attempt 1；
- 上游 detect/extract/segment：仍 succeeded、attempt 1、原 Artifact ID 不变；
- 中断时已有 28 个 succeeded Segment、772 个 pending。

HTTP `POST /api/jobs/{id}/retry` 后：

- Job 最终 `succeeded`；
- translate attempt 2；其余已完成上游仍 attempt 1；
- 28 个已成功 Segment 的 `updated_at` 前后完全相同；
- 最终 800 个 unique sequence，全部 succeeded，无重复；
- TXT export 包含 800 个 Segment，SHA-256
  `27333642c0735293f27eec17bfbfc960b780fa590ad43545319e3a4ce65dc65d`。

详细证据：`artifacts/acceptance-v010/recovery-evidence.json`。

## 7. Provider、Adapter、安全与产品边界

### 真实 OpenAI-compatible Provider — Pass

- `.env` 权限为 `600`，受到 Git ignore 保护；只做配置存在性布尔检查，不输出任何值；
- Docker Provider status 与 GUI 均显示 `configured/available`；
- 真实 OpenAI-compatible Provider 最小端到端实跑通过。已验证 Docker 后端、WSL Headless
  Chromium GUI、真实远端请求、Job 持久化、TXT/JSON 导出和密钥不落盘；
- 长文本规模、并发、限流及长期稳定性尚未验收。

### 真实 manga-image-translator — Blocked

- `LINGUASPINDLE_MIT_BASE_URL` 未配置；
- 上游模型、字体、硬件与逐资产许可证条件未提供；
- GUI capability 页面显示 unavailable；真实 Adapter Job 得到稳定
  `ADAPTER_UNAVAILABLE / External service URL is not configured`；
- Mock Manga 的单页端到端路径为 Pass；没有把上游源码、模型或字体打入核心镜像。

### 密钥、身份和 Artifact

- 真实调用后 Docker `/data` 扫描：43 files、3,019,776 bytes；真实密钥精确值与
  Authorization/Bearer 均 0 hit；
- 浏览器截图/trace/下载及验收文件扫描：33 files、9,092,891 bytes；两类命中均为 0；
- SQLite 表仅包含 Project/Job/Step/Artifact/Profile/ProviderConfig/Segment/QA 等实例级实体；
  identity-shaped match 为空；

最终候选提交还对当前 Docker `/data` 的 115 个文件（4,925,531 bytes），以及浏览器证据、
验收文档、wheel、sdist 与其 archive members 共 267 个扫描单元（7,147,792 bytes）复扫；真实
密钥与 Authorization/Bearer 均为 0 hit。
- `provider_configs` 仅有 `id/base_url/model/timeout/concurrency/retries/updated_at`，没有
  key/secret/token/credential 列；
- OpenAPI 没有 auth/user/account/tenant/role/permission 路由，GUI 没有密码、登录、注册入口；
- ZIP/CBZ/path 安全和递归脱敏继续由完整自动化测试覆盖；
- Docker 专用删除实跑验证 provenance、级联删除、payload 清理与 404。专用测试 Project
  `04823be4-c4bb-40ca-937f-7de6e7cdf4d6` 已删除且不可恢复；其他验收数据保留。

## 8. 最终门禁

```text
ruff format --check: 41 files already formatted
ruff check: All checks passed
mypy: Success, 24 source files
compileall: exit 0
node --check app.js: exit 0
pytest: 69 passed, 2 browser skips, 108 upstream FastAPI deprecation warnings
coverage: 69 passed, 2 browser skips, total 82%
Docker-target Mock browser: 1 passed, 1 real-provider skip, 68 deselected
real Provider opt-in evidence replay: 1 passed, 69 deselected
final compose config/build/up: exit 0
final health: ok / database ok / version 0.1.0
ordinary Linux docker version/info/compose ps: exit 0 outside the Codex sandbox
ordinary Linux docker compose restart + post-restart health: exit 0
```

警告来自 FastAPI 0.115 在 Python 3.14 下使用已弃用的 `asyncio.iscoroutinefunction`，与已有
known limitation 一致，没有测试失败。

## 9. 实际修复

发现的是验收可观测性和测试基础设施缺陷，不是 Provider/Job 产品失败：

1. `tests/conftest.py` 会在测试体开始前移除所有 `LINGUASPINDLE_*`，使新增 Docker browser
   target/evidence 环境变量失效；原 browser skip 开关因 collection-time 求值而看似正常。
2. 失败页面有多个相同错误文本，Playwright strict locator 需要明确 `.first`。
3. Chromium 对已被 Playwright 接管的成功下载导航报告预期 `net::ERR_ABORTED`，不应把它计为
   网络故障。

4. 真实 Job 的宽泛 `.badge.succeeded` locator 会先命中成功 Step，必须通过 Job API 等待明确终态。

修改 `tests/browser/test_gui_flow.py`：在 collection-time 快照验收控制变量，保留应用 runtime
环境隔离；扩展同一 Playwright 流而未增加第二套框架；只忽略明确属于成功 Artifact 下载的
`ERR_ABORTED`；真实流程支持 existing-Job 只读采证，避免因测试断言重试而重复计费。Provider
结果新增标准 token usage，并以脱敏 Step log 持久化；Compose 只补全现有 timeout/concurrency/
retry 环境变量透传。正式仓库确认后，Python metadata、安装文档、Changelog 和 OCI source label
统一为 `taoning0403/lingua-spindle`。隔离 wheel 验证发现 CLI 缺少发布所需的 `--version`，已在
现有 Typer 接口中补齐并新增回归测试。schema/API 不变。

新增两个只用于本轮证据的脚本：

- `artifacts/acceptance-v010/recovery_acceptance.py`
- `artifacts/acceptance-v010/deletion_acceptance.py`

## 10. Blocked、Failed 与发布限制

`Blocked`：

- 当前 Codex `workspace-write` + managed/restricted agent 沙箱无法连接
  `/var/run/docker.sock`；沙箱外普通 WSL Docker 为 Pass，此项不是 WSL integration blocker；
- Docker Hub OAuth endpoint 直连失败；需修复 host proxy/network 或使用可信 registry mirror；
- 真实 manga-image-translator 缺少服务、模型/字体/许可证/运行条件；
- annotated tag 与 GitHub Release 在制品校验和最终远端复核完成前仍待创建。

`Failed`：无。

`Not in scope`：原生 Windows、完整 Python 版本矩阵、容器内 `ps`、GitHub Release/tag、v0.2.0。

## 11. 最终发布判断

静态检查、自动化测试、Docker 镜像构建、Compose 启动与健康、loopback-only、非 root、真实业务
Volume 持久化、WSL Headless Chromium → Docker GUI、真实 OpenAI-compatible Provider 最小流程、
进程中断恢复、密钥与身份边界均已实跑通过。

因此：

```text
LinguaSpindle v0.1.0 is ready for a WSL2/Linux Technical Preview release.
```

发布说明必须保留：真实 Provider 只完成最小短文本实跑；长文本、并发、限流与长期稳定性未验收；
真实漫画上游仍未完成模型实跑；Docker Hub 直连仍受 host proxy/network 限制。普通 WSL Docker
命令已通过，不要将 Codex 沙箱的 socket 权限错误记为 WSL integration 故障。首个审计基线为
`98682bde47c536d5856e196b03cf8116693dbbaa`；本报告阶段尚未创建 tag/GitHub Release，且没有开始
v0.2.0。
