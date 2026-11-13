// Speaks new notifications aloud (same woman's voice as the OPS assistant).
//
//  * Never talks over the assistant: if the assistant is listening / thinking /
//    speaking, or the browser is already speaking, the announcement waits its turn.
//  * Announcements are queued, so two notifications are read one after the other.
//  * Can be switched on/off from the bell (saved in this browser, default ON).

import { speak, hasSynthesis } from './speech';

const KEY = 'opsflow-speak-notifications';
const MAX_QUEUE = 5;
const MAX_WAIT_MS = 45000; // give up on an announcement that waited this long (it is stale)

let busyProbe = () => false;
const queue = [];
let running = false;

// The voice assistant registers a function that says whether it is busy right now.
export function setBusyProbe(fn) {
  busyProbe = typeof fn === 'function' ? fn : () => false;
}

export function isSpeakEnabled() {
  try {
    return localStorage.getItem(KEY) !== 'off';
  } catch {
    return true;
  }
}

export function setSpeakEnabled(on) {
  try {
    localStorage.setItem(KEY, on ? 'on' : 'off');
  } catch {
    /* ignore */
  }
  if (!on) {
    queue.length = 0;
    if (hasSynthesis()) {
      try {
        window.speechSynthesis.cancel();
      } catch {
        /* ignore */
      }
    }
  }
}

// Make text sound natural: no emoji, "DEP-1000001" -> "DEP 1000001".
export function cleanForSpeech(text) {
  return String(text || '')
    .replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/gu, ' ')
    .replace(/\b([A-Za-z]{2,6})-(\d+)\b/g, '$1 $2')
    .replace(/\s+/g, ' ')
    .trim();
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const isBusy = () =>
  busyProbe() || (hasSynthesis() && (window.speechSynthesis.speaking || window.speechSynthesis.pending));

async function run() {
  if (running) return;
  running = true;
  try {
    while (queue.length) {
      const item = queue.shift();
      let waited = 0;
      while (isBusy() && waited < MAX_WAIT_MS) {
        await sleep(700);
        waited += 700;
      }
      if (!isSpeakEnabled()) continue;
      if (waited >= MAX_WAIT_MS) continue;
      await speak(item, { full: false });
      await sleep(300);
    }
  } finally {
    running = false;
  }
}

export function announce(text) {
  if (!hasSynthesis() || !isSpeakEnabled()) return;
  const t = cleanForSpeech(text);
  if (!t) return;
  if (queue.length >= MAX_QUEUE) queue.shift();
  queue.push(t);
  run();
}
