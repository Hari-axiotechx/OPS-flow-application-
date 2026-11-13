// Bridge between the voice assistant and the real forms on screen.
//
// Each form modal registers itself while it is open (see useVoiceForm.js). The assistant can then
//   * read the form's CURRENT values (so manual typing is never overwritten by stale state),
//   * write values into it  -> the user watches the fields fill in live,
//   * close it (cancel).
// The assistant can NOT submit a form: there is deliberately no `submit` here. Only the user can
// click "Submit Request".

const registry = new Map(); // kind -> { getForm, apply, reset, close }
const listeners = new Set();

function emit(event) {
  listeners.forEach((fn) => {
    try {
      fn(event);
    } catch {
      /* a listener must never break a form */
    }
  });
}

export const voiceForms = {
  register(kind, handlers) {
    registry.set(kind, handlers);
    emit({ type: 'registered', kind });
    return () => {
      if (registry.get(kind) === handlers) registry.delete(kind);
      emit({ type: 'closed', kind });
    };
  },
  get: (kind) => registry.get(kind) || null,
  // Resolves with the handlers as soon as the form has opened (or null after `timeout` ms).
  waitFor(kind, timeout = 4000) {
    if (registry.has(kind)) return Promise.resolve(registry.get(kind));
    return new Promise((resolve) => {
      const done = (value) => {
        clearTimeout(timer);
        listeners.delete(onEvent);
        resolve(value);
      };
      const onEvent = (e) => {
        if (e.type === 'registered' && e.kind === kind) done(registry.get(kind));
      };
      const timer = setTimeout(() => done(null), timeout);
      listeners.add(onEvent);
    });
  },
  // Forms call this after a successful create so the assistant can confirm out loud.
  submitted(kind, recordId) {
    emit({ type: 'submitted', kind, recordId });
  },
  subscribe(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
};

/* ---- what the server is allowed to see: no uploaded files, no env-var values ---- */
export function summarizeForm(form) {
  const out = { ...(form || {}) };
  delete out.dbChangeFileData;
  delete out.envVarDetails;
  if (Array.isArray(out.envVars)) {
    out.envVars = out.envVars
      .filter((r) => r.key || r.value)
      .map((r) => ({ key: r.key, hasValue: !!r.value }));
  }
  return out;
}

/* ---- highlight the fields the assistant just filled ---- */
const FIELDS = 'input, select, textarea';

export function snapshotValues() {
  const map = new Map();
  document.querySelectorAll(`[data-modal-root] ${FIELDS}, [data-voice-form] ${FIELDS}`).forEach((el) => {
    if (el.type !== 'file') map.set(el, el.value);
  });
  return map;
}

export function flashChanged(before) {
  // wait for React to re-render the patched values
  setTimeout(() => {
    document.querySelectorAll(`[data-modal-root] ${FIELDS}, [data-voice-form] ${FIELDS}`).forEach((el) => {
      if (el.type === 'file') return;
      const was = before.get(el);
      if (el.value !== '' && el.value !== was) {
        el.classList.remove('voice-flash');
        void el.offsetWidth; // restart the animation
        el.classList.add('voice-flash');
        setTimeout(() => el.classList.remove('voice-flash'), 1800);
      }
    });
  }, 120);
}

export function localNowIso() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
