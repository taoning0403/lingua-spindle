# LinguaSpindle

LinguaSpindle 是一个面向小说与漫画的开源翻译编排引擎。导入的源文件保持不可变；持久化
Pipeline 在重启后仍可检查和重试；无登录 Web GUI、`linguaspindle` CLI 和异步 HTTP API
共用同一个应用层与编排核心。

v0.1.0 包含两条闭环：

- TXT → 段落感知分段 → Mock 或 OpenAI-compatible 翻译 → QA → TXT/JSON；
- 图片/CBZ → 按能力选择漫画 Adapter → 译后页面与原始输出 → CBZ。

内置 Mock Provider 与 Mock Manga Adapter 可以在无 API Key、无大型模型、离线环境中完成
自动化验收。首个真实漫画集成通过 HTTP 调用单独运行的
[`manga-image-translator`](https://github.com/zyddnys/manga-image-translator)。LinguaSpindle
不会复制、静默安装或分发其 GPL 源码、模型、字体及 GPU 运行栈。

[English README](README.md)

## 信任边界

LinguaSpindle 是单实例工具，永久不包含注册、登录、账户、角色、权限、租户、所有者或协作
模型。能访问 HTTP 端口的人即可操作实例。

非容器服务默认监听 `127.0.0.1`；Docker Compose 默认也只把宿主端口发布到
`127.0.0.1`。**不要将 LinguaSpindle 直接暴露到公网。** 远程访问应使用私有网络、
VPN/Tailscale、Cloudflare Access，或经过明确配置的反向代理作为外围保护；该外围身份不进入
LinguaSpindle 的领域模型。

## 本机快速启动

需要 Python 3.11 或更高版本。

Linux、macOS 或 WSL：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
linguaspindle doctor
linguaspindle serve
```

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
linguaspindle doctor
linguaspindle serve
```

打开 <http://127.0.0.1:8765>，不会出现登录页面。若 PowerShell 禁止激活脚本，可直接执行
`.venv\Scripts\linguaspindle.exe`。详见[本地安装文档](docs/installation.md)。

## Docker Compose

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
```

打开 <http://127.0.0.1:8765>。SQLite 和全部 Artifact 位于命名 Volume
`linguaspindle-data`。核心镜像以 UID/GID 10001 非 root 运行，不包含任何外部漫画工具或
大型模型。修改回环地址端口映射前请阅读 [Docker 部署文档](docs/docker.md)。

## CLI 示例

```bash
linguaspindle projects create \
  --name "示例小说" \
  --kind novel \
  --source-language en \
  --target-language zh-CN \
  --source ./sample.txt

linguaspindle projects list
linguaspindle run PROJECT_ID --provider mock
linguaspindle jobs show JOB_ID
linguaspindle artifacts list PROJECT_ID
linguaspindle export PROJECT_ID --format txt
```

`linguaspindle run` 默认等待任务结束。通过 Web/API 创建的 Job 由持久化后台 Worker 异步
领取。暂停和取消在段落/页面安全边界生效；无法立即中断的外部 Adapter 会保持
`cancelling`，不会伪装成已经取消。

## HTTP API 示例

```bash
curl -sS -X POST http://127.0.0.1:8765/api/projects \
  -F 'name=API 示例' \
  -F 'kind=novel' \
  -F 'source_language=en' \
  -F 'target_language=fr' \
  -F 'source=@sample.txt;type=text/plain'

curl -sS -X POST http://127.0.0.1:8765/api/projects/PROJECT_ID/jobs \
  -H 'Content-Type: application/json' \
  -d '{"provider_id":"mock"}'

curl -sS http://127.0.0.1:8765/api/jobs/JOB_ID
```

OpenAPI 页面位于 <http://127.0.0.1:8765/docs>，状态与错误语义见 [API 文档](docs/api.md)。

## Provider 与密钥

Mock Provider 始终可用。OpenAI-compatible Provider 只从进程环境读取密钥：

```bash
export LINGUASPINDLE_OPENAI_BASE_URL=https://api.openai.com/v1
export LINGUASPINDLE_OPENAI_API_KEY='仅在运行环境设置'
export LINGUASPINDLE_OPENAI_MODEL=gpt-4.1-mini
linguaspindle serve
```

PowerShell 使用 `$env:LINGUASPINDLE_OPENAI_API_KEY = '...'`。HTTP API 不接收 API Key；
应用不会有意将运行时 Key 写入配置、Job 快照、数据库视图、日志、Artifact 或导出。不要提交
已填写的 `.env`。

## 真实漫画 Adapter

请单独安装、运行并核实 `zyddnys/manga-image-translator` 的许可证，然后设置：

```bash
export LINGUASPINDLE_MIT_BASE_URL=http://127.0.0.1:5003
export LINGUASPINDLE_MIT_CONFIG_JSON='{}'
linguaspindle adapters doctor
```

Adapter 调用 `/translate/with-form/image`，不会下载或启动上游。已检查的上游快照没有完整列出
每个模型权重和字体的再分发许可证，因此生产使用者必须按自身配置重新核实。详见
[Adapter 开发文档](docs/adapter-development.md)和[工具调研](docs/research/translation-tools.md)。

## 开发与验收

```bash
python -m pip install -c constraints-v010.txt -e '.[dev]'
ruff format --check src tests
ruff check src tests
mypy src
python -m compileall -q src tests
pytest -q
```

浏览器验收需要单独安装 Playwright Chromium：

```bash
playwright install chromium
LINGUASPINDLE_RUN_BROWSER_TESTS=1 pytest -q -m browser
```

实际执行结果见 [acceptance-v010.md](acceptance-v010.md)。核心代码采用
[Apache-2.0](LICENSE)；外部服务与依赖保留各自许可证，详见
[结构化第三方清单](third-party-components.toml)和[第三方声明](THIRD_PARTY_NOTICES.md)。
