import { get, set, del } from 'idb-keyval';
import { publishers, validAccess } from './access';
import { withTimeout } from './timeout';
import { writeToken, ZoteroClient } from './api/zotero';
import type { AccessRecord, Batch, ItemResult, LocalState, Paper, Settings } from './types';
const KEY = 'papercart:v1';
export function emptyState(): LocalState {
  return { settings: { apiKey: '', userID: null, collection: '', tags: [], collections: [], safariOpen: true, access: {} },
    read: {}, cart: {}, batches: {}, nextRequestAt: 0, filters: { group: '', source: '' } };
}
export class Store {
  state = emptyState();
  private listeners = new Set<() => void>();
  private tail: Promise<unknown> = Promise.resolve();
  busy = false;
  storageStatus: 'loading' | 'ready' | 'unavailable' = 'loading';
  storageError = '';
  private loadAttempt = 0;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private notify() { this.listeners.forEach(listener => listener()); }
  async load() {
    const attempt = ++this.loadAttempt;
    this.storageStatus = 'loading';
    this.storageError = '';
    this.notify();
    try {
      const next = await withTimeout((async () => {
        const saved = await get<LocalState>(KEY);
        if (attempt !== this.loadAttempt) throw new Error('本地存储初始化已取消');
        const next = saved ?? emptyState();
        next.settings = { ...emptyState().settings, ...next.settings };
        // A closed tab may have sent the request: never auto-resume or replace its token.
        for (const entry of Object.values(next.cart)) {
          if (entry.status === 'writing') {
            entry.status = 'failed';
            entry.result = { status: 'failed', error: '上次写入中断，结果未确认；重试沿用原批次', retry: 'same' };
          }
        }
        await set(KEY, next);
        return next;
      })(), 5000, '本地存储打开超时');
      // Publish only once the complete operation succeeds, never from a late timed-out promise.
      if (attempt !== this.loadAttempt) return;
      this.state = next;
      this.storageStatus = 'ready';
    } catch (error) {
      if (attempt !== this.loadAttempt) return;
      ++this.loadAttempt;
      this.storageStatus = 'unavailable';
      this.storageError = error instanceof Error && error.message === '本地存储打开超时' ? error.message : '本地存储不可用';
    }
    this.notify();
  }
  private update(change: (state: LocalState) => void) {
    const run = async () => {
      if (this.storageStatus !== 'ready') throw new Error('本地存储不可用，无法保存或写入 Zotero；请重试本地存储');
      const next = structuredClone(this.state);
      change(next);
      await set(KEY, next);
      this.state = next;
      this.notify();
    };
    const result = this.tail.then(run);
    this.tail = result.catch(() => undefined);
    return result;
  }
  markRead(ids: string[]) { return this.update(s => { ids.forEach(id => { s.read[id] = true; }); }); }
  settings(settings: Settings) { return this.update(s => { s.settings = settings; }); }
  accessRecord(id: string, record?: AccessRecord) {
    if (!publishers.some(p => p.id === id) || (record && !validAccess(record))) return Promise.reject(new Error('请填写有效配对日期和正整数天数'));
    return this.update(s => {
      s.settings.access ??= {};
      if (record) s.settings.access[id] = { pairedOn: record.pairedOn, days: record.days };
      else delete s.settings.access[id];
    });
  }
  filters(group: string, source: string) {
    if (this.storageStatus !== 'ready') {
      this.state = { ...this.state, filters: { group, source } };
      this.notify();
      return Promise.resolve();
    }
    return this.update(s => { s.filters = { group, source }; });
  }
  cooldown(at: number) { return this.update(s => { s.nextRequestAt = Math.max(s.nextRequestAt, at); }); }
  async clear() {
    if (this.busy) throw new Error('请等待当前 Zotero 请求完成后再清除');
    if (this.storageStatus !== 'ready') throw new Error('本地存储不可用');
    await this.tail;
    await del(KEY);
    this.state = emptyState();
    this.notify();
  }
  async enqueue(papers: Paper[]): Promise<Batch[]> {
    const batches: Batch[] = [];
    await this.update(s => {
      const settings = s.settings;
      if (!settings.apiKey || !settings.userID) throw new Error('请先在设置中校验 Zotero Key');
      const eligible = papers.filter(p => !s.cart[p.id] || (s.cart[p.id].status === 'failed' && s.cart[p.id].result?.retry === 'new'));
      const unique = [...new Map(eligible.map(p => [p.id, p])).values()];
      for (let start = 0; start < unique.length; start += 50) {
        const group = unique.slice(start, start + 50);
        const token = writeToken();
        const batch: Batch = { id: token, token, userID: settings.userID,
          paperIDs: group.map(p => p.id), status: 'pending', body: JSON.stringify(group.map(p => ({
            ...p.zotero, collections: settings.collection ? [settings.collection] : [],
            tags: settings.tags.map(tag => ({ tag })),
          }))),
        };
        s.batches[batch.id] = batch;
        group.forEach(paper => { s.cart[paper.id] = { paper, status: 'writing', batchID: batch.id }; });
        batches.push(batch);
      }
    });
    return batches;
  }
  async apply(batch: Batch, results: ItemResult[]) {
    await this.update(s => {
      s.batches[batch.id].results = results;
      s.batches[batch.id].status = results.some(r => r.retry === 'blocked' && r.status === 'failed') ? 'blocked' :
        results.every(r => r.status === 'added') ? 'done' : 'failed';
      batch.paperIDs.forEach((id, i) => {
        if (s.cart[id]?.batchID === batch.id) { s.cart[id].status = results[i].status; s.cart[id].result = results[i]; }
      });
    });
  }
  async add(paper: Paper, client: ZoteroClient) {
    // Serialize UI actions; repeated taps cannot create another batch.
    if (this.storageStatus !== 'ready') throw new Error('本地存储不可用，无法写入 Zotero');
    if (this.busy) return;
    this.busy = true;
    this.notify();
    try {
      const entry = this.state.cart[paper.id];
      let batches: Batch[];
      if (entry?.status === 'added' || entry?.result?.retry === 'blocked') return;
      if (entry?.result?.retry === 'same') {
        const batch = this.state.batches[entry.batchID];
        if (batch.userID !== this.state.settings.userID) throw new Error('请使用原 Zotero 账号重试此批次');
        batches = [batch];
        await this.update(s => { batch.paperIDs.forEach(id => { if (s.cart[id]?.batchID === batch.id) s.cart[id].status = 'writing'; }); });
      } else batches = await this.enqueue([paper]);
      for (const batch of batches) await this.apply(batch, await client.write(this.state.settings.apiKey, batch));
    } finally { this.busy = false; this.notify(); }
  }
}
export const store = new Store();
export const client = new ZoteroClient({ cooldown: () => store.state.nextRequestAt, saveCooldown: at => store.cooldown(at) });
