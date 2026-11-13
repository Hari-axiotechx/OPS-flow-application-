import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useToast } from '../../context/ToastContext';
import { RecordIdBadge, StatusBadge } from '../ui/Badge';
import { SpeechRecognitionCtor as SR } from '../../voice/speech';
import { buildEngine, HANDS_FREE_KEY } from '../../voice/engine';
import { setBusyProbe } from '../../voice/announce';

/* =========================================================================
   OPS voice assistant - React side (provider, mic button, panel).
   The listening / speaking / conversation logic lives in  src/voice/engine.js.

   * Always listening (hands-free, ON by default) for "Hello Ops" or "Hey Ops".
     It greets the signed-in user and handles a command spoken in the same
     breath (for example, "Hello Ops, open deployment 12").
   * Understands follow-ups and "it / this one" (record on screen, last record
     talked about); with an AI key it understands free-form questions too.
   * "Create a deployment / access request / AWS issue" opens the real form and
     fills it by conversation. You watch the fields fill in and click Submit.
   * Speech recognition needs Chrome / Edge, microphone permission, and https://
     (or localhost).
   ========================================================================= */

const DEFAULT_HINTS = [
  'Open deployment 123',
  'Who requested it?',
  'Approve it',
  'Show failed deployments today',
  'Assign deployment 123 to Eswar',
  'Create a deployment request',
  'I need access to S3',
  'What went wrong in prod this week?',
];

/* -------------------------------------------------------------------------
   React wrapper
   ------------------------------------------------------------------------- */

const VoiceContext = createContext({
  supported: false,
  handsFree: false,
  phase: 'idle',
  micError: '',
  setHandsFree() {},
  toggle() {},
});

export const useVoice = () => useContext(VoiceContext);

function readHandsFree() {
  try {
    return localStorage.getItem(HANDS_FREE_KEY) !== 'off'; // default: ON
  } catch {
    return true;
  }
}

