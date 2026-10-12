# M4 前端：写入 Zotero 的数据约定

M3 的 `paper.zotero` 已是可编辑的 Zotero 元数据对象。前端只需复制它，补上用户选择的 `collections`（collection key 数组）和 `tags`（`{ "tag": "标签名" }` 数组），再把对象放入数组 POST 到 `https://api.zotero.org/users/{userID}/items`。不发送整个 paper，也不发送 `data` 包装层；不修改 feed 中的原对象。空的 collections/tags 用 `[]`。

请求头为 `Content-Type: application/json`、`Zotero-API-Key`、`Zotero-API-Version: 3`、`Zotero-Write-Token`。API Key 来自用户本机设置，不放入样本、日志或仓库。映射及作者的单字段 `name` 格式参照 [Zotero 写入文档](https://www.zotero.org/support/dev/web_api/v3/write_requests)。

```ts
const payload = selected.map(paper => ({
  ...paper.zotero,
  collections: selectedCollectionKeys,
  tags: selectedTags.map(tag => ({ tag })),
}));
// POST 的 JSON body 为 payload 数组；一批最多 50 条。
```

每个新批次用安全随机数生成一个 32 位十六进制 Write-Token；同一批次的 body 和 token 在网络重试时保持不变。队列中保存批次、token 和结果，避免双击或超时后重建 token 导致重复创建。成功请求的 token 在服务端保留 12 小时，再次使用会返回 412；412 不能直接当作成功，也不要自动换 token 重发，应核对已写入的条目或提示用户确认结果。token 不代替本机跨批次的已添加标记。[Write-Token 语义](https://www.zotero.org/support/dev/web_api/v3/write_requests#zotero-write-token)

每次响应都检查 Backoff，包括 200。维护共享的下一次请求允许时间，所有 Zotero 读写排队等待；至少保持 AGENTS.md 要求的一秒间隔。429/503 优先等待 Retry-After（秒数；若为 HTTP 日期则计算剩余时间），没有时指数退避，最多重试三次；等待时间取 Backoff、Retry-After、指数退避和现有冷却中的最大值。暂停倒计时可在界面显示，等待期间不另发请求。[限流与 Backoff](https://www.zotero.org/support/dev/web_api/v3/basics#rate_limiting)

HTTP 200 仍需逐条解析 `successful`、`unchanged`、`failed`，其键是上传数组中的下标。只把已确认成功或 unchanged 的条目标记为“已添加”；保留 failed 的原因。对明确失败条目的下一次提交建立新批次和 token，排除已经成功的条目。400/403 等不可重试错误提示修正内容或凭据；不要无限重试。

期刊是 `journalArticle`，工作论文是 `report`。摘要仅存在时写 `abstractNote`；无 DOI、作者或日期时保持缺失或空作者数组，不推断。`date` 保留年/月/日精度；`first_seen` 是排序时间，不能补到 date。ECB 的开放 PDF 地址只作为 `url` 保存/展示，前端不得 fetch、预取或下载它，不创建 attachment。

离线开发样本为 [feed.sample.json](../web/src/fixtures/feed.sample.json)：12 个启用来源各 3 条，共 36 条；BFI 有停用状态但无论文。包含无摘要、无作者、无 DOI、无发表日期和开放 PDF 链接的实际 fixture 条目。`sources.count/abstract_count` 为样本统计，`backends` 保留原录制构建的抓取统计。重现命令：

```bash
aggregator/.venv/bin/python aggregator/scripts/make_feed_sample.py
```

脚本只重放已有 M2 元数据 fixture，不访问网络，不改持久化 state 或 public feed。M3 未调用任何 Zotero 写入接口；实际写入客户端和界面留给 M4。
