// AudioWorklet: microphone/tab audio -> 16 kHz mono Int16 frames (~100 ms).
//
// C2-SPEC-01 REQ-02: the backend forwards these bytes to Deepgram as
// `linear16` at 16 kHz. The page asks for a 16 kHz AudioContext, so Chrome
// resamples with a proper filter and this processor only converts; if the
// context runs at another rate, it falls back to linear interpolation.
//
// Runs on the audio thread: it reuses its mixing buffer, and each finished
// frame's buffer is transferred (not copied) to the page.

const TARGET_RATE = 16000;
const FRAME_SAMPLES = 1600; // 100 ms at 16 kHz

class PcmFrameProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / TARGET_RATE; // `sampleRate` is a worklet global
    this.position = 0; // fractional read position into the incoming stream
    this.previous = 0; // last input sample, for interpolation across blocks
    this.frame = new Int16Array(FRAME_SAMPLES);
    this.filled = 0;
    this.mono = new Float32Array(128); // one render quantum
  }

  push(sample) {
    const clamped = Math.max(-1, Math.min(1, sample));
    this.frame[this.filled++] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
    if (this.filled === FRAME_SAMPLES) {
      this.port.postMessage(this.frame.buffer, [this.frame.buffer]);
      this.frame = new Int16Array(FRAME_SAMPLES);
      this.filled = 0;
    }
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const length = input[0].length;
    // Mix every channel down to mono.
    if (this.mono.length !== length) this.mono = new Float32Array(length);
    const mono = this.mono;
    mono.fill(0);
    for (const channel of input) {
      for (let i = 0; i < length; i++) mono[i] += channel[i] / input.length;
    }
    if (this.ratio === 1) {
      for (let i = 0; i < length; i++) this.push(mono[i]);
      return true;
    }
    // Linear interpolation between consecutive input samples.
    while (this.position < length) {
      const index = Math.floor(this.position);
      const fraction = this.position - index;
      const before = index === 0 ? this.previous : mono[index - 1];
      const after = mono[index];
      this.push(before + (after - before) * fraction);
      this.position += this.ratio;
    }
    this.position -= length;
    this.previous = mono[length - 1];
    return true;
  }
}

registerProcessor('pcm-frame-processor', PcmFrameProcessor);
