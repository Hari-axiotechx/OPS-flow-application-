// Professional streaming speech-to-text (Deepgram) that looks like the browser's SpeechRecognition,
// so the engine can use either one. Used for COMMANDS; the wake word "Hello Ops" is still detected by the
// browser's free recognizer, so audio is only sent to the cloud AFTER you say "Hello Ops" (or press the mic).
//
// SPEED
//   * the connection is opened and primed BEFORE you speak, so words are sent with no connect delay
//   * audio is streamed in 100 ms pieces; words appear while you are still talking
// CLARITY
//   * echo cancellation + noise suppression + auto gain on the microphone
//   * the server tells the recognizer your application names and key words (keyterm)
// SAFETY
//   * if anything fails, the engine falls back to the browser recognizer automatically
import { voiceService } from '../api/voiceService';

const MIME = 'audio/webm;codecs=opus';
const SUPPORTED =
  typeof window !== 'undefined' &&
  typeof WebSocket !== 'undefined' &&
  typeof MediaRecorder !== 'undefined' &&
  !!navigator.mediaDevices?.getUserMedia &&
  !!MediaRecorder.isTypeSupported?.(MIME);

let cfg = null; // { enabled, token, url, exp }
let stream = null;
let primed = null; // an open (or opening) socket waiting for the next command
let offUntil = 0; // after a failure, use the browser recognizer for a while

export const sttAvailable = () => SUPPORTED && Date.now() > offUntil && cfg?.enabled !== false;
export const wakeCloud = () => !!cfg?.wake;
export const markSttBad = (ms = 60000) => {
  offUntil = Date.now() + ms;
};

async function getConfig() {
  if (cfg && cfg.exp > Date.now()) return cfg;
  let res = null;
  try {
    res = await voiceService.sttToken();
  } catch {
    res = null;
  }
  cfg = res?.enabled
    ? { enabled: true, wake: !!res.wake, token: res.token, url: res.url, exp: Date.now() + Math.max(30, (res.expires_in || 600) - 60) * 1000 }
    : { enabled: false, exp: Date.now() + 5 * 60 * 1000 };
  return cfg;
}

// Make quiet speech louder before it is sent: gain + a compressor so loud words do not distort.
const MIC_GAIN = 4; // quiet / far voices: x4 (the compressor keeps loud words from distorting)
function boost(raw) {
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return raw;
    const ac = new AC();
    const src = ac.createMediaStreamSource(raw);
    const gain = ac.createGain();
    gain.gain.value = MIC_GAIN;
    const comp = ac.createDynamicsCompressor();
    comp.threshold.value = -24;
    comp.ratio.value = 4;
    comp.attack.value = 0.003;
    comp.release.value = 0.15;
    const dest = ac.createMediaStreamDestination();
    src.connect(gain);
    gain.connect(comp);
    comp.connect(dest);
    if (ac.state === 'suspended') ac.resume().catch(() => {});
    return dest.stream;
  } catch {
    return raw;
  }
}

let rawStream = null;
async function getStream() {
  if (stream && rawStream && rawStream.getAudioTracks().some((t) => t.readyState === 'live')) return stream;
  rawStream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  stream = boost(rawStream);
  return stream;
}

// One socket = one command. It is opened early and kept alive until it is used.
function openSocket(c) {
  const ws = new WebSocket(c.url, ['bearer', c.token]);
  const sock = { ws, open: false, queue: [], keep: null, onmessage: null, onclose: null, dead: false };
  ws.onopen = () => {
    sock.open = true;
    sock.queue.splice(0).forEach((b) => ws.send(b));
    sock.keep = setInterval(() => {
      if (ws.readyState === 1 && !sock.streaming) ws.send(JSON.stringify({ type: 'KeepAlive' }));
    }, 4000);
  };
  ws.onmessage = (e) => sock.onmessage?.(e.data);
  ws.onclose = () => {
    sock.dead = true;
    clearInterval(sock.keep);
    if (primed === sock) primed = null;
    sock.onclose?.();
  };
  ws.onerror = () => {};
  sock.send = (blob) => {
    sock.streaming = true;
    if (sock.open) ws.send(blob);
    else sock.queue.push(blob);
  };
  sock.close = () => {
    sock.dead = true;
    clearInterval(sock.keep);
    try {
      if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'CloseStream' }));
      ws.close();
    } catch {
      /* ignore */
    }
  };
  return sock;
}

// Get everything ready for the next command: token, microphone, and an open socket. Safe to call often.
export async function primeStt() {
  if (!sttAvailable()) return;
  try {
    const c = await getConfig();
    if (!c.enabled) return;
    await getStream();
    if (!primed || primed.dead) primed = openSocket(c);
  } catch {
    /* microphone denied or offline: the engine will use the browser recognizer */
  }
}

const result = (text, isFinal) => Object.assign([{ transcript: text, confidence: 1 }], { isFinal });

// Same shape as window.SpeechRecognition: start(), abort(), onstart, onresult, onerror.
export class DeepgramRecognition {
  constructor() {
    this.finals = [];
    this.interim = '';
    this.dead = false;
    this.sock = null;
    this.recorder = null;
  }

  start() {
    this.begin();
  }

  async begin() {
    try {
      const c = await getConfig();
      if (!c.enabled) throw new Error('stt disabled');
      const s = await getStream();
      if (this.dead) return;
      // a 'wake' session (always listening for "Hello Ops") gets its own socket; commands re-use the primed one
      const sock = this.kind !== 'wake' && primed && !primed.dead ? primed : openSocket(c);
      if (primed === sock) primed = null;
      this.sock = sock;
      sock.onmessage = (d) => this.onMessage(d);
      sock.onclose = () => {
        if (this.dead) return;
        if (this.kind === 'wake') {
          this.cleanup();
          this.onend?.(); // the engine simply starts a new wake session
        } else this.fail();
      };
      const rec = new MediaRecorder(s, { mimeType: MIME, audioBitsPerSecond: 32000 });
      rec.ondataavailable = (e) => {
        if (e.data && e.data.size) sock.send(e.data);
      };
      this.recorder = rec;
      rec.start(100); // a chunk every 100 ms
      this.onstart?.();
    } catch {
      this.fail();
    }
  }

  onMessage(raw) {
    let m;
    try {
      m = JSON.parse(raw);
    } catch {
      return;
    }
    if (m.type !== 'Results') return;
    const t = (m.channel?.alternatives?.[0]?.transcript || '').trim();
    if (m.is_final) {
      if (t) this.finals.push(t);
      this.interim = '';
    } else {
      this.interim = t;
    }
    if (this.kind === 'wake' && this.trim !== false && this.finals.length > 4) this.finals.splice(0, this.finals.length - 4);
    const results = this.finals.map((x) => result(x, true));
    if (this.interim) results.push(result(this.interim, false));
    // speechFinal = Deepgram heard you stop talking: the engine can answer straight away
    if (results.length) this.onresult?.({ resultIndex: 0, results, speechFinal: !!m.speech_final });
  }

  fail() {
    if (this.dead) return;
    this.cleanup();
    this.onerror?.({ error: 'dg-fail' });
  }

  cleanup() {
    this.dead = true;
    try {
      if (this.recorder && this.recorder.state !== 'inactive') this.recorder.stop();
    } catch {
      /* ignore */
    }
    this.sock?.close();
  }

  abort() {
    if (this.dead) return;
    this.cleanup();
    if (this.kind !== 'wake') setTimeout(primeStt, 0); // have the next socket ready before the next command
  }

  stop() {
    this.abort();
  }
}
