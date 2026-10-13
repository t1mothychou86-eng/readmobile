import { useState } from 'preact/hooks';
import { publishers, validAccess } from '../access';
import { store } from '../store';
import type { AccessRecord } from '../types';
function PublisherForm({ publisher, report }: { publisher: typeof publishers[number]; report: (m: string) => void }) {
  const saved = store.state.settings.access?.[publisher.id];
  const [date, setDate] = useState(saved?.pairedOn ?? '');
  const [days, setDays] = useState(saved ? String(saved.days) : '');
  const [saving, setSaving] = useState(false);
  const save = async (record?: AccessRecord) => {
    setSaving(true);
    try { await store.accessRecord(publisher.id, record); if (!record) { setDate(''); setDays(''); } report(record ? '配对日期与有效天数已保存' : '提醒记录已删除'); }
    catch (error) { report(error instanceof Error ? error.message : '保存失败'); }
    finally { setSaving(false); }
  };
  return <section class="panel publisher" id={publisher.id}><h2>{publisher.name}<span class="hint"> · {publisher.journals}</span></h2>
    <p>{publisher.steps}</p><a class="guide-link" href={publisher.url} target="_blank" rel="noopener noreferrer">官方机构访问说明 ↗</a>
    <p class="hint">{publisher.duration}{publisher.durationURL && <> <a class="guide-link" href={publisher.durationURL} target="_blank" rel="noopener noreferrer">有效期来源 ↗</a></>}</p>
    <form onSubmit={e => { e.preventDefault(); void save({ pairedOn: date, days: Number(days) }); }}>
      <label>记录配对日期<input type="date" required value={date} onInput={e => setDate(e.currentTarget.value)} /></label>
      <label>有效天数（自行填写）<input type="number" required min="1" max="36500" step="1" value={days} placeholder="按实际授权期限填写" onInput={e => setDays(e.currentTarget.value)} /></label>
      <div class="confirm"><button disabled={saving || store.storageStatus !== 'ready' || !validAccess({ pairedOn: date, days: Number(days) })} type="submit">保存提醒</button>{saved && <button disabled={saving || store.storageStatus !== 'ready'} type="button" onClick={() => void save()}>删除记录</button>}</div>
    </form>
  </section>;
}
export function AccessPage({ report }: { report: (m: string) => void }) {
  return <><a class="guide-link" href="#settings">← 返回设置</a><section class="intro"><h1>机构访问指南</h1><p>先在校园网内确认订阅，再按出版商指引设置远程访问。</p></section>
    <p class="hint">请在 Safari 或学校的官方页面登录，可用 iCloud 钥匙串填写密码。PaperCart 只在此设备保存日期和有效天数，不接收学校账号或密码。提醒会在到期前 7 天及到期后显示；重新配对后请手动更新日期。</p>
    <nav class="publisher-index" aria-label="出版商">{publishers.map(p => <button onClick={() => document.getElementById(p.id)?.scrollIntoView({ behavior: 'smooth' })}>{p.name}</button>)}</nav>
    {publishers.map(p => <PublisherForm key={p.id} publisher={p} report={report} />)}
  </>;
}
