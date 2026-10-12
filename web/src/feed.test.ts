import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { loadFeed } from './feed';
import sample from './fixtures/feed.sample.json';
beforeEach(() => { vi.stubGlobal('fetch', vi.fn()); vi.stubEnv('BASE_URL', './'); });
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.useRealTimers(); });
it('loads only the relative metadata feed, without fetching paper/PDF links', async () => {
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(sample)));
  expect((await loadFeed()).feed.papers).toHaveLength(36);
  expect(fetch).toHaveBeenCalledExactlyOnceWith('./data/feed.json', { signal: expect.any(AbortSignal) });
});
it('uses the fixture only when the development feed is missing', async () => {
  vi.stubEnv('DEV', true); vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 404 }));
  expect((await loadFeed()).sample).toBe(true); expect(fetch).toHaveBeenCalledTimes(1);
});
it('recognizes Vite HTML fallback for a missing development feed', async () => {
  vi.stubEnv('DEV', true); vi.mocked(fetch).mockResolvedValue(new Response('<!doctype html>', { headers: { 'Content-Type': 'text/html' } }));
  expect((await loadFeed()).sample).toBe(true);
});
it('never silently substitutes the sample in production', async () => {
  vi.stubEnv('DEV', false); vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 404 }));
  await expect(loadFeed()).rejects.toThrow('404');
});
it('reports offline failures without trying external paper URLs', async () => {
  vi.mocked(fetch).mockRejectedValue(new Error('offline'));
  await expect(loadFeed()).rejects.toThrow('无法读取'); expect(fetch).toHaveBeenCalledTimes(1);
});
it('rejects an unsupported feed schema', async () => {
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ ...sample, schema: 2 })));
  await expect(loadFeed()).rejects.toThrow('不支持');
});

it('bounds an unresolved feed request and presents a retryable timeout', async () => {
  vi.useFakeTimers(); vi.mocked(fetch).mockImplementation(() => new Promise(() => {}));
  const result = expect(loadFeed()).rejects.toThrow('信息流加载超时');
  await vi.advanceTimersByTimeAsync(5000); await result;
});
it('also bounds a stalled response body', async () => {
  vi.useFakeTimers(); const response = new Response();
  vi.spyOn(response, 'json').mockImplementation(() => new Promise(() => {}));
  vi.mocked(fetch).mockResolvedValue(response);
  const result = expect(loadFeed()).rejects.toThrow('信息流加载超时');
  await vi.advanceTimersByTimeAsync(5000); await result;
});
