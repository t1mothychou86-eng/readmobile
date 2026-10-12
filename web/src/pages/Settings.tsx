import { useState } from 'preact/hooks';
import { client, store } from '../store';
import type { Feed } from '../types';
export function SettingsPage({ feed, sample, report, cleared }: { feed?: Feed; sample: boolean; report: (m: string) => void; cleared: () => void }) {
  const settings = store.state.settings;
  const writable = store.storageStatus === 'ready';
  const [key, setKey] = useState(settings.apiKey);
  const [tags, setTags] = useState(settings.tags.join('，'));
  const [validating, setValidating] = useState(false);
  const [clearConfirm, setClearConfirm] = useState(false);
  const saveKey = async () => {
    if (!key.trim()) { report('请输入 API Key'); return; }
    setValidating(true);
    store.busy = true;
    try {
      const apiKey = key.trim();
      const userID = await client.validateKey(apiKey);
      const collections = await client.collections(apiKey, userID);
      const previous = store.state.settings;
      const collection = previous.userID === userID && collections.some(c => c.key === previous.collection) ? previous.collection :
        collections.find(c => c.data.name === '00 Inbox')?.key ?? '';
      await store.settings({ ...previous, apiKey, userID, collections, collection });
      report(`已校验个人文库写权限，用户 ${userID}${collections.length === 200 ? '；只显示前 200 个集合' : ''}`);
    } catch (error) { report(error instanceof Error ? error.message : '校验失败'); }
    finally { store.busy = false; setValidating(false); }
  };
  const saveTags = () => void store.settings({ ...store.state.settings, tags: [...new Set(tags.split(/[,，\n]/).map(t => t.trim()).filter(Boolean))] }).then(() => report('默认标签已保存')).catch(() => report('标签保存失败'));
  return <><section class="intro"><span class="eyebrow">为你的阅读习惯而设</span><h1>设置</h1><p>Key、已读和购物车仅保存在此设备。</p></section>
    <section class="panel"><h2>Zotero 连接</h2><label>API Key<input type="password" value={key} autoComplete="off" autoCapitalize="off" spellcheck={false} onInput={e => setKey(e.currentTarget.value)} placeholder="输入有个人文库写权限的 Key" /></label>
      <button class="primary" disabled={!writable || validating || store.busy} onClick={() => void saveKey()}>{validating ? '校验并读取集合中…' : '校验并保存 Key'}</button>
      <p class="hint">{settings.userID ? `已连接用户 ${settings.userID}` : '尚未连接 Zotero'}。请使用专门为 PaperCart 创建的 Key。</p>
      <label>目标集合<select value={settings.collection} disabled={!writable || !settings.userID || store.busy} onChange={e => void store.settings({ ...store.state.settings, collection: e.currentTarget.value }).catch(() => report('集合保存失败'))}><option value="">文库根目录</option>{settings.collections.map(c => <option value={c.key}>{c.data.parentCollection ? '↳ ' : ''}{c.data.name}</option>)}</select></label>
      <label>默认标签<input value={tags} onInput={e => setTags(e.currentTarget.value)} placeholder="例如：待读，金融" /></label><p class="hint">多个标签用逗号分隔，新加购时生效。</p><button disabled={!writable || store.busy} onClick={saveTags}>保存标签</button>
    </section>
    <section class="panel"><h2>信息流状态</h2><p class="hint">{feed ? `生成于 ${new Date(feed.generated_at).toLocaleString('zh-CN')}` : '信息流尚未加载'}{sample && ' · 开发样本'}</p>
      <ul class="source-status">{feed?.sources.map(s => <li><div><strong>{s.short}</strong><span class={`status ${s.status}`}>{{ ok: '正常', partial: '部分可用', disabled: '已停用', error: '不可用', failed: '不可用' }[s.status] ?? '未知状态'} · {s.count} 篇</span></div>{s.errors.length > 0 && <p class="error">{s.errors.join('；')}</p>}</li>)}</ul>
    </section>
    <section class="panel"><h2>本地数据</h2><p class="hint">清除 Key、集合、标签、已读记录和购物车。Zotero 中已写入的文献仍保留；清除后再次加购可能产生重复条目。</p>
      {clearConfirm ? <div class="confirm"><button disabled={!writable || store.busy || validating} class="danger" onClick={() => void store.clear().then(async () => { if ('caches' in window) { const names = await caches.keys(); await Promise.all(names.filter(n => n.startsWith('papercart-feed')).map(n => caches.delete(n))); } cleared(); report('本地数据已清除'); }).catch(() => report('清除失败，请重试'))}>确认清除</button><button onClick={() => setClearConfirm(false)}>取消</button></div> : <button class="danger" disabled={!writable || store.busy || validating} onClick={() => setClearConfirm(true)}>清除本地数据</button>}
    </section><p class="install-tip">在 Safari 的分享菜单选择“添加到主屏幕”，即可像 App 一样使用。</p>
  </>;
}
