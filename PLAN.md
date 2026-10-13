# PaperCart：iOS 文献“购物车”（路线 A：PWA + 定时聚合）

> 目标链路：iPhone 刷最新标题和摘要 → 一键加入购物车 → 电脑端 Zotero 指定文件夹自动出现条目 → 回到电脑上，在校园网或 WebVPN 下用“查找可用 PDF”拿全文精读。
> 实施由 Codex 推进，约定见 [AGENTS.md](AGENTS.md)。不需要 Mac，也不需要 Apple 开发者账号。

---

## 0. 范围

**MVP 包含**
- 定时抓取期刊和工作论文，生成静态 `feed.json`；
- PWA 信息流（按来源筛选、已读状态、离线缓存）；
- 一键把条目写入 Zotero 指定集合；
- 点标题后用 Safari 打开原文页。

**MVP 不包含**
- 机构认证；
- PDF 下载或上传；
- 推送通知；
- 多用户。

---

## 1. 架构

```
┌──── GitHub Actions（cron，每 6 小时一次，Linux）──────────────────┐
│ aggregator/（Python ≥3.10）                                         │
│   sources.yaml ──► CrossrefFetcher（按 ISSN 或 DOI 前缀）           │
│                └─► RSSFetcher（feedparser）                         │
│   ──► normalize（统一 Paper 模型，去 JATS 标签，过滤非论文条目）    │
│   ──► dedupe（以 DOI 为主，其次规范化 URL）──► zotero_map           │
│   ──► web/public/data/feed.json（保留最近 120 天）                  │
│ web/（Vite + Preact + TS + vite-plugin-pwa）build ──► 静态站点部署  │
└─────────────────────────────────────────────────────────────────────┘
                 │ HTTPS 静态文件
┌──── iPhone Safari →“添加到主屏幕” ──────────────────────────────────┐
│ 读取 feed.json → 信息流 → 点“加购”                                  │
│   → 在 zotero 字段的基础上补上 collections 和 tags                  │
│   → 浏览器直接 POST 到 api.zotero.org（如果 CORS 不通，走 Worker 中转）│
│ API Key、目标集合、已读和购物车状态全部存在 IndexedDB，只留在本机    │
└─────────────────────────────────────────────────────────────────────┘
```

**设计原则**
- **元数据转换只在 Python 端做一次**：聚合器直接输出 Zotero item JSON（不含 collections），前端只负责“补上集合，然后 POST”。这样字段映射集中在一处，可以用 pytest 做快照测试。
- **整个仓库不含任何密钥**：Zotero Key 只在手机设置页里输入；CI 只需要 Crossref 的 `mailto`，而且它不是机密。
- **配置外置**：`sources.yaml` 里每个源都带 `verified: YYYY-MM-DD` 字段。

### 1.1 `feed.json` 结构（schema 版本 1）

```json
{
  "schema": 1,
  "generated_at": "2026-10-13T06:00:00Z",
  "sources": [{"id": "jf", "name": "Journal of Finance", "short": "JF", "group": "finance", "kind": "journal"}],
  "papers": [{
    "id": "doi:10.1111/jofi.xxxxx",
    "doi": "10.1111/jofi.xxxxx",
    "source": "jf",
    "kind": "journalArticle",
    "title": "...",
    "authors": [{"given": "...", "family": "..."}],
    "abstract": "纯文本或 null",
    "published": "2026-10-01",
    "first_seen": "2026-10-13T06:00:00Z",
    "date_precision": "published",
    "url": "https://doi.org/10.1111/jofi.xxxxx",
    "wp_number": null,
    "zotero": {"itemType": "journalArticle", "title": "...", "creators": [], "...": "..."}
  }]
}
```

`group` 字段的取值为 `econ-top5`、`finance`、`working-paper`。
`date_precision` 表示用于排序和保留的日期来源：`published` 或 `first_seen`。没有发表日期时 `published` 为 null，使用持久化首次发现时间，不伪造发表日期。年月精度仍保留在 `published` 本身。

### 1.2 数据源策略

| 来源 | 策略 | 说明 |
|---|---|---|
| AER、QJE、JPE、ECTA、RES、JF、JFE、RFS | Crossref `/journals/{ISSN}/works`，参数为 `filter=from-pub-date:…,type:journal-article`、`sort=published`、`mailto=…` | 过滤掉 front matter、勘误、编辑报告、致审稿人名单等条目 |
| 期刊摘要缺失时 | 用出版商 eTOC RSS 的 description 补全，按 DOI 匹配 | 实测各家的覆盖率 |
| NBER、FEDS | 优先用 Crossref 的 `/prefixes/{prefix}/works`，其次用官方 RSS | DOI 前缀需要实测确认 |
| ECB WP、BIS WP、BFI WP | 官方 RSS | 没有 DOI 时用规范化 URL 作为 id |

