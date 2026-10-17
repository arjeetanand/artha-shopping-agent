class ArthaPcmRecorder extends AudioWorkletProcessor {
  process(inputs) {
    const channels = inputs[0];
    if (channels?.[0]?.length) {
      const samples = new Float32Array(channels[0].length);
      for (let index = 0; index < samples.length; index += 1) {
        samples[index] = channels.reduce((sum, channel) => sum + channel[index], 0) / channels.length;
      }
      this.port.postMessage(samples, [samples.buffer]);
    }
    return true;
  }
}

registerProcessor('artha-pcm-recorder', ArthaPcmRecorder);
