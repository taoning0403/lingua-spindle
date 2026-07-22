# LinguaSpindle

LinguaSpindle 是一个面向小说与漫画的无界面、可嵌入翻译编排引擎。默认 Python 包是无副作用
的纯库：不要求 GUI、数据库、服务端、账号、API Key 或后台 Worker。

当前能力包括：

- TXT 检查、稳定分段、选段翻译和 UTF-8/LF 重建；
- 常见、有效、未加密 EPUB 2/3 的结构保持翻译；
- PNG/JPEG/WebP 单图与 CBZ/ZIP 漫画翻译；
- 可由调用方实现的文本 Provider，以及职责独立的 Manga Adapter；
- 默认可用、离线且确定性的 Mock Provider 与 Mock Manga Adapter；
- 有界重试与并发、进度事件、协作式取消、部分结果和稳定错误；
- 可选的 SQLite/Artifact/Job 恢复、CLI、OpenAI-compatible Provider、真实漫画 HTTP
  Adapter 与 headless FastAPI 服务。

输入源保持不可变；输出路径或流必须由调用方显式提供。阅读器、校对界面、修订/审批历史、
书架和调用侧业务状态均由嵌入 LinguaSpindle 的应用负责。

[English README](README.md)

## 安装默认核心

需要 Python 3.11 或更高版本：

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

默认依赖只包含 TXT/EPUB 核心需要的内容，不安装 FastAPI、Uvicorn、Typer、SQLAlchemy、
HTTPX、Pydantic、Playwright、浏览器、外部漫画工具、模型、字体或 GPU 运行栈。

## 翻译 TXT 或 EPUB

```python
from pathlib import Path

from linguaspindle import MockProvider, TranslationOptions, translate_document

result = translate_document(
    Path("book.epub"),  # .txt 使用相同 API
    Path("book.zh-CN.epub"),
    MockProvider(),
    TranslationOptions(source_language="en", target_language="zh-CN"),
)

print(result.translations.status)
print(result.build.output_sha256)
```

EPUB 输出保留阅读顺序、导航、链接、锚点、封面、图片、CSS、字体和其他非文本资源。核心从
不可变原始 EPUB 重建；没有翻译或翻译失败的 Segment 保留原文；然后更新目标语言并重新打开、
检查输出。精确规则见 [EPUB 支持文档](docs/epub.md)。

## 选段翻译与人工文本

```python
from linguaspindle import (
    MockProvider,
    TranslationOptions,
    inspect_document,
    rebuild_document,
    translate_segments,
)

options = TranslationOptions(source_language="en", target_language="zh-CN")
manifest = inspect_document("novel.txt", options=options)
selected = [manifest.segments[0].segment_id]

batch = translate_segments(
    manifest,
    MockProvider(),
    options,
    selected_segment_ids=selected,
)

# 调用方可以用校对后的文本直接重建，不调用 Provider。
rebuild_document(
    "novel.txt",
    manifest,
    {selected[0]: "人工校对后的第一段。"},
    "novel.reviewed.txt",
    target_language="zh-CN",
)
```

`selected_segment_ids=None` 表示全部；显式空列表表示不翻译任何段，绝不会误变成“全部”。未知
ID 会在调用 Provider 前失败；已有翻译或人工文本优先且不会被静默覆盖。即使并发完成顺序不同，
返回记录仍按源文顺序排列，并可序列化后继续重试或重建。

## 翻译图片或 CBZ 漫画

```python
from linguaspindle import (
    MockMangaAdapter,
    TranslationOptions,
    build_manga_output,
    translate_manga,
)

translated = translate_manga(
    "chapter.cbz",
    MockMangaAdapter(),
    TranslationOptions(source_language="ja", target_language="zh-CN"),
)
build_manga_output(translated, "chapter.zh-CN.cbz")
```

Mock 会原样返回图片字节，用于离线、确定性测试；它不是实际 OCR、翻译、修复或嵌字模型执行。
真实整页翻译由可选、独立运行的 Adapter 提供。

## 可选依赖

```bash
python -m pip install -e '.[openai]'   # OpenAI-compatible HTTP Provider
python -m pip install -e '.[manga]'    # 真实漫画 HTTP Adapter 客户端
python -m pip install -e '.[runtime]'  # SQLite、Artifact、持久化 Job
python -m pip install -e '.[cli]'      # headless Typer CLI
python -m pip install -e '.[server]'   # FastAPI/Uvicorn JSON 服务和 runtime
python -m pip install -e '.[all]'      # 全部受支持可选层
```

缺少可选依赖时会返回明确的 extra 安装提示。详见[安装文档](docs/installation.md)。

## Headless CLI

```bash
python -m pip install -e '.[cli]'

linguaspindle document inspect sample.txt --target-language zh-CN
linguaspindle document translate sample.txt --target-language zh-CN --output sample.zh-CN.txt
linguaspindle manga inspect chapter.cbz
linguaspindle manga translate chapter.cbz --target-language zh-CN --output chapter.zh-CN.cbz
linguaspindle validate sample.zh-CN.txt
```