**候选 ISSN（print/online），使用前必须实测：**

| 期刊 | ISSN |
|---|---|
| AER | 0002-8282 / 1944-7981 |
| QJE | 0033-5533 / 1531-4650 |
| JPE | 0022-3808 / 1537-534X |
| ECTA | 0012-9682 / 1468-0262 |
| RES | 0034-6527 / 1467-937X |
| JF | 0022-1082 / 1540-6261 |
| JFE | 0304-405X / 1879-2773 |
| RFS | 0893-9454 / 1465-7368 |

### 1.3 Zotero 映射与写入

- **期刊论文**：`itemType` 为 `journalArticle`，包含 `title`、`creators`（`creatorType: author`）、`abstractNote`、`publicationTitle`、`journalAbbreviation`、`volume`、`issue`、`pages`、`date`、`DOI`、`ISSN`、`url`。
- **工作论文**：`itemType` 为 `report`，并设置 `reportType: "Working Paper"`、`institution`（例如 National Bureau of Economic Research）、`reportNumber`、`seriesTitle`。
- **写入接口**：`POST https://api.zotero.org/users/{userID}/items`，请求头带 `Zotero-API-Key`、`Zotero-API-Version: 3`、`Zotero-Write-Token`（32 位十六进制随机串，重试时复用同一个）。
- **结果解析**：检查响应中的 `successful`、`unchanged`、`failed` 三项。
- **限流**：遵守 `Backoff` 和 `Retry-After` 响应头，遇到 429 或 503 时做指数退避，最多重试 3 次。
- **设置页**：调用 `GET /keys/current` 校验 Key 是否有写权限并取得 userID，再用 `GET /users/{id}/collections` 列出集合供用户选择。
- 字段名以 `GET https://api.zotero.org/items/new?itemType=…` 返回的模板为准，M0 时拉取并存为 fixture。

### 1.4 M0 之后的决策（2026-10-13，依据见 `docs/SPIKES.md`）

| # | 问题 | 决策 |
|---|---|---|
| D1 | M0 验证中发现的限制 | 接受，作为 M0 结论记录并提交 |
| D2 | JPE、JFE 两种渠道都没有摘要 | MVP 先只显示书目信息，前端标明“无摘要”。M2 实测 OpenAlex、Semantic Scholar 元数据 API；后续补全范围与持久化按 E3–E5 执行，**不抓出版商网页** |
| D3 | ECTA 在 Crossref 的采样窗口为空 | 以 RSS 为主来源（摘要取自 `content:encoded`），Crossref 为辅。M1 顺带查明窗口为空的原因，例如 type 过滤或日期字段，写入 SPIKES.md |
| D4 | RSS 摘要所在字段不统一 | 解析器同时支持 `description` 和 `content:encoded`，按 `sources.yaml` 中的 `abstract_location` 选择 |
| D5 | BFI 没有合格的工作论文 feed | MVP 中停用（`status: disabled`），保留配置条目以后再议 |
| D6 | ECB 条目的链接直接指向 PDF | 允许 `url` 字段为开放获取的 PDF 链接，只用于用户点击后在 Safari 中打开；聚合器和前端**都不请求**这个 URL |
| D7 | Crossref 前缀查询会混入其他系列 | NBER 只保留 `10.3386/w<数字>`，FEDS 只保留 `10.17016/feds.` 开头的 DOI |
| D8 | Crossref 的 `mailto` | 用用户的账号邮箱，通过环境变量 `CROSSREF_MAILTO` 注入：本地放在 shell 环境，CI 放在 GitHub Secret。**仓库里不写入** |

### 1.5 M2 审查决策（协调方确认）

| # | 决策 |
|---|---|
| E1 | ECB 只保留 Working Paper Series，排除 Discussion Papers 等其他系列 |
| E2 | 无日期条目以 state 中不可重置的 first_seen 排序并保留 120 天；feed 增加 first_seen 和 date_precision（published/first_seen）。build 支持 --state，默认 aggregator/state/state.json，git 忽略，CI 持久化留待 M5。NBER 从 /papers/w<n> 推出已验证 DOI，与 Crossref 按 DOI 合并，以 RSS 摘要为准 |
| E3 | 所有已获取摘要写入 state 跨运行保留；S2 缓存与冷却同在 state，不再独立保存缓存文件 |
| E4 | S2 回填 NBER 中仍缺摘要的条目，最新优先；默认全运行请求上限 2，可配置，遵守 429 冷却。JPE 保留既有补全能力 |
| E5 | JFE 暂接受缺摘要，不请求 S2 补全；OpenAlex 暂不接入，后续需要免费 API key，由用户决定是否申请 |

