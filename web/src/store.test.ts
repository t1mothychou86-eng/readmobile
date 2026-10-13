import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const db = vi.hoisted(() => new Map<string, unknown>());
vi.mock('idb-keyval', () => ({
  get: vi.fn(async (key: string) => structuredClone(db.get(key))),
  set: vi.fn(async (key: string, value: unknown) => { db.set(key, structuredClone(value)); }),
  del: vi.fn(async (key: string) => { db.delete(key); }),
}));
import { Store } from './store';
import { get, set } from 'idb-keyval';
import { ZoteroClient } from './api/zotero';
import sample from './fixtures/feed.sample.json';
import type { Paper } from './types';
const paper = sample.papers[0] as Paper;
async function ready() { const store = new Store(); await store.load(); await store.settings({ ...store.state.settings, apiKey: 'mock-credential', userID: 1, collection: 'INBOX001', tags: ['待读'] }); return store; }
function clientWith(fetcher: typeof fetch) { return new ZoteroClient({ fetch: fetcher, now: () => 0, sleep: async () => {} }); }
beforeEach(() => { db.clear(); vi.clearAllMocks(); vi.stubGlobal('fetch', vi.fn(() => { throw new Error('禁止真实网络'); })); });
afterEach(() => { vi.useRealTimers(); });
describe('read and local settings', () => {
  it('persists read state, selected filters and settings across reloads', async () => {
    const store = await ready(); await Promise.all([store.markRead([paper.id]), store.markRead(['another'])]); await store.filters('finance', 'jf');
    const reloaded = new Store(); await reloaded.load();
    expect(reloaded.state.read).toEqual({ [paper.id]: true, another: true });
    expect(reloaded.state.filters).toEqual({ group: 'finance', source: 'jf' });
    expect(reloaded.state.settings.collection).toBe('INBOX001');
  });
  it('clears credentials, read and cart data and blocks clearing in-flight requests', async () => {
    const store = await ready(); await store.markRead([paper.id]); await store.enqueue([paper]);
    store.busy = true; await expect(store.clear()).rejects.toThrow('等待'); store.busy = false;
    await store.clear(); const reloaded = new Store(); await reloaded.load();
    expect(reloaded.state.settings.apiKey).toBe(''); expect(reloaded.state.read).toEqual({}); expect(reloaded.state.cart).toEqual({});
  });
});
describe('persistent cart queue', () => {
  it('persists body/token before writing, adds collections/tags without changing feed', async () => {
    const store = await ready(); const original = JSON.stringify(paper); const fetcher = vi.fn<typeof fetch>(async (_, init) => {
      const saved = db.get('papercart:v1') as typeof store.state;
      expect(saved.cart[paper.id].status).toBe('writing');
      const batch = saved.batches[saved.cart[paper.id].batchID];
      expect(batch.body).toBe(init?.body); expect(batch.token).toBe((init?.headers as Record<string,string>)['Zotero-Write-Token']);
      expect(JSON.parse(batch.body)[0]).toMatchObject({ collections: ['INBOX001'], tags: [{ tag: '待读' }] });
      return new Response(JSON.stringify({ successful: { '0': { key: 'ITEM0001' } } }));
    });
    await store.add(paper, clientWith(fetcher));
    expect(store.state.cart[paper.id].status).toBe('added'); expect(JSON.stringify(paper)).toBe(original);
    await store.add(paper, clientWith(fetcher)); expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('deduplicates simultaneous taps and splits 101 items into batches of at most 50', async () => {
    const store = await ready(); const papers = Array.from({ length: 101 }, (_, i) => ({ ...paper, id: `paper:${i}` }));
    const [a, b] = await Promise.all([store.enqueue([...papers, papers[0]]), store.enqueue(papers)]);
    expect(a.map(x => x.paperIDs.length)).toEqual([50, 50, 1]); expect(b).toEqual([]);
    expect(new Set(a.map(x => x.token)).size).toBe(3);
  });
  it('recovers interrupted writes and reuses body/token despite changed defaults', async () => {
    const store = await ready(); const [batch] = await store.enqueue([paper]);
    const reloaded = new Store(); await reloaded.load(); expect(reloaded.state.cart[paper.id].result?.retry).toBe('same');
    await reloaded.settings({ ...reloaded.state.settings, collection: 'OTHER001', tags: ['new'] });
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({ unchanged: { '0': 'ITEM0001' } })));
    await reloaded.add(paper, clientWith(fetcher));
    expect(fetcher.mock.calls[0][1]?.body).toBe(batch.body);
    expect(fetcher.mock.calls[0][1]?.headers).toMatchObject({ 'Zotero-Write-Token': batch.token });
    expect(reloaded.state.cart[paper.id].status).toBe('added');
  });
  it('creates a new batch for explicitly failed entries and excludes confirmed successes', async () => {
    const store = await ready(); const second = { ...paper, id: 'second' }; const [batch] = await store.enqueue([paper, second]);
    await store.apply(batch, [{ status: 'added', key: 'ITEM0001', retry: 'blocked' }, { status: 'failed', error: 'Invalid field', retry: 'new' }]);
    const [retry] = await store.enqueue([paper, second]);
    expect(retry.paperIDs).toEqual(['second']); expect(retry.token).not.toBe(batch.token);
    expect(store.state.cart[paper.id].status).toBe('added');
  });
  it('412 remains blocked after reload and manual taps do not resubmit', async () => {
    const store = await ready(); const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 412 }));
    await store.add(paper, clientWith(fetcher)); const reloaded = new Store(); await reloaded.load();
    await reloaded.add(paper, clientWith(fetcher)); expect(fetcher).toHaveBeenCalledTimes(1);
    expect(reloaded.state.cart[paper.id]).toMatchObject({ status: 'failed', result: { retry: 'blocked' } });
  });
  it('does not retry an uncertain batch under a different Zotero user', async () => {
    const store = await ready(); await store.enqueue([paper]); const reloaded = new Store(); await reloaded.load();
    await reloaded.settings({ ...reloaded.state.settings, userID: 2 }); const fetcher = vi.fn<typeof fetch>();
    await expect(reloaded.add(paper, clientWith(fetcher))).rejects.toThrow('原 Zotero 账号'); expect(fetcher).not.toHaveBeenCalled();
  });
});


