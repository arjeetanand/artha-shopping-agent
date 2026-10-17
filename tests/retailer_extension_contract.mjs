import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import test from 'node:test';

test('retailer bridge sends allowlisted order fields for each DOM-backed shop', async () => {
  const script = await readFile(new URL('../extension/retailer_bridge.js', import.meta.url), 'utf8');
  const cases = [
    ['amazon', 'https://www.amazon.in/gp/your-account/order-history?orderFilter=year-2026', 'https://www.amazon.in/dp/B000TEST01', '111-1234567-1234567'],
    ['myntra', 'https://www.myntra.com/my/orders', 'https://www.myntra.com/kurta/123/buy', 'MN123456789'],
    ['ajio', 'https://www.ajio.com/my-account/orders', 'https://www.ajio.com/kurta/p/123456789', 'AJIO123456789'],
  ];
  for (const [provider, href, productUrl, orderId] of cases) {
    const posted = [];
    const raw = `Order ID: ${orderId} Order placed on 17 Oct 2026 Delivered Ship to Jane Doe, 123 Private Street, Pune 411001`;
    const product = { href: productUrl, innerText: 'Olive cotton kurta', textContent: 'Olive cotton kurta',
      parentElement: { innerText: 'Olive cotton kurta Size: M Color: Olive ₹1,599.00 Ship to Jane Doe, 123 Private Street' },
      querySelector: () => null };
    const card = { innerText: raw, textContent: raw,
      getAttribute: (name) => name === 'data-order-id' ? orderId : '',
      querySelectorAll: (selector) => selector.includes('href*') ? [product] : [] };
    const document = {
      readyState: 'complete', body: { innerText: raw, scrollHeight: 100 },
      querySelector: () => null,
      querySelectorAll: (selector) => selector.startsWith('[class') || selector.startsWith('.order-card') ? [card] : [],
    };
    let init;
    const context = {
      document, location: { origin: new URL(href).origin, pathname: new URL(href).pathname, href }, URL, Event,
      window: { scrollTo() {}, setTimeout: (fn) => setImmediate(fn) },
      chrome: { runtime: { onMessage: { addListener: (listener) => { init = listener; } }, sendMessage: (message) => posted.push(message) } },
    };
    vm.runInNewContext(script, context);
    init({ type: 'INIT', job_id: 'sync-0123456789abcdef0123456789abcdef', provider, cutoff: '2026-04-17' });
    await new Promise((resolve) => setTimeout(resolve, 20));
    const batch = posted.find((message) => message.type === 'RETAILER_PAGE');
    assert.ok(batch, provider);
    assert.equal(batch.page.orders[0].orderId, orderId);
    assert.equal(batch.page.orders[0].orderDate, '2026-10-17');
    assert.equal(batch.page.orders[0].products[0].name, 'Olive cotton kurta');
    assert.equal(JSON.stringify(batch).includes('Private Street'), false);
    assert.equal(JSON.stringify(batch).includes('411001'), false);
  }
});
