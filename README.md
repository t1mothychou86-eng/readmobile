# PaperCart

文献购物车：定时聚合元数据，供 iPhone PWA 浏览，并把选中的条目加入 Zotero。
完整范围和里程碑见 [PLAN.md](PLAN.md)，工作约定见 [AGENTS.md](AGENTS.md)。

目前完成 M0–M4：元数据聚合、Zotero 映射，以及中文移动端 PWA（信息流、购物车、设置、IndexedDB 和离线缓存）。CI/CD 与真机联调留给 M5/M6。
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

Vitest 使用 mock fetch 和 mock IndexedDB 适配器，默认不访问网络。生产构建包含 manifest、图标和 Service Worker。
开发时若 `public/data/feed.json` 不存在，会使用 36 条录制样本；生产环境必须提供生成的 `data/feed.json`。
页面支持 `#feed`、`#cart`、`#settings`。存储或 feed 初始化失败/超时会显示明确错误并提供重试；本地存储不可用时可以浏览，无法保存设置或加购。
Key 在设置页输入并校验，集合默认选 `00 Inbox`（若存在）。Key、集合、标签、筛选、已读、购物车、写入批次及冷却时间均存于本机 IndexedDB。
写入未确认时重试沿用原正文和 Token；412 需先在 Zotero 核对，界面阻止重发。真实 Key 校验及写入仅供后续真机联调，本次测试没有调用授权接口。

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
NBER/FEDS 同时按配置和 D7 限制系列。`Paper` 保留日期的年/月/日精度，缺摘要为 null，build 在合并和摘要回填后生成 Zotero 映射。

可选的真实验证（每个命令每个源最多两页；不要并发运行）：

```bash
LIVE_TEST=1 aggregator/.venv/bin/python aggregator/scripts/verify_crossref.py ecta-metadata
LIVE_TEST=1 aggregator/.venv/bin/python aggregator/scripts/verify_crossref.py ecta-controls
LIVE_TEST=1 aggregator/.venv/bin/python aggregator/scripts/verify_crossref.py ecta-year-sample
LIVE_TEST=1 aggregator/.venv/bin/python aggregator/scripts/verify_crossref.py pagination
LIVE_TEST=1 aggregator/.venv/bin/python aggregator/scripts/verify_crossref.py prefixes
```

这些命令保存脱敏的 Crossref 响应，不保存请求中真实的 mailto。

## M2 构建信息流

```bash
aggregator/.venv/bin/python -m papercart.build --out web/public/data/feed.json
```

构建按源合并 Crossref 与 RSS；ECTA 和 NBER 优先 RSS（NBER 以 RSS 摘要为准），其他源优先 Crossref，BFI 停用。ECB 仅保留 Working Paper Series，排除 Discussion Papers 等其他系列。
RSS 只请求配置中已验证且 enabled 未关闭的 feed 地址，解析 description 或 content:encoded；不请求条目链接。JFE RSS 按 F1 设 enabled: false，保留 URL，但因无 DOI/摘要且重复 Crossref 而不再请求。
先按 DOI 合并，再按规范化 URL/元数据 URL 别名去重；同源规范化标题完全相同、缺 DOI 且能唯一对应有 DOI 条目时，合并到有 DOI 的条目。不同 DOI、不同来源或近似标题不会按标题合并，摘要回填仍只用相同 DOI。Crossref、RSS 和历史 feed/state 共用非论文过滤，排除 Editorial Board、Recent Referees、JPE Turnaround Times 等。
ECB PDF 链接仅保存为 url；下载/请求 PDF 或全文的代码不存在。

保留发表日期范围与最近 120 天重叠的条目，保留年月日期精度、不伪造日。无日期条目使用持久化 first_seen 参与排序和保留，published 仍为 null。
每条 feed 记录增加 first_seen（UTC 时间戳）和 date_precision（published 或 first_seen，表示日期来源）。同一条目重复出现不会重置 first_seen；120 天过期后也保留其观测标记，避免旧 RSS 被重新当成新论文。
state 保存每条 paper 的元数据、首次发现时间和已获取摘要，按身份复用，源暂时失败或 RSS 换期不会清空历史摘要。过期记录不输出到 feed；已有旧版 feed 可以迁移到新字段。
每个 Crossref 源最多两页（每页 100 条），RSS 只取一页；同一次 build 的所有请求间隔至少一秒。429/503 时当次运行停止请求该 host。

