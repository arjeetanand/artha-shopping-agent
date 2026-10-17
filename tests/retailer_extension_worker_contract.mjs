import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import test from 'node:test';

test('extension worker follows Amazon year and page links, then forwards one complete batch', async () => {
  const manifest = JSON.parse(await readFile(new URL('../extension/manifest.json', import.meta.url), 'utf8'));
  const script = await readFile(new URL('../extension/service_worker.js', import.meta.url), 'utf8');
  let onMessage, onUpdated;
  let storage = {};
  let currentUrl = '';
  const portalMessages = [];
  const chrome = {
    runtime: { getManifest: () => manifest, onMessage: { addListener: (listener) => { onMessage = listener; } } },
    storage: { session: { get: async () => storage, set: async (value) => { storage = { ...storage, ...value }; } } },
    tabs: {
      create: async () => ({ id: 99 }),
      update: async (_id, details) => { currentUrl = details.url; },
      sendMessage: async (_id, message) => { portalMessages.push(message); },
      remove: async () => {},
      onUpdated: { addListener: (listener) => { onUpdated = listener; } },
      onRemoved: { addListener: () => {} },
    },
  };
  vm.runInNewContext(script, { chrome, URL, TextEncoder, Intl, Date, setTimeout, clearTimeout });
  const jobId = 'sync-0123456789abcdef0123456789abcdef';
  let started;
  const accepted = onMessage({ type: 'START', job_id: jobId, provider: 'amazon', cutoff: '2025-10-17' },
    { url: 'http://127.0.0.1:5176/taste-graph', tab: { id: 7 } }, (value) => { started = value; });
  assert.equal(accepted, true);
  for (let i = 0; i < 30 && !started; i += 1) await new Promise((resolve) => setImmediate(resolve));
  assert.equal(JSON.stringify(started), JSON.stringify({ ok: true, started: true }));
  assert.match(currentUrl, /orderFilter=year-2026/);

  const submitPage = async (url, next_url = '') => {
    await onUpdated(99, { status: 'complete' }, { url });
    await onMessage({ type: 'RETAILER_PAGE', provider: 'amazon', job_id: jobId, page: {
      url, next_url, orders: [{ orderId: url.includes('year-2025') ? 'old-order' : 'recent-order', orderDate: '2026-05-01' }], empty: false,
    } }, { url, tab: { id: 99 } }, () => {});
    for (let i = 0; i < 30 && currentUrl === url; i += 1) await new Promise((resolve) => setImmediate(resolve));
  };

  const first = currentUrl;
  const second = 'https://www.amazon.in/gp/your-account/order-history?orderFilter=year-2026&page=2';
  const third = 'https://www.amazon.in/gp/your-account/order-history?orderFilter=year-2025';
  await submitPage(first, second);
  assert.equal(currentUrl, second);
  await submitPage(second);
  assert.equal(currentUrl, third);
  await submitPage(third);

  const complete = portalMessages.filter((message) => message.type === 'COMPLETE_BATCH');
  assert.equal(complete.length, 1);
  assert.equal(complete[0].provider, 'amazon');
  assert.equal(complete[0].stop_reason, 'history_end');
  assert.equal(complete[0].pages.length, 3);
  assert.equal(complete[0].pages[0].url, first);
});
