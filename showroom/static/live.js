"use strict";

class LiveMicrophone {
  constructor(events) {
    this.events = events;
    this.sources = new Set();
    this.nextAudio = 0;
    this.started = false;
    this.closed = false;
  }

  async start(callId) {
    this.context = new AudioContext({sampleRate: 16000});
    if (this.context.sampleRate !== 16000) throw new Error("This browser could not start 16 kHz microphone capture.");
    await this.context.resume();
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {echoCancellation: true, noiseSuppression: true, channelCount: 1},
    });
    if (this.closed) {
      stream.getTracks().forEach(track => track.stop());
      return;
    }
    this.stream = stream;
    await this.context.audioWorklet.addModule("/static/live-audio.js");
    if (this.closed) return;
    this.capture = new AudioWorkletNode(this.context, "showroom-pcm");
    this.capture.port.onmessage = ({data}) => {
      if (this.started && this.socket.readyState === WebSocket.OPEN && this.socket.bufferedAmount < 64000) {
        this.socket.send(data);
      }
    };
    const url = new URL("/api/calls/" + encodeURIComponent(callId) + "/live", location.href);
    url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
    this.socket = new WebSocket(url);
    this.socket.binaryType = "arraybuffer";
    this.socket.onmessage = ({data}) => this.receive(data);
    this.socket.onclose = () => {
      if (!this.closed) this.events.fail("Gemini Live disconnected. You can continue with the local microphone.");
    };
  }

  receive(data) {
    if (this.closed) return;
    if (data instanceof ArrayBuffer) {
      if (this.events.speak()) this.play(data);
      return;
    }
    const message = JSON.parse(data);
    if (message.error) {
      this.events.fail(message.error);
      return;
    }
    if (message.ready) {
      this.context.createMediaStreamSource(this.stream).connect(this.capture);
      this.capture.connect(this.context.destination);
      this.started = true;
      this.events.ready();
    }
    if (message.interrupted) this.clearAudio();
    if (message.turnDone) this.events.turn(message);
    if (message.status) this.events.status(message.status);
  }

  play(data) {
    const samples = new Int16Array(data);
    if (!samples.length) return;
    const buffer = this.context.createBuffer(1, samples.length, 24000);
    const output = buffer.getChannelData(0);
    for (let index = 0; index < samples.length; index++) output[index] = samples[index] / 32768;
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.context.destination);
    this.sources.add(source);
    source.onended = () => this.sources.delete(source);
    const start = Math.max(this.context.currentTime + 0.025, this.nextAudio);
    source.start(start);
    this.nextAudio = start + buffer.duration;
  }

  clearAudio() {
    for (const source of this.sources) source.stop();
    this.sources.clear();
    this.nextAudio = 0;
  }

  close() {
    this.closed = true;
    this.started = false;
    this.socket?.close();
    this.stream?.getTracks().forEach(track => track.stop());
    this.clearAudio();
    if (this.context && this.context.state !== "closed") void this.context.close();
  }
}