describe('first-run storage initialization', () => {
  it('resolves with an empty state on a fresh profile', async () => {
    const store = new Store(); await store.load();
    expect(store.storageStatus).toBe('ready');
    expect(store.state.cart).toEqual({}); expect(store.state.settings.apiKey).toBe('');
    expect(db.has('papercart:v1')).toBe(true);
  });
  it('finishes in an explicit unavailable state when IndexedDB cannot open', async () => {
    vi.mocked(get).mockRejectedValueOnce(new Error('SecurityError'));
    const store = new Store(); await store.load();
    expect(store.storageStatus).toBe('unavailable'); expect(store.storageError).toContain('不可用');
    await expect(store.settings({ ...store.state.settings, apiKey: 'mock-credential' })).rejects.toThrow('本地存储不可用');
    const fetcher = vi.fn<typeof fetch>();
    await expect(store.add(paper, clientWith(fetcher))).rejects.toThrow('本地存储不可用');
    expect(fetcher).not.toHaveBeenCalled();
    await store.load(); expect(store.storageStatus).toBe('ready');
  });
  it('finishes in an explicit unavailable state when the first transaction fails', async () => {
    vi.mocked(set).mockRejectedValueOnce(new Error('QuotaExceededError'));
    const store = new Store(); await store.load();
    expect(store.storageStatus).toBe('unavailable'); expect(store.state.cart).toEqual({});
  });
  it('times out an unresolved IndexedDB open and ignores its late result', async () => {
    vi.useFakeTimers(); let resolve!: (value: undefined) => void;
    vi.mocked(get).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    const store = new Store(); const loading = store.load();
    await vi.advanceTimersByTimeAsync(5000); await loading;
    expect(store.storageStatus).toBe('unavailable'); expect(store.storageError).toContain('超时');
    resolve(undefined); await vi.advanceTimersByTimeAsync(0);
    expect(store.storageStatus).toBe('unavailable'); expect(set).not.toHaveBeenCalled();
  });
});

describe('institution dates and Safari preference', () => {
  it('migrates old settings, persists reminders and preference, and clears both', async () => {
    const old = new Store().state; delete old.settings.safariOpen; delete old.settings.access; db.set('papercart:v1', old);
    const local = new Store(); await local.load(); expect(local.state.settings.safariOpen).toBe(true);
    await local.settings({ ...local.state.settings, safariOpen: false });
    await local.accessRecord('wiley', { pairedOn: '2026-10-13', days: 60 });
    const reloaded = new Store(); await reloaded.load();
    expect(reloaded.state.settings.safariOpen).toBe(false);
    expect(reloaded.state.settings.access?.wiley).toEqual({ pairedOn: '2026-10-13', days: 60 });
    await reloaded.accessRecord('wiley'); expect(reloaded.state.settings.access).toEqual({});
    await reloaded.accessRecord('jstor', { pairedOn: '2026-10-13', days: 365 });
    await reloaded.clear(); expect(reloaded.state.settings.access).toEqual({}); expect(reloaded.state.settings.safariOpen).toBe(true);
  });
  it('rejects invalid dates and publishers and only retains date and days', async () => {
    const local = new Store(); await local.load();
    await expect(local.accessRecord('wiley', { pairedOn: '2026-02-30', days: 1 })).rejects.toThrow('有效');
    await expect(local.accessRecord('unknown', { pairedOn: '2026-10-13', days: 1 })).rejects.toThrow('有效');
    await local.accessRecord('wiley', { pairedOn: '2026-10-13', days: 60, unrelated: 'discard' } as any);
    expect(local.state.settings.access?.wiley).toEqual({ pairedOn: '2026-10-13', days: 60 });
  });
});