Semantic Scholar 补回 NBER/JPE 的缺失摘要（可用 --no-enrich 关闭），NBER 优先，条目按最新日期及工作论文编号优先；JFE 暂时接受缺摘要，不请求补全。
默认全运行最多 2 个批量请求，可用 --abstract-max-requests 调整；每源至多两批，每批不超过 500 DOI。匿名元数据查询不使用 API Key，严格核对返回 DOI。
所有来源的已获取摘要持久化保留；S2 缺失结果缓存一天，429 冷却与 Retry-After 从响应到达时起计时并跨运行保存，不反复请求已缓存 DOI。
OpenAlex 暂不接入；后续可用性验证/接入需要用户决定是否申请免费 API key，以免依赖本机已经耗尽的匿名共享 IP 预算。政策和覆盖率见 SPIKES.md。

唯一运行状态文件默认 aggregator/state/state.json（git 忽略），可通过 --state 指定。paper 记录和 S2 缓存/冷却都在该文件中；不再写独立 abstracts.json。
首次使用默认 state 时，会导入已有的旧 S2 缓存，成功保存新 state/feed 后删除旧缓存文件。state 损坏时失败，不静默清空首次发现时间。M5 再处理 CI 中的持久化。

```bash
aggregator/.venv/bin/python -m papercart.build --out web/public/data/feed.json \
  --state aggregator/state/state.json --abstract-max-requests 2
```

feed.schema.json 是 schema 1 的校验依据，使用白名单之外零依赖的标准库校验器验证该 schema 所用关键词，同时检查 DOI/URL 身份、日期与重复 ID。
每条 paper.zotero 含经过 M0 模板字段检查的 journalArticle/report 元数据；collections 和 tags 由前端补充。旧 M2 feed/state 的空映射会在构建时重新生成。
源的状态、错误、各后端计数、摘要覆盖和日期排除计数都写入 sources，单源失败不阻断其他源；输出经校验后原子替换。

真实网络验证并录制脱敏响应：

```bash
LIVE_TEST=1 aggregator/.venv/bin/python -m papercart.build \
  --out web/public/data/feed.json \
  --record-fixtures aggregator/tests/fixtures/m2/build
```

fixture 保留实际响应的元数据；Crossref 录制删除未使用的引用/许可/资助字段以控制体积，邮箱统一脱敏。
连续两次真实验证各生成 610 条；NBER 各 222 条、42 条有摘要，第二次 S2 HTTP 请求为 0，first_seen 和摘要未改变。两次各源统计见 SPIKES.md。
不要执行 git commit；协调方审查后提交。每次只执行被指派的里程碑。

## M3 Zotero 映射

`to_zotero(paper)` 是纯元数据映射，不发请求。工作论文按 NBER/FEDS/ECB/BIS 填写 institution/seriesTitle，reportNumber 来自 wp_number；缺失字段省略，无 given 的作者使用 name 单字段形式。feed 校验同时检查模板字段、作者格式与 paper 元数据的一致性。

前端约定和 Write-Token/Backoff 处理见 [docs/zotero-write.md](docs/zotero-write.md)。离线开发样本每个启用来源三条，可复现：

```bash
aggregator/.venv/bin/python aggregator/scripts/make_feed_sample.py
```

输出为 web/src/fixtures/feed.sample.json，共 36 条；BFI 停用不生成论文。此命令只重放录制 fixture，不访问网络。

M3 审查修复后，离线重建及一次真实 build 均输出 586 条，各源重复标题数为 0；NBER RSS 本次 503，由 state 保留条目与摘要。ECB 官方 RSS 未提供作者，保留空 creators。逐源计数、覆盖率及限制见 SPIKES.md。


可选的 M4 浏览器回归（无需额外 npm 依赖）：先运行 `npm run build` 与 `npx vite preview --port 4174 --strictPort`，用本机 Chromium 启动 `--remote-debugging-port=9224`，另一个终端在 web 目录运行 `node scripts/browser-check.mjs`。脚本明确模拟手机视口，检查页面就绪/错误状态、320–430px 宽度与两种主题，并把截图保存到 `/tmp/papercart-m4`。可通过 CDP_URL、PREVIEW_URL、SCREENSHOT_DIR 改地址或输出目录；检查完结束 Chromium 和 preview。脚本不访问外部服务。
