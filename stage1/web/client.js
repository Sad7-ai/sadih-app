// Shared صادِح client: mic -> /ws/audio -> live text. One instance = one session, so the floating
// window and the full-screen app are two views of the SAME running session.
// (web/index.html — the playground — still carries its own copy of this logic; it is untouched.)
// The access code, if the server wants one. Remembered so nobody retypes it every session.
window.sadihCode = {
  get() { return new URLSearchParams(location.search).get("code") || localStorage.getItem("sadih.code") || ""; },
  set(c) { try { c ? localStorage.setItem("sadih.code", c) : localStorage.removeItem("sadih.code"); } catch {} },
};

window.SadihClient = class {
  constructor(handlers = {}) {
    this.h = handlers;                 // onState, onInterim, onUnit, onMotion, onMotionError, onStats, onError
    this.state = "idle";               // idle | connecting | live | finishing | error
    this.units = [];
    this.buffer = "";                  // committed words of the clause being built
    this.pending = "";                 // words the recogniser may still change
    this.session = null;
    this.error = "";
    this.ws = this.ctx = this.stream = this.node = null;
  }

  get busy() { return this.state === "connecting" || this.state === "finishing"; }

  _set(s) { this.state = s; this.h.onState?.(s, this); }

  _fail(msg) {
    this.error = msg;
    this.h.onErrorCode?.(this.errorCode || "", msg);
    this._teardown();
    this._set("error");
    this.h.onError?.(msg);
  }

  _teardown() {
    try { this.node?.disconnect(); } catch {}
    this.stream?.getTracks().forEach(t => t.stop());
    if (this.ctx && this.ctx.state !== "closed") this.ctx.close();
    this.node = this.stream = this.ctx = null;
  }

  async start() {
    if (this.state === "live" || this.busy) return;
    this.units = []; this.buffer = this.pending = ""; this.error = "";
    this._set("connecting");

    // mic first, socket second — the recogniser's idle timer starts the moment we connect
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: true },
      });
    } catch (e) {
      return this._fail("المايكروفون ممنوع. اسمح للمتصفح باستخدامه وحاول مرة ثانية.");
    }
    try {
      this.ctx = new AudioContext({ sampleRate: 16000 });
      await this.ctx.audioWorklet.addModule("/static/worklet.js");
    } catch (e) {
      return this._fail("ما قدرنا نشغّل الصوت: " + e.message);
    }

    const proto = location.protocol === "https:" ? "wss" : "ws";
    const code = window.sadihCode.get();
    this.ws = new WebSocket(`${proto}://${location.host}/ws/audio` + (code ? "?code=" + encodeURIComponent(code) : ""));
    this.ws.binaryType = "arraybuffer";

    this.ws.onopen = () => {
      const src = this.ctx.createMediaStreamSource(this.stream);
      this.node = new AudioWorkletNode(this.ctx, "pcm16", { processorOptions: { targetRate: 16000 } });
      this.node.port.onmessage = e => { if (this.ws?.readyState === 1) this.ws.send(e.data); };
      const mute = this.ctx.createGain(); mute.gain.value = 0;   // pull the graph without playing the mic back
      src.connect(this.node); this.node.connect(mute); mute.connect(this.ctx.destination);
      this._set("live");
    };
    this.ws.onmessage = e => this._msg(JSON.parse(e.data));
    this.ws.onerror = () => { if (this.state !== "error") this._fail("ما قدرنا نوصل للخادم."); };
    this.ws.onclose = () => {
      this._teardown();
      if (this.state !== "error") this._set("idle");
      this.ws = null;
    };
  }

  stop() {
    if (this.ws?.readyState === 1) this.ws.send(JSON.stringify({ type: "stop" }));
    this._teardown();                   // mic off immediately; socket stays open for the last units
    if (this.state === "live") this._set("finishing");
  }

  toggle() { this.state === "live" ? this.stop() : this.start(); }

  _msg(m) {
    switch (m.type) {
      case "hello":
        this.session = m.session; this.mock = m.mock; break;
      case "interim":
        this.buffer = m.buffer; this.pending = m.pending;
        this.h.onInterim?.(m.buffer, m.pending); break;
      case "unit":
        this.units.push(m); this.buffer = "";
        this.h.onUnit?.(m); break;
      case "motion":                    // an avatar clip for one unit (CONTRACT-MOTION.md)
        this.h.onMotion?.(m); break;
      case "motion_error":              // that clause got no clip; the captions carry on
        this.h.onMotionError?.(m); break;
      case "stats":
        this.pending = ""; this.h.onStats?.(m); break;
      case "error":
        this.errorCode = m.code || "";
        if (m.code === "bad_code") window.sadihCode.set("");   // stop reusing a code the server rejected
        this._fail(m.message); break;
      case "done":
        this.ws?.close(); break;
    }
  }

  // everything said so far, oldest first
  get transcript() { return this.units.map(u => u.text); }
};
