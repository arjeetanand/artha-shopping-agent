// Use PCM WAV so microphone recordings do not depend on the browser's container/codec.
export function encodeWav(buffer) {
  const samples = Array.from({ length: buffer.numberOfChannels }, (_, channel) => buffer.getChannelData(channel));
  const bytes = new ArrayBuffer(44 + buffer.length * 2);
  const view = new DataView(bytes);
  for (const [offset, text] of [[0, 'RIFF'], [8, 'WAVE'], [12, 'fmt '], [36, 'data']]) {
    for (let index = 0; index < text.length; index += 1) view.setUint8(offset + index, text.charCodeAt(index));
  }
  view.setUint32(4, bytes.byteLength - 8, true);
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, buffer.sampleRate, true);
  view.setUint32(28, buffer.sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  view.setUint32(40, buffer.length * 2, true);
  for (let index = 0; index < buffer.length; index += 1) {
    const mixed = samples.reduce((sum, channel) => sum + channel[index], 0) / samples.length;
    const sample = Math.max(-1, Math.min(1, mixed));
    view.setInt16(44 + index * 2, sample * (sample < 0 ? 32768 : 32767), true);
  }
  return new Blob([bytes], { type: 'audio/wav' });
}
