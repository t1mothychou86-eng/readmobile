// Regression checks against vite preview using Chromium's CDP; no browser library/dependency.
// Start Chromium with --remote-debugging-port=9224, then run node scripts/browser-check.mjs.
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
const base = process.env.PREVIEW_URL ?? 'http://localhost:4174/';
const output = process.env.SCREENSHOT_DIR ?? '/tmp/papercart-m4';
const version = await (await fetch(`${process.env.CDP_URL ?? 'http://127.0.0.1:9224'}/json/version`)).json();
async function connect(url) {
  const ws = new WebSocket(url); await new Promise(resolve => ws.addEventListener('open', resolve, { once: true }));
  let id = 0; const waiting = new Map(); const events = [];
  ws.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.id) { const call = waiting.get(message.id); waiting.delete(message.id); message.error ? call.reject(message.error) : call.resolve(message.result); }
    else { events.push(message); if (message.method === 'Fetch.requestPaused') {
      const local = ['localhost', '127.0.0.1'].includes(new URL(message.params.request.url).hostname);
      void send(local ? 'Fetch.continueRequest' : 'Fetch.failRequest', { requestId: message.params.requestId, ...(local ? {} : { errorReason: 'BlockedByClient' }) });
    } }
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const current = ++id; waiting.set(current, { resolve, reject }); ws.send(JSON.stringify({ id: current, method, params }));
  });
  return { send, events, close: () => ws.close() };
}
const browser = await connect(version.webSocketDebuggerUrl);
await mkdir(output, { recursive: true });
const results = [];
async function page(script = '') {
  const { browserContextId } = await browser.send('Target.createBrowserContext');
  const { targetId } = await browser.send('Target.createTarget', { url: 'about:blank', browserContextId });
  const list = await (await fetch(`${process.env.CDP_URL ?? 'http://127.0.0.1:9224'}/json/list`)).json();
  const cdp = await connect(list.find(target => target.id === targetId).webSocketDebuggerUrl);
  await cdp.send('Runtime.enable'); await cdp.send('Page.enable'); await cdp.send('Fetch.enable', { patterns: [{ urlPattern: '*' }] });
  if (script) await cdp.send('Page.addScriptToEvaluateOnNewDocument', { source: script });
  const evaluate = async expression => {
    const data = await cdp.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (data.exceptionDetails) throw new Error(JSON.stringify(data.exceptionDetails));
    return data.result.value;
  };
  const wait = expression => evaluate(`new Promise((resolve, reject) => { const started = performance.now(); const timer = setInterval(() => { if (${expression}) { clearInterval(timer); resolve(true); } else if (performance.now() - started > 8000) { clearInterval(timer); reject(new Error('UI readiness timeout: ' + document.body.innerText.slice(0,300))); } }, 50); })`);
  const size = width => cdp.send('Emulation.setDeviceMetricsOverride', { width, height: 844, deviceScaleFactor: 2, mobile: true });
  const shot = async name => { await cdp.send('Page.bringToFront'); await new Promise(resolve => setTimeout(resolve, 200)); await evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))'); const { data } = await cdp.send('Page.captureScreenshot', { format: 'png' }); await writeFile(`${output}/${name}.png`, Buffer.from(data, 'base64')); };
  const check = async label => {
    const metrics = await evaluate(`({ width: innerWidth, client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth, overflow: [...document.querySelectorAll('header, header button, .tabs, .tabs button, main, .paper, .panel, input, select')].filter(e => { const r = e.getBoundingClientRect(); return r.left < -1 || r.right > innerWidth + 1; }).map(e => e.tagName + '.' + e.className) })`);
    assert.equal(metrics.scroll, metrics.client, `${label}: document overflow ${JSON.stringify(metrics)}`);
    assert.deepEqual(metrics.overflow, [], `${label}: controls outside viewport`);
    results.push({ label, ...metrics });
  };
  return { ...cdp, evaluate, wait, size, shot, check, async close() { cdp.close(); await browser.send('Target.disposeBrowserContext', { browserContextId }); } };
}
try {
  const normal = await page();
  await normal.size(390); await normal.send('Page.navigate', { url: base });
  await normal.wait(`document.querySelector('.paper') && !document.body.innerText.includes('正在打开本地数据')`);
  for (const theme of ['light', 'dark']) {
    await normal.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: theme }] });
    for (const tab of ['feed', 'cart', 'settings']) {
      await normal.evaluate(`location.hash = ${JSON.stringify(tab)}`);
      const heading = { feed: '文献信息流', cart: '文献购物车', settings: '设置' }[tab];
      await normal.wait(`document.querySelector('h1')?.textContent === ${JSON.stringify(heading)}`);
      for (const width of [320, 360, 375, 390, 414, 430]) { await normal.size(width); await normal.check(`${tab}-${theme}-${width}`); }
      await normal.size(390); await normal.evaluate('window.scrollTo(0, 0)'); await normal.shot(`${tab}-${theme}`);
      const header = await normal.evaluate('({ y: document.querySelector("header").getBoundingClientRect().top, scroll: scrollY })');
      assert.equal(header.y, 0, JSON.stringify(header));
    }
  }
  assert.equal(normal.events.filter(e => e.method === 'Runtime.exceptionThrown').length, 0);
  await normal.close();
  for (const [name, script, expected] of [
    ['idb-unavailable', `Object.defineProperty(window, 'indexedDB', { get() { throw new Error('SecurityError'); } });`, '本地存储不可用'],
    ['idb-timeout', `Object.defineProperty(window, 'indexedDB', { value: { open() { return {}; } } });`, '本地存储打开超时'],
    ['feed-failed', `const originalFetch = window.fetch; window.fetch = (url, options) => String(url).endsWith('data/feed.json') ? Promise.resolve(new Response(null, {status:503})) : originalFetch(url, options);`, '信息流读取失败'],
    ['feed-timeout', `const originalFetch = window.fetch; window.fetch = (url, options) => String(url).endsWith('data/feed.json') ? new Promise(() => {}) : originalFetch(url, options);`, '信息流加载超时'],
  ]) {
    const scenario = await page(script); await scenario.size(390); await scenario.send('Page.navigate', { url: base });
    await scenario.wait(`document.body.innerText.includes(${JSON.stringify(expected)})`);
    if (name.startsWith('idb')) {
      assert.equal(await scenario.evaluate(`!!document.querySelector('.paper')`), true);
      assert.equal(await scenario.evaluate(`document.querySelector('.add')?.disabled`), true);
      assert.equal(await scenario.evaluate(`!![...document.querySelectorAll('button')].find(b => b.textContent === '重试本地存储')`), true);
    } else {
      assert.equal(await scenario.evaluate(`!![...document.querySelectorAll('button')].find(b => b.textContent === '重试信息流')`), true);
    }
    await scenario.check(name); await scenario.shot(name);
    await scenario.evaluate(`document.querySelector('.tabs button:last-child').click()`);
    await scenario.wait(`document.querySelector('h1')?.textContent === '设置'`);
    await scenario.check(`${name}-settings`); await scenario.close();
  }
  const longText = await page(`const originalFetch = window.fetch; window.fetch = async (url, options) => { const response = await originalFetch(url, options); if (!String(url).endsWith('data/feed.json')) return response; const feed = await response.json(); const text = 'https://example.invalid/' + 'LongDOI0123456789'.repeat(50); feed.papers.forEach(p => { p.title = text; p.abstract = text; }); feed.sources.forEach(s => { s.errors = [text]; }); return new Response(JSON.stringify(feed), {headers:{'Content-Type':'application/json'}}); };`);
  await longText.size(320); await longText.send('Page.navigate', { url: base });
  await longText.wait(`document.querySelector('.paper') && !document.body.innerText.includes('正在打开本地数据')`);
  await longText.evaluate(`document.querySelector('.abstract-toggle').click()`);
  for (const width of [320, 360, 390, 430]) { await longText.size(width); await longText.check(`long-url-${width}`); }
  await longText.shot('long-url');
  await longText.evaluate(`location.hash = 'settings'`); await longText.wait(`document.querySelector('h1')?.textContent === '设置'`);
  for (const width of [320, 390, 430]) { await longText.size(width); await longText.check(`long-source-error-${width}`); }
  await longText.close();
  await writeFile(`${output}/checks.json`, JSON.stringify(results, null, 2));
  console.log(`Browser regressions passed: ${results.length} layout checks; fresh-profile startup, unavailable/stalled IndexedDB, failed/stalled feed and long URLs. Screenshots: ${output}`);
} finally { browser.close(); }
