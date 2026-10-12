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

ECTA 的 zero-result 不等于没有发表论文，更不能把覆盖率写成 0%；RSS 包含 2026 年论文。当前记录无法解释 Crossref 窗口为空的原因，不能推断出版社不再登记 DOI。JFE 的 404 只说明该候选 ISSN 当前不能用作 Crossref journal endpoint，不证明 ISSN 本身无效。

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

实测：Python 3.10 可编辑安装成功；pytest 收集 0 项、退出 0；Vitest 4 收集 0 项、退出 0；`tsc --noEmit` 和 Vite 7 build 成功。M0 空测试通过不是业务正确性证明。pytest 只转换 NO_TESTS_COLLECTED，不掩盖测试失败。

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
