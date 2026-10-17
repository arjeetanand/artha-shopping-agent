import { transcribeAudio } from './api';
import { encodeWav } from './wav';

export function supportsSlngRecording() {
  return typeof window !== 'undefined' && Boolean(window.AudioWorkletNode && window.AudioContext && navigator.mediaDevices?.getUserMedia);
}

// Match the existing recognition callbacks so both microphone controls share one recorder.
export class SlngRecognition {
  async start(track) {
    this.cancelled = false;
    this.controller = new AbortController();
    this.chunks = [];
    this.context = new AudioContext();
    await this.context.audioWorklet.addModule('/pcm-recorder.js');
    if (this.cancelled) { this.cleanup(); return; }
    this.source = this.context.createMediaStreamSource(new MediaStream([track]));
    this.processor = new AudioWorkletNode(this.context, 'artha-pcm-recorder');
    let heardSpeech = false;
    let lastSpeech = performance.now();
    const started = lastSpeech;
    this.processor.port.onmessage = ({ data }) => {
      if (!this.recording || this.cancelled) return;
      this.chunks.push(data);
      const rms = Math.sqrt(data.reduce((sum, sample) => sum + sample * sample, 0) / data.length);
      if (rms > 0.012) { heardSpeech = true; lastSpeech = performance.now(); }
    };
    this.processor.onprocessorerror = () => {
      this.abort();
      this.onerror?.({ message: 'Microphone recording failed. Please try again.' });
    };
    this.source.connect(this.processor);
    // The worklet leaves its output silent, so captured speech is never played back.
    this.processor.connect(this.context.destination);
    await this.context.resume();
    if (this.cancelled) { this.cleanup(); return; }
    this.recording = true;
    this.onstart?.();
    this.timer = window.setInterval(() => {
      const now = performance.now();
      if (!heardSpeech && now - started > 10_000) {
        this.abort();
        this.onerror?.({ message: 'No microphone audio detected. Check your selected microphone and try again.' });
      } else if ((heardSpeech && now - lastSpeech > 1200) || now - started > 30_000) this.stop();
    }, 100);
  }

  stop() {
    if (!this.recording || this.cancelled) return;
    this.recording = false;
    window.clearInterval(this.timer);
    void this.finish();
  }

  async finish() {
    this.onprocessing?.();
    try {
      const length = this.chunks.reduce((sum, chunk) => sum + chunk.length, 0);
      if (!length) throw new Error('No microphone audio was captured. Speak for a moment before sending.');
      const captured = this.context.createBuffer(1, length, this.context.sampleRate);
      let offset = 0;
      for (const chunk of this.chunks) {
        captured.getChannelData(0).set(chunk, offset);
        offset += chunk.length;
      }
      this.chunks = [];
      this.cleanup();
      const renderer = new OfflineAudioContext(1, Math.ceil(captured.duration * 16000), 16000);
      const source = renderer.createBufferSource();
      source.buffer = captured;
      source.connect(renderer.destination);
      source.start();
      const pcm = await renderer.startRendering();
      if (this.cancelled) return;
      const reply = await transcribeAudio(encodeWav(pcm), this.controller.signal);
      if (this.cancelled) return;
      if (!reply.text?.trim()) throw new Error('No speech was detected. Speak closer to the microphone and try again.');
      this.onresult?.({ resultIndex: 0, results: [{ 0: { transcript: reply.text }, isFinal: true }] });
    } catch (error) {
      if (!this.cancelled) this.onerror?.({ message: error.message });
    } finally {
      this.cleanup();
      if (!this.cancelled) this.onend?.();
    }
  }

  abort() {
    this.cancelled = true;
    this.recording = false;
    this.chunks = [];
    this.controller?.abort();
    this.cleanup();
  }

  cleanup() {
    window.clearInterval(this.timer);
    this.source?.disconnect();
    this.processor?.disconnect();
    this.processor?.port.close();
    if (this.context && this.context.state !== 'closed') void this.context.close().catch(() => {});
  }
}
