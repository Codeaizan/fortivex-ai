class ShowroomPcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frame = new Int16Array(320);
    this.offset = 0;
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel) return true;
    for (const sample of channel) {
      this.frame[this.offset++] = Math.max(-32768, Math.min(32767, sample * 32768));
      if (this.offset === this.frame.length) {
        this.port.postMessage(this.frame.buffer, [this.frame.buffer]);
        this.frame = new Int16Array(320);
        this.offset = 0;
      }
    }
    return true;
  }
}
registerProcessor("showroom-pcm", ShowroomPcmCapture);