这些核心命令使用离线 Mock，不需要数据库。Project/Job/Artifact 命令需要 `[runtime,cli]`。
完整说明见 [CLI 文档](docs/cli.md)。

## Headless HTTP 服务

```bash
python -m pip install -e '.[server,cli]'
linguaspindle serve
```

OpenAPI 位于 <http://127.0.0.1:8765/docs>。根路径返回 JSON，不提供 Web GUI 或阅读器。API
保留异步 Project/Job/Artifact 链路，并提供稳定 Segment 查询、显式选段翻译和“调用方翻译映射
→ 无 Provider 重建”。详见 [HTTP API](docs/api.md)与 [Docker 部署](docs/docker.md)。

会持久化状态或触发 Provider 的 POST 接口支持 `Idempotency-Key`。默认兼容模式允许省略；服务间
调用部署可设置 `LINGUASPINDLE_REQUIRE_IDEMPOTENCY_KEY=true`。相同 Key 与相同语义请求会返回
既有资源而不重复执行。所有响应都包含 `X-Request-ID`；接口范围、重放响应头、冲突与活动 Job
合并规则见 API 文档。

## 信任边界

LinguaSpindle 是单实例引擎，永久不包含注册、登录、账户、角色、权限、租户、所有者或协作模型。
能访问可选 HTTP 端口的人即可操作实例。

服务和 Compose 默认只发布到 `127.0.0.1`。**不要将 LinguaSpindle 直接暴露到公网。** 远程
访问应使用明确配置的私有网络、VPN/Tailscale、Cloudflare Access 或具备访问控制的反向代理；
外围身份不会写入 LinguaSpindle 领域模型。

## Provider 与密钥

库调用方直接传入 Key 或 Key resolver；纯核心不会读取固定环境变量。可选 CLI/server 可以从
进程环境解析：

```bash
export LINGUASPINDLE_OPENAI_BASE_URL=https://api.example.test/v1
export LINGUASPINDLE_OPENAI_API_KEY='仅在运行环境设置'
export LINGUASPINDLE_OPENAI_MODEL=example-model
```

HTTP API 不接受 API Key；序列化模型、数据库视图、事件、错误、日志、Artifact 和导出均不应
包含 Key。不要提交已填写的 `.env`。

## 真实漫画 Adapter

可选客户端通过 HTTP 调用单独运行的
[`manga-image-translator`](https://github.com/zyddnys/manga-image-translator)：

```bash
python -m pip install -e '.[manga,runtime,cli]'
export LINGUASPINDLE_MIT_BASE_URL=http://127.0.0.1:5003
export LINGUASPINDLE_MIT_CONFIG_JSON='{}'
linguaspindle adapters doctor
```

LinguaSpindle 不复制、安装、下载、启动或分发其 GPL 源码、模型、字体、容器或 GPU 运行栈；
操作者需独立核实许可证并保障服务安全。当前 Adapter 不声明流式内部进度或即时 mid-image
取消；取消在页面边界观察。详见 [Provider 与 Manga Adapter 开发](docs/adapter-development.md)。

## v0.2.0 runtime 迁移

纯核心没有数据目录。使用可选 runtime 时，v0.2.0 的 TXT/EPUB/漫画 Project、Job、Segment
和 Artifact 可通过增量迁移 0003 保留。升级前必须停止写入并备份整个数据根；回滚通过完整恢复
备份完成，不进行原地 schema 降级。

请阅读 [v0.2 到 v0.3 迁移指南](docs/migrations/v0.2-to-v0.3.md)。

将可选 v0.3.0 runtime 升级到 v0.3.1 时，先停止写入并备份完整数据根，再应用增量迁移 0004。
详见 [v0.3 到 v0.3.1 迁移指南](docs/migrations/v0.3-to-v0.3.1.md)。

## 开发验证

```bash
python -m pip install -c constraints-v031.txt -e '.[dev]'
python -m ruff format --check src tests tools
python -m ruff check --no-cache src tests tools
python -m mypy src tools/generate_v020_acceptance.py tools/generate_v030_acceptance.py \
  tools/verify_v030_extras.py tools/generate_v031_acceptance.py tools/verify_v031_extras.py
python -m compileall -q src tests tools
python -m pytest -q
```

默认测试不访问付费服务、网络或模型，也不安装浏览器。准确的候选版本结果以
[分版本验收归档](acceptance/README.md)为准。

## 文档与许可证

- [Python 库 API](docs/library-api.md)
- [架构](docs/architecture.md)
- [数据模型](docs/data-model.md)
- [决策记录](docs/DECISIONS.md)
- [当前项目状态](docs/PROJECT_STATE.md)
- [v0.3.1 Release Notes](docs/releases/v0.3.1.md)
- [第三方组件清单](third-party-components.toml)
- [安全策略](SECURITY.md)

LinguaSpindle 核心采用 [Apache-2.0](LICENSE)。依赖和外部服务保留各自许可证；核心许可证不
替代它们的条款。
