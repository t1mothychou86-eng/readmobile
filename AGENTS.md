# AGENTS.md（Codex 工作约定）

本仓库实现 PaperCart：一个 PWA 加定时聚合器形式的文献“购物车”。完整方案见 [PLAN.md](PLAN.md)。

## 工作方式
- 严格按 PLAN.md §2 的里程碑**顺序**推进。每完成一个里程碑，就在 PLAN.md 里勾选，并附一行说明（实际做了什么、怎么验证的），**不要执行 git commit**（Codex 沙箱里的 `.git` 是只读的），由协调方（Claude）在审查后提交。汇报时附上建议的提交信息，格式为 `M<n>: <摘要>`。
- **每次只做被指派的里程碑**，做完就停下来汇报，不要自行开始下一个。
- 遇到以下情况时**停下来问**，不要自行决定：
  - 需要修改 MVP 范围；
  - 需要账号、密钥或邮箱；
  - 需要引入下方白名单以外的依赖；
  - 验证结论与 PLAN.md 的前提不一致。
- 不确定的外部事实（ISSN、RSS URL、DOI 前缀、API 字段、CORS 行为）**一律先实测再写入**，不要凭记忆硬编码。

## 环境
- 环境是 WSL Ubuntu。Python 3.10：用 `python3 -m venv aggregator/.venv` 创建虚拟环境，再用 pip 安装依赖（本机没有 uv）。Node 24 和 npm 可用（**不要用 pnpm**，本机的 pnpm 指向一个无法运行的 Windows 程序）。
- 代码必须兼容 Python ≥3.10，因为 CI 用的是 3.12。

## 依赖白名单
- **Python**：`httpx`、`feedparser`、`pyyaml`、`pytest`、`respx`（用于 mock httpx）
- **Web**：`vite`、`preact`、`@preact/preset-vite`、`typescript`、`vite-plugin-pwa`、`idb-keyval`、`vitest`

## 代码结构
- `aggregator/src/papercart/`：`sources.py`、`crossref.py`、`rss.py`、`normalize.py`、`dedupe.py`、`zotero_map.py`、`build.py`
- `aggregator/sources.yaml`：数据源配置，每一条都要有 `verified` 字段。
- `aggregator/tests/fixtures/`：录制好的真实响应。
- `web/src/`：`api/zotero.ts`、`store.ts`（基于 IndexedDB）、`components/`、`pages/`
- `docs/SPIKES.md`：技术验证记录。

## 测试
- 单元测试默认**不访问网络**，统一使用 fixture。
- 真实网络测试只在环境变量 `LIVE_TEST=1` 时运行。任何测试都**不写入**真实的 Zotero 库。

## 红线
- 不抓取全文，也不实现任何下载 PDF 的功能。程序（聚合器、前端、测试、脚本）**不得请求**任何 PDF 或全文 URL。作为链接保存或展示开放获取的 PDF 地址是允许的（见 PLAN.md D6）。
- 仓库、日志和 fixture 里不能出现 API Key 或个人邮箱。腾讯云密钥只从环境变量 `TENCENTCLOUD_SECRET_ID` 和 `TENCENTCLOUD_SECRET_KEY` 读取，不打印，也不写入 state 或 feed。
- 不保存、不请求、不处理用户的学校账号或密码，不实现任何代为登录的功能。
- `mailto` 从环境变量 `CROSSREF_MAILTO` 读取；未设置时用 `papercart@example.invalid` 作为占位，并输出一条警告。
- Zotero 请求必须遵守 `Backoff` 和 `Retry-After` 响应头，写入请求必须带 `Zotero-Write-Token`。
- 对外请求的频率要克制：每个源每次运行最多 2 页，请求之间间隔至少 1 秒。
