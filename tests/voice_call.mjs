import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { createServer } from 'vite';

const vite = await createServer({ server: { host: '127.0.0.1', port: 0 } });
await vite.listen();
const browser = await chromium.launch({
  headless: true,
  ...(process.env.SHOPPINGHELP_CHROME_PATH ? { executablePath: process.env.SHOPPINGHELP_CHROME_PATH } : { channel: 'chrome' }),
});

try {
  const page = await browser.newPage();
  let refineRequests = 0;
  let lastRefine = null;
  let speakRequests = 0;
  let emptySearch = false;
  let holdNextOrder = false;
  let signalBlockedOrder;
  let releaseOrder;
  const chair = {
    id: 'chair-1', name: 'Acme Chair', seller: 'Store A', brand: 'Acme',
    price: 3000, total_price: 3000, url: 'https://store.example/chair',
    source_kind: 'fixture', reason_tags: ['Within budget'], price_history: { status: 'unknown' },
  };
  await page.addInitScript(() => {
    window.__recognitionStarts = 0;
    window.__failNextRecognitionStart = false;
    window.__spoken = [];
    class Recognition {
      start() {
        window.__recognition = this;
        window.__recognitionStarts += 1;
        if (window.__failNextRecognitionStart) {
          window.__failNextRecognitionStart = false;
          throw new Error('Recognition restart unavailable');
        }
        queueMicrotask(() => this.onstart?.());
      }
      abort() { this.onend?.(); }
      emit(text) {
        this.onresult?.({ results: [[{ transcript: text }]] });
        this.onend?.();
      }
    }
    window.SpeechRecognition = Recognition;
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) },
    });
    window.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; } };
    Object.defineProperty(window, 'speechSynthesis', {
      configurable: true,
      value: { cancel() {}, speak(utterance) { window.__spoken.push(utterance.text); setTimeout(() => utterance.onend?.(), 50); } },
    });
  });
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/orders' && holdNextOrder) {
      holdNextOrder = false;
      signalBlockedOrder();
      await new Promise((resolve) => { releaseOrder = resolve; });
    }
    if (path === '/api/voice/speak' && ++speakRequests === 1) {
      return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'Server voice unavailable' }) });
    }
    if (path === '/api/agent/refine') {
      refineRequests += 1;
      lastRefine = route.request().postDataJSON();
    }
    const body = path === '/api/health'
      ? { ok: true, voice: { provider: 'browser', ready: true }, payment: { provider: 'sandbox' }, payment_provider: 'sandbox' }
      : path === '/api/voice/status'
        ? { provider: 'slng', label: 'SLNG voice', model: 'aura-2-thalia-en', configured: true, ready: true }
      : path === '/api/auth/session'
        ? { authenticated: true, user: { id: 'user-test', name: 'Shopper' } }
      : path === '/api/orders'
        ? { orders: [{ id: 'order-1', status: 'shipped', payment_provider: 'sandbox' }] }
      : path === '/api/agent/search/jobs'
          ? { job_id: 'voice-test', status: 'complete', result: emptySearch
            ? { status: 'complete', search_id: 'search-empty', products: [], intent: { category: 'Furniture', decision: { status: 'no_safe_fit', reasons: [], blocking_risks: [], mission_change: 'Try a more specific product.' } }, workflow: [], source: { mode: 'live', research: { completed: 0 } }, summary: {} }
            : { status: 'needs_clarification', search_id: 'search-1', products: [], intent: { category: 'Furniture', clarifications: [{ key: 'budget', question: 'What is your budget?' }] }, workflow: [] } }
          : path === '/api/agent/refine'
            ? { status: 'complete', search_id: 'search-2', products: [chair], selected_product_ids: ['chair-1'], intent: { category: 'Furniture', budget: 4000, mission: { budget: 4000 }, decision: { status: 'buy_now', recommended_product_id: 'chair-1', reasons: ['Within budget'] } }, source: { mode: 'sandbox' }, workflow: [], summary: {} }
          : path === '/api/voice/speak'
            ? { provider: 'browser', text: 'What is your budget?' }
            : {};
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.goto(vite.resolvedUrls.local[0]);
  await page.getByLabel('Purchase plan summary').getByText('Delivery timing to confirm').waitFor();
  assert.equal(await page.getByLabel('Purchase plan summary').getByText('Delivering to Bengaluru').count(), 0);
  await page.getByRole('button', { name: 'Talk to Artha' }).first().click();
  await page.getByText('Mic: browser speech recognition · Reply: SLNG voice (aura-2-thalia-en)').waitFor();
  await page.getByRole('button', { name: 'Start call' }).click();
  await page.waitForFunction(() => Boolean(window.__recognition));
  await page.evaluate(() => window.__recognition.emit('Find me a chair'));
  await page.getByRole('log').getByText('Find me a chair', { exact: true }).waitFor();
  await page.getByRole('log').getByText(/What is your budget/).waitFor();
  await page.waitForFunction(() => window.__spoken.length >= 1);
  await page.waitForFunction(() => window.__recognitionStarts >= 2);
  await page.evaluate(() => window.__recognition.emit('Under four thousand rupees'));
  await page.getByRole('log').getByText('Under four thousand rupees', { exact: true }).waitFor();
  await page.getByRole('log').getByText(/Acme Chair now clears the mission/).waitFor();
  await page.waitForFunction(() => window.__recognitionStarts >= 3);
  await page.evaluate(() => window.__recognition.emit('Why did you rank it first?'));
  await page.getByRole('log').getByText(/leads the checked shortlist/).waitFor();
  assert.equal(refineRequests, 1, 'a question about ranking should use existing evidence');
  await page.waitForFunction(() => window.__recognitionStarts >= 4);
  await page.evaluate(() => window.__recognition.emit('Where is my delivery?'));
  await page.getByRole('log').getByText(/latest sandbox order is shipped/).waitFor();
  await page.getByRole('button', { name: 'End call' }).click();
  assert.equal(await page.getByRole('button', { name: 'Start call' }).count(), 1);

  for (const closeDrawer of [false, true]) {
    const previousAnswers = await page.getByRole('log').getByText(/latest sandbox order is shipped/).count();
    const spokenBefore = await page.evaluate(() => window.__spoken.length);
    const requestsBefore = speakRequests;
    holdNextOrder = true;
    const blockedOrder = new Promise((resolve) => { signalBlockedOrder = resolve; });
    await page.getByRole('button', { name: 'Start call' }).click();
    await page.evaluate(() => window.__recognition.emit('Where is my delivery?'));
    await blockedOrder;
    await page.getByRole('button', { name: closeDrawer ? 'Close shopping copilot' : 'End call' }).click();
    releaseOrder();
    if (closeDrawer) await page.getByRole('button', { name: 'Talk to Artha' }).first().click();
    await page.getByRole('log').getByText(/latest sandbox order is shipped/).nth(previousAnswers).waitFor();
    await page.waitForTimeout(100);
    assert.equal(speakRequests, requestsBefore, 'ending or closing a call must not play a pending answer');
    assert.equal(await page.evaluate(() => window.__spoken.length), spokenBefore);
  }

  await page.getByRole('button', { name: 'Start call' }).click();
  const startsBeforeFailure = await page.evaluate(() => window.__recognitionStarts);
  await page.evaluate(() => {
    window.__failNextRecognitionStart = true;
    window.__recognition.emit('Where is my delivery?');
  });
  await page.waitForFunction((previous) => window.__recognitionStarts > previous, startsBeforeFailure);
  await page.getByRole('button', { name: 'Start call' }).waitFor({ timeout: 2000 });

  await page.getByRole('button', { name: 'Close shopping copilot' }).click();
  await page.getByLabel('Budget').fill('3500');
  const missionRefinement = page.waitForRequest('**/api/agent/refine');
  await page.getByRole('button', { name: 'Refine shortlist' }).click();
  await missionRefinement;
  assert.equal(lastRefine?.mission?.budget, '3500');
  assert.equal(lastRefine?.search_id, 'search-2');

  emptySearch = true;
  await page.reload();
  await page.getByRole('textbox', { name: 'Shopping brief' }).fill('Find an office chair under ₹4000 in Bengaluru within five days');
  await page.getByRole('button', { name: 'Find sources' }).click();
  await page.getByText('No purchasable product page found.').waitFor();
  assert.equal(await page.getByText('No retailer sources were found for that brief.').count(), 0);
  console.log('voice_call_ok');
} finally {
  await browser.close();
  await vite.close();
}
