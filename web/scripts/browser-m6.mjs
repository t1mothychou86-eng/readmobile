// Regression checks against vite preview using Chromium's CDP; no browser library/dependency.
// Start Chromium with --remote-debugging-port=9226, then run node scripts/browser-check.mjs.
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
const base = process.env.PREVIEW_URL ?? 'http://localhost:4174/';
const output = process.env.SCREENSHOT_DIR ?? '/tmp/papercart-m6';
const version = await (await fetch(`${process.env.CDP_URL ?? 'http://127.0.0.1:9226'}/json/version`)).json();
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
  const list = await (await fetch(`${process.env.CDP_URL ?? 'http://127.0.0.1:9226'}/json/list`)).json();
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
    await normal.evaluate(`location.hash='feed'; window.scrollTo(0,0)`);
    await normal.wait(`document.querySelector('.paper')`);
    const first = await normal.evaluate(`(() => { const cards=[...document.querySelectorAll('.paper')]; const r=cards[0].getBoundingClientRect(); const preview=cards[0].querySelector('.abstract.preview'); return {top:r.top,bottom:r.bottom,tabTop:document.querySelector('.tabs').getBoundingClientRect().top,nextTop:cards[1].getBoundingClientRect().top,previewHeight:preview?.getBoundingClientRect().height,lineHeight:preview && parseFloat(getComputedStyle(preview).lineHeight),title:cards[0].querySelector('h2').textContent}; })()`);
    results.push({label:`first-card-${theme}`, ...first});
    assert.ok(first.bottom <= first.tabTop, `First card incomplete: ${JSON.stringify(first)}`);
    assert.ok(first.nextTop < first.tabTop, 'Next card should start on first screen');
    assert.ok(Math.abs(first.previewHeight - first.lineHeight*4) < 2, 'Four abstract lines visible');
    assert.equal(await normal.evaluate(`!!document.querySelector('.title-zh, .language-toggle')`), false);
    await normal.check(`feed-${theme}`); await normal.shot(`feed-${theme}`);
    await normal.evaluate(`document.querySelector('.abstract-toggle').click()`);
    await normal.wait(`document.querySelector('.abstract.expanded')`);
    assert.ok(await normal.evaluate(`document.querySelector('.abstract.expanded').getBoundingClientRect().height > 90`));
    await normal.check(`expanded-${theme}`); await normal.shot(`expanded-${theme}`);
    await normal.evaluate(`var select=document.querySelector('.filter-row select'); select.value='jfe'; select.dispatchEvent(new Event('change',{bubbles:true})); window.scrollTo(0,0)`);
    await normal.wait(`document.querySelector('.no-abstract')`);
    assert.equal(await normal.evaluate(`!!document.querySelector('.paper .abstract-toggle')`), false);
    await normal.check(`no-abstract-${theme}`); await normal.shot(`no-abstract-${theme}`);
    await normal.evaluate(`location.hash='access'`); await normal.wait(`document.querySelector('h1')?.textContent==='机构访问指南'`);
    await normal.check(`access-${theme}`); await normal.shot(`access-${theme}`);
    // Save via the real form / IndexedDB, then verify both reminder surfaces.
    await normal.evaluate(`(() => { const date=new Date(); const paired=new Date(Date.UTC(date.getFullYear(),date.getMonth(),date.getDate())-56*86400000).toISOString().slice(0,10); const form=document.querySelector('#wiley form'); const d=form.querySelector('[type=date]'); const n=form.querySelector('[type=number]'); d.value=paired; d.dispatchEvent(new Event('input',{bubbles:true})); n.value='60'; n.dispatchEvent(new Event('input',{bubbles:true})); })()`);
    await normal.wait(`!document.querySelector('#wiley [type=submit]').disabled`);
    await normal.evaluate(`document.querySelector('#wiley [type=submit]').click()`);
    await normal.wait(`document.body.innerText.includes('配对日期与有效天数已保存')`);
    await normal.evaluate(`document.querySelector('[aria-label="关闭提示"]').click(); location.hash='feed'`);
    await normal.wait(`document.querySelector('.access-reminder')`);
    assert.ok(await normal.evaluate(`document.querySelector('.access-reminder').textContent.includes('4 天后到期')`));
    await normal.evaluate(`var select=document.querySelector('.filter-row select'); select.value=''; select.dispatchEvent(new Event('change',{bubbles:true}));`);
    await normal.wait(`document.querySelector('.abstract.preview')`);
    const reminderMetrics = await normal.evaluate(`({bottom:document.querySelector('.paper').getBoundingClientRect().bottom, tab:document.querySelector('.tabs').getBoundingClientRect().top, reminderHeight:document.querySelector('.access-reminder').getBoundingClientRect().height,title:document.querySelector('.paper h2').textContent})`);
    assert.ok(reminderMetrics.bottom <= reminderMetrics.tab, JSON.stringify(reminderMetrics));
    await normal.check(`reminder-${theme}`); await normal.shot(`reminder-${theme}`);
    await normal.evaluate(`location.hash='settings'`); await normal.wait(`document.querySelector('h1')?.textContent==='设置'`);
    assert.ok(await normal.evaluate(`!!document.querySelector('.access-reminder')`));
    await normal.shot(`reminder-settings-${theme}`);
    await normal.evaluate(`document.querySelector('[type=checkbox]').click()`);
    await normal.evaluate(`location.hash='feed'`); await normal.wait(`document.querySelector('.paper')`);
    assert.equal(await normal.evaluate(`!!document.querySelector('.safari-link')`),false);
    // Reset preference and record for the next theme, using UI actions only.
    await normal.evaluate(`location.hash='settings'`); await normal.wait(`document.querySelector('[type=checkbox]')`);
    await normal.evaluate(`document.querySelector('[type=checkbox]').click(); location.hash='access'`);
    await normal.wait(`document.querySelector('#wiley form')`);
    await normal.evaluate(`document.querySelector('#wiley [type=button]').click()`);
    await normal.wait(`document.body.innerText.includes('提醒记录已删除')`);
    await normal.evaluate(`document.querySelector('[aria-label="关闭提示"]').click(); location.hash='feed'`);
    await normal.wait(`document.querySelector('.filter-row select')`);
    await normal.evaluate(`var select=document.querySelector('.filter-row select'); select.value=''; select.dispatchEvent(new Event('change',{bubbles:true}));`);
    await normal.wait(`document.querySelector('.abstract.preview')`);
  }
  for (const width of [320,360,390,430]) {
    await normal.size(width);
    for (const tab of ['feed','access','settings']) {
      await normal.evaluate(`location.hash=${JSON.stringify(tab)}`);
      await normal.wait(`document.querySelector('h1')?.textContent===${JSON.stringify({feed:'文献信息流',access:'机构访问指南',settings:'设置'}[tab])}`);
      await normal.check(`${tab}-${width}`);
    }
  }
  assert.equal(normal.events.filter(e=>e.method==='Runtime.exceptionThrown').length,0);
  await normal.close();
  await writeFile(`${output}/checks.json`, JSON.stringify(results,null,2));
  console.log(`M6 browser checks passed; screenshots: ${output}`);
} finally {browser.close();}
