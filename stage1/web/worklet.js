// Mic -> 16 kHz mono int16, posted in 100 ms blocks. Runs on the audio thread.
// We ask the AudioContext for 16 kHz, so `ratio` is normally 1 and the browser has already done a
// proper resample. If a browser ignores that request, we box-average down ourselves (cheap anti-alias).
class PCM16 extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.target = (options.processorOptions && options.processorOptions.targetRate) || 16000;
    this.ratio = sampleRate / this.target;
    this.block = this.target / 10;            // 100 ms
    this.out = new Int16Array(this.block);
    this.n = 0;
    this.acc = 0; this.cnt = 0; this.pos = 0; // decimator state
  }
  push(s) {
    s = Math.max(-1, Math.min(1, s));
    this.out[this.n++] = s < 0 ? s * 32768 : s * 32767;
    if (this.n === this.block) {
      this.port.postMessage(this.out.buffer, [this.out.buffer]);
      this.out = new Int16Array(this.block);
      this.n = 0;
    }
  }
  process(inputs) {
    const x = inputs[0] && inputs[0][0];
    if (!x) return true;
    if (this.ratio === 1) { for (let i = 0; i < x.length; i++) this.push(x[i]); return true; }
    for (let i = 0; i < x.length; i++) {
      this.acc += x[i]; this.cnt++; this.pos += 1;
      if (this.pos >= this.ratio) { this.push(this.acc / this.cnt); this.acc = 0; this.cnt = 0; this.pos -= this.ratio; }
    }
    return true;
  }
}
registerProcessor("pcm16", PCM16);
