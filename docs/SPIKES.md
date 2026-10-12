# M0 技术验证记录

验证日期：2026-10-13（Asia/Singapore）；响应录制时间为 2026-10-12 17:10–17:16 UTC。
环境：WSL Ubuntu、Python 3.10.12、Node 24.17.0、npm 11.13.0。经本机 HTTP 代理访问，不能据此保证 GitHub Actions 或国内网络同样可达。

## M0 结论与已确认决策

1. **Zotero CORS 可行**：写入接口 POST 预检和 `/keys/current` GET 预检均通过，所需请求头允许，限流头可被浏览器读取。不需要因 CORS 改走 Worker。没有提供 Key、没有执行实际授权写入；真实功能与 iPhone 验证留待后续里程碑。
2. **Crossref 返回 CORS 头**：实测 GET 返回 `Access-Control-Allow-Origin: *`，只记录，不改变前端架构。
3. **数据源身份与地址已逐项尝试**：8 刊 print ISSN 已确认，7 个候选 online ISSN 可用于 Crossref；JFE 候选 online ISSN 的两个端点均 404。NBER/FEDS 前缀验证通过。7 个期刊 RSS、4 个工作论文 RSS 可用；AER 官方 eTOC RSS 未确认，BFI 候选不是工作论文 feed。
4. **摘要统计已完成**：见下表。JPE/JFE 两种渠道均缺摘要；ECTA 在采样窗口没有 Crossref 条目；ECTA/JF RSS 摘要在 `content:encoded` 而非 `description`。按 DOI 匹配检查，本批样本的 RSS 没有补回任何 Crossref 缺失摘要。
5. **Zotero 模板已录制**：`journalArticle`、`report` 都返回 HTTP 200，`itemType` 正确，可作为 M3 字段校验基准。
6. **骨架验收通过**：Python 可编辑安装、pytest 空套件、Vitest 空套件、TypeScript 检查和 Vite build 全部通过。

用户已在 PLAN.md §1.4 的 D1–D8 接受限制：ECTA 以 RSS 为主、Crossref 为辅；BFI 状态设为 disabled；M2 支持按配置选用 description/content:encoded，并另行验证 JPE/JFE 元数据补全 API。D6 允许保存 ECB 开放获取 PDF 地址供用户点击，但所有程序不得请求该地址。M0 在这些决策下完成。

## 1. Zotero 预检与模板

预检使用以下命令（只发送 OPTIONS，不进行 POST）：

```bash
curl -i -X OPTIONS 'https://api.zotero.org/users/0/items' \
  -H 'Origin: https://example.github.io' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: zotero-api-key,zotero-api-version,zotero-write-token,content-type'

curl -i -X OPTIONS 'https://api.zotero.org/keys/current' \
  -H 'Origin: https://example.github.io' \
  -H 'Access-Control-Request-Method: GET' \
  -H 'Access-Control-Request-Headers: zotero-api-key,zotero-api-version'
```

两次最终 HTTP 响应都是 200（代理的 `200 Connection established` 不是服务端响应）。共同结果：

| 响应头 | 实测值/意义 |
|---|---|
| `Access-Control-Allow-Origin` | `*`，允许指定 Origin |
| `Access-Control-Allow-Methods` | `HEAD, GET, POST, PUT, PATCH, DELETE` |
| `Access-Control-Allow-Headers` | 包含 `Content-Type`、`Zotero-API-Key`、`Zotero-API-Version`、`Zotero-Write-Token` |
| `Access-Control-Expose-Headers` | 包含 `Backoff`、`Retry-After`，可实现浏览器端退避 |
| `Access-Control-Max-Age` | `86400` |

这证明 M0 要求的预检条件成立，不证明 Key 权限、库 ID、写入结果或 Safari 实机功能已经验证。前端后续应使用 Key 头进行授权，不需要跨域 cookie（`credentials: include` 与通配 Origin 不兼容）。

原始预检响应：[items](../aggregator/tests/fixtures/zotero-options-items.txt)、[keys](../aggregator/tests/fixtures/zotero-options-keys.txt)。

