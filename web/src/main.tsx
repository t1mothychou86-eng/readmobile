import { render } from 'preact';
import { useEffect, useLayoutEffect, useState } from 'preact/hooks';
import { loadFeed } from './feed';
import { store, client } from './store';
import { AccessPage } from './pages/Access';
import { AccessReminder } from './components/AccessReminder';
import { FeedPage } from './pages/Feed';
import { CartPage } from './pages/Cart';
import { SettingsPage } from './pages/Settings';
import type { Feed, Paper } from './types';
import './style.css';
type Tab = 'feed' | 'cart' | 'settings' | 'access';
const currentTab = (): Tab => ['cart', 'settings', 'access'].includes(location.hash.slice(1)) ? location.hash.slice(1) as Tab : 'feed';
function App() {
  const [tab, setTab] = useState<Tab>(currentTab);
  const navigate = (tab: Tab) => { location.hash = tab; setTab(tab); window.scrollTo(0, 0); };
  const [feed, setFeed] = useState<Feed>();
  const [sample, setSample] = useState(false);
  const [loading, setLoading] = useState(true);
  const [feedError, setFeedError] = useState('');
  const [message, report] = useState('');
  const [offline, setOffline] = useState(!navigator.onLine);
  const [revision, refresh] = useState(0);
  const [epoch, setEpoch] = useState(0);
  const reload = async () => {
    setLoading(true);
    setFeedError('');
    try { const data = await loadFeed(); setFeed(data.feed); setSample(data.sample); setEpoch(v => v + 1); }
    catch (error) { setFeedError(error instanceof Error ? error.message : '信息流加载失败'); }
    finally { setLoading(false); }
  };
  useLayoutEffect(() => {
    const unsubscribe = store.subscribe(() => refresh(v => v + 1));
    void store.load();
    void reload();
    const online = () => setOffline(!navigator.onLine);
    window.addEventListener('online', online); window.addEventListener('offline', online);
    return () => { unsubscribe(); window.removeEventListener('online', online); window.removeEventListener('offline', online); };
  }, []);
  useEffect(() => {
    const tick = setInterval(() => refresh(v => v + 1), 60000);
    const focused = () => refresh(v => v + 1);
    window.addEventListener('focus', focused);
    const changed = () => { setTab(currentTab()); window.scrollTo(0, 0); };
    window.addEventListener('hashchange', changed);
    return () => { clearInterval(tick); window.removeEventListener('focus', focused); window.removeEventListener('hashchange', changed); };
  }, []);
  const add = (paper: Paper) => {
    if (store.storageStatus !== 'ready') { report('本地存储不可用，无法加购；请重试本地存储'); return; }
    if (!store.state.settings.userID) { report('请先输入并校验 Zotero API Key'); navigate('settings'); return; }
    void store.add(paper, client).catch(error => report(error instanceof Error ? error.message : '本地保存失败，请重试'));
  };
  const count = Object.values(store.state.cart).filter(e => e.status !== 'added').length;
  return <><header class="topbar"><a class="brand" href="#" onClick={e => { e.preventDefault(); navigate('feed'); }}>▤ <span>PaperCart</span></a><button class="text-button" disabled={loading} onClick={() => void reload()}>{loading ? '刷新中…' : '刷新'}</button></header>
    {offline && <div class="offline" role="status">离线浏览 · 已缓存的信息流仍可阅读</div>}
    <main data-revision={revision}>
      {message && <div class="notice" role="status"><span>{message}</span><button aria-label="关闭提示" onClick={() => report('')}>×</button></div>}
      {store.storageStatus !== 'ready' && <div class="notice" role="status"><span>{store.storageStatus === 'loading' ? '正在打开本地数据，可先浏览文献…' : `${store.storageError}。当前仅可浏览，无法保存已读、设置或加购。`}</span>{store.storageStatus === 'unavailable' && <button onClick={() => void store.load()}>重试本地存储</button>}</div>}
      {feedError && <div class="notice" role="alert"><span>{feedError}</span><button disabled={loading} onClick={() => void reload()}>重试信息流</button></div>}
      <>
        {(tab === 'feed' || tab === 'settings') && <AccessReminder settings={store.state.settings} />}
        {tab === 'access' && <AccessPage report={report} />}
        {tab === 'feed' && (feed ? <FeedPage key={`feed-${epoch}`} feed={feed} add={add} report={report} /> : <div class="empty">{loading ? '正在加载文献…' : '暂时没有信息流，请点击刷新重试。'}</div>)}
        {tab === 'cart' && <CartPage feed={feed} add={add} />}
        {tab === 'settings' && <SettingsPage key={`settings-${epoch}`} feed={feed} sample={sample} report={report} cleared={() => setEpoch(v => v + 1)} />}
      </>
      {store.busy && <p class="queue-status" role="status">正在处理 Zotero 请求，限流时会等待后继续。请保持页面打开。</p>}
    </main><nav class="tabs" aria-label="主导航">{([['feed', '▤', '信息流'], ['cart', '◫', '购物车'], ['settings', '⚙', '设置']] as const).map(([value, icon, label]) => <button aria-current={(tab === value || (tab === 'access' && value === 'settings')) ? 'page' : undefined} onClick={() => navigate(value)}><span class="tab-icon" aria-hidden="true">{icon}</span><span>{label}{value === 'cart' && count > 0 && <span class="count">{count}</span>}</span></button>)}</nav></>;
}
render(<App />, document.getElementById('app')!);
