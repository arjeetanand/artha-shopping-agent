// Live SLNG smoke test: actual recorded audio -> STT -> shopping -> TTS.
// Each microphone turn receives real SLNG-generated audio; speech APIs and search are not mocked.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { createServer as createNetServer } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { chromium } from 'playwright';
import { createServer } from 'vite';

const temporary = await mkdtemp(join(tmpdir(), 'artha-voice-'));
const socket = createNetServer();
await new Promise((resolve) => socket.listen(0, '127.0.0.1', resolve));
const port = socket.address().port;
await new Promise((resolve) => socket.close(resolve));
const api = `http://127.0.0.1:${port}`;
const backend = spawn('.venv/bin/python', ['-u', 'backend/server.py'], {
  env: {
    ...process.env, APP_ENV: 'development', SHOPPINGHELP_HOST: '127.0.0.1',
    SHOPPINGHELP_PORT: String(port), SHOPPINGHELP_DB_PATH: join(temporary, 'test.sqlite3'),
    SHOPPINGHELP_PRIVATE_DIR: temporary, SHOPPINGHELP_SEARCH_MODE: 'fixture',
    VOICE_PROVIDER: 'slng', PAYMENT_PROVIDER: 'sandbox',
  },
  stdio: ['ignore', 'ignore', 'pipe'],
});
let backendErrors = '';
backend.stderr.on('data', (chunk) => { backendErrors += chunk; });
let vite;
let browser;
let page;
try {
  let healthy = false;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (backend.exitCode !== null) throw new Error(`Backend exited: ${backendErrors}`);
    const health = await fetch(`${api}/api/health`).then((r) => r.json()).catch(() => null);
    if (health?.ok) {
      assert.equal(health.voice.provider, 'slng');
      assert.equal(health.voice.configured, true, 'Set SLNG_API_KEY in .env before running this live test');
      healthy = true;
      break;
    }
    await delay(100);
  }
  assert.ok(healthy, 'Backend must start');
  const turns = [
    ['I want to buy an office chair.', /maximum.*spend|budget/i],
    ['My budget is twelve thousand rupees, delivered to Bangalore within five days.', /PosturePro|ErgoForm|DailySeat|Luma/i],
    ['Can anything arrive faster?', /quickest stated delivery/],
  ];
  const samples = [];
  for (const [text] of turns) {
    const sample = await fetch(`${api}/api/voice/speak`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }),
    });
    assert.equal(sample.status, 200, 'SLNG must generate each synthetic microphone sample');
    samples.push(Buffer.from(await sample.arrayBuffer()).toString('base64'));
  }
  vite = await createServer({ server: { host: '127.0.0.1', port: 0, proxy: { '/api': api } } });
  await vite.listen();
  browser = await chromium.launch({
    headless: true,
    ...(process.env.SHOPPINGHELP_CHROME_PATH ? { executablePath: process.env.SHOPPINGHELP_CHROME_PATH } : { channel: 'chrome' }),
    args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--disable-audio-output', '--autoplay-policy=no-user-gesture-required'],
  });
  page = await browser.newPage({ permissions: ['microphone'] });
  page.setDefaultTimeout(60_000);
  const errors = [];
  const audioResponses = [];
  const searches = [];
  const transcripts = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('response', (response) => {
    const path = new URL(response.url()).pathname;
    if (path === '/api/voice/speak') {
      audioResponses.push({ status: response.status(), type: response.headers()['content-type'] });
      console.log('SLNG response:', JSON.stringify(audioResponses.at(-1)));
    }
    if (path === '/api/agent/search/jobs' || path === '/api/agent/refine') searches.push(path);
    if (path === '/api/voice/transcribe') transcripts.push(response.json());
  });
  await page.addInitScript(({ samples }) => {
    window.MediaRecorder = undefined;
    let microphoneTurn = 0;
    navigator.mediaDevices.getUserMedia = async () => {
      const context = new AudioContext();
      const output = context.createMediaStreamDestination();
      const source = context.createBufferSource();
      const sample = samples[microphoneTurn++];
      if (sample) source.buffer = await context.decodeAudioData(Uint8Array.from(atob(sample), (char) => char.charCodeAt(0)).buffer);
      source.connect(output);
      await context.resume();
      if (sample) source.start(context.currentTime + 0.5);
      const track = output.stream.getAudioTracks()[0];
      const stop = track.stop.bind(track);
      track.stop = () => { stop(); if (context.state !== 'closed') void context.close().catch(() => {}); };
      return output.stream;
    };
    window.__audioEnded = 0;
    window.__browserFallbacks = 0;
    window.__audioEvents = [];
    window.SpeechRecognition = undefined;
    window.webkitSpeechRecognition = undefined;
    const play = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () {
      this.playbackRate = 4;
      for (const event of ['playing', 'ended', 'error', 'loadedmetadata']) {
        this.addEventListener(event, () => window.__audioEvents.push({ event, duration: this.duration, error: this.error?.message }));
      }
      this.addEventListener('ended', () => { window.__audioEnded += 1; }, { once: true });
      return play.call(this);
    };
    window.speechSynthesis.speak = () => { window.__browserFallbacks += 1; };
  }, { samples });
  await page.goto(vite.resolvedUrls.local[0]);
  await page.getByRole('button', { name: 'Talk to Artha' }).first().click();
  await page.getByText('Mic: SLNG Nova 3 · Reply: SLNG voice (aura-2-thalia-en)').waitFor();
  await page.getByRole('button', { name: 'Start call', exact: true }).click();
  for (const [index, [, answer]] of turns.entries()) {
    await page.getByRole('log').getByText(answer).last().waitFor();
    await page.waitForFunction((count) => window.__audioEnded > count || window.__browserFallbacks > 0 || window.__audioEvents.some((event) => event.event === 'error'), index);
    assert.equal(await page.evaluate(() => window.__browserFallbacks), 0, 'Every answer must use SLNG audio');
    assert.equal(await page.evaluate(() => window.__audioEnded), index + 1, 'SLNG audio must finish playing');
    console.log(`turn_${index + 1}_ok: product workflow and SLNG playback`);
  }
  await page.getByRole('button', { name: 'End call', exact: true }).click();
  const shortlist = page.getByRole('region', { name: 'Current voice shortlist' });
  assert.ok(await shortlist.getByRole('link', { name: /View .* at/ }).count() > 0, 'Product links must be reachable inside the voice chat');
  assert.ok(searches.includes('/api/agent/search/jobs'), 'Spoken brief must start a backend search');
  assert.equal(transcripts.length, turns.length, 'Every turn must go through the real transcription endpoint');
  const transcript = await transcripts[0];
  assert.match(transcript.text, /chair/i);
  assert.match((await transcripts[1]).text, /thousand|12.?000/i);
  assert.ok(searches.includes('/api/agent/refine'), 'Spoken clarification must resume the original search');
  assert.equal(audioResponses.length, turns.length);
  assert.ok(audioResponses.every((r) => r.status === 200 && r.type === 'audio/wav'), JSON.stringify(audioResponses));
  assert.deepEqual(errors, []);
  await page.screenshot({ path: '/tmp/artha-slng-voice-e2e.png', fullPage: true });
  console.log('voice_live_ok: continuous call, three recorded turns, real SLNG STT/TTS, clarification, recommendation, delivery, and product links');
} catch (error) {
  if (page && !page.isClosed()) console.error(await page.evaluate(() => ({ audio: window.__audioEvents, transcript: document.querySelector('[role=log]')?.innerText })));
  throw error;
} finally {
  await browser?.close();
  await vite?.close();
  backend.kill('SIGTERM');
  if (backend.exitCode === null && backend.signalCode === null) await new Promise((resolve) => backend.once('exit', resolve));
  await rm(temporary, { recursive: true, force: true });
}
