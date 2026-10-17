import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import { encodeWav } from '../src/lib/wav.js';

test('WAV is mono PCM16 at the PCM sample rate, with stereo mixed and peaks clipped', async () => {
  const channels = [new Float32Array([0.5, -0.5, 2, -2, 1]), new Float32Array([0.5, -0.5, 2, -2, -1])];
  const blob = encodeWav({ numberOfChannels: 2, length: 5, sampleRate: 16000, getChannelData: (index) => channels[index] });
  const bytes = await blob.arrayBuffer();
  const view = new DataView(bytes);
  assert.equal(blob.type, 'audio/wav');
  assert.equal(new TextDecoder().decode(bytes.slice(0, 4)), 'RIFF');
  assert.equal(new TextDecoder().decode(bytes.slice(8, 12)), 'WAVE');
  assert.equal(view.getUint32(4, true) + 8, bytes.byteLength);
  assert.equal(view.getUint16(20, true), 1);
  assert.equal(view.getUint16(22, true), 1);
  assert.equal(view.getUint32(24, true), 16000);
  assert.equal(view.getUint32(28, true), 32000);
  assert.equal(view.getUint16(34, true), 16);
  assert.equal(view.getUint32(40, true), 10);
  assert.deepEqual(Array.from({ length: 5 }, (_, index) => view.getInt16(44 + index * 2, true)), [16383, -16384, 32767, -32768, 0]);
});

test('microphone worklet captures raw PCM with stereo mixed and silent output', async () => {
  const captured = [];
  let Recorder;
  runInNewContext(await readFile(new URL('../public/pcm-recorder.js', import.meta.url), 'utf8'), {
    AudioWorkletProcessor: class { constructor() { this.port = { postMessage: (samples) => captured.push(samples) }; } },
    registerProcessor(name, processor) { assert.equal(name, 'artha-pcm-recorder'); Recorder = processor; },
  });
  const recorder = new Recorder();
  const output = new Float32Array(3);
  assert.equal(recorder.process([[new Float32Array([0.2, 0.4, -0.6]), new Float32Array([0.4, 0.2, 0.6])]], [[output]]), true);
  assert.equal(captured.length, 1);
  assert.ok(Math.abs(captured[0][0] - 0.3) < 0.00001);
  assert.ok(Math.abs(captured[0][1] - 0.3) < 0.00001);
  assert.equal(captured[0][2], 0);
  assert.deepEqual(Array.from(output), [0, 0, 0]);
  recorder.process([[]]);
  assert.equal(captured.length, 1, 'Disconnected microphone input must not invent audio frames');
});