---

## 2. 里程碑（Codex 按顺序推进，每完成一项就勾选并写一行说明）

- [x] **M0 骨架与技术验证**
  - 完成：建立 Python/Web 骨架并录制 CORS、模板、逐源响应及摘要统计；pytest/Vitest 空套件、Web 构建和 npm ci 通过。按 D1–D8 接受限制，ECTA 以 RSS 为主、BFI 停用，详情见 `docs/SPIKES.md`。
  - **仓库骨架**：`aggregator/`（pyproject、src 布局、pytest）、`web/`（Vite + Preact + TS + Vitest）、根目录 `README.md`、`.gitignore`。
  - **验证项**，结果写入 `docs/SPIKES.md`：
    1. 用 `curl -i -X OPTIONS` 模拟预检请求（`Origin` 设为 `https://example.github.io`，`Access-Control-Request-Method: POST`，`Access-Control-Request-Headers: zotero-api-key,zotero-api-version,zotero-write-token,content-type`），确认 api.zotero.org 是否允许跨域写入；对 `GET /keys/current` 也做同样检查。
    2. 确认 api.crossref.org 是否返回 CORS 头（仅作记录，前端并不直接调用 Crossref）。
    3. 逐个实测 8 本期刊的 ISSN、NBER 和 FEDS 的 DOI 前缀，以及各工作论文 RSS 和期刊 eTOC RSS 的 URL，写入 `aggregator/sources.yaml`，并标注 `verified` 日期。
    4. 按 1.2 的参数抓取期刊样本，统计各期刊返回的摘要条数，写入 `SPIKES.md`。
    5. 拉取 `journalArticle` 和 `report` 两种条目模板，存为 fixture。
  - **验收**：`SPIKES.md` 对每一项都给出明确结论；两边的空测试都能跑通。
  - **CORS 判定**：如果 Zotero 不允许跨域，**停下来报告**，由用户决定是否改走 Cloudflare Worker 中转。
- [x] **M1 Crossref 抓取**：实现 fetcher、normalize、非论文过滤和 JATS 标签清理；用录制的 fixture 做单元测试。
  - 完成：实现限两页且间隔至少一秒的 Crossref 抓取、Paper 规范化、非论文/JATS 清理、NBER/FEDS 系列过滤和邮箱脱敏；查明 ECTA 年份日期导致空窗口并记录在 SPIKES.md。82 项离线 fixture 测试通过，真实 AER 两页及 NBER/FEDS 抓取复验通过，未开始 M2。
- [x] **M2 RSS 抓取与合并**：实现 RSS fetcher、URL 规范化、以 DOI 优先的去重、摘要回填；输出 `feed.json` 并按 schema 校验。
  - 完成：落实 D2/D4/D6 与 E1–E5，实现 RSS 合并、统一 state/首次发现日期/摘要持久化、NBER 优先补全和全运行请求上限；143 项离线测试通过，连续两次真实 build 各输出 610 条并通过 schema，NBER 各 222 条/42 条有摘要，第二次 S2 请求 0 且 first_seen/摘要未改变。未提交、未开始 M3，详情见 SPIKES.md。
  - 命令行入口：`python -m papercart.build --out web/public/data/feed.json`。
- [x] **M3 Zotero 映射**：实现 `zotero_map`，对每种来源各做一条快照测试，并断言产出的字段名都在 M0 拉取的模板字段集合内。
  - 完成：实现 journalArticle/report 映射、M0 模板字段及作者格式校验，接入 build/schema 并兼容旧 M2 feed/state；12 个启用来源各一条快照，BFI 保留停用空快照，生成 36 条前端样本及 zotero-write.md。落实审查 F1–F4：关闭 JFE RSS、增加同源缺 DOI 的精确标题去重、统一非论文及历史记录过滤，记录 ECB 缺作者限制；201 项离线测试通过，离线重建及一次真实 build 各 586 条并通过 schema，各源重复标题均为 0；真实 NBER RSS 返回 503，state 保留 222 条/42 条摘要。未调用 Zotero 写入接口、未提交、未开始 M4，详情见 SPIKES.md。
