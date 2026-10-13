import { PaperCard } from '../components/PaperCard';
import { store } from '../store';
import type { Feed, Paper } from '../types';
export function CartPage({ feed, add }: { feed?: Feed; add: (paper: Paper) => void }) {
  const entries = Object.values(store.state.cart);
  return <><section class="intro"><span class="eyebrow">把兴趣留给下一次精读</span><h1>文献购物车</h1><p>成功入库后，可在电脑端 Zotero 同步查看。</p></section>
    {!entries.length && <div class="empty">购物车还是空的。去信息流加购一篇感兴趣的文献。</div>}
    {(['failed', 'writing', 'added'] as const).map(status => {
      const group = entries.filter(e => e.status === status);
      return group.length > 0 && <section class="cart-group"><h2 class="section-title">{{ failed: '待处理', writing: '写入中', added: '已入库' }[status]} <span>{group.length}</span></h2>
        {group.map(entry => <PaperCard safariOpen={store.state.settings.safariOpen !== false} key={entry.paper.id} paper={entry.paper} source={feed?.sources.find(s => s.id === entry.paper.source)} read={!!store.state.read[entry.paper.id]} entry={entry} busy={store.busy || store.storageStatus !== 'ready'} add={() => add(entry.paper)} />)}</section>;
    })}</>;
}
