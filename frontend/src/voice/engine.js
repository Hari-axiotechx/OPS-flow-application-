import { voiceService } from '../api/voiceService';
import { deploymentService } from '../api/deploymentService';
import { accessService } from '../api/accessService';
import { SpeechRecognitionCtor as SR, speak, cancelSpeech, chime } from './speech';
import { DeepgramRecognition, sttAvailable, primeStt, markSttBad, wakeCloud } from './stt';
import { findWake, normalizeSpeech, pickIndex, localCommand, formEscape, fixSpeech, bestTranscript, YES_RE, NO_RE, DISMISS_RE } from './wake';
import { voiceForms, summarizeForm, snapshotValues, flashChanged, localNowIso } from './voiceForms';

/* =========================================================================
   OPS voice engine (plain JS, no React)
   -------------------------------------------------------------------------
   SPEED (what makes it feel instant)
   * ONE microphone session does both jobs. While waiting for "Hello Ops" the mic
     is already streaming; the moment the wake phrase shows up in the *interim*
     text the panel opens and a short chime plays. Wake phrases do not trigger
     a spoken greeting; a command said in the same breath is processed normally.
   * Our own end-of-speech detection: ~0.45 s after the browser marks the words
     final (longer if the sentence obviously continues: "...deployment", "...to"),
     instead of waiting for the browser's slow end-of-utterance.
   * Simple things never wait for the server: "go to dashboard", "go back",
     "open deployment 123" navigate immediately (the server answer follows).
   * The server's AI connection is warmed up while you are still talking.
   * Faster speech, cached voice, the mic re-opens 0.1 s after speaking.

   SMART
   * Every command is sent with CONTEXT (record on screen, last record talked
     about, results shown) and the last turns of the CONVERSATION, so
     "approve it", "who requested it?", "assign this to Eswar", "and the failed
     ones?" just work. The server answers with rules (instant) or the AI agent.

   FORMS
   * "Create a deployment / access request / AWS issue / application" starts a
     GUIDED FORM conversation: the real form opens, the assistant asks one question
     at a time (voiceForm action), and writes every answer into the visible form.
     The assistant never submits: the user clicks Submit.
   ========================================================================= */

export const LANG = 'en-IN';
// Hands-free is ON by default (the assistant opens when you say "Hello Ops"). The browser shows its own
// mic / recording indicator while the mic is open - that cannot be hidden by a page.
export const HANDS_FREE_KEY = 'opsflow-voice-handsfree-v3';

export const STATUS_SPOKEN = {
  REQUESTED: 'requested',
  APPROVED: 'approved',
  REJECTED: 'rejected',
  IN_PROGRESS: 'in progress',
  COMPLETED_SUCCESS: 'deployed successfully',
  COMPLETED_FAILED: 'marked as failed',
  ROLLED_BACK: 'rolled back',
  ACCESS_GIVEN: 'access given',
};

const KIND_WORD = {
  DEPLOYMENT: 'deployment',
  ACCESS: 'access request',
  AWS_ISSUE: 'AWS issue',
  APPLICATION: 'application',
};

// End-of-speech timing (ms). Tuned for speed; raise them if you get cut off while pausing.
const END_AFTER_FINAL = 400; // browser marked the words final
const END_AFTER_INTERIM = 1000; // words still interim but nothing new arrived
const END_DANGLING = 1600; // sentence obviously continues ("open deployment ...", "assign it to ...")
const LISTEN_WINDOW_MS = 60000; // after "Hello Ops" (and after every answer) keep listening this long
const NO_SPEECH_MS = LISTEN_WINDOW_MS; // nothing said at all for a full minute -> close quietly
const MAX_COMMAND_MS = 20000;
const FORM_SLOWER = 1.4; // answers in a form (URLs, branch names) get more time
const DANGLING_RE = new RegExp(
  [
    '\\b(?:to|the|a|an|of|for|and|or|in|on|with|at|from|by|is|are|my|number|branch|slash|dot|dash|set|change|assign)$',
    // "open deployment ..." / "approve access request ..." - the number is still coming
    '\\b(?:open|show|view|check|approve|reject|start|complete|grant|update|edit|assign|reassign|mark|roll ?back|is|of)\\s+(?:the\\s+)?(?:deployment|access(?: request)?|aws issue|issue|request|record|id)$',
    '^(?:open|show|approve|reject|assign)$',
  ].join('|'),
  'i'
);
const HISTORY_TTL = 5 * 60 * 1000; // forget the conversation after 5 quiet minutes

