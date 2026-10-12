import type { Batch, Collection, ItemResult } from '../types';

export function writeToken(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
}
export function retryDelay(value: string | null, now: number): number {
  if (!value) return 0;
  const seconds = Number(value);
  if (Number.isFinite(seconds)) return Math.max(0, seconds * 1000);
  const date = Date.parse(value);
  return Number.isFinite(date) ? Math.max(0, date - now) : 0;
}
interface Options {
  fetch?: typeof fetch; now?: () => number; sleep?: (ms: number) => Promise<void>;
  cooldown?: () => number; saveCooldown?: (at: number) => Promise<void>;
}
export class ZoteroClient {
  private tail: Promise<unknown> = Promise.resolve();
  private nextAt = 0;
  private fetcher: typeof fetch;
  private now: () => number;
  private sleep: (ms: number) => Promise<void>;
  constructor(private options: Options = {}) {
    this.fetcher = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.now = options.now ?? Date.now;
    this.sleep = options.sleep ?? (ms => new Promise(resolve => setTimeout(resolve, ms)));
  }
  private async cool(at: number) {
    this.nextAt = Math.max(this.nextAt, at, this.options.cooldown?.() ?? 0);
    await this.options.saveCooldown?.(this.nextAt);
  }
  private request(path: string, apiKey: string, init: RequestInit = {}): Promise<Response> {
    const run = async () => {
      for (let attempt = 0; ; attempt++) {
        const wait = Math.max(this.nextAt, this.options.cooldown?.() ?? 0) - this.now();
        if (wait > 0) await this.sleep(wait);
        // Reserve the spacing even on network failure; all read/write calls share this queue.
        await this.cool(this.now() + 1000);
        let response: Response;
        try {
          response = await this.fetcher(`https://api.zotero.org${path}`, {
            ...init, redirect: 'error', headers: {
              'Zotero-API-Key': apiKey, 'Zotero-API-Version': '3', ...init.headers,
            }, signal: AbortSignal.timeout(30000),
          });
        } catch {
          if (attempt >= 3) throw new Error('网络中断或超时，写入结果未确认');
          await this.cool(this.now() + 1000 * 2 ** attempt);
          continue;
        }
        await this.cool(this.now() + Math.max(
          retryDelay(response.headers.get('Backoff'), this.now()),
          retryDelay(response.headers.get('Retry-After'), this.now()),
        ));
        if (![429, 503].includes(response.status) || attempt >= 3) return response;
        await this.cool(this.now() + 1000 * 2 ** attempt);
      }
    };
    const result = this.tail.then(run);
    this.tail = result.catch(() => undefined);
    return result;
  }
  async validateKey(apiKey: string): Promise<number> {
    const response = await this.request('/keys/current', apiKey);
    if (!response.ok) throw new Error(`Key 校验失败（HTTP ${response.status}）`);
    const data = await response.json();
    if (!Number.isSafeInteger(data.userID) || data.userID <= 0 ||
        data.access?.user?.library !== true || data.access?.user?.write !== true) {
      throw new Error('此 Key 没有个人文库的读写权限');
    }
    return data.userID;
  }
  async collections(apiKey: string, userID: number): Promise<Collection[]> {
    const collections: Collection[] = [];
    // Two metadata pages at most, as required by AGENTS.md.
    for (let page = 0; page < 2; page++) {
      const response = await this.request(`/users/${userID}/collections?limit=100&start=${page * 100}`, apiKey);
      if (!response.ok) throw new Error(`集合读取失败（HTTP ${response.status}）`);
      const data = await response.json();
      if (!Array.isArray(data) || data.some(c => typeof c.key !== 'string' || typeof c.data?.name !== 'string')) {
        throw new Error('集合响应格式异常');
      }
      collections.push(...data);
      if (data.length < 100) break;
    }
    return collections;
  }
  async write(apiKey: string, batch: Batch): Promise<ItemResult[]> {
    const items = JSON.parse(batch.body);
    if (!Array.isArray(items) || items.length === 0 || items.length > 50 || items.length !== batch.paperIDs.length) {
      throw new Error('每批必须包含 1–50 条文献');
    }
    if (!/^[a-f0-9]{32}$/.test(batch.token)) throw new Error('Write-Token 格式错误');
    const allFailed = (error: string, retry: ItemResult['retry']): ItemResult[] =>
      items.map(() => ({ status: 'failed', error, retry }));
    let response: Response;
    try {
      response = await this.request(`/users/${batch.userID}/items`, apiKey, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Zotero-Write-Token': batch.token }, body: batch.body,
      });
    } catch {
      return allFailed('网络中断或超时，结果未确认；重试会沿用原批次', 'same');
    }
    if (response.status === 412) return allFailed('HTTP 412：此批次可能已写入，请在 Zotero 核对；禁止自动重发', 'blocked');
    if (!response.ok) {
      const transient = response.status >= 500 || response.status === 429;
      return allFailed(`写入失败（HTTP ${response.status}）${transient ? '，可沿用原批次重试' : '，请检查权限或数据后重试'}`, transient ? 'same' : 'new');
    }
    try {
      const data = await response.json();
      return items.map((_: unknown, index: number): ItemResult => {
        const key = data.successful?.[index]?.key ?? data.unchanged?.[index];
        if (typeof key === 'string' && key) return { status: 'added', key, retry: 'blocked' };
        const failed = data.failed?.[index];
        if (failed && typeof failed.message === 'string') return {
          status: 'failed', error: `${failed.code ?? ''} ${failed.message}`.trim(), retry: 'new',
        };
        return { status: 'failed', error: '响应未确认此条结果，请核对 Zotero', retry: 'blocked' };
      });
    } catch {
      return allFailed('响应格式异常，写入结果未确认；可沿用原批次重试', 'same');
    }
  }
}
