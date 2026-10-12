import { useMemo, useState } from 'preact/hooks';
import { PaperCard } from '../components/PaperCard';
import { store } from '../store';
import type { Feed as FeedData, Paper } from '../types';
export function FeedPage({ feed, add, report }: { feed: FeedData; add: (paper: Paper) => void; report: (message: string) => void }) {
  const { group, source } = store.state.filters;
  // Freeze read order for this visit so observer updates never move the card being read.
  const [readAtEntry] = useState(() => ({ ...store.state.read }));
  const papers = useMemo(() => feed.papers.filter(p => (!source || p.source === source) &&
    (!group || feed.sources.find(s => s.id === p.source)?.group === group)).sort((a, b) =>
    Number(!!readAtEntry[a.id]) - Number(!!readAtEntry[b.id]) ||
    (b.published ?? b.first_seen).localeCompare(a.published ?? a.first_seen)), [feed, group, source, readAtEntry]);
  const change = (g: string, s: string) => { void store.filters(g, s).catch(() => report('筛选保存失败')); };
  return <>
    <section class="intro"><span class="eyebrow">每天一点，读得更远</span><h1>文献信息流</h1><p>{papers.length} 篇文献 · {papers.filter(p => !store.state.read[p.id]).length} 篇未读</p></section>
    <section class="filters" aria-label="筛选文献">
      <div class="chips">{[['', '全部'], ['econ-top5', 'Top5'], ['finance', '金融'], ['working-paper', '工作论文']].map(([value, label]) =>
        <button aria-pressed={group === value} onClick={() => change(value, '')}>{label}</button>)}</div>
      <div class="filter-row"><label>来源<select value={source} onChange={e => change(group, e.currentTarget.value)}><option value="">全部来源</option>{feed.sources.filter(s => !group || s.group === group).map(s => <option value={s.id}>{s.short} · {s.name}</option>)}</select></label>
        <button class="text-button" disabled={store.storageStatus !== 'ready'} onClick={() => void store.markRead(feed.papers.map(p => p.id)).catch(() => report('已读状态保存失败'))}>全部标为已读</button></div>
    </section>
    <div class="paper-list">{papers.map(p => <PaperCard key={p.id} paper={p} source={feed.sources.find(s => s.id === p.source)} read={!!store.state.read[p.id]} entry={store.state.cart[p.id]} busy={store.busy || store.storageStatus !== 'ready'} add={() => add(p)} markRead={store.storageStatus === 'ready' ? () => void store.markRead([p.id]).catch(() => report('已读状态保存失败')) : undefined} />)}</div>
    {!papers.length && <div class="empty">这个筛选下暂无文献，试试其他来源。</div>}
  </>;
}