公开模板分别取自 [journalArticle 模板 API](https://api.zotero.org/items/new?itemType=journalArticle) 和 [report 模板 API](https://api.zotero.org/items/new?itemType=report)，录制在 [journalArticle fixture](../aggregator/tests/fixtures/zotero-journalArticle.json)、[report fixture](../aggregator/tests/fixtures/zotero-report.json)。GET 与 OPTIONS 都没有 Key，也没有写入请求。

## 2. Crossref 参数、身份与摘要覆盖率

每刊对 print/online 两个候选 ISSN 各取一页，最多两页，不翻页。期刊采样参数为：

```text
GET https://api.crossref.org/journals/{ISSN}/works
filter=from-pub-date:2026-06-15,type:journal-article
sort=published&order=desc&rows=25
mailto=papercart@example.invalid
select=DOI,title,type,ISSN,container-title,abstract,published,prefix,publisher,author
```

2026-06-15 是本次验证日期向前 120 天。没有设置终止日期，所以按接口返回记录统计，可能包含已经登记的未来刊期；不是过去 120 天全部论文的普查。保留前 25 条（不足则全部），统计非空 `abstract`；统计原始 `journal-article`，尚未做 M1 非论文过滤。两种 ISSN 返回的相同 DOI 不重复计入主表，以 print ISSN 样本为准。

实测 HTTP 200 的 Crossref GET 响应均包含 `Access-Control-Allow-Origin: *`、`Access-Control-Expose-Headers: Link`；前端仍不直连 Crossref。

| 期刊 | print / online 候选 ISSN | 身份与接口结论 | Crossref 摘要/返回条目 | 原始样本覆盖率 |
|---|---|---|---:|---:|
| AER | 0002-8282 / 1944-7981 | 两者 200，名称和 ISSN 匹配 | 23/25 | 92.0% |
| QJE | 0033-5533 / 1531-4650 | 两者 200，名称和 ISSN 匹配 | 18/19 | 94.7% |
| JPE | 0022-3808 / 1537-534X | 两者 200，名称和 ISSN 匹配 | 0/25 | 0.0% |
| ECTA | 0012-9682 / 1468-0262 | works 两者 200 但零条；单独 journals 元数据两者均确认 Econometrica 及两个 ISSN | 0/0 | **无法计算** |
| RES | 0034-6527 / 1467-937X | 两者 200，名称和 ISSN 匹配 | 25/25 | 100.0% |
| JF | 0022-1082 / 1540-6261 | 两者 200，名称和 ISSN 匹配 | 22/25 | 88.0% |
| JFE | 0304-405X / 1879-2773 | print 200；online works 和 journals 均 404 | 0/25 | 0.0% |
| RFS | 0893-9454 / 1465-7368 | 两者 200，名称和 ISSN 匹配 | 25/25 | 100.0% |

AER 两条缺摘要的是 Front Matter；QJE 一条是 Correction；JF 三条是 Announcements、Issue Information、American Finance Association。排除这些已识别非论文后，AER 23/23、QJE 18/18、JF 22/22 都有摘要。这只是本批样本观察，不代表未来完整覆盖。

ECTA 的 zero-result 不等于没有发表论文，更不能把覆盖率写成 0%；RSS 包含 2026 年论文。M0 当时未能解释原因；M1 的对照验证已查明年份日期的精度问题，见 §7，不能推断出版社不再登记 DOI。JFE 的 404 只说明该候选 ISSN 当前不能用作 Crossref journal endpoint，不证明 ISSN 本身无效。

逐请求状态、响应头、期刊名称和 ISSN 集合见 [spike-crossref.json](../aggregator/tests/fixtures/spike-crossref.json)；补充 ECTA/JFE journals 元数据见 [spike-followup.json](../aggregator/tests/fixtures/spike-followup.json)。对应 `crossref-{source}-{ISSN}.json` 均为该页真实响应，使用 API 的 `select` 减少无关字段，并替换邮箱。

## 3. 期刊 RSS 与摘要字段

| 期刊 | 实测 URL | RSS 结论 | RSS 真正摘要/全部条目 |
|---|---|---|---:|
| AER | `https://www.aeaweb.org/journals/aer/rss`（猜测候选，非官网发现） | 404；[官方期刊页](https://www.aeaweb.org/journals/aer) 未确认 eTOC 链接；没有把 Research Highlights 当作 eTOC | 无样本 |
| QJE | `https://academic.oup.com/rss/site_5504/3365.xml` | 200，有效 current-issue RSS，description 有摘要 | 15/15（100%） |
| JPE | `https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=jpe` | 200，有效 eTOC；description 和 content 都只有刊名、卷期页码 | 0/19（0%） |
| ECTA | `https://onlinelibrary.wiley.com/feed/14680262/most-recent` | 200，有效 eTOC；摘要位于 `content:encoded`；description 无摘要 | 12/14（85.7%），另两条为 front/back matter |
| RES | `https://academic.oup.com/rss/site_5508/3369.xml` | 200，有效 current-issue RSS，description 有摘要 | 18/18（100%） |
| JF | `https://onlinelibrary.wiley.com/feed/15406261/most-recent` | 200，有效 eTOC；摘要位于 `content:encoded`；description 无摘要 | 33/37（89.2%），另四条为公告、人物纪念等非论文 |
| JFE | `https://rss.sciencedirect.com/publication/science/0304405X` | 200，有效 RSS；只有出版日期、来源、作者，未提供摘要，也未提供可直接用的 DOI 字段 | 0/32（0%） |
| RFS | `https://academic.oup.com/rss/site_5511/3372.xml` | 200，有效 current-issue RSS，description 有摘要 | 8/8（100%） |

RSS 摘要数来自离线审查响应内容，不把“非空 description”当作“摘要”。`spike-rss.json` 的 `summaries` 只是非空 description 数；不能直接用于摘要覆盖率。ECTA/JF 的 `content:encoded` 是摘要元数据，不是论文全文。没有跟进 RSS 中的链接获取论文内容。

QJE/RES/RFS 地址均可在 [QJE issue 页](https://academic.oup.com/qje/issue)、[RES issue 页](https://academic.oup.com/restud/issue)、[RFS issue 页](https://academic.oup.com/rfs/issue) 的 RSS Feeds 区域确认，再直接取 RSS 验证内容。最初测试 RFS 的旧式 `/rfs/rss/recent.xml` 返回 404，随后改测官网链接成功；配置中只放成功的地址。

以 DOI 检查同批 print ISSN 样本和 RSS 的交集：QJE 15、JPE 17、JF 25；本次没有实际补回缺失摘要。ECTA 的 Crossref 样本为空；RES/RFS 的 current-issue 条目与 Crossref 最新 25 条时间范围不同；JFE 无直接 DOI 字段。单页 RSS 和截断 Crossref 样本不能保证相同时间范围。

证据：[spike-rss.json](../aggregator/tests/fixtures/spike-rss.json)、RFS 正确地址记录 [spike-followup.json](../aggregator/tests/fixtures/spike-followup.json)、对应 `rss-*.xml`。

## 4. 工作论文源

| 源 | 方式与实测地址 | 结论 |
|---|---|---|
| NBER | Crossref `/prefixes/10.3386/works` | 200，25 条，publisher 为 NBER，样本 DOI 都是 `10.3386/w数字`；前缀不等同于工作论文筛选，后续需按后缀限制 |
| FEDS | Crossref `/prefixes/10.17016/works` | 200，25 条，但仅 10 条 DOI 属于 `10.17016/feds.`；混入 IFDP、FEDS Notes 等，必须按系列限制 |
| NBER RSS | `https://back.nber.org/rss/new.xml` | 200，有效 NBER Working Papers feed，22 条，description 有摘要 |
| FEDS RSS | `https://www.federalreserve.gov/feeds/feds.xml` | 200，有效 FEDS Working Papers feed，15 条，description 有作者及摘要 |
| ECB WP RSS | `https://www.ecb.europa.eu/rss/wppub.html` | 200，有效 RSS，15 条，description 有摘要；条目 link 直接指向 PDF，**仅记录字符串，没有请求 PDF** |
| BIS WP RSS | `https://www.bis.org/doclist/wppubls.rss` | 200，有效 BIS working papers feed，25 条，description 有摘要 |
| BFI WP 候选 | `https://bfi.uchicago.edu/feed/?post_type=working-paper` | HTTP 200、XML 可解析，7 条，但包含 Protected、新闻、职位，样本含 2024 年旧新闻；不是合格工作论文源，**验证失败** |

NBER/FEDS 第一轮 prefix 采样使用了未经验证的 `select` 字段集，服务器返回 400。第二轮去掉 `select` 后两者都成功；没有把 400 误判为前缀不存在。前缀每个最多两次单页请求。重现脚本已改为成功的参数。第一轮状态在 `spike-crossref.json`，最终有效证据在 `spike-followup.json`、`crossref-nber.json`、`crossref-feds.json`。

FEDS RSS 是从 [官方 FEDS 列表页](https://www.federalreserve.gov/econres/feds/index.htm) 链接发现，ECB 从 [官方 RSS 索引](https://www.ecb.europa.eu/home/html/rss.en.html) 发现；BIS 在 [官方 working-paper 页面](https://www.bis.org/publications/working-paper) 对应系列另行验证，避免把综合研究 RSS 混入。BFI [官方工作论文页](https://bfi.uchicago.edu/working-papers/) 只发现通用 `/feed/` 和评论 feed；增加候选查询参数后实测内容仍不符。不能仅凭可解析 XML 就标记为通过，也不能据此断言 BFI 永远没有官方 RSS。

`sources.yaml` 保留全部 13 个目标源。通过的具体端点有 `verified: '2026-10-13'`；失败候选的 `verified` 为 null，另有 `checked`、`reason`、`candidate_url`。AER 的 Crossref 通过，不因其 RSS 失败关闭整源；ECTA 身份和 RSS 通过但 Crossref 窗口空，标记 limited；BFI 按 D5 整源 disabled，保留失败证据，未启用候选地址。

## 5. 骨架、复现与验证

已有根目录 README、gitignore；aggregator 的 pyproject、src 包布局、约定模块占位、pytest 配置及 fixture 目录；web 的 Vite/Preact/TS/Vitest 配置、最小页面、约定目录占位和 npm lockfile。未实现 M1–M6 的业务功能。

```bash
aggregator/.venv/bin/python -m pip install -e './aggregator[test]'
aggregator/.venv/bin/python -m pytest aggregator
cd web
npm test
npm run build
```

M0 实测：Python 3.10 可编辑安装成功；pytest 收集 0 项、退出 0；Vitest 4 收集 0 项、退出 0；`tsc --noEmit` 和 Vite 7 build 成功。M0 空测试通过不是业务正确性证明。当时 pytest 只转换 NO_TESTS_COLLECTED，不掩盖测试失败；M1 已添加业务测试并移除此空套件特例。

本机 venv 初次创建因缺 `ensurepip` 失败，使用系统已有的 pip `--python aggregator/.venv install pip` 在虚拟环境内修复，无需 sudo。构建使用 setuptools，属于 pyproject 的构建工具；应用直接依赖全部来自白名单。Vitest 初始 3.x 安装的依赖审计有漏洞，升级同一白名单依赖到 4.x 后 npm install 的审计报告为 0 vulnerabilities，测试和构建仍通过。

M0 网络脚本位于 `aggregator/scripts/spike.py`，运行需显式 `LIVE_TEST=1`；默认测试不运行它。请求间隔至少 1 秒，限制页数，不请求 PDF，只有 Zotero OPTIONS 和公开模板 GET；预检与模板请求遵守限流头。`CROSSREF_MAILTO` 缺失时输出占位警告，未索要真实邮箱。

fixtures 只录制元数据。邮箱替换为 `papercart@example.invalid`；HTTP 头仅保留 CORS、日期、类型及限流头。BFI 失败候选删去了新闻全文的 `content:encoded`，只保留用于判断类别的元数据；模板和其他 feed 保留收到的元数据结构。npm lockfile 的 glob 可选 `deprecated` 说明含维护者邮箱，已移除该说明字段，版本、resolved、integrity 均未更改。仓库文件没有个人邮箱、API Key、cookie 或真实 Zotero 库数据。

## 6. 决策落实与后续工作

- D1/D3/D5：M0 完成；配置中 ECTA `primary: rss`，BFI `status: disabled`。
- D2/D4：摘要缺失可以进入 MVP；RSS 字段选择和补全 API 验证属于 M2，本次未实现。
- D3/D7：M1 查清 ECTA 窗口为空原因，并落实 NBER/FEDS 的 DOI 系列限制。
- D6：ECB 的开放获取 PDF URL 可以保存、展示供用户点击，程序不会请求 PDF 或全文 URL；不再要求另行批准该链接。
- D8：真实 mailto 仅从环境读取用于 Crossref 请求；文件、fixture 和日志使用占位符，不记录真实值。
- GitHub 仓库、Zotero Key 和集合留待对应后续里程碑；CORS 不触发 Worker 决策。

## 7. M1：ECTA 空窗口原因（D3）

验证日期仍为 2026-10-13（Asia/Singapore），仅请求 api.crossref.org 的元数据，不请求出版商页面、DOI 跳转页、PDF 或全文。

| 对照 | 参数/响应 | 结论 |
|---|---|---|
| 移除类型过滤 | `/journals/0012-9682/works?filter=from-pub-date:2026-06-15` 返回 200、0 条 | 不是 `type:journal-article` 排除了当期数据 |
| 查询 RSS 中的当期 DOI | `/works/10.3982%2FECTA23242` 返回 `type: journal-article`、ISSN `0012-9682`、`published`/`published-online`/`issued` 均为 `[[2026]]`，没有月日 | 身份与类型正确；日期只有年份 |
| 同一 DOI 加年初条件 | `/works`，`filter=doi:10.3982/ecta23242,from-pub-date:2026-01-01,type:journal-article`，返回 1 条 | 记录存在且满足 journal-article 条件 |
| 同一 DOI 加 M0 窗口条件 | 仅把上述日期换为 `2026-06-15`，返回 0 条 | 日期条件直接造成排除 |
| 扩大期刊窗口到年初 | `/journals/0012-9682/works`，`filter=from-pub-date:2026-01-01,type:journal-article`，共 76 条，最新 25 条的 published 全部为 `[[2026]]` | 不是单个 DOI 的偶发现象，样本普遍缺月日 |

RSS 将该论文列在 2026 年 9 月刊；Crossref 元数据没有这层月日精度。[Crossref 官方日期规则](https://github.com/CrossRef/rest-api-doc#notes-on-dates) 说明缺失的月份/日期按最早可能日期参与 API 筛选，因此 `[[2026]]` 被当作 2026-01-01；6 月 15 日窗口会漏掉这些当期论文。上述同一 DOI 的 A/B 对照与规则一致，明确排除类型过滤作为原因。

结论限于本次可见元数据和样本，不推断出版社内部原因，也不声称全部 76 条都经过逐条审查。按 D3 保持 **RSS primary、Crossref auxiliary**；未扩大生产 Crossref 的时间窗口，也未用 Crossref 创建/索引日期冒充论文发表日期。规范化输出保留 `2026`、`2026-09`、`2026-09-30` 的真实精度，后续 M2 用 RSS 的当期日期信息。

真实响应：`ecta-without-type.json`、`ecta-current-doi.json`、`ecta-date-control-year-start.json`、`ecta-date-control-window-start.json`、`ecta-year-sample.json`。请求状态与对照记录：`spike-m1-ecta.json`、`spike-m1-ecta-controls.json`、`spike-m1-ecta-year-sample.json`。全部位于 `aggregator/tests/fixtures/`，邮箱已脱敏。

复现：`LIVE_TEST=1` 运行 `aggregator/scripts/verify_crossref.py` 的 `ecta-metadata`、`ecta-controls`、`ecta-year-sample` 模式；每次每源最多两次单页请求，间隔至少一秒。

## 8. M1：抓取、规范化与系列过滤（D7/D8）

- `sources.py` 加载 schema 1，保留 disabled 源，校验重复 ID、验证日期、ISSN/前缀和系列表达式。ECTA primary RSS 不影响显式辅助 Crossref 请求；BFI disabled 不发送请求。
- `crossref.py` 按 ISSN 或前缀取元数据。实测期刊的 `rows=2&offset=0/2` 两页成功，使用最多两页的小范围 offset 分页；期刊带 journal-article 类型条件，前缀不限定为 report（FEDS 存在 journal-article 类型）。响应不足一页、达到 total-results 或发生错误时停止。每次运行每源最多两页，无自动重试；同一 fetcher 中跨页、跨源请求均至少间隔一秒。
- 单源错误返回安全的错误状态，不中断其他源；第二页失败保留第一页、标记 partial。HTTP 重定向禁止跟随；唯一可请求目标是由合法 ISSN/前缀构造的 Crossref API 路径，响应中的 `URL`、`resource` 和 `link` 从不被请求。
- `normalize.py` 输出 Paper 的 DOI ID、来源、类型、标题、作者、纯文本摘要、日期、URL、工作论文编号和后续 Zotero 映射所需书目字段。清理 JATS/HTML 标签、实体及段落空白；过滤 front/back matter、勘误、编辑报告、公告、致审稿人名单等。缺摘要为 null；M3 的 Zotero 字段暂为空，不提前实现映射。
- 按 D7，NBER 严格匹配 `10.3386/w<数字>`，FEDS 只接受 `10.17016/feds.` 开头；DOI 比较不区分大小写。修复 M0 配置中过度转义的系列正则，并增加测试，防止只看前缀或误收其他系列。
- 真实 M1 抓取器验证：NBER 25 条接收、25 条保留；FEDS 25 条接收、10 条保留、15 条其他系列剔除。证据为 `crossref-m1-nber-page-1.json`、`crossref-m1-feds-page-1.json` 与 `spike-m1-prefixes.json`。
- `privacy.py` 从环境读取联系信息用于请求，保存元数据前递归替换原文及 URL 编码的邮箱；httpx INFO 日志也过滤请求邮箱，错误不包含 URL 或底层异常详情。单元测试使用占位联系信息，不接触开发者的真实邮箱。
- M0 诊断脚本一并加强只读元数据 URL 白名单，拒绝 PDF/全文请求及跳转，BFI 停用后不再请求其候选 feed。没有实现 RSS 抓取器、去重、摘要回填或 feed.json 构建；这些仍属于 M2。

单元测试使用录制的真实响应与 respx：覆盖所有 8 刊、NBER/FEDS 系列筛选、日期对照、分页上限/间隔、短页/空页、失败隔离、非法响应、PDF/全文跳转拒绝、JATS 清理、非论文过滤及邮箱脱敏。默认通过 socket guard 禁止真实网络连接；网络脚本只有 `LIVE_TEST=1` 才运行。没有任何 Zotero 写入。

最终验证：`python -m pytest aggregator -q` **82 passed**（Python 3.10）；源码与诊断脚本编译检查通过。真实抓取器的 AER 分页复验为两页、4 条接收/保留，记录在 `crossref-m1-aer-page-1.json`、`crossref-m1-aer-page-2.json`、`spike-m1-pagination.json`。仓库文本与全部 JSON fixture 检查通过，真实 CROSSREF_MAILTO 及其 URL 编码形式均不存在于文件中。

本次环境的原仓库 `.git` 为只读挂载，正常 git add/commit 因不能创建 index.lock 而失败。为保持里程碑提交顺序，在 `/tmp/papercart-milestones` 的独立 Git 仓库生成 M0、M1 提交，代码保存在原工作区，另交付 bundle 供可写 Git 环境导入；没有替换原仓库 `.git` 或修改其分支。


## 9. M2：补全 API 当前政策与实测（D2）

验证日期：2026-10-13（Asia/Singapore）；只请求只读元数据 API，未请求论文页面、全文、PDF、snippets、数据集或内容下载端点。

| API | 当前官方政策与本机响应 | M2 处理 |
|---|---|---|
| OpenAlex | [鉴权说明](https://help.openalex.org/api/authentication/)（2026-08-19）允许无 Key 基础查询；[费用实例](https://help.openalex.org/access/example-costs/)（2026-10-09）说明匿名 $0.10/天、免费 Key $1/天，list/filter 每次 $0.0001、singleton 免费，速率上限 100 请求/秒。实测批量 DOI filter 返回 429，响应明确说匿名额度由网络 IP 共享且剩余为 0，Retry-After 为约 22129 秒。 | 不接入生产，不申请账号、Key 或付费；没有重试循环。未取得匹配结果，摘要覆盖率无法计算，不能宣称 0%。 |
| Semantic Scholar | [官方产品页](https://webflow.semanticscholar.org/product/api)说明大部分端点可匿名访问，匿名共享 1000 RPS 池，高峰还会额外限流；Key 的初始速率为 1 RPS，不是给每个匿名用户承诺的速率。按[官方 API 文档](https://api.semanticscholar.org/api-docs/)批量论文查询最多 500 ID，POST /graph/v1/paper/batch 是只读查询。 | 实测匿名 batch 200、有少量摘要收益，接入为可关闭的补充；保守请求间隔至少 1 秒，每源最多两批，缓存并在 429/503 时停止该 host，保存冷却期。 |

没有使用旧版的 OpenAlex “每天 100000 次/必须 Key”或第三方的 Semantic Scholar “100 次/5 分钟”等数字替代当前官方政策。政策查询也没有抓出版商页面；网页来源只用于核实 API 政策。

D2 使用 M0 已录制 Crossref 样本，排除 front matter 后取所有缺摘要条目：

| 期刊 | 样本 DOI 数 | OpenAlex | Semantic Scholar 匹配条数 | S2 有摘要 | 占待补回样本 |
|---|---:|---|---:|---:|---:|
| JPE | 24 | HTTP 429、未获结果 | 15 | 4 | 16.7% |
| JFE | 25 | HTTP 429、未获结果 | 18 | 2 | 8.0% |
| 合计 | 49 | 无法计算覆盖率 | 33 | 6 | 12.2% |

OpenAlex 的首次两刊探测均遇到预算耗尽；此后不再请求该服务。S2 的收益小但为真实 DOI 匹配的 6 条，两次批量请求即可取得，故接入为补充而不作为必要成功条件。每条返回的 externalIds.DOI 必须与请求 DOI 严格一致，不按位置、标题或作者猜测。没有 API Key、邮箱或全文请求。

证据：`aggregator/tests/fixtures/m2/d2-openalex-{jpe,jfe}.json`、`d2-probe-summary.json`、`d2-semantic-scholar-{jpe,jfe}.json`、`d2-semantic-summary.json`。官方政策链接与本机配额错误都明确写出匿名预算共享 IP 的实际限制。要对 OpenAlex 测得覆盖率，需等预算重置，或用户另行批准使用其自己的 Key；本次没有扩大鉴权需求。

## 10. M2 首轮实现（E1–E5 之前的历史记录）

- D4：按已验证配置选 description/content:encoded；ECTA/JF 从 content 取得真实摘要，JPE/JFE 不把书目信息当摘要。RSS 解析只处理已取到的字节，不将 item link 交给 HTTP client 或 feedparser 抓取。
- D6：ECB 链接保留为公开 PDF URL，并规范化重复斜杠、跟踪参数等；所有请求只面向 RSS/元数据 API。测试验证即使客户端默认允许跳转，也不会请求 PDF/全文 Location。
- 去重以 DOI 为主、规范化 URL/元数据别名为辅，保留重要 query 参数、删除跟踪参数。不同 DOI 不因共同 URL 合并；不按标题模糊匹配。摘要回填只发生于相同 DOI。Crossref 可补齐 RSS 中没有的作者和书目字段；同年份可补日期精度，不伪造发表日期。
- ECTA 优先 RSS，其他源优先 Crossref；NBER 从官方 /papers/w<number> 识别已验证系列 DOI，FEDS 使用 Crossref 的真实 DOI 与原始 landing-page 元数据进行 URL 去重。BFI 始终停用。
- 日期范围为 build 的 UTC 日期向前 120 天。完整日必须落入窗口，年月/年份按其可能日期区间是否与窗口相交保留；输出继续保留原精度。无日期且无法在相同条目合并中补齐的记录被排除，计入 excluded_date_count；未将“抓到的时间”假装成发表日期。
- 重用上一版 feed 中仍在窗口内的记录，避免单源暂时失败或 current-issue RSS 换期时清空历史；当前无 Key 缓存只含 DOI 摘要、缺失标记、到期时间及 S2 冷却期。
- feed.schema.json 定义 schema 1；标准库校验器实现其中实际使用的 JSON Schema 关键词，并检查 source 引用、ID 唯一性、DOI/URL 身份及真实日期。没有引入 jsonschema 依赖。zotero 为 `{}`，M3 尚未开始，当前输出不能当作完整 Zotero 写入负载。
- 每个 Crossref fetch 最多两页（100 条/页），每个 RSS 只取一页、没有跟随 pagination/item/全文链接。完整 build 全部服务共享至少 1 秒的请求间隔。429/503 熔断 host；S2 冷却和 Retry-After 跨 build 保存。白名单依赖不变，Python 3.10 兼容。

## 11. M2 首轮完整真实 build（E1–E5 之前）

命令：

```bash
LIVE_TEST=1 aggregator/.venv/bin/python -m papercart.build \
  --out web/public/data/feed.json \
  --record-fixtures aggregator/tests/fixtures/m2/build
```

真实 build 完成时间：2026-10-12T18:04:08.105723Z（UTC）；保留窗口起点 2026-06-14，窗口终点 2026-10-12。共 24 次元数据 HTTP 请求；输出 **589 条**，schema 校验通过。录制 manifest 列出每次请求的安全地址、非敏感参数、状态及 fixture，删去 mailto；Crossref fixture 是保留真实消费字段的投影，删除未使用的参考文献/许可/资助字段。

| 源 | 最终条数 | 有摘要 | 覆盖率 | 日期排除条数 | 失败原因/状态 |
|---|---:|---:|---:|---:|---|
| AER | 45 | 42 | 93.3% | 0 | 无请求失败 |
| QJE | 18 | 18 | 100.0% | 0 | 无请求失败 |
| JPE | 61 | 7 | 11.5% | 0 | 无请求失败 |
| ECTA | 12 | 12 | 100.0% | 0 | 无请求失败 |
| RES | 54 | 54 | 100.0% | 18 | 无请求失败 |
| JF | 34 | 33 | 97.1% | 0 | 无请求失败 |
| JFE | 62 | 0 | 0.0% | 36 | Semantic Scholar HTTP 429 |
| RFS | 37 | 37 | 100.0% | 7 | 无请求失败 |
| NBER | 200 | 0 | 0.0% | 22 | 无请求失败 |
| FEDS | 30 | 30 | 100.0% | 0 | 无请求失败 |
| ECB | 15 | 15 | 100.0% | 0 | 无请求失败 |
| BIS | 21 | 21 | 100.0% | 4 | 无请求失败 |
| BFI | 0 | 0 | — | 0 | 停用 |

上述百分比是本轮输出记录的覆盖率，不是期刊所有论文的普查。跨源/渠道去重及 120 天过滤后才计数。

真实 build 的 S2：JPE 请求 61 个 DOI、匹配 35、补回 7 条；JFE 请求 48 个缺摘要 DOI 时返回 429，未取得该批次摘要，保留原书目并标记 partial。限流响应没有 Retry-After，使用至少 60 秒冷却，不自动重试。与 D2 小样本的 2/25 不矛盾：该样本曾成功，本轮完整 build 因共享池节流失败；不把失败当作无摘要的证据。

NBER：Crossref 两页上限接收并保留 200 条（端点更多结果未取），本轮没有 abstract；当前 RSS 22 条无日期，DOI 均为更晚的新工作论文，与这两页 Crossref 无交集，无法确认它们属于 120 天窗口，因此均作为无日期排除。没有从 NBER 网页补日期，也没有把运行日期赋给论文。该限制需要后续来源元数据改善；当前 source 后端正常不等于数据完整。

AER 没有已验证 eTOC，RSS 后端 not_applicable，不重复请求已失败候选；ECTA Crossref 空窗口已知，RSS 12 条均有摘要；JFE RSS 没有 DOI，无法按标题与 Crossref 猜测合并/回填；RES/RFS current-issue RSS 有早于窗口的论文，保留 Crossref 时间窗记录而排除过期 RSS。BFI 为用户决定的 disabled，非运行故障。

## 12. M2 首轮验证及已解决的审查事项

- 离线 `python -m pytest aggregator -q`：**128 passed**，使用真实 fixture；默认 socket guard 阻止网络。完整 build 可以通过 24 次真实响应的 manifest 离线重放，源计数、S2 成功/失败、PDF 链接留存与最终 feed 校验可复现。
- 覆盖 description/content、DOI/URL 合并、跨别名去重、禁止不同 DOI/标题回填、日期精度/时间窗、旧 feed 保留、源失败隔离、API 缓存/429 冷却、schema 错误和原子写入失败保护。没有任何 Zotero 写入。
- **首轮新发现，现已由 E1 决定**：ECB “working papers” RSS 含 `ecb.dp32`，其标题 Artificial intelligence and financial markets；[ECB 官方页面](https://www.ecb.europa.eu/home/html/index.fi.html)明确列为 Discussion Paper Series No.32。其余 14 条是 wp 编号。首轮原始 build 包含该条；协调方随后决定仅保留 Working Paper Series，最终版本已过滤其他系列，见 §13。
- 不提交 git；提交由协调方审查后执行。没有开始 M3。


## 13. M2 审查后收尾：E1–E5 与统一 state

E1–E5 均已由协调方明确授权并记录在 PLAN.md §1.5；没有待确认的系列范围，也没有提交 git 或开始 M3。

- **E1**：ECB 只接受 PDF 链接中的 ecb.wp<数字>，Discussion/其他系列被过滤（真实 RSS 15 条取 14 条 WP）。只是检查元数据字符串，程序不请求 PDF；旧 feed/state 中混入的 dp32 也不会再输出。
- **E2**：--state 默认 `aggregator/state/state.json`，目录已 git 忽略。state 为每个身份记录 first_seen；feed 新增 first_seen 与 date_precision（published/first_seen）。无日期条目 published 仍为 null，使用 first_seen 参与排序与 120 天保留。已过期无日期身份仍保留首次观测标记，不能因再次出现在 RSS 中而刷新寿命。后来补齐真实发表日期时切换到 published，first_seen 不变。
- **E2/NBER**：从已验证的 /papers/w<n> 构造 10.3386/w<n>，与 Crossref 按 DOI 合并；RSS 的摘要优先，同一条目的 Crossref 作者/日期/书目仍可补齐。本轮 22 条新 RSS DOI 与 Crossref 两页无交集，现在全部以 first_seen 保留，不再因无日期丢弃。
- **E3**：state.papers 保存元数据和已获取摘要，RSS/Crossref/S2 摘要均可跨运行复用；state.semantic_scholar 保存 DOI 查询缓存和 blocked_until，已经没有第二个正在使用的缓存文件。成功摘要持久保留，缺失结果缓存一天；首次默认状态构建导入旧缓存，保存成功后删除旧 abstracts.json。state 损坏时失败，不默默重置 first_seen。
- **E4**：S2 仅补 NBER/JPE，NBER 优先，最新日期优先，同月 NBER DOI 以数字工作论文号优先。默认全运行最多 2 个批量请求（--abstract-max-requests 可配置），每批至多 500 DOI、每源至多两批。正/负缓存均不重复查询；429/503 保存冷却，Retry-After 从响应到达时起计算，避免慢 build 的起始时间使冷却提前过期。
- **E5**：JFE 暂接受缺摘要，不再消耗 S2 配额。OpenAlex 不接入；后续稳定实测/接入**需要申请免费 API key**以避开已耗尽的共享 IP 预算，是否申请由用户以后决定。此为本项目的接入前置条件，不改写 §9 中官方允许受限匿名查询的事实；本次没有账号、密钥或费用需求。

旧版 feed 的已知观测时间可以由其 generated_at 迁移为 first_seen；不把该时间写成 published。state 持久化与新字段不会触发 Zotero 映射，zotero 仍为 {}；CI 中的 state 持久化留待 M5。

## 14. 连续两次完整真实 build 与 state 复用

连续执行（同一默认 state 和 out，分别录制响应）：

```bash
LIVE_TEST=1 aggregator/.venv/bin/python -m papercart.build \
  --out web/public/data/feed.json \
  --record-fixtures aggregator/tests/fixtures/m2/state-run-1
LIVE_TEST=1 aggregator/.venv/bin/python -m papercart.build \
  --out web/public/data/feed.json \
  --record-fixtures aggregator/tests/fixtures/m2/state-run-2
```

第 1 次：2026-10-12T18:24:47.784110Z，23 次元数据 HTTP 请求，其中 1 次 S2 批量查询；第 2 次：2026-10-12T18:26:56.644983Z，22 次元数据 HTTP 请求，**S2 请求 0 次**。两次各 610 条、均通过新 schema。

| 来源 | 第1次条数 | 有摘要 | 覆盖率 | 第2次条数 | 有摘要 | 覆盖率 |
|---|---:|---:|---:|---:|---:|---:|
| AER | 45 | 42 | 93.3% | 45 | 42 | 93.3% |
| QJE | 18 | 18 | 100.0% | 18 | 18 | 100.0% |
| JPE | 61 | 7 | 11.5% | 61 | 7 | 11.5% |
| ECTA | 12 | 12 | 100.0% | 12 | 12 | 100.0% |
| RES | 54 | 54 | 100.0% | 54 | 54 | 100.0% |
| JF | 34 | 33 | 97.1% | 34 | 33 | 97.1% |
| JFE | 62 | 0 | 0.0% | 62 | 0 | 0.0% |
| RFS | 37 | 37 | 100.0% | 37 | 37 | 100.0% |
| NBER | 222 | 42 | 18.9% | 222 | 42 | 18.9% |
| FEDS | 30 | 30 | 100.0% | 30 | 30 | 100.0% |
| ECB | 14 | 14 | 100.0% | 14 | 14 | 100.0% |
| BIS | 21 | 21 | 100.0% | 21 | 21 | 100.0% |
| BFI | 0 | 0 | — | 0 | 0 | — |

**NBER**：200 条 Crossref + 22 条新 RSS，共 222 条。首次 RSS 提供 22 条摘要；S2 请求 200 个仍缺摘要 DOI，匹配 174、补回 20 条，因此最终 42/222（18.9%）。第二次保持 42 条摘要，剩余 180 个缺摘要 DOI 命中负缓存，没有再次请求；22 条无日期 RSS 的首次发现时间保持不变。

JPE 原有 7 条摘要跨运行保留，54 条仍缺摘要的 DOI 命中既有查询缓存，两次都无需再查询。JFE 0/62 是 E5 接受的摘要缺失，不是这两次运行的失败。所有当前可用后端均成功；ECTA Crossref 仍是已知空窗口，AER 没有可用 RSS，BFI 为已决定的 disabled。未请求任何论文 URL 或 PDF。

两次所有 610 个 paper 的 first_seen 映射完全一致；所有已获取摘要也完全一致。report.json 中保存 first_seen/摘要映射的 SHA-256，两次摘要和首次发现哈希相同，第二次 reuse_checks 为 true。manifest.json 证明第二次没有 POST/S2 请求；S2 成功响应、各 RSS 与 Crossref 元数据均已脱敏录制。实际 state 文件被 git 忽略，不作为 fixture 提交。

最终 **143 项离线测试通过**（Python 3.10），覆盖无日期保留/过期不重置、URL 到 DOI 身份升级、真实日期替代 first_seen、RSS 摘要优先、从 state 独立恢复元数据/摘要、S2 正负缓存跨进程复用、最新优先/全局请求预算、响应时刻冷却、E1 系列过滤及 E5 不请求 JFE。原有 schema、限流、源失败、PDF/全文红线测试也通过。源码和脚本编译检查、最终 feed schema 校验及真实邮箱/编码形式文件检查通过。

遗留属于后续里程碑：M3 完整 Zotero 映射；M5 为 state 配置 CI 持久化。NBER Crossref 两页上限和 API 索引/摘要覆盖率限制仍存在，当前覆盖率是这次产出数据的覆盖率，不是所有 NBER 论文的普查。OpenAlex 免费 Key 由用户以后决定，当前 M2 无需新决定。