// After the form is complete these just close the assistant (the form stays open for the user).
const FORM_DISMISS_RE = /^(thanks?( you)?|thank you|bye|goodbye|good bye|that'?s all|that is all|go to sleep|dismiss)\b/;

export function spokenName(item) {
  const n = Number(String(item.id).split('-')[1]);
  return `${KIND_WORD[item.type] || 'record'} ${Number.isNaN(n) ? item.id : n}`;
}

export function friendlyError(e) {
  if (e?.isAuthError) return 'Your session has expired. Please log in again.';
  const m = String(e?.message || '');
  if (!m || /failed to fetch|networkerror|load failed/i.test(m)) return 'Sorry, I could not reach the server.';
  return m;
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const RECORD_IN_PATH = /\/(?:deployments|access|aws-issues)\/((?:DEP|ACC|AWS)-\d+)/i;

/* -------------------------------------------------------------------------
   Engine (created once). It only touches refs / setters, so React re-renders
   never affect it.
   ui = { setPanelOpen, setPhase, setHeard, setReply, setResults, setHints, setMicError, setForm }
   ------------------------------------------------------------------------- */
export function buildEngine(ui, getCtx, initialHandsFree) {
  const S = {
    rec: null,
    mode: null, // 'wake' | 'command' | null
    cmd: null, // the command being heard: { from, text, final, timer, maxTimer, heardAny }
    handsFree: initialHandsFree,
    busy: false, // true while the assistant is speaking / thinking
    convo: false, // a conversation is open
    denied: false, // microphone blocked
    pending: null, // { action, stage: 'reason' | 'confirm', reason }
    carry: null, // unfinished sentence ("approve deployment" + number)
    form: null, // guided form conversation: { kind, flow, done, starting, lastQuestion }
    results: [],
    lastRecordId: null, // the record we last talked about ("approve it")
    history: [], // [{ role: 'user' | 'assistant', text }]
    historyAt: 0,
    navigatedTo: null, // route already opened instantly by a local command
    silence: 0,
    sayId: 0,
    restarts: [],
    startTimer: null,
    closeTimer: null,
    warmedAt: 0,
    listenSince: 0, // when the current listening window started
  };

  /* ---------------- microphone ---------------- */

  function stopRec() {
    clearTimeout(S.startTimer);
    if (S.cmd) {
      clearTimeout(S.cmd.timer);
      clearTimeout(S.cmd.maxTimer);
    }
    S.mode = null;
    const r = S.rec;
    S.rec = null;
    if (r) {
      r.onresult = r.onerror = r.onend = r.onstart = null;
      try {
        r.abort();
      } catch {
        /* ignore */
      }
    }
  }

  function recError(code) {
    if (code === 'not-allowed' || code === 'service-not-allowed') {
      S.denied = true;
      ui.setMicError(
        window.isSecureContext === false
          ? 'The microphone only works on https:// (or localhost). Open the app with https:// and allow the microphone.'
          : 'Microphone access is blocked. Click the lock icon in the address bar, allow the microphone, then press the mic button.'
      );
      ui.setPhase('idle');
    } else if (code === 'audio-capture') {
      S.denied = true;
      ui.setMicError('No microphone was found.');
      ui.setPhase('idle');
    } else if (code === 'network') {
      ui.setMicError('Voice recognition needs an internet connection.');
    }
  }

  // Opens ONE continuous recognition session. mode 'wake' waits for "Hello Ops" and then
  // switches itself to 'command' without restarting; mode 'command' listens right away.
  function openMic(mode) {
    stopRec();
    // Commands are heard by the professional recognizer when it is set up; otherwise by the browser's.
    const useDg = (mode === 'command' || (mode === 'wake' && wakeCloud())) && sttAvailable();
    if ((!SR && !useDg) || S.denied) {
      if (mode === 'command') ui.setPhase('typing');
      return;
    }
    const rec = useDg ? new DeepgramRecognition() : new SR();
    rec.kind = mode;
    ui.setRecName?.(useDg ? 'clear voice engine' : 'browser voice (basic)');
    if (mode === 'wake' && !useDg) {
      // Learn (once) whether the clear voice engine is set up; if it also listens for the wake word, switch to it.
      primeStt().then(() => {
        if (S.rec === rec && S.mode === 'wake' && wakeCloud() && sttAvailable()) openMic('wake');
      });
    }
    rec.lang = LANG;
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 5; // several guesses per sentence: we pick the one that sounds most like a real command
    S.rec = rec;
    S.mode = mode;
    if (mode === 'command') beginCommand(0, '');

    rec.onstart = () => {
      ui.setMicError('');
      if (S.mode === 'wake') ui.setPhase('wake');
    };
    rec.onresult = (e) => {
      if (S.rec !== rec) return;
      if (S.mode === 'wake') return onWakeResult(e);
      if (S.mode === 'command') return onCommandResult(e);
      return undefined;
    };
    rec.onerror = (e) => {
      if (e.error === 'dg-fail') {
        // The professional recognizer failed: use the browser's for a minute and carry on.
        markSttBad();
        console.info('[voice] speech service unavailable, using the browser recognizer');
        if (S.rec === rec && S.mode === 'command') openMic('command');
        return;
      }
      if (['not-allowed', 'service-not-allowed', 'audio-capture', 'network'].includes(e.error)) recError(e.error);
    };
    rec.onend = () => {
      if (S.rec !== rec) return;
      const was = S.mode;
      S.rec = null;
      S.mode = null;
      if (S.denied) {
        if (was === 'command') ui.setPhase('typing');
        return;
      }
      if (was === 'command') {
        finishCommand(); // the browser ended the session: use what we have
        return;
      }
      // The browser ends a listening session every minute or so: start a new one.
      const now = Date.now();
      S.restarts = S.restarts.filter((t) => now - t < 10000);
      S.restarts.push(now);
      startWake(S.restarts.length > 6 ? 4000 : 120);
    };
    try {
      rec.start();
    } catch {
      /* already started */
    }
  }

  /* ---------------- wake word ---------------- */

  function startWake(delay = 150) {
    if (!SR || !S.handsFree || S.convo || S.busy || S.denied || document.hidden || !getCtx().user) return;
    if (S.rec && S.mode === 'wake') return;
    stopRec();
    S.startTimer = setTimeout(() => {
      if (!S.handsFree || S.convo || S.busy || S.denied || S.rec) return;
      openMic('wake');
    }, delay);
  }

  function onWakeResult(e) {
    // SpeechRecognition may finalize "Hey" and "Ops" in separate result
    // entries, so inspect recent entries together instead of only resultIndex.
    const recent = Array.from(e.results || [])
      .slice(-6)
      .map(bestTranscript)
      .join(' ');
    const found = findWake(recent);
    if (found) openConversation(found.remainder);
  }

  /* ---------------- hearing a command (own end-of-speech detection) ---------------- */

  function beginCommand(from, text) {
    if (S.cmd) {
      clearTimeout(S.cmd.timer);
      clearTimeout(S.cmd.maxTimer);
    }
    S.cmd = { from, text: text || '', final: false, timer: null, maxTimer: null, heardAny: !!text };
    S.cmd.maxTimer = setTimeout(finishCommand, MAX_COMMAND_MS);
    ui.setPhase('listening');
    ui.setHeard(text || '');
    scheduleEnd();
  }

  function onCommandResult(e) {
    const C = S.cmd;
    if (!C) return;
    let text = '';
    let final = true;
    for (let i = C.from; i < e.results.length; i++) {
      text += ' ' + bestTranscript(e.results[i]);
      if (!e.results[i].isFinal) final = false;
    }
    text = text.trim();
    const wake = findWake(text);
    if (wake) text = wake.remainder; // "hello ops open deployment 12" -> "open deployment 12"
    if (text !== C.text || final !== C.final) {
      C.text = text;
      C.final = final;
      if (text) C.heardAny = true;
      ui.setHeard(text);
    }
    // The clear voice engine heard you stop talking: answer straight away (not while a sentence is clearly unfinished).
    if (e.speechFinal && final && text.split(' ').length >= 2 && !DANGLING_RE.test(text) && !(S.form && !S.form.starting)) {
      return finishCommand();
    }
    scheduleEnd();
  }

  function scheduleEnd() {
    const C = S.cmd;
    if (!C) return;
    clearTimeout(C.timer);
    const text = C.text.trim();
    let ms;
    if (!text) {
      const left = LISTEN_WINDOW_MS - (Date.now() - (S.listenSince || Date.now()));
      ms = C.heardAny ? 1500 : Math.max(1500, Math.min(NO_SPEECH_MS, left));
    }
    else if (DANGLING_RE.test(text)) ms = END_DANGLING;
    else ms = C.final ? END_AFTER_FINAL : END_AFTER_INTERIM;
    if (text && S.form && !S.form.starting) ms *= FORM_SLOWER;
    C.timer = setTimeout(finishCommand, ms);
  }

  function finishCommand() {
    const C = S.cmd;
    if (!C) return;
    clearTimeout(C.timer);
    clearTimeout(C.maxTimer);
    S.cmd = null;
    const text = C.text.trim();
    stopRec();
    if (text) handleUtterance(text);
    else onSilence();
  }

  function listenCommand() {
    S.busy = false;
    S.listenSince = Date.now();
    if (!S.convo) return startWake();
    openMic('command');
  }

  /* ---------------- speaking ---------------- */

  function say(text, then, opts) {
    const id = ++S.sayId;
    S.busy = true;
    stopRec();
    ui.setReply(text);
    ui.setPhase('speaking');
    primeStt(); // while the assistant talks, get the next listening connection ready
    return speak(text, opts).then(() => {
      if (id !== S.sayId) return; // closed / replaced meanwhile
      // tiny pause so the microphone does not hear the tail of our own voice
      setTimeout(() => {
        if (id !== S.sayId) return;
        S.busy = false;
        (then || afterSpeech)();
      }, 60);
    });
  }

  function afterSpeech() {
    if (S.convo) listenCommand();
    else startWake();
  }

  function onSilence() {
    // Filling a form: repeat the question once, then step back and leave the form open for the user.
    if (S.form && !S.form.starting) {
      if (!S.form.done && S.silence === 0) {
        S.silence = 1;
        return say(S.form.lastQuestion || "I'm listening.", listenCommand);
      }
      ui.setReply('Say “Hello Ops” when you want to continue. The form stays open.');
      return endConversation('', { speakIt: false, delay: 0 });
    }
    // The browser ends a listening session after a few quiet seconds: listen again until the 1-minute window is over.
    if (S.convo && !S.busy && Date.now() - (S.listenSince || 0) < LISTEN_WINDOW_MS - 1500) {
      ui.setPhase('listening');
      return openMic('command');
    }
    // Nothing (more) was said for the whole window: close quietly - no "I didn't catch that" speech to wait through.
    ui.setReply((r) => r || 'Say “Hello Ops” whenever you need me.');
    chime('close');
    endConversation('', { speakIt: false, delay: 1200 });
    return undefined;
  }

  /* ---------------- conversation ---------------- */

  function warm() {
    const now = Date.now();
    if (now - S.warmedAt < 20000) return;
    S.warmedAt = now;
    voiceService.warmup();
  }

  // Open the conversation, greet the user, then listen (or handle speech that
  // followed the wake phrase in the same recognition event).
  function openConversation(initialCommand = '') {
    clearTimeout(S.closeTimer);
    cancelSpeech();
    S.sayId++;
    S.convo = true;
    S.busy = false;
    S.silence = 0;
    S.pending = null;
    S.carry = null;
    if (Date.now() - S.historyAt > HISTORY_TTL) S.history = [];
    S.listenSince = Date.now();
    chime('open');
    warm();
    ui.setPanelOpen(true);
    ui.setResults(null);
    ui.setHints(null);
    ui.setHeard('');
    say(conversationGreeting(), () => {
      if (initialCommand) handleUtterance(initialCommand);
      else listenCommand();
    });
  }

  function conversationGreeting() {
    const q = S.form && !S.form.starting ? S.form.lastQuestion : '';
    const firstName = String(getCtx().user?.name || '').trim().split(/\s+/)[0];
    const greeting = firstName ? `Hi ${firstName}, how can I help you?` : 'Hi, how can I help you?';
    return q ? `${greeting} ${q}` : greeting;
  }

  function activate() {
    stopRec();
    openConversation();
  }

  function endConversation(message, { speakIt = true, delay = 1500 } = {}) {
    S.convo = false;
    S.pending = null;
    S.carry = null;
    const finish = () => {
      S.busy = false;
      clearTimeout(S.closeTimer);
      S.closeTimer = setTimeout(() => {
        if (S.convo) return;
        // while a form is being filled the panel (checklist) stays visible
        if (!S.form) ui.setPanelOpen(false);
        ui.setPhase(S.handsFree ? 'wake' : 'idle');
      }, delay);
      startWake(150);
    };
    if (message && speakIt) say(message, finish);
    else {
      S.sayId++;
      finish();
    }
  }

  function remember(role, text) {
    if (!text) return;
    S.history.push({ role, text: String(text).slice(0, 400) });
    if (S.history.length > 10) S.history = S.history.slice(-10);
    S.historyAt = Date.now();
  }

  function context() {
    const path = window.location.pathname;
    const m = RECORD_IN_PATH.exec(path);
    return {
      route: path,
      recordId: m ? m[1].toUpperCase() : null,
      lastRecordId: S.lastRecordId,
      results: (S.results || []).map((r) => r.id).slice(0, 8),
    };
  }

  async function handleUtterance(raw) {
    stopRec();
    S.busy = true;
    let text = String(raw || '').trim();
    if (!text) return onSilence();
    const wake = findWake(text);
    if (wake) text = wake.remainder;
    ui.setHeard(String(raw).trim());
    if (!text) return listenCommand();

    S.convo = true;
    clearTimeout(S.closeTimer);
    ui.setPanelOpen(true);
    const low = normalizeSpeech(text);

    if (S.form && !S.form.starting) {
      if (S.form.done && FORM_DISMISS_RE.test(low)) {
        return endConversation('Okay. The form is ready for you to review and submit.');
      }
      // Navigation / sleep / logout always win over a form answer: "open profile", "go to dashboard"...
      const esc = formEscape(text, { isDevOps: getCtx().user?.role === 'DevOps' });
      if (esc) return leaveForm(esc);
      return formTurn(fixFormHearing(text));
    }

    if (S.pending) return handlePending(low, text);
    if (DISMISS_RE.test(low)) {
      chime('close');
      return endConversation('Okay.', { delay: 600 });
    }

    text = fixSpeech(text);
    const ctx = getCtx();
    const idx = pickIndex(low, S.results.length);
    if (idx !== null) {
      const item = S.results[idx];
      S.silence = 1;
      S.lastRecordId = item.id;
      ctx.navigate(item.route);
      return say(`Opening ${spokenName(item)}.`, listenCommand);
    }

    if (S.carry) {
      text = `${S.carry} ${text}`;
      S.carry = null;
    }

    // Instant, in-browser commands: no waiting for the server.
    S.navigatedTo = null;
    const local = localCommand(text, { isDevOps: ctx.user?.role === 'DevOps' });
    if (local?.back) {
      remember('user', text);
      ctx.navigate(-1);
      return say(local.speech, listenCommand);
    }
    if (local && !local.record) {
      remember('user', text);
      remember('assistant', local.speech);
      ctx.navigate(local.route);
      return say(local.speech, listenCommand);
    }
    if (local?.record) {
      ctx.navigate(local.route); // open it right now; the server's answer (status etc.) follows
      S.navigatedTo = local.route;
      ui.setReply(`Opening ${local.label}…`);
    }

    ui.setPhase('thinking');
    ui.setHints(null);
    const history = S.history.slice();
    remember('user', text);
    // If the server needs more than ~0.3 s (AI thinking), play a soft tick so there is no dead silence.
    const tickTimer = setTimeout(() => chime('tick'), 300);
    try {
      const t0 = performance.now();
      const res = await voiceService.command(text, { context: context(), history });
      clearTimeout(tickTimer);
      // Open DevTools > Console to see where the time goes: network+server vs. the server's own work.
      console.info(`[voice] heard="${text}" total=${Math.round(performance.now() - t0)}ms server=${res.ms}ms source=${res.source}`);
      return applyResponse(res, text);
    } catch (e) {
      clearTimeout(tickTimer);
      S.silence = 1;
      return say(friendlyError(e), listenCommand);
    }
  }

  function applyResponse(res, spokenText) {
    const ctx = getCtx();
    S.silence = 1;
    S.results = res.results || [];
    if (res.focus) S.lastRecordId = res.focus;
    remember('assistant', res.speech);
    ui.setResults(res.results || null);
    ui.setHints(res.examples || null);
    if (res.intent === 'clarify') S.carry = res.carry || null;

    // "Create a deployment ..." -> open the form and fill it by conversation
    if (res.intent === 'form_start' && res.formKind) return startForm(res.formKind, res.route, spokenText);

    if (res.intent === 'confirm' && res.action) {
      S.pending = { action: res.action, stage: res.action.needsReason ? 'reason' : 'confirm', reason: '' };
      return say(res.action.needsReason ? `Please tell me the reason to ${res.action.label}.` : res.speech, listenCommand);
    }
    if (res.route && res.route !== S.navigatedTo) ctx.navigate(res.route);
    S.navigatedTo = null;
    if (res.intent === 'back') ctx.navigate(-1);
    if (res.intent === 'logout') {
      return say(res.speech, () => {
        closePanel();
        ctx.logout();
      });
    }
    if (res.intent === 'dismiss') return endConversation(res.speech);
    return say(res.speech, listenCommand);
  }

  /* ---------------- guided form filling ---------------- */

  function endForm() {
    S.form = null;
    ui.setForm(null);
  }

  async function startForm(kind, route, spokenText) {
    S.form = { kind, flow: {}, done: false, starting: true, lastQuestion: '' };
    ui.setForm(null);
    ui.setPhase('thinking');
    ui.setReply('Opening the form…');
    getCtx().navigate(route);
    const handlers = await voiceForms.waitFor(kind, 4500);
    if (!S.form || S.form.kind !== kind) return; // cancelled while opening
    if (!handlers) {
      endForm();
      return say("Sorry, I couldn't open that form.", listenCommand);
    }
    handlers.reset(); // always start from a clean form
    await wait(40); // let React apply the reset before we read the form back
    S.form.starting = false;
    return formTurn(spokenText, { start: true });
  }

  // The user asked for something else while a form was open. Close the voice form conversation
  // (the form on screen stays open unless we move to another page, so nothing is lost by accident).
  function leaveForm(esc) {
    const F = S.form;
    const handlers = F && voiceForms.get(F.kind);
    S.silence = 1;
    if (esc.kind === 'sleep') {
      ui.setReply('Say “Hello Ops” or “Hey Ops” when you want to continue. The form stays open.');
      return endConversation('Okay. The form stays open.', { delay: 300 });
    }
    endForm();
    if (esc.kind === 'logout') {
      return say('Logging you out.', () => {
        closePanel();
        getCtx().logout();
      });
    }
    // close the form popup first, then open the page that was asked for
    handlers?.close();
    setTimeout(() => getCtx().navigate(esc.route), 60);
    remember('user', 'navigate');
    return say(esc.speech, listenCommand);
  }

  // Light clean-up of heard form answers (none needed today; kept as one place to add fixes).
  function fixFormHearing(text) {
    return text;
  }

  async function formTurn(text, { start = false } = {}) {
    const F = S.form;
    if (!F) return;
    const handlers = voiceForms.get(F.kind);
    if (!handlers) {
      endForm();
      return endConversation('Okay, the form is closed.');
    }
    ui.setPhase('thinking');
    let res;
    try {
      res = await voiceService.form({
        kind: F.kind,
        text,
        start,
        form: summarizeForm(handlers.getForm()),
        flow: F.flow,
        now: localNowIso(),
      });
    } catch (e) {
      if (S.form !== F) return;
      S.silence = 1;
      return say(friendlyError(e), listenCommand);
    }
    if (S.form !== F) return; // closed meanwhile

    if (res.intent === 'error') {
      endForm();
      return endConversation(res.speech);
    }
    F.flow = res.flow || F.flow;
    F.done = !!res.done;
    F.lastQuestion = F.done ? '' : res.flow?.last_question || F.lastQuestion;
    if (res.progress) ui.setForm(res.progress);

    if (res.intent === 'form_cancel') {
      endForm();
      handlers.close();
      return endConversation(res.speech);
    }
    if (res.patch && Object.keys(res.patch).length) {
      const before = snapshotValues();
      handlers.apply(res.patch);
      flashChanged(before);
    }
    S.silence = F.done ? 1 : 0; // when everything is filled, one quiet moment ends the listening
    return say(res.speech, listenCommand, { full: !!res.review }); // "review" is read out in full
  }

  function onFormEvent(e) {
    const F = S.form;
    if (!F || e.kind !== F.kind || F.starting) return;
    if (e.type === 'submitted') {
      endForm();
      const what =
        F.kind === 'APPLICATION' ? 'The application was added.' : `${spokenName({ type: F.kind, id: e.recordId })} is submitted.`;
      if (e.recordId) S.lastRecordId = e.recordId;
      S.sayId++;
      return endConversation(`Done. ${what}`);
    }
    if (e.type === 'closed') {
      // the user closed or left the form themselves: stop the conversation quietly
      endForm();
      S.sayId++;
      cancelSpeech();
      stopRec();
      S.convo = false;
      S.busy = false;
      ui.setPanelOpen(false);
      ui.setPhase(S.handsFree ? 'wake' : 'idle');
      startWake(150);
    }
  }
  const offFormEvents = voiceForms.subscribe(onFormEvent);

  /* ---------------- yes / no / reason for confirmed actions ---------------- */

  function handlePending(low, raw) {
    const p = S.pending;
    if (p.stage === 'reason') {
      if (/^(cancel|stop|never ?mind|forget it|abort)\b/.test(low)) {
        S.pending = null;
        return say('Okay, cancelled.', listenCommand);
      }
      p.reason = raw;
      p.stage = 'confirm';
      return say(`Okay. Shall I ${p.action.label}, with the reason: ${raw}? Say yes to confirm.`, listenCommand);
    }
    if (YES_RE.test(low)) return executeAction(p);
    if (NO_RE.test(low)) {
      S.pending = null;
      return say('Okay, I cancelled that.', listenCommand);
    }
    // Something else entirely: drop the question and treat it as a new command.
    S.pending = null;
    return handleUtterance(raw);
  }

  async function executeAction(p) {
    ui.setPhase('thinking');
    const a = p.action;
    const { recordType, id, route } = a;
    const ctx = getCtx();
    const name = spokenName({ type: recordType, id });
    const Name = name.charAt(0).toUpperCase() + name.slice(1);
    try {
      let done;
      if (a.kind === 'edit') {
        await deploymentService.updateDetails(id, a.fields || {});
        done = `Done. ${Name} is updated.`;
      } else if (a.kind === 'reassign') {
        await deploymentService.reassign(id, a.newDevOpsId);
        done = `Done. ${a.label.replace(/^assign /, '').replace(/^./, (c) => c.toUpperCase()).replace(' to ', ' is now assigned to ')}.`;
      } else {
        const service = recordType === 'ACCESS' ? accessService : deploymentService;
        await service.updateStatus(id, a.newStatus, p.reason || undefined);
        done = `Done. ${Name} is now ${STATUS_SPOKEN[a.newStatus] || 'updated'}.`;
      }
      S.pending = null;
      S.results = [];
      S.lastRecordId = id;
      ui.setResults(null);
      ctx.toast.success(done.replace(/^Done\. /, ''));
      window.dispatchEvent(new Event('opsflow:data-changed'));
      if (route && window.location.pathname !== route) ctx.navigate(route);
      remember('assistant', done);
      return say(done, listenCommand);
    } catch (e) {
      S.pending = null;
      return say(friendlyError(e), listenCommand);
    }
  }

  /* ---------------- public controls ---------------- */

  function closePanel() {
    S.sayId++;
    cancelSpeech();
    stopRec();
    S.cmd = null;
    clearTimeout(S.closeTimer);
    S.convo = false;
    S.busy = false;
    S.pending = null;
    S.carry = null;
    // The form flow is kept: the form is still open, and "Hello Ops" continues where we stopped.
    ui.setPanelOpen(false);
    ui.setPhase(S.handsFree ? 'wake' : 'idle');
    startWake(150);
  }

  return {
    S,
    startWake,
    stopRec,
    closePanel,
    dispose() {
      offFormEvents();
      S.sayId++;
      cancelSpeech();
      stopRec();
      clearTimeout(S.closeTimer);
    },
    toggle() {
      if (S.convo) return closePanel();
      S.denied = false; // the user may have allowed the microphone since
      ui.setMicError('');
      activate();
      return undefined;
    },
    setHandsFree(on) {
      S.handsFree = on;
      try {
        localStorage.setItem(HANDS_FREE_KEY, on ? 'on' : 'off');
      } catch {
        /* ignore */
      }
      if (on) {
        S.denied = false;
        startWake(50);
      } else {
        if (S.mode === 'wake') stopRec();
        if (!S.convo) ui.setPhase('idle');
      }
    },
    submitTyped(text) {
      S.sayId++;
      cancelSpeech();
      stopRec();
      S.cmd = null;
      S.convo = true;
      handleUtterance(text);
    },
  };
}
