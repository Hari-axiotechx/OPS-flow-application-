// Browser speech helpers: text-to-speech with a WOMAN's voice, a short "I'm listening"
// chime, and detection of speech recognition support (Chrome / Edge / Safari; not Firefox).
//
// SPEED: the voice is picked once and cached, speech starts immediately (the old
// fixed 60 ms delay is only used when something else was still speaking), and the
// speaking rate is a little faster.

export const SpeechRecognitionCtor =
  typeof window !== 'undefined' ? window.SpeechRecognition || window.webkitSpeechRecognition : undefined;

export const hasSynthesis = () => typeof window !== 'undefined' && 'speechSynthesis' in window;

export const SPEECH_RATE = 1.18; // 1.0 = normal. A bit faster feels snappier but stays clear.

// Known female voices on Windows / Edge ("Neerja", "Heera" are Indian English),
// macOS / iOS, Android and Chrome.
const FEMALE =
  /(neerja|heera|veena|priya|kalpana|swara|raveena|lekha|zira|aria|jenny|sonia|libby|natasha|hazel|susan|samantha|karen|moira|tessa|fiona|catherine|serena|google uk english female|google us english|female|woman)/i;
const MALE =
  /(\bmale\b|ravi|hemant|prabhat|rishi|david|mark|james|george|daniel|alex|fred|guy|ryan|thomas|oliver|christopher|eric|brian|liam|aaron|matthew)/i;

let voices = [];
let cachedVoice; // undefined = not picked yet, null = none available
function refreshVoices() {
  if (!hasSynthesis()) return;
  voices = window.speechSynthesis.getVoices() || [];
  cachedVoice = undefined;
}
if (hasSynthesis()) {
  refreshVoices();
  window.speechSynthesis.addEventListener?.('voiceschanged', refreshVoices);
}

export function pickFemaleVoice() {
  if (cachedVoice !== undefined && voices.length) return cachedVoice;
  if (!voices.length) refreshVoices();
  let best = null;
  let bestScore = 0;
  for (const v of voices) {
    let score = 0;
    if (/^en[-_]IN/i.test(v.lang)) score += 4;
    else if (/^en[-_](GB|US|AU)/i.test(v.lang)) score += 2;
    else if (/^en/i.test(v.lang)) score += 1;
    else continue; // English only
    if (FEMALE.test(v.name)) score += 10;
    else if (MALE.test(v.name)) score -= 10;
    if (/natural|online/i.test(v.name)) score += 1;
    // local voices start instantly; online ones wait for the network first
    if (v.localService) score += 2;
    if (score > bestScore) {
      best = v;
      bestScore = score;
    }
  }
  if (voices.length) cachedVoice = best;
  return best;
}

let current = null;

export function cancelSpeech() {
  if (!hasSynthesis()) return;
  try {
    window.speechSynthesis.cancel();
  } catch {
    /* ignore */
  }
  current?.();
}

// Long answers are only READ ALOUD in part (the panel still shows everything): faster to hear, faster to continue.
export function shortenForSpeech(text, max = 230) {
  const t = String(text || '');
  if (t.length <= max) return t;
  const cut = t.slice(0, max);
  const end = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('? '), cut.lastIndexOf('! '));
  return end > 60 ? cut.slice(0, end + 1) : cut.replace(/\s+\S*$/, '') + '.';
}

// Speaks `text` and resolves when finished (or when speech is unavailable / cancelled).
export function speak(text, { full = false } = {}) {
  return new Promise((resolve) => {
    if (!hasSynthesis() || !text) return resolve();
    const synth = window.speechSynthesis;
    let done = false;
    let timer;
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      if (current === finish) current = null;
      resolve();
    };
    current = finish;
    const busy = synth.speaking || synth.pending;
    if (busy) {
      try {
        synth.cancel();
      } catch {
        /* ignore */
      }
    }
    const go = () => {
      if (done) return;
      const u = new SpeechSynthesisUtterance(full ? String(text) : shortenForSpeech(text));
      const v = pickFemaleVoice();
      if (v) {
        u.voice = v;
        u.lang = v.lang;
        u.pitch = 1.05;
      } else {
        u.lang = 'en-IN';
        u.pitch = 1.25; // no known female voice installed: raise the pitch
      }
      u.rate = SPEECH_RATE;
      u.onend = finish;
      u.onerror = finish;
      // Some browsers never fire onend for long text; do not hang the assistant.
      timer = setTimeout(finish, Math.max(2000, String(text).length * 95) + 1500);
      synth.speak(u);
    };
    // Chrome drops a speak() that comes straight after cancel(): only then wait a moment.
    if (busy) setTimeout(go, 50);
    else go();
  });
}

/* ---------------- "I'm listening" chime (instant feedback, no speech needed) ---------------- */

let audioCtx = null;
function ctx() {
  if (typeof window === 'undefined') return null;
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return null;
  if (!audioCtx) {
    try {
      audioCtx = new AC();
    } catch {
      return null;
    }
  }
  if (audioCtx.state === 'suspended') audioCtx.resume().catch(() => {});
  return audioCtx;
}

// Unlock audio on the first click / key so the chime can play later from "Hello Ops".
if (typeof window !== 'undefined') {
  const unlock = () => {
    ctx();
    window.removeEventListener('pointerdown', unlock);
    window.removeEventListener('keydown', unlock);
  };
  window.addEventListener('pointerdown', unlock);
  window.addEventListener('keydown', unlock);
}

// Two quick soft notes, ~180 ms in total. kind: 'open' (rising) | 'close' (falling).
export function chime(kind = 'open') {
  const ac = ctx();
  if (!ac) return;
  try {
    const notes = kind === 'open' ? [660, 990] : kind === 'tick' ? [740] : [880, 587];
    const t0 = ac.currentTime + 0.005;
    notes.forEach((f, i) => {
      const o = ac.createOscillator();
      const g = ac.createGain();
      o.type = 'sine';
      o.frequency.value = f;
      const s = t0 + i * 0.085;
      g.gain.setValueAtTime(0.0001, s);
      g.gain.exponentialRampToValueAtTime(0.12, s + 0.012);
      g.gain.exponentialRampToValueAtTime(0.0001, s + 0.09);
      o.connect(g).connect(ac.destination);
      o.start(s);
      o.stop(s + 0.1);
    });
  } catch {
    /* ignore */
  }
}