- [x] **M4 PWA 界面**：
  - 完成：实现中文移动端三 Tab、safe-area/深色模式、筛选/已读/摘要、IndexedDB 购物车与设置，以及持久化 Zotero 批次/Token/共享退避/412 核对保护；加入相对路径 PWA、图标和 feed 网络优先缓存。审查后修复初始化阻塞、超时/错误重试及窄屏收缩换行；36 项 mock Vitest、npm run build、本机子路径静态冒烟、Chromium 51 项布局/故障回归与六张主题截图检查及 git diff --check 通过。未访问 Zotero 写入或 PDF，iPhone 真机/授权接口/实际 SW 离线行为留待 M6，未提交、未开始 M5。
  - 信息流：按 group 和来源筛选，未读优先，点击展开摘要；
  - 加购：每条一个按钮，状态依次为“未加购 → 写入中 → 已入库 / 失败可重试”；
  - 购物车页；设置页（输入 Key 并校验、选择集合、可选默认标签）；
  - manifest、图标、Service Worker 缓存 feed；
  - Vitest：Zotero client 的写入 Token 复用、退避逻辑、结果解析（mock 掉 fetch）。
- [x] **M5 CI/CD**：GitHub Actions 包括两个 workflow：
  - [x] `test.yml`：push / pull_request 跑 Python 3.12 pytest，以及 Node 24 的 npm ci、Vitest、build；pip/npm 使用依赖文件缓存。
  - [x] `publish.yml`：每 6 小时（UTC 分钟 17）及手动触发，恢复 state → 聚合 → 校验 → Web 构建 → 校验产物 → 官方 Pages 上传/部署；Secret 注入 mailto，最小权限及串行部署已配置。
  - [x] state 随站点发布为 data/state.json，从 SITE_URL 或 Pages base_url 恢复，下载失败从空 state 开始；原始 state 敏感信息/字段白名单校验和回归测试完成，前端及 SW 不读取/缓存 state。
  - [x] 单源失败可继续发布；空 feed、schema 错误或敏感 state 会阻止上传，README 已写明部署步骤。
  - [x] 本地工作流校验与无部署模拟：actionlint 1.7.12 通过，真实 curl 下载失败回退后从空 state 聚合 586 条；源数据/构建产物校验、npm ci、36 项 Vitest、Web build 均通过，218 项 Python 离线测试（含 17 项发布回归）通过，本地 Python 3.10 / CI 配置 3.12。S2 429 按既有冷却处理，不影响产出；未请求 PDF/全文或 Zotero 写入，未提交。
  - [x] 首次真实部署：2026-10-13 推送到 t1mothychou86-eng/readmobile，Test 与 Publish 均成功；站点 https://t1mothychou86-eng.github.io/readmobile/ 返回 586 条（gzip 后约 215 KB），state.json 中没有邮箱。publish 增加了 push 到 main 时的触发。
  - [x] 跨部署 state 恢复：第二次发布（feed 生成时间 01:21:16Z）保留了第一次的 first_seen（01:18:11Z），state 共 633 条。
- [ ] **M6 真机与国内访问**：在 iPhone 上添加到主屏幕，走通“刷新 → 加购 → 电脑端出现条目”；如果 GitHub Pages 在国内访问不稳定，就评估 Cloudflare Pages 或其他托管方式，结论交给用户决定。
- [ ] **M7（可选）**：远端去重（在 Zotero 中按 DOI 查询）；增加 JFQA、RF 等源；关键词高亮。

---

## 3. 需要用户提供或决定的事项

| 事项 | 何时需要 |
|---|---|
| ~~Crossref `mailto`~~ | 已决定：使用账号邮箱，通过环境变量注入（见 D8） |
| ~~如果 Zotero 不允许跨域，是否用 Worker 中转~~ | 不需要：M0 实测 CORS 可行 |
| ~~GitHub 公开仓库~~ | 已完成：t1mothychou86-eng/readmobile |
| Zotero API Key（勾选写权限）、目标集合（建议叫 `00 Inbox`） | M6，只在手机上输入 |

## 4. 风险与合规

- 只抓取元数据，**不抓全文、不批量下载 PDF**。全文都在电脑端由用户逐篇手动获取。
- Crossref 请求要带 `mailto`，频率控制在每 6 小时一次，每个源分页上限 2 页。
- RSS 和 API 的格式会变化：CI 中如果某个源失败，只把该源标记为不可用，不影响其他源的产出，并且在 `feed.json` 中记录失败原因。

## 5. 以后的扩展

PWA 不够用时，可以改走原生路线：TestFlight 加云端 macOS 编译（需要付费开发者账号）。`sources.yaml`、`feed.json` 和 Zotero 映射都可以直接复用。