export function VoiceAssistantProvider({ children }) {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const toast = useToast();

  const ctxRef = useRef({});
  ctxRef.current = { navigate, user, logout, toast };

  const [panelOpen, setPanelOpen] = useState(false);
  const [phase, setPhase] = useState('idle');
  // Lets the notification announcer wait while the assistant is in a conversation.
  const phaseRef = useRef('idle');
  phaseRef.current = phase;
  useEffect(() => {
    setBusyProbe(() => ['listening', 'thinking', 'speaking', 'typing'].includes(phaseRef.current));
    return () => setBusyProbe(null);
  }, []);
  const [heard, setHeard] = useState('');
  const [reply, setReply] = useState('');
  const [results, setResults] = useState(null);
  const [hints, setHints] = useState(null);
  const [micError, setMicError] = useState('');
  const [recName, setRecName] = useState('');
  const [form, setForm] = useState(null); // checklist of the form being filled by voice
  const [handsFree, setHandsFreeState] = useState(readHandsFree);

  const engine = useMemo(
    () =>
      buildEngine(
        { setPanelOpen, setPhase, setHeard, setReply, setResults, setHints, setMicError, setForm, setRecName },
        () => ctxRef.current,
        handsFree
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  // Start / stop hands-free listening.
  useEffect(() => {
    if (!SR || !user) return undefined;
    engine.setHandsFree(handsFree);
    return undefined;
  }, [engine, handsFree, user]);

  // Pause listening in a hidden tab, resume when it is visible again.
  useEffect(() => {
    function onVisibility() {
      if (document.hidden) {
        if (engine.S.mode === 'wake') engine.stopRec();
      } else {
        engine.startWake(300);
      }
    }
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, [engine]);

  // If the browser refused to start the microphone before any interaction, retry on the first click / key.
  useEffect(() => {
    function retry() {
      const S = engine.S;
      if (SR && S.handsFree && !S.rec && !S.convo && !S.denied) engine.startWake(0);
    }
    window.addEventListener('pointerdown', retry);
    window.addEventListener('keydown', retry);
    return () => {
      window.removeEventListener('pointerdown', retry);
      window.removeEventListener('keydown', retry);
    };
  }, [engine]);

  // Escape closes the assistant (while a form is open, Escape belongs to the form).
  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape' && engine.S.convo && !engine.S.form) engine.closePanel();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [engine]);

  useEffect(() => () => engine.dispose(), [engine]);

  const value = useMemo(
    () => ({
      supported: !!SR,
      handsFree,
      phase,
      micError,
      setHandsFree: (on) => {
        setHandsFreeState(on);
        engine.setHandsFree(on);
      },
      toggle: () => engine.toggle(),
    }),
    [engine, handsFree, phase, micError]
  );

  return (
    <VoiceContext.Provider value={value}>
      {children}
      <VoiceAssistantLauncher />
      {panelOpen && (
        <VoicePanel
          phase={phase}
          heard={heard}
          reply={reply}
          results={results}
          hints={hints}
          form={form}
          micError={micError}
          recName={recName}
          handsFree={handsFree}
          supported={!!SR}
          onClose={() => engine.closePanel()}
          onSubmit={(t) => engine.submitTyped(t)}
          onHandsFree={value.setHandsFree}
          onOpenItem={(item) => navigate(item.route)}
        />
      )}
    </VoiceContext.Provider>
  );
}

/* -------------------------------------------------------------------------
   UI
   ------------------------------------------------------------------------- */

const PHASE_LABEL = {
  idle: 'Ready',
  wake: 'Listening for “Hello Ops” or “Hey Ops”',
  listening: 'Listening…',
  thinking: 'Thinking…',
  speaking: 'Speaking…',
  typing: 'Type a command',
};

function MicIcon({ className = 'w-[18px] h-[18px]' }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0" />
      <line x1="12" y1="18" x2="12" y2="22" />
    </svg>
  );
}

export function VoiceAssistantLauncher() {
  const { toggle, phase, handsFree, supported, micError } = useVoice();
  const [top, setTop] = useState(null);
  const drag = useRef(null);
  const suppressClick = useRef(false);
  const listening = phase === 'listening';
  const title = micError
    ? micError
    : supported
      ? handsFree
        ? 'OPS Assistant — say “Hello Ops” or “Hey Ops”, or click to open'
        : 'OPS Assistant — click to open (hands-free is off)'
      : 'OPS Assistant — type commands (speech needs Chrome or Edge)';

  return (
    <button
      type="button"
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        drag.current = {
          pointerId: event.pointerId,
          startY: event.clientY,
          startTop: bounds.top,
          moved: false,
        };
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={(event) => {
        const activeDrag = drag.current;
        if (!activeDrag || activeDrag.pointerId !== event.pointerId) return;
        const delta = event.clientY - activeDrag.startY;
        if (Math.abs(delta) > 3) activeDrag.moved = true;
        if (!activeDrag.moved) return;
        const minTop = window.innerHeight * 0.3;
        const maxTop = Math.max(minTop, window.innerHeight - event.currentTarget.offsetHeight - 12);
        setTop(Math.min(maxTop, Math.max(minTop, activeDrag.startTop + delta)));
      }}
      onPointerUp={(event) => {
        if (drag.current?.pointerId !== event.pointerId) return;
        suppressClick.current = drag.current.moved;
        drag.current = null;
      }}
      onPointerCancel={() => { drag.current = null; }}
      onClick={() => {
        if (suppressClick.current) {
          suppressClick.current = false;
          return;
        }
        toggle();
      }}
      title={title}
      aria-label="OPS Assistant"
      style={{ top: top === null ? undefined : `${top}px`, bottom: top === null ? '16px' : 'auto' }}
      className={`fixed z-[100] right-3 sm:right-4 w-11 h-11 rounded-full flex items-center justify-center text-white shadow-lg cursor-grab active:cursor-grabbing touch-none select-none ${
        listening
          ? 'bg-danger hover:bg-danger'
          : 'bg-brand-600 hover:bg-brand-700'
      }`}
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="w-6 h-6" aria-hidden="true">
        <path d="M12 3v2" />
        <path d="M8 7h8a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3v-7a3 3 0 0 1 3-3Z" />
        <path d="M3 11v4M21 11v4M9 12h.01M15 12h.01M9 16h6" />
      </svg>
      {supported && handsFree && phase === 'wake' && !micError && (
        <span className="absolute right-0 top-0 w-2.5 h-2.5 rounded-full bg-green-400 ring-2 ring-white" />
      )}
      {micError && <span className="absolute right-0 top-0 w-2.5 h-2.5 rounded-full bg-amber-400 ring-2 ring-white" />}
    </button>
  );
}

// Live checklist of the form being filled by voice.
function FormChecklist({ form }) {
  const pct = form.total ? Math.round((form.filled / form.total) * 100) : 0;
  return (
    <div className="border border-ink-100 rounded-xl overflow-hidden">
      <div className="px-3 py-2 bg-ink-50 flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-ink-700 capitalize">{form.title}</p>
        <p className="text-xs text-ink-500">
          {form.filled} of {form.total} filled
        </p>
      </div>
      <div className="h-1 bg-ink-100">
        <div className="h-1 bg-success transition-all" style={{ width: `${pct}%` }} />
      </div>
      <ul className="max-h-[32vh] overflow-y-auto divide-y divide-ink-100">
        {form.fields.map((f) => (
          <li key={f.key} className="flex items-center gap-2 px-3 py-1.5 text-xs">
            <span
              className={`w-4 text-center ${
                f.status === 'filled' ? 'text-success' : f.status === 'asking' ? 'text-brand-500' : 'text-ink-300'
              }`}
              aria-hidden="true"
            >
              {f.status === 'filled' ? '✓' : f.status === 'asking' ? '●' : '○'}
            </span>
            <span className={`shrink-0 ${f.status === 'asking' ? 'font-semibold text-ink-900' : 'text-ink-500'}`}>
              {f.label}
              {!f.required && ' (optional)'}
            </span>
            <span className="ml-auto truncate text-right text-ink-800 max-w-[55%]">{f.display}</span>
          </li>
        ))}
      </ul>
      {form.manual?.length > 0 && (
        <div className="px-3 py-2 bg-warning-bg text-warning-text text-xs space-y-1">
          {form.manual.map((m) => (
            <p key={m}>☝ {m}</p>
          ))}
        </div>
      )}
      <p className="px-3 py-2 text-[11px] text-ink-400 bg-white border-t border-ink-100">
        Watch the form fill in. <b>You</b> click Submit when you are happy: the assistant never submits.
      </p>
    </div>
  );
}

function VoicePanel({
  phase,
  heard,
  reply,
  results,
  hints,
  form,
  micError,
  recName,
  handsFree,
  supported,
  onClose,
  onSubmit,
  onHandsFree,
  onOpenItem,
}) {
  const [typed, setTyped] = useState('');
  const examples = hints && hints.length ? hints : DEFAULT_HINTS;

  function submit(e) {
    e.preventDefault();
    const t = typed.trim();
    if (!t) return;
    setTyped('');
    onSubmit(t);
  }

  return (
    <div
      role="dialog"
      aria-label="OPS voice assistant"
      className="fixed z-[110] bottom-[76px] left-3 right-3 sm:left-auto sm:right-6 sm:w-[400px] max-h-[calc(100vh-96px)] flex flex-col bg-white border border-ink-200 rounded-xl2 shadow-popover overflow-hidden animate-fade-in"
    >
      {/* header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-ink-100 shrink-0">
        <div className="voice-orb" data-phase={phase}>
          <MicIcon className="w-5 h-5" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-ink-900">OPS Assistant</p>
          <p className="text-xs text-ink-400">{PHASE_LABEL[phase] || ''}{recName ? ` · ${recName}` : ''}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close assistant"
          className="w-8 h-8 rounded-lg text-ink-400 hover:bg-ink-50 hover:text-ink-900"
        >
          ✕
        </button>
      </div>

      {/* conversation */}
      <div className="px-4 py-3 space-y-3 overflow-y-auto">
        {micError && <p className="text-xs rounded-lg bg-warning-bg text-warning-text px-3 py-2">{micError}</p>}
        {!supported && (
          <p className="text-xs rounded-lg bg-info-bg text-info-text px-3 py-2">
            Speech recognition is not available in this browser. Use Chrome or Edge to talk to the assistant — you can still
            type commands below and it will answer out loud.
          </p>
        )}

        {heard && (
          <div className="flex justify-end">
            <p className="max-w-[85%] rounded-xl rounded-br-sm bg-brand-50 text-brand-700 text-sm px-3 py-2">{heard}</p>
          </div>
        )}
        {reply && (
          <div className="flex justify-start">
            <p className="max-w-[90%] rounded-xl rounded-bl-sm bg-ink-50 text-ink-900 text-sm px-3 py-2">{reply}</p>
          </div>
        )}

        {form && <FormChecklist form={form} />}

        {!form && Array.isArray(results) && results.length > 0 && (
          <div className="border border-ink-100 rounded-xl overflow-hidden">
            {results.map((r, i) => (
              <button
                key={r.id}
                type="button"
                onClick={() => onOpenItem(r)}
                className="w-full text-left px-3 py-2 flex items-center gap-2 border-b border-ink-100 last:border-0 hover:bg-ink-50"
              >
                <span className="text-xs text-ink-400 w-4">{i + 1}</span>
                <RecordIdBadge id={r.id} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-ink-900 truncate">{r.title}</p>
                  {r.subtitle && <p className="text-xs text-ink-400 truncate">{r.subtitle}</p>}
                </div>
                <StatusBadge status={r.status} />
              </button>
            ))}
          </div>
        )}

        {!form && !(Array.isArray(results) && results.length > 0) && (
          <div className="flex flex-wrap gap-1.5">
            {examples.map((h) => (
              <button
                key={h}
                type="button"
                onClick={() => onSubmit(h)}
                className="text-xs rounded-full border border-ink-200 px-2.5 py-1 text-ink-600 hover:bg-ink-50"
              >
                {h}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* type a command + hands-free switch */}
      <form onSubmit={submit} className="px-4 pb-3 flex gap-2 shrink-0">
        <input
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder={form ? 'Or type your answer…' : 'Or type a command…'}
          className="flex-1 bg-ink-50 border border-ink-200 focus:bg-white focus:border-brand-500 rounded-lg px-3 py-2 text-sm outline-none"
        />
        <button
          type="submit"
          className="rounded-lg bg-brand-500 hover:bg-brand-600 text-white text-sm px-3 py-2 disabled:opacity-50"
          disabled={!typed.trim()}
        >
          Send
        </button>
      </form>

      <label className="flex items-center justify-between gap-3 px-4 py-2.5 border-t border-ink-100 bg-ink-50 text-xs text-ink-600 cursor-pointer shrink-0">
        <span>Hands-free “Hello Ops” / “Hey Ops” (keeps the mic on)</span>
        <input
          type="checkbox"
          checked={handsFree}
          disabled={!supported}
          onChange={(e) => onHandsFree(e.target.checked)}
          className="w-4 h-4 accent-[#2E4CDB]"
        />
      </label>
    </div>
  );
}
