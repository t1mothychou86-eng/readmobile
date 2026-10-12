import type { Feed } from './types';
import { withTimeout } from './timeout';
export function loadFeed(): Promise<{ feed: Feed; sample: boolean }> {
  return withTimeout(readFeed(), 5000, '信息流加载超时，请点击刷新重试');
}
async function readFeed(): Promise<{ feed: Feed; sample: boolean }> {
  let response: Response;
  try {
    response = await fetch(`${import.meta.env.BASE_URL}data/feed.json`, { signal: AbortSignal.timeout(5000) });
  } catch { throw new Error('无法读取信息流，请连接网络后重试'); }
  if (import.meta.env.DEV && response.status === 404) {
    const { default: sample } = await import('./fixtures/feed.sample.json');
    return { feed: sample as Feed, sample: true };
  }
  if (!response.ok) throw new Error(`信息流读取失败（HTTP ${response.status}）`);
  let feed: Feed;
  try { feed = await response.json(); }
  catch {
    // Vite's SPA fallback returns index.html for missing public files.
    if (import.meta.env.DEV && response.headers.get('Content-Type')?.includes('text/html')) {
      const { default: sample } = await import('./fixtures/feed.sample.json');
      return { feed: sample as Feed, sample: true };
    }
    throw new Error('信息流格式异常');
  }
  if (feed.schema !== 1 || !Array.isArray(feed.papers) || !Array.isArray(feed.sources)) throw new Error('不支持的信息流格式');
  return { feed, sample: false };
}
