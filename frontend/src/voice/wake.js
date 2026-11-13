// Wake phrases: "Hello Ops" and "Hey Ops" (also "OK Ops"), plus common speech-to-text mis-hearings.
const PREFIX = '(?:hello|helo|hullo|hallo|hallow|hellow|hell o|hell oh|hey|hay|hei|he|hi|ok|okay)';
const NAME = "(?:ops ?flow|ops?|opps|obs|oops|apps|hops|op's|ox|opus|hops|abs)";
const WAKE_RE = new RegExp(`(?:^|\\s)${PREFIX}\\s*,?\\s+${NAME}\\b`, 'i');
// Chrome sometimes glues the phrase together: "helloops", "hellops"
const GLUED_RE = /(?:^|\s)(?:hello|helo|hallo|hey|okay|ok)ops\b/i;

export function normalizeSpeech(text) {
  return String(text || '')
    .toLowerCase()
    .replace(/[^\w\s']/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

// Returns { remainder } when the text contains a wake phrase, else null.
// `remainder` is whatever was said after it ("hello ops open deployment 5" -> "open deployment 5").
export function findWake(text) {
  const n = normalizeSpeech(text);
  const m = WAKE_RE.exec(n) || GLUED_RE.exec(n);
  if (!m) return null;
  return { remainder: n.slice(m.index + m[0].length).trim() };
}

export const YES_RE =
  /^(yes|yeah|yea|yep|yup|ya|haan|han|ha|sure|confirm|confirmed|go ahead|do it|proceed|correct|right|okay|ok|please do|of course|absolutely)\b/;
export const NO_RE = /^(no|nope|nah|cancel|don'?t|do not|stop|negative|never ?mind|abort|wait|hold on|not now)\b/;
export const DISMISS_RE =
  /^(thanks?( you)?|thank you|bye|goodbye|good bye|that'?s all|that is all|never ?mind|stop|close|dismiss|nothing|no thanks|go to sleep)\b/;

const ORDINALS = { first: 0, second: 1, third: 2, fourth: 3, fifth: 4, sixth: 5, seventh: 6, eighth: 7 };

// "open the second one", "number 3", "last one"  ->  index into the shown results.
export function pickIndex(text, count) {
  if (!count) return null;
  const t = normalizeSpeech(text).replace(/^(open|show|go to|select|choose|take me to)\s+/, '').replace(/^the\s+/, '');
  let m = /^(first|second|third|fourth|fifth|sixth|seventh|eighth)(?: one| result| item)?$/.exec(t);
  if (m) return ORDINALS[m[1]] < count ? ORDINALS[m[1]] : null;
  if (/^last(?: one| result| item)?$/.test(t)) return count - 1;
  m = /^(?:number|no) (\d)$/.exec(t) || /^(\d)(?:st|nd|rd|th)(?: one| result| item)?$/.exec(t);
  if (m) return Number(m[1]) - 1 < count && Number(m[1]) >= 1 ? Number(m[1]) - 1 : null;
  return null;
}

/* ---------------- instant, in-browser commands (no server round trip) ---------------- */

const PAGES = [
  [/^(?:the )?(?:dashboard|home|home page|main page)$/, '/', 'the dashboard'],
  [/^(?:the )?(?:deployments?|deployment requests?|deployments page)$/, '/deployments', 'deployments'],
  [/^(?:the )?(?:access|access requests?|access page)$/, '/access', 'access requests'],
  [/^(?:the )?(?:aws|aws issues?|issues)(?: page)?$/, '/aws-issues', 'AWS issues'],
  [/^(?:my |the |user )?(?:profile|account|settings|my account)(?: page)?$/, '/profile', 'your profile'],
  [/^(?:the )?(?:users?|user management|manage users)$/, '/users', 'user management'],
  [/^(?:the )?(?:applications?|apps)$/, '/applications', 'applications'],
];
const KIND_ROUTE = [
  [/^(?:deployment|deploy|dep|release)$/, '/deployments/DEP-', 'deployment'],
  [/^(?:access|access request|acc)$/, '/access/ACC-', 'access request'],
  [/^(?:aws issue|aws|issue|incident)$/, '/aws-issues/AWS-', 'AWS issue'],
];
const DIGITS = { zero: 0, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, to: 2, too: 2, for: 4 };

function digitsOf(s) {
  const parts = s.trim().split(/[\s-]+/);
  if (!parts.length) return null;
  let out = '';
  for (const p of parts) {
    if (/^\d+$/.test(p)) out += p;
    else if (p in DIGITS && (parts.length > 1 || !['to', 'too', 'for'].includes(p))) out += DIGITS[p];
    else return null;
  }
  return out || null;
}

// Commands the browser can do by itself, instantly:
//   "go to dashboard", "open deployments", "open deployment 123", "go back".
// Returns { route, speech } / { back: true, speech } or null (= ask the server).
export function localCommand(text, { isDevOps = false } = {}) {
  const t = normalizeSpeech(text)
    .replace(/^(?:please|can you|could you)\s+/, '')
    .replace(/(?:\s+(?:please|page|now))+$/, '');
  // "go back to the dashboard" / "back to profile" -> that page (NOT just one step back)
  const backTo = /^(?:go )?back to\s+(.+)$/.exec(t);
  if (/^(?:go )?back$|^previous page$|^go back (?:one )?(?:step|page)$|^one step back$/.test(t)) return { back: true, speech: 'Going back.' };
  const nav = backTo || /^(?:go to|open|show|take me to|navigate to|switch to)\s+(.+)$/.exec(t);
  if (nav) {
    for (const [re, route, label] of PAGES) {
      if (re.test(nav[1])) {
        if (route === '/aws-issues' && !isDevOps) return null; // the server explains the permission
        return { route, speech: `Opening ${label}.` };
      }
    }
  }
  const rec = /^(?:open|show|go to|view|pull up|bring up)\s+(?:the\s+)?(deployment|deploy|dep|release|access request|access|acc|aws issue|aws|issue|incident)\s+(?:number\s+|no\s+|id\s+)?([a-z0-9 -]+)$/.exec(
    t
  );
  if (rec) {
    const n = digitsOf(rec[2]);
    if (!n || n.length > 9) return null;
    for (const [re, prefix, label] of KIND_ROUTE) {
      if (re.test(rec[1])) {
        if (prefix.startsWith('/aws') && !isDevOps) return null;
        return { route: `${prefix}${String(Number(n)).padStart(6, '0')}`, record: true, label: `${label} ${Number(n)}` };
      }
    }
  }
  return null;
}

/* ---------------- understanding: pick the best guess + fix common mis-hearings ---------------- */

// Words this assistant expects to hear. Used to choose between the browser's alternative guesses.
const VOCAB = new Set(
  ('deployment deployments access request requests aws issue issues open show list count how many pending approve ' +
    'reject rollback roll back start complete failed failure success successful production prod dev qa uat today ' +
    'tomorrow yesterday week month my all create new report add application dashboard profile go to back summary ' +
    'search who what when why which branch assign assigned requested scheduled status number hello ops yes no cancel ' +
    'frontend backend environment github version commit stylo').split(' ')
);

// The browser can return several guesses for the same speech. Take the one with the most words we know.
export function bestTranscript(result) {
  if (!result) return '';
  const n = Math.min(result.length || 1, 5);
  let best = result[0]?.transcript || '';
  let bestScore = -1;
  for (let i = 0; i < n; i++) {
    const t = result[i]?.transcript || '';
    const words = normalizeSpeech(t).split(' ');
    let score = 0;
    for (const w of words) if (VOCAB.has(w)) score += 1;
    if (WAKE_RE.test(normalizeSpeech(t)) || GLUED_RE.test(normalizeSpeech(t))) score += 3;
    score -= i * 0.01; // on a tie, trust the browser's first choice
    if (score > bestScore) {
      best = t;
      bestScore = score;
    }
  }
  return best;
}

const FIXES = [
  [/\b(?:deploy ?ments)\b/g, 'deployments'],
  [/\b(?:deploy ?ment|deploy mint|deployed meant|deploy meant|deploy mend|deployed ment)\b/g, 'deployment'],
  [/\b(?:role|rowl|roll) ?(?:back|bag|pack)\b/g, 'roll back'],
  [/\b(?:a prove|a proof|a prove it|approved it)\b/g, 'approve'],
  [/\b(?:re ject|reject it)\b/g, 'reject'],
  [/\b(?:ax is|axes|axis|accessed) request/g, 'access request'],
  [/\b(?:a w s|a double u s|ew s|easy s|a ws|aws's)\b/g, 'aws'],
  [/\b(?:production|prod|prude|prud|brod|broad)\b(?= (?:deployments?|requests?|issues?)|$)/g, 'prod'],
  [/\b(?:q a|queue a|cue a|que a)\b/g, 'qa'],
  [/\b(?:you at|u a t)\b/g, 'uat'],
  [/\b(?:dev ops|def ops)\b/g, 'devops'],
  [/\bpending\s+excess\b/g, 'pending access'],
];

// Fixes typical speech-to-text slips in COMMANDS (not used for dictated form answers such as branch names).
export function fixSpeech(text) {
  let t = String(text || '');
  for (const [re, to] of FIXES) t = t.replace(re, to);
  return t;
}

/* ---------------- commands that always win, even in the middle of a form ----------------
   While the assistant is filling a form, every sentence used to be treated as a form answer, so
   "go back" and "open profile" just repeated the question. These are recognised first.
   Returns { kind: 'go', route, speech } | { kind: 'sleep' } | { kind: 'logout' } | null.
   ("go back" / "previous" / "review" / "cancel" are understood by the form itself.) */
export function formEscape(text, { isDevOps = false } = {}) {
  const t = normalizeSpeech(text).replace(/^(?:please|can you|could you)\s+/, '').replace(/(?:\s+(?:please|now))+$/, '');
  if (/^(?:log ?out|sign ?out|log me out)$/.test(t)) return { kind: 'logout' };
  if (/^(?:close|hide|dismiss|stop) (?:the )?(?:assistant|panel|voice|listening)$|^(?:stop listening|voice off|mic off|turn off (?:the )?voice|go to sleep)$/.test(t))
    return { kind: 'sleep' };
  const local = localCommand(t, { isDevOps });
  if (local && !local.back) return { kind: 'go', route: local.route, speech: local.speech || `Opening ${local.label}.` };
  return null;
}
