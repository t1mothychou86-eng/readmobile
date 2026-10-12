import { beforeEach, describe, expect, it, vi } from 'vitest';
import { retryDelay, writeToken, ZoteroClient } from './zotero';
import type { Batch } from '../types';
const batch = (length = 1): Batch => ({ id: 'batch', token: 'a'.repeat(32), body: JSON.stringify(Array.from({ length }, (_, i) => ({ itemType: 'report', title: `Paper ${i}` }))), paperIDs: Array.from({ length }, (_, i) => `${i}`), userID: 1, status: 'pending' });
const json = (data: unknown, status = 200, headers?: Record<string, string>) => new Response(JSON.stringify(data), { status, headers });
const success = () => json({ successful: { '0': { key: 'ITEM0001' } }, unchanged: {}, failed: {} });
function setup() {
  let time = Date.parse('2026-10-13T00:00:00Z');
  const fetcher = vi.fn<typeof fetch>();
  const sleep = vi.fn(async (ms: number) => { time += ms; });
  const saveCooldown = vi.fn(async () => {});
  const client = new ZoteroClient({ fetch: fetcher, now: () => time, sleep, saveCooldown });
  return { client, fetcher, sleep, saveCooldown };
}
beforeEach(() => { vi.restoreAllMocks(); vi.stubGlobal('fetch', vi.fn(() => { throw new Error('禁止真实网络'); })); });
describe('Zotero batch writes', () => {
  it('generates secure 32 character hex tokens', () => {
    const a = writeToken(); expect(a).toMatch(/^[0-9a-f]{32}$/); expect(writeToken()).not.toBe(a);
  });
  it('reuses the exact body and token after network errors', async () => {
    const { client, fetcher, sleep } = setup();
    fetcher.mockRejectedValueOnce(new Error('timeout')).mockResolvedValueOnce(success());
    const original = batch();
    expect((await client.write('mock-credential', original))[0].status).toBe('added');
    expect(fetcher).toHaveBeenCalledTimes(2);
    for (const [, init] of fetcher.mock.calls) {
      expect(init?.body).toBe(original.body);
      expect(init?.headers).toMatchObject({ 'Zotero-Write-Token': original.token, 'Zotero-API-Version': '3' });
    }
    expect(sleep.mock.calls).toEqual([[1000]]);
  });
  it('parses successful, unchanged and failed individually', async () => {
    const { client, fetcher } = setup();
    fetcher.mockResolvedValueOnce(json({ successful: { '0': { key: 'OK000001', data: { title: 'a' } } }, unchanged: { '1': 'SAME0001' }, failed: { '2': { code: 400, message: 'Invalid title' } } }));
    expect(await client.write('mock-credential', batch(3))).toEqual([
      { status: 'added', key: 'OK000001', retry: 'blocked' },
      { status: 'added', key: 'SAME0001', retry: 'blocked' },
      { status: 'failed', error: '400 Invalid title', retry: 'new' },
    ]);
  });
  it('blocks 412 without changing token or automatically retrying', async () => {
    const { client, fetcher } = setup(); const original = batch();
    fetcher.mockResolvedValueOnce(new Response(null, { status: 412 }));
    const result = await client.write('mock-credential', original);
    expect(result[0]).toMatchObject({ status: 'failed', retry: 'blocked' });
    expect(result[0].error).toContain('412'); expect(fetcher).toHaveBeenCalledTimes(1);
    expect(original.token).toBe('a'.repeat(32));
  });
  it('accepts 50 items but rejects 51 before any request', async () => {
    const { client, fetcher } = setup(); fetcher.mockResolvedValueOnce(json({ successful: {}, unchanged: {}, failed: {} }));
    expect(await client.write('mock-credential', batch(50))).toHaveLength(50);
    await expect(client.write('mock-credential', batch(51))).rejects.toThrow('1–50');
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('never confirms missing or malformed individual results', async () => {
    const { client, fetcher } = setup(); fetcher.mockResolvedValueOnce(json({ successful: {}, failed: {} }));
    expect((await client.write('mock-credential', batch()))[0]).toMatchObject({ status: 'failed', retry: 'blocked' });
  });
  it('does not retry permanent HTTP errors', async () => {
    const { client, fetcher } = setup(); fetcher.mockResolvedValueOnce(new Response(null, { status: 403 }));
    expect((await client.write('mock-credential', batch()))[0]).toMatchObject({ status: 'failed', retry: 'new' });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('keeps an ambiguous batch retryable with its original token', async () => {
    const { client, fetcher, sleep } = setup(); fetcher.mockRejectedValue(new Error('offline'));
    expect((await client.write('mock-credential', batch()))[0].retry).toBe('same');
    expect(fetcher).toHaveBeenCalledTimes(4); expect(sleep.mock.calls).toEqual([[1000], [2000], [4000]]);
  });
});
describe('shared read/write rate limiting', () => {
  it('honors Backoff on HTTP 200 before a following read', async () => {
    const { client, fetcher, sleep, saveCooldown } = setup();
    fetcher.mockResolvedValueOnce(json({ successful: { '0': { key: 'OK000001' } } }, 200, { Backoff: '7' })).mockResolvedValueOnce(json([]));
    await client.write('mock-credential', batch()); await client.collections('mock-credential', 1);
    expect(sleep.mock.calls).toEqual([[7000]]); expect(saveCooldown).toHaveBeenCalled();
  });
  it('uses maximum of Backoff, Retry-After and exponential delay for 429/503', async () => {
    const { client, fetcher, sleep } = setup();
    fetcher.mockResolvedValueOnce(json({}, 429, { Backoff: '5', 'Retry-After': '3' }))
      .mockResolvedValueOnce(json({}, 503, { 'Retry-After': '10' })).mockResolvedValueOnce(success());
    await client.write('mock-credential', batch()); expect(sleep.mock.calls).toEqual([[5000], [10000]]);
    expect(fetcher.mock.calls.map(c => (c[1]?.headers as Record<string, string>)['Zotero-Write-Token'])).toEqual(Array(3).fill('a'.repeat(32)));
  });
  it('honors HTTP date Retry-After', async () => {
    const { client, fetcher, sleep } = setup();
    fetcher.mockResolvedValueOnce(json({}, 429, { 'Retry-After': 'Tue, 13 Oct 2026 00:00:09 GMT' })).mockResolvedValueOnce(success());
    await client.write('mock-credential', batch()); expect(sleep.mock.calls).toEqual([[9000]]);
    expect(retryDelay('not-a-date', 0)).toBe(0); expect(retryDelay('-1', 0)).toBe(0);
  });
  it('caps 429 retries at three and keeps the batch token', async () => {
    const { client, fetcher, sleep } = setup(); fetcher.mockResolvedValue(json({}, 429));
    expect((await client.write('mock-credential', batch()))[0].retry).toBe('same');
    expect(fetcher).toHaveBeenCalledTimes(4); expect(sleep.mock.calls).toEqual([[1000], [2000], [4000]]);
  });
  it('serializes concurrent reads and writes with at least one second spacing', async () => {
    const { client, fetcher, sleep } = setup();
    fetcher.mockResolvedValueOnce(success()).mockResolvedValueOnce(json({ userID: 1, access: { user: { library: true, write: true } } }));
    await Promise.all([client.write('mock-credential', batch()), client.validateKey('mock-credential')]);
    expect(sleep.mock.calls).toEqual([[1000]]);
  });
  it('honors persisted cooldown after reload', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(success()); let time = 100;
    const sleep = vi.fn(async (ms: number) => { time += ms; });
    const client = new ZoteroClient({ fetch: fetcher, now: () => time, sleep, cooldown: () => 6100 });
    await client.write('mock-credential', batch()); expect(sleep.mock.calls).toEqual([[6000]]);
  });
});
describe('settings read requests', () => {
  it('validates personal library write permission and user ID', async () => {
    const { client, fetcher } = setup();
    fetcher.mockResolvedValueOnce(json({ userID: 123, access: { user: { library: true, write: true } } }));
    expect(await client.validateKey('mock-credential')).toBe(123);
    expect(fetcher.mock.calls[0][0]).toBe('https://api.zotero.org/keys/current');
    fetcher.mockResolvedValueOnce(json({ userID: 123, access: { user: { library: true, write: false } } }));
    await expect(client.validateKey('mock-credential')).rejects.toThrow('读写权限');
  });
  it('reads at most two collection pages', async () => {
    const { client, fetcher } = setup();
    fetcher.mockImplementation(async () => json(Array.from({ length: 100 }, (_, i) => ({ key: `${i}`, data: { name: `Collection ${i}` } }))));
    expect(await client.collections('mock-credential', 1)).toHaveLength(200);
    expect(fetcher).toHaveBeenCalledTimes(2); expect(fetcher.mock.calls[1][0]).toContain('start=100');
  });
});
