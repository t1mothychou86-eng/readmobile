# PaperCart

文献购物车：定时聚合元数据，供 iPhone PWA 浏览，并把选中的条目加入 Zotero。
完整范围和里程碑见 [PLAN.md](PLAN.md)，工作约定见 [AGENTS.md](AGENTS.md)。

目前完成 M0 骨架与技术验证、M1 Crossref 抓取及规范化。RSS、摘要补全、去重、Zotero 映射、IndexedDB、PWA 和 CI 留待对应后续里程碑。
技术验证、失败原因和需要用户决定的事项见 [docs/SPIKES.md](docs/SPIKES.md)。

## Python（≥3.10）

```bash
python3 -m venv aggregator/.venv
aggregator/.venv/bin/python -m pip install -e './aggregator[test]'
aggregator/.venv/bin/python -m pytest aggregator
```

本次 WSL 缺少 `ensurepip`，但已有系统用户级 pip。创建 venv 后可用下述命令在该虚拟环境内补齐工具（无需 sudo，也不修改系统）：

```bash
python3 -m pip --python aggregator/.venv install pip
aggregator/.venv/bin/python -m pip install -e './aggregator[test]'
```

pytest 使用真实录制的 fixture 和 respx 模拟 API 响应。默认禁止 socket 网络连接，测试还会覆盖 shell 中的 mailto，避免将真实邮箱写入 mock 请求和测试失败输出。
真实网络测试应标记 `live`，只有 `LIVE_TEST=1` 才运行；诊断脚本同样需要显式开启该变量。

## Web（Node 24、npm）

```bash
cd web
npm ci
npm test
npm run build
npm run dev
```

Vitest 的 M0 空套件使用 `--passWithNoTests`。PWA 插件和 IndexedDB 依赖已声明，实际功能留给 M4。

## 重现 M0 网络采样

```bash
LIVE_TEST=1 aggregator/.venv/bin/python aggregator/scripts/spike.py zotero
LIVE_TEST=1 aggregator/.venv/bin/python aggregator/scripts/spike.py crossref
LIVE_TEST=1 aggregator/.venv/bin/python aggregator/scripts/spike.py rss
```

脚本没有 Zotero 写入功能；OPTIONS 使用库 ID `0`，只验证预检；GET 只拉取公开模板。
Crossref 采样固定为 `from-pub-date:2026-06-15`、每页 25 条；每刊分别查询两个候选 ISSN，共两页，不翻页。
每个工作论文前缀取一页，每个 RSS 取一页，重定向最多一次。请求间等待至少一秒；Zotero 的 `Backoff`、`Retry-After` 优先。
不要并发运行这些网络命令；默认测试不会运行脚本。

`CROSSREF_MAILTO` 未设置时使用 `papercart@example.invalid` 并警告。没有账号、密钥或个人邮箱的需求。
录制内容中的邮箱统一替换为占位符，日志不输出真实请求邮箱；失败响应只保存状态及安全的 JSON 错误信息。
BFI 不合格 feed 的录制删去了 `content:encoded`，只保留判定内容类型所需的标题、链接、description。
`sources.yaml` 中 `verified: null` 表示未验证通过，`checked` 表示已尝试；不能把候选 URL 当作可用源。

严格只处理元数据，不请求全文或 PDF URL，也不向真实 Zotero 库写入。D6 允许保存开放获取 PDF 地址供用户点击，程序不会请求该链接。

## M1 Crossref 模块

`load_sources()` 读取配置；`CrossrefFetcher.fetch(source, from_date=...)` 返回源状态、论文列表及接收/过滤/页数统计。
`fetch_all()` 隔离每个源的失败；默认最多两页、每页 100 条，请求之间至少一秒，禁用重定向。
只请求 Crossref 的 journal/prefix 元数据端点，不跟进响应中的 DOI、resource、link 或 PDF 地址。
ECTA 可以显式请求辅助 Crossref 数据，但 `primary: rss` 决策保持不变；BFI disabled 时不会发请求。
NBER/FEDS 同时按配置和 D7 限制系列。`Paper` 保留日期的年/月/日精度，缺摘要为 null，Zotero 映射留待 M3。

可选的真实验证（每个命令每个源最多两页；不要并发运行）：

```bash
LIVE_TEST=1 aggregator/.venv/bin/python aggregator/scripts/verify_crossref.py ecta-metadata
LIVE_TEST=1 aggregator/.venv/bin/python aggregator/scripts/verify_crossref.py ecta-controls
LIVE_TEST=1 aggregator/.venv/bin/python aggregator/scripts/verify_crossref.py ecta-year-sample
LIVE_TEST=1 aggregator/.venv/bin/python aggregator/scripts/verify_crossref.py pagination
LIVE_TEST=1 aggregator/.venv/bin/python aggregator/scripts/verify_crossref.py prefixes
```

这些命令保存脱敏的 Crossref 响应，不保存请求中真实的 mailto。M2 必须另行指派。
