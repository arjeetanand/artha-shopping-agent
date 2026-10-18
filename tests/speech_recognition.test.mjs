import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { createServer } from 'vite';

const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom' });
const { createSpeechRecognition } = await vite.ssrLoadModule('/src/lib/speechRecognition.js');
const { LocalWavRecognition } = await vite.ssrLoadModule('/src/lib/slngRecognition.js');
after(() => vite.close());

test('adapts browser speech results and completion callbacks', () => {
  const previousWindow = globalThis.window;
  class BrowserRecognition {}
  globalThis.window = { SpeechRecognition: BrowserRecognition };
  try {
    let transcript;
    let ended = false;
    const recognition = createSpeechRecognition({
      provider: 'browser',
      onTranscript: (text, isFinal) => { transcript = { text, isFinal }; },
      onEnd: () => { ended = true; },
    });
    recognition.onresult({ resultIndex: 0, results: [{ 0: { transcript: 'linen shirt' }, isFinal: true }] });
    recognition.onend();
    assert.deepEqual(transcript, { text: 'linen shirt', isFinal: true });
    assert.equal(ended, true);
  } finally {
    globalThis.window = previousWindow;
  }
});

test('selects local WAV recording for the Whisper local provider', () => {
  const previousWindow = globalThis.window;
  const previousNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  globalThis.window = { AudioWorkletNode: class {}, AudioContext: class {}, isSecureContext: true };
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { mediaDevices: { getUserMedia: async () => ({}) } } });
  try {
    const transcribeAudio = async () => ({ text: 'shopping brief' });
    const recognition = createSpeechRecognition({ provider: 'whisper_local', transcribeAudio });
    assert.ok(recognition instanceof LocalWavRecognition);
    assert.equal(recognition.transcribeAudio, transcribeAudio);
  } finally {
    globalThis.window = previousWindow;
    if (previousNavigator) Object.defineProperty(globalThis, 'navigator', previousNavigator);
    else delete globalThis.navigator;
  }
});
