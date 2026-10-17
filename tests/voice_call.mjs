import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { createServer } from 'vite';

const vite = await createServer({ server: { host: '127.0.0.1', port: 0 } });
await vite.listen();
const browser = await chromium.launch({
  headless: true,
  args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--disable-audio-output'],
  ...(process.env.SHOPPINGHELP_CHROME_PATH ? { executablePath: process.env.SHOPPINGHELP_CHROME_PATH } : { channel: 'chrome' }),
});

try {
  const page = await browser.newPage();
  let refineRequests = 0;
  let lastRefine = null;
  let lastSearch = null;
  let orderRequests = 0;
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
    window.__failNextMicrophone = false;
    window.__microphoneRequests = 0;
    window.__microphoneTracks = [];
    window.__recognitionTracks = [];
    window.__spoken = [];
    window.__holdSpeech = false;
    window.__speechCancels = 0;
    window.__audioPlaybackFailures = 0;
    window.Audio = class {
      constructor(src) { this.src = src; }
      play() {
        window.__audioPlaybackFailures += 1;
        setTimeout(() => { this.onerror?.(); this.onerror?.(); }, 10);
        return Promise.resolve();
      }
      pause() {}
    };
    class Recognition {
      start(track) {
        window.__recognition = this;
        window.__recognitionStarts += 1;
        window.__recognitionTracks.push(track);
        if (window.__failNextRecognitionStart) {
          window.__failNextRecognitionStart = false;
          throw new Error('Recognition restart unavailable');
        }
        queueMicrotask(() => this.onstart?.());
      }
      abort() { this.onend?.(); }
      emit(text) {
        this.onresult?.({ resultIndex: 0, results: [{ 0: { transcript: text }, isFinal: true }] });
        this.onend?.();
      }
      emitInterim(text) {
        this.onresult?.({ resultIndex: 0, results: [{ 0: { transcript: text }, isFinal: false }] });
      }
    }
    window.SpeechRecognition = Recognition;
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: async () => {
        window.__microphoneRequests += 1;
        if (window.__failNextMicrophone) {
          window.__failNextMicrophone = false;
          throw Object.assign(new Error('Blocked by the test'), { name: 'NotAllowedError' });
        }
        const track = { kind: 'audio', readyState: 'live', stop() { this.readyState = 'ended'; } };
        window.__microphoneTracks.push(track);
        return { getTracks: () => [track], getAudioTracks: () => [track] };
      } },
    });
    window.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; } };
    Object.defineProperty(window, 'speechSynthesis', {
      configurable: true,
      value: { cancel() { window.__speechCancels += 1; }, speak(utterance) { window.__spoken.push(utterance.text); if (!window.__holdSpeech) setTimeout(() => utterance.onend?.(), 50); } },
    });
  });
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/agent/search/jobs') lastSearch = route.request().postDataJSON();
    if (path === '/api/orders' && route.request().method() === 'POST') {
      orderRequests += 1;
      return route.fulfill({ json: { order: { id: 'voice-order', status: 'placed' } } });
    }
    if (path === '/api/orders' && holdNextOrder) {
      holdNextOrder = false;
      signalBlockedOrder();
      await new Promise((resolve) => { releaseOrder = resolve; });
    }
    if (path === '/api/voice/speak' && ++speakRequests === 1) {
      return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'Server voice unavailable' }) });
    }
    if (path === '/api/voice/speak' && speakRequests === 2) {
      return route.fulfill({ status: 200, contentType: 'audio/mpeg', body: Buffer.from('unplayable test audio') });
    }
    if (path === '/api/agent/refine') {
      refineRequests += 1;
      lastRefine = route.request().postDataJSON();
    }
    const body = path === '/api/health'
      ? { ok: true, voice: { provider: 'browser', ready: true }, payment: { provider: 'sandbox' }, payment_provider: 'sandbox' }
      : path === '/api/voice/status'
        ? { provider: 'browser', label: 'Local browser voice', configured: true, ready: true }
      : path === '/api/auth/session'
        ? { authenticated: true, user: { id: 'user-test', name: 'Shopper' } }
      : path === '/api/orders'
        ? { orders: [{ id: 'order-1', status: 'shipped', payment_provider: 'sandbox' }] }
      : path === '/api/agent/search/jobs'
          ? { job_id: 'voice-test', status: 'complete', result: emptySearch
            ? { status: 'complete', search_id: 'search-empty', products: [], intent: { category: 'Furniture', decision: { status: 'no_safe_fit', reasons: [], blocking_risks: [], mission_change: 'Try a more specific product.' } }, workflow: [], source: { mode: 'live', research: { completed: 0 } }, summary: {} }
            : { status: 'needs_clarification', search_id: 'search-1', products: [], intent: { category: 'Furniture', clarifications: [{ key: 'budget', question: 'What is your budget?' }, { key: 'location', question: 'Where should this be delivered?' }] }, workflow: [] } }
          : path === '/api/agent/refine'
            ? { status: 'complete', search_id: 'search-2', products: [chair], selected_product_ids: ['chair-1'], intent: { category: 'Furniture', budget: 4000, mission: { budget: 4000 }, decision: { status: 'buy_now', recommended_product_id: 'chair-1', reasons: ['Within budget'] } }, source: { mode: 'sandbox' }, workflow: [], summary: {} }
          : path === '/api/voice/speak'
            ? { provider: 'browser', text: 'What is your budget?' }
            : {};
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.goto(vite.resolvedUrls.local[0]);
  await page.getByRole('button', { name: 'Talk to Artha' }).first().click();
  await page.getByRole('button', { name: 'Start call' }).click();
  await page.waitForFunction(() => window.__recognitionStarts >= 1);
  const shirtBrief = 'so i wanted to buy a white shirt and a white pant';
  await page.evaluate((text) => window.__recognition.emit(text), shirtBrief);
  await page.getByRole('log').getByText(/What is your budget/).waitFor({ timeout: 2000 });
  assert.equal(lastSearch?.text, shirtBrief, 'a desire to buy clothes must start research');
  assert.equal(await page.getByRole('log').getByText(/Where should this be delivered/).count(), 0, 'voice should ask one follow-up question at a time');
  await page.waitForFunction(() => window.__recognitionStarts >= 2);
  const tripBudget = 'so it should be i wanted to go to a go out trip and my budget is two thousand and so i wanted to buy it';
  await page.evaluate((text) => window.__recognition.emit(text), tripBudget);
  await page.getByRole('log').getByText(/Acme Chair now clears the mission/).waitFor();
  assert.equal(lastRefine?.text, tripBudget, 'the budget follow-up must refine the original research');
  assert.equal(lastRefine?.search_id, 'search-1');
  const shortlist = page.getByRole('region', { name: 'Current voice shortlist' });
  await shortlist.getByText('Acme Chair', { exact: true }).waitFor();
  const retailerLink = shortlist.getByRole('link', { name: /View Acme Chair at Store A/ });
  assert.equal(await retailerLink.getAttribute('href'), chair.url);
  assert.equal(await retailerLink.getAttribute('rel'), 'noopener noreferrer');
  await page.waitForFunction(() => window.__recognitionStarts >= 3);
  await page.evaluate((text) => window.__recognition.emit(text), shirtBrief);
  await page.waitForFunction(() => window.__recognitionStarts >= 4);
  assert.equal(orderRequests, 0, 'a shopping description must not order an existing recommendation');
  await page.evaluate(() => window.__recognition.emit('I want it cheaper'));
  await page.waitForFunction(() => window.__recognitionStarts >= 5);
  assert.equal(lastRefine?.text, 'I want it cheaper', 'a cheaper request must refine the researched products');
  assert.equal(lastRefine?.search_id, 'search-2');
  await page.evaluate(() => { window.__holdSpeech = true; window.__recognition.emit('Why did you rank it first?'); });
  const interrupt = page.getByRole('button', { name: 'Interrupt and speak' });
  await interrupt.waitFor();
  const cancelsBefore = await page.evaluate(() => window.__speechCancels);
  await interrupt.click();
  await page.waitForFunction(() => window.__recognitionStarts >= 6);
  assert.ok(await page.evaluate(() => window.__speechCancels) > cancelsBefore, 'interrupting must stop playback before listening');
  await page.evaluate(() => { window.__holdSpeech = false; });
  await page.evaluate(() => window.__recognition.emit('Buy recommended item'));
  await page.getByRole('log').getByText(/Agentic Checkout complete/).waitFor();
  assert.equal(orderRequests, 1, 'an explicit checkout command must still work');
  await page.getByRole('button', { name: 'End call' }).click();
  await page.getByRole('dialog').screenshot({ path: '/tmp/artha-voice-desktop.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  const drawerBounds = await page.getByRole('dialog').boundingBox();
  assert.ok(drawerBounds.width <= 390, 'the voice drawer must fit a mobile screen');
  await page.getByRole('dialog').screenshot({ path: '/tmp/artha-voice-mobile.png' });
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.reload();
  refineRequests = 0;
  speakRequests = 0;
  await page.getByLabel('Purchase plan summary').getByText('Delivery timing to confirm').waitFor();
  assert.equal(await page.getByLabel('Purchase plan summary').getByText('Delivering to Bengaluru').count(), 0);
  const brief = page.getByRole('textbox', { name: 'Shopping brief' });
  await brief.fill('I need');
  await page.evaluate(() => { window.__failNextMicrophone = true; });
  await page.getByRole('button', { name: 'Speak brief' }).click();
  await page.getByText(/Microphone access is blocked/).waitFor();
  assert.equal(await brief.inputValue(), 'I need', 'a denied microphone must leave the typed brief intact');
  await page.getByRole('button', { name: 'Speak brief' }).click();
  await page.waitForFunction(() => window.__recognitionStarts >= 1);
  assert.equal(await page.evaluate(() => window.__recognitionTracks[0] === window.__microphoneTracks[0]), true, 'recognition must use the granted live microphone track');
  await page.evaluate(() => window.__recognition.emitInterim('Find me a chair'));
  await page.waitForFunction(() => document.getElementById('shopping-brief')?.value === 'I need Find me a chair');
  assert.equal(await brief.inputValue(), 'I need Find me a chair');
  await page.evaluate(() => window.__recognition.emit('Find me an office chair'));
  assert.equal(await brief.inputValue(), 'I need Find me an office chair', 'final speech must replace its interim draft instead of duplicating it');
  assert.equal(await page.evaluate(() => window.__microphoneRequests), 2, 'permission denial and retry must each request the microphone');
  await page.waitForFunction(() => window.__microphoneTracks[0]?.readyState === 'ended');
  await page.getByRole('button', { name: 'Talk to Artha' }).first().click();
  await page.getByText('Mic: browser speech recognition · Reply: Local browser voice').waitFor();
  let startsBeforeCall = await page.evaluate(() => window.__recognitionStarts);
  await page.getByRole('button', { name: 'Start call' }).click();
  await page.waitForFunction((previous) => window.__recognitionStarts > previous, startsBeforeCall);
  assert.equal(await page.evaluate(() => window.__recognitionTracks.at(-1) === window.__microphoneTracks.at(-1)), true, 'the call must start recognition with its microphone track');
  await page.evaluate(() => window.__recognition.emit('Find me a chair'));
  await page.waitForFunction(() => window.__microphoneTracks[1]?.readyState === 'ended');
  await page.getByRole('log').getByText('Find me a chair', { exact: true }).waitFor();
  await page.getByRole('log').getByText(/What is your budget/).waitFor();
  await page.waitForFunction(() => window.__spoken.length >= 1);
  await page.waitForFunction(() => window.__recognitionStarts >= 3);
  await page.evaluate(() => window.__recognition.emit('Under four thousand rupees'));
  await page.getByRole('log').getByText('Under four thousand rupees', { exact: true }).waitFor();
  await page.getByRole('log').getByText(/Acme Chair now clears the mission/).waitFor();
  await page.waitForFunction(() => window.__spoken.length >= 2, null, { timeout: 2000 });
  assert.equal(await page.evaluate(() => window.__audioPlaybackFailures), 1, 'a media error after play starts must fall back to browser speech');
  await page.waitForFunction(() => window.__recognitionStarts >= 4);
  await page.evaluate(() => window.__recognition.emit('Why did you rank it first?'));
  await page.getByRole('log').getByText(/leads the checked shortlist/).waitFor();
  assert.equal(refineRequests, 1, 'a question about ranking should use existing evidence');
  await page.waitForFunction(() => window.__recognitionStarts >= 5);
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
    startsBeforeCall = await page.evaluate(() => window.__recognitionStarts);
    await page.getByRole('button', { name: 'Start call' }).click();
    await page.waitForFunction((previous) => window.__recognitionStarts > previous, startsBeforeCall);
    await page.evaluate(() => window.__recognition.emit('Where is my delivery?'));
    await blockedOrder;
    await page.getByRole('button', { name: closeDrawer ? 'Close shopping copilot' : 'End call' }).click();
    await page.waitForFunction(() => window.__microphoneTracks.at(-1)?.readyState === 'ended');
    releaseOrder();
    if (closeDrawer) await page.getByRole('button', { name: 'Talk to Artha' }).first().click();
    await page.getByRole('log').getByText(/latest sandbox order is shipped/).nth(previousAnswers).waitFor();
    await page.waitForTimeout(100);
    assert.equal(speakRequests, requestsBefore, 'ending or closing a call must not play a pending answer');
    assert.equal(await page.evaluate(() => window.__spoken.length), spokenBefore);
  }

  startsBeforeCall = await page.evaluate(() => window.__recognitionStarts);
  await page.getByRole('button', { name: 'Start call' }).click();
  await page.waitForFunction((previous) => window.__recognitionStarts > previous, startsBeforeCall);
  const startsBeforeFailure = await page.evaluate(() => window.__recognitionStarts);
  await page.evaluate(() => {
    window.__failNextRecognitionStart = true;
    window.__recognition.emit('Where is my delivery?');
  });
  await page.waitForFunction((previous) => window.__recognitionStarts > previous, startsBeforeFailure);
  await page.getByRole('button', { name: 'Start call' }).waitFor({ timeout: 2000 });
  assert.equal(await page.evaluate(() => window.__microphoneTracks.at(-1)?.readyState), 'ended', 'a failed recognition start must release its microphone track');

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
  const recordingPage = await browser.newPage({ permissions: ['microphone'] });
  recordingPage.setDefaultTimeout(5000);
  let uploadedRecording;
  let failTranscription = false;
  let holdTranscription = false;
  let releaseTranscription;
  await recordingPage.addInitScript(() => {
    BaseAudioContext.prototype.decodeAudioData = () => Promise.reject(new Error('Unable to decode audio data'));
    window.SpeechRecognition = undefined;
    window.webkitSpeechRecognition = undefined;
    Object.defineProperty(window, 'speechSynthesis', {
      configurable: true,
      value: { cancel() {}, speak(utterance) { setTimeout(() => utterance.onend?.(), 20); } },
    });
  });
  await recordingPage.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/voice/transcribe') {
      uploadedRecording = route.request().postDataJSON();
      if (holdTranscription) {
        await new Promise((resolve) => { releaseTranscription = resolve; });
        return route.fulfill({ status: 200, json: { text: 'Late transcript', provider: 'slng' } }).catch(() => {});
      }
      if (failTranscription) return route.fulfill({ status: 503, json: { error: 'Transcription is temporarily unavailable. Try again.' } });
    }
    const body = path === '/api/voice/status'
      ? { provider: 'slng', label: 'SLNG voice', model: 'aura-2-thalia-en', configured: true, ready: true }
      : path === '/api/voice/transcribe'
        ? { text: 'Find an office chair', provider: 'slng' }
        : path === '/api/voice/speak'
          ? { provider: 'browser' }
          : path === '/api/agent/search/jobs'
            ? { status: 'complete', result: { status: 'needs_clarification', search_id: 'recording-test', products: [], intent: { clarifications: [{ key: 'budget', question: 'What is your budget?' }] }, workflow: [] } }
            : {};
    await route.fulfill({ status: 200, json: body });
  });
  await recordingPage.goto(vite.resolvedUrls.local[0]);
  await recordingPage.getByRole('button', { name: 'Talk to Artha' }).first().click();
  await recordingPage.getByText('Mic: SLNG Nova 3 · Reply: SLNG voice (aura-2-thalia-en)').waitFor();
  await recordingPage.getByRole('button', { name: 'Start call', exact: true }).click();
  await recordingPage.getByText('Listening — speak your question', { exact: true }).waitFor();
  // A real microphone needs time to produce a nonempty recording.
  await recordingPage.waitForTimeout(400);
  await recordingPage.getByRole('button', { name: 'Send voice', exact: true }).first().click();
  await recordingPage.getByRole('log').getByText('Find an office chair', { exact: true }).waitFor();
  assert.ok(uploadedRecording.audio.length > 0, 'Manual send must upload actual recorded audio');
  assert.match(uploadedRecording.content_type, /^audio\//);
  assert.equal(uploadedRecording.content_type, 'audio/wav');
  assert.equal(Buffer.from(uploadedRecording.audio, 'base64').subarray(0, 4).toString(), 'RIFF');
  await recordingPage.getByRole('button', { name: 'End call', exact: true }).click();
  failTranscription = true;
  await recordingPage.getByRole('button', { name: 'Start call', exact: true }).click();
  await recordingPage.getByText('Listening — speak your question', { exact: true }).waitFor();
  await recordingPage.waitForTimeout(400);
  await recordingPage.getByRole('button', { name: 'Send voice', exact: true }).first().click();
  await recordingPage.getByRole('dialog').getByRole('alert').getByText('Transcription is temporarily unavailable. Try again.').waitFor({ timeout: 2000 });
  await recordingPage.getByRole('button', { name: 'Start call', exact: true }).waitFor();
  await recordingPage.getByRole('button', { name: 'Start call', exact: true }).click();
  await recordingPage.getByText('Listening — speak your question', { exact: true }).waitFor();
  await recordingPage.getByRole('button', { name: 'Close shopping copilot' }).click();
  assert.equal(await recordingPage.getByRole('dialog').count(), 0, 'Closing the call must cancel recording');
  failTranscription = false;
  await recordingPage.reload();
  await recordingPage.getByRole('button', { name: 'Talk to Artha' }).first().click();
  await recordingPage.getByRole('button', { name: 'Use voice input', exact: true }).click();
  await recordingPage.getByText('Listening — speak your question', { exact: true }).waitFor();
  await recordingPage.waitForTimeout(400);
  await recordingPage.getByRole('button', { name: 'Send voice', exact: true }).click();
  await recordingPage.getByRole('log').getByText('Find an office chair', { exact: true }).waitFor({ timeout: 2000 });
  await recordingPage.getByRole('log').getByText(/What is your budget/).waitFor();
  holdTranscription = true;
  await recordingPage.getByRole('button', { name: 'Use voice input', exact: true }).click();
  await recordingPage.getByText('Listening — speak your question', { exact: true }).waitFor();
  await recordingPage.waitForTimeout(400);
  await recordingPage.clock.install();
  const pendingRecording = recordingPage.waitForRequest('**/api/voice/transcribe');
  await recordingPage.getByRole('button', { name: 'Send voice', exact: true }).click();
  await pendingRecording;
  await recordingPage.clock.fastForward(40_001);
  await recordingPage.getByRole('alert').getByText(/Transcription timed out/).waitFor();
  await recordingPage.getByRole('button', { name: 'Use voice input', exact: true }).waitFor();
  assert.equal(await recordingPage.getByText('Transcribing your voice with SLNG…').count(), 0, 'A timed-out recording must leave the transcribing state');
  releaseTranscription();
  await recordingPage.close();
  console.log('voice_call_ok: browser fallback, real recording/manual send, transcription failure and cancellation');
} finally {
  await browser.close();
  await vite.close();
}
