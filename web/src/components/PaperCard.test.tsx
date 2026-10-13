import { beforeEach, expect, it, vi } from 'vitest';
import type { VNode } from 'preact';
const state = vi.hoisted(() => ({ expanded: false, chinese: false, call: 0 }));
vi.mock('preact/hooks', () => ({ useState: () => [state.call++ === 0 ? state.expanded : state.chinese, vi.fn()], useRef: (current: unknown) => ({ current }), useEffect: vi.fn() }));
import { PaperCard } from './PaperCard';
import sample from '../fixtures/feed.sample.json';
import type { Paper } from '../types';
function nodes(value: unknown): VNode<Record<string, any>>[] {
  if (Array.isArray(value)) return value.flatMap(nodes);
  if (!value || typeof value !== 'object' || !('props' in value)) return [];
  const node = value as VNode<Record<string, any>>;
  return [node, ...nodes(node.props.children)];
}
function card(paper: Paper, safariOpen = true) { state.call = 0; return nodes(PaperCard({ paper, busy: false, add: vi.fn(), safariOpen })); }
const paper = { ...sample.papers[0], abstract: 'An abstract visible on the default card.' } as Paper;
beforeEach(() => { state.expanded = false; state.chinese = false; });
it.each([{}, { title_zh: null, abstract_zh: null }, { title_zh: ' ', abstract_zh: '' }])('omits translation elements when translations are absent: %j', fields => {
  const result = card({ ...paper, ...fields });
  expect(result.some(n => ['title-zh', 'language-toggle'].includes(n.props.class))).toBe(false);
  expect(result.find(n => n.props.class === 'abstract preview')?.props.children).toBe(paper.abstract);
});
it('renders translations independently and selects the Chinese abstract', () => {
  const title = card({ ...paper, title_zh: '中文标题' });
  expect(title.find(n => n.props.class === 'title-zh')?.props.children).toBe('中文标题');
  expect(title.some(n => n.props.class === 'language-toggle')).toBe(false);
  state.chinese = true;
  const result = card({ ...paper, abstract_zh: '中文摘要' });
  expect(result.find(n => n.props.class === 'abstract preview')?.props.children).toBe('中文摘要');
  expect(result.find(n => n.props.class === 'language-toggle')?.props.children).toBe('EN');
  expect(result.some(n => n.props.class === 'title-zh')).toBe(false);
});
it('expands in place and renders missing abstracts without empty space or toggle', () => {
  state.expanded = true;
  expect(card(paper).some(n => n.props.class === 'abstract expanded')).toBe(true);
  const result = card({ ...paper, abstract: null });
  expect(result.find(n => n.props.class === 'no-abstract')?.props.children).toBe('无摘要');
  expect(result.some(n => n.props.class === 'abstract-toggle')).toBe(false);
});
it('keeps ordinary new-window links when Safari is switched off', () => {
  const result = card(paper, false);
  expect(result.some(n => n.props.class === 'article-link safari-link')).toBe(false);
  expect(result.find(n => n.props.class === 'article-link')?.props).toMatchObject({ href: paper.url, target: '_blank', rel: 'noopener noreferrer' });
});
