export interface Paper {
  id: string; source: string; title: string;
  authors: { given?: string; family?: string; name?: string }[];
  abstract: string | null; published: string | null; first_seen: string;
  date_precision: 'published' | 'first_seen'; url: string;
  zotero: Record<string, unknown>;
}
export interface Source {
  id: string; name: string; short: string; group: string; status: string;
  count: number; errors: string[];
}
export interface Feed { schema: number; generated_at: string; sources: Source[]; papers: Paper[] }
export interface Collection { key: string; data: { name: string; parentCollection?: string | false } }
export interface Settings { apiKey: string; userID: number | null; collection: string; tags: string[]; collections: Collection[] }
export interface ItemResult {
  status: 'added' | 'failed'; key?: string; error?: string;
  retry: 'new' | 'same' | 'blocked';
}
export interface Batch {
  id: string; token: string; body: string; paperIDs: string[]; userID: number;
  status: 'pending' | 'done' | 'failed' | 'blocked'; results?: ItemResult[];
}
export interface CartEntry { paper: Paper; status: 'writing' | 'added' | 'failed'; batchID: string; result?: ItemResult }
export interface LocalState {
  settings: Settings; read: Record<string, true>; cart: Record<string, CartEntry>;
  batches: Record<string, Batch>; nextRequestAt: number;
  filters: { group: string; source: string };
}
