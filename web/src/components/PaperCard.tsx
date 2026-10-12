import { useEffect, useRef, useState } from 'preact/hooks';
import type { CartEntry, Paper, Source } from '../types';
interface Props { paper: Paper; source?: Source; read?: boolean; entry?: CartEntry; busy: boolean; add: () => void; markRead?: () => void }
export function PaperCard({ paper, source, read, entry, busy, add, markRead }: Props) {
  const [expanded, setExpanded] = useState(false);
  const ref = useRef<HTMLElement>(null);
  const onRead = useRef(markRead);
  onRead.current = markRead;
  useEffect(() => {
    if (!onRead.current || !ref.current || !('IntersectionObserver' in window)) return;
    let seen = false;
    const observer = new IntersectionObserver(entries => {
      const entry = entries[0];
      if (entry.isIntersecting) seen = true;
      // Only mark cards actually seen and scrolled above the reading area.
      else if (seen && entry.boundingClientRect.bottom <= (entry.rootBounds?.top ?? 0)) {
        onRead.current?.(); observer.disconnect();
      }
    }, { rootMargin: '-68px 0px -90px 0px', threshold: 0 });
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, [paper.id]);
  const authors = paper.authors.map(a => a.name || [a.given, a.family].filter(Boolean).join(' ')).join(' · ') || '作者信息暂缺';
  const label = entry?.status === 'writing' ? '写入中…' : entry?.status === 'added' ? '✓ 已入库' :
    entry?.result?.retry === 'blocked' ? '失败 · 需核对' : entry?.status === 'failed' ? '失败 · 重试' : '＋ 加购';
  const link = /^https?:\/\//i.test(paper.url) ? paper.url : undefined;
  return <article ref={ref} class={`paper ${read ? 'read' : ''}`} onClick={() => setExpanded(v => !v)}>
    <div class="paper-meta"><span class="source-badge">{source?.short ?? paper.source}</span><span>{paper.date_precision === 'first_seen' ? `首次收录 ${paper.first_seen.slice(0, 10)}` : paper.published}<span class="read-label"> · {read ? '已读' : '未读'}</span></span></div>
    <h2><a href={link} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}>{paper.title}<span class="external" aria-label="在新窗口打开"> ↗</span></a></h2>
    <p class="authors" title={authors}>{authors}</p>
    <button class="abstract-toggle" aria-expanded={expanded} onClick={e => { e.stopPropagation(); setExpanded(v => !v); }}>{expanded ? '收起摘要 ↑' : '展开摘要 ↓'}</button>
    {expanded && <p class="abstract">{paper.abstract || '无摘要'}</p>}
    {entry?.status === 'failed' && <p class="error" role="status">{entry.result?.error}</p>}
    <button class={`add ${entry?.status ?? ''}`} disabled={busy || entry?.status === 'added' || entry?.result?.retry === 'blocked'} onClick={e => { e.stopPropagation(); add(); }}>{label}</button>
  </article>;
}
