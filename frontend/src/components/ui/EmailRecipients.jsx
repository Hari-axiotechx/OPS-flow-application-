import { useEffect, useMemo, useRef, useState } from 'react';
import { userService } from '../../api/userService';
import { useAuth } from '../../context/AuthContext';

/**
 * E-mail block used at the bottom of the Deployment, Access and AWS (production) issue forms.
 *
 *   [ To  ........ ]  [ Cc  ........ ]      <- two separate search + select boxes
 *                                         [Cancel] [Submit]
 *
 * All request emails are mandatory: there is no enable/disable control. Only the people
 * picked here receive the e-mail.
 * It is sent from no-reply@axiotechx.com (set on the server) and replies go to the requester.
 */

// The list is shown instantly from this cache and refreshed every time a form opens,
// so newly approved people (or changed preferences) appear without reloading the page.
let cache = null;

export function useEmailRecipients(open = true) {
  const [people, setPeople] = useState(cache || []);
  const [loading, setLoading] = useState(!cache);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    let live = true;
    if (!cache) setLoading(true);
    setError('');
    userService
      .listEmailRecipients()
      .then((rows) => {
        cache = rows || [];
        if (live) setPeople(cache);
      })
      .catch((e) => live && setError(e.message || 'Could not load people.'))
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [open]);

  return { people, loading, error };
}

function RecipientBox({ label, required, selected, onChange, people, blockedIds, loading, error, mandatory }) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef(null);
  const inputRef = useRef(null);

  const byId = useMemo(() => new Map(people.map((p) => [p.id, p])), [people]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    return people.filter((p) => {
      if (selected.includes(p.id) || blockedIds.includes(p.id)) return false;
      if (!q) return true;
      return `${p.name} ${p.email} ${p.role}`.toLowerCase().includes(q);
    });
  }, [people, query, selected, blockedIds]);

  useEffect(() => { setActive(0); }, [query, open]);

  useEffect(() => {
    function away(e) {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, []);

  function pick(p) {
    if (!p || (p.emailOn === false && !mandatory)) return;
    onChange([...selected, p.id]);
    setQuery('');
    inputRef.current?.focus();
  }

  function remove(id) {
    onChange(selected.filter((x) => x !== id));
  }

  function onKeyDown(e) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(i + 1, Math.max(matches.length - 1, 0)));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      // Never submit the form from here: Enter only picks the highlighted person.
      e.preventDefault();
      e.stopPropagation();
      if (open && matches[active]) pick(matches[active]);
    } else if (e.key === 'Escape' && open) {
      e.stopPropagation(); // close the list, not the whole modal
      setOpen(false);
    } else if (e.key === 'Backspace' && !query && selected.length) {
      remove(selected[selected.length - 1]);
    }
  }

  return (
    <div ref={boxRef} className="relative min-w-0">
      <label className="block text-xs font-medium text-slate-600 mb-1">
        {label}
        {required && <span className="text-red-500"> *</span>}
        {selected.length > 0 && (
          <span className="ml-1 text-slate-400 font-normal">({selected.length})</span>
        )}
      </label>

      <div
        onClick={() => { setOpen(true); inputRef.current?.focus(); }}
        className={`flex flex-wrap items-center gap-1 min-h-[38px] max-h-[86px] overflow-y-auto
          rounded-lg border bg-white px-2 py-1 cursor-text
          ${open ? 'border-brand-500 ring-2 ring-brand-100' : 'border-slate-300'}`}
      >
        {selected.map((id) => {
          const p = byId.get(id);
          return (
            <span
              key={id}
              title={p?.email}
              className="inline-flex items-center gap-1 max-w-full rounded-full bg-brand-50
                border border-brand-200 text-brand-800 text-xs pl-2 pr-1 py-0.5"
            >
              <span className="truncate max-w-[150px]">{p?.name || p?.email || id}</span>
              <button
                type="button"
                aria-label={`Remove ${p?.name || id}`}
                onClick={(e) => { e.stopPropagation(); remove(id); }}
                className="w-4 h-4 leading-none rounded-full hover:bg-brand-200 text-brand-700"
              >
                ×
              </button>
            </span>
          );
        })}
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder={selected.length ? 'Add more…' : 'Search name or email…'}
          autoComplete="off"
          className="flex-1 min-w-[110px] text-sm bg-transparent outline-none py-1 px-1 text-slate-800 placeholder:text-slate-400"
        />
      </div>

      {open && (
        <ul
          role="listbox"
          className="absolute z-30 bottom-full mb-1 left-0 right-0 max-h-52 overflow-y-auto
            rounded-lg border border-slate-200 bg-white shadow-xl py-1"
        >
          {loading && <li className="px-3 py-2 text-xs text-slate-500">Loading people…</li>}
          {error && <li className="px-3 py-2 text-xs text-red-600">{error}</li>}
          {!loading && !error && matches.length === 0 && (
            <li className="px-3 py-2 text-xs text-slate-500">
              {query ? 'No one matches that search.' : 'No more people to add.'}
            </li>
          )}
          {matches.map((p, i) => {
            const off = p.emailOn === false && !mandatory;   // mandatory mail ignores the profile switch
            return (
              <li
                key={p.id}
                role="option"
                aria-selected={i === active}
                aria-disabled={off}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => { e.preventDefault(); pick(p); }}
                className={`px-3 py-1.5 text-sm flex items-center justify-between gap-2
                  ${off ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                  ${i === active && !off ? 'bg-brand-50' : ''}`}
              >
                <span className="min-w-0">
                  <span className="block truncate text-slate-800">{p.name}</span>
                  <span className="block truncate text-xs text-slate-500">{p.email}</span>
                </span>
                <span className="shrink-0 text-[10px] uppercase tracking-wide text-slate-500">
                  {off ? 'email off' : p.role}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/**
 * Drop-in footer for a request modal:
 *   <Modal footer={<EmailNotifyFooter {...email}> <Button>Cancel</Button> <Button>Submit</Button> </EmailNotifyFooter>}>
 * `email` comes from useEmailNotify().
 */
export function useEmailNotify(open, { mandatory = false } = {}) {
  const [to, setTo] = useState([]);
  const [cc, setCc] = useState([]);
  const [prefilled, setPrefilled] = useState(false);

  useEffect(() => {
    if (open) setPrefilled(false);
  }, [open]);

  return {
    mandatory, allowed: true, sendEmail: true, to, setTo, cc, setCc, active: true,
    prefilled, markPrefilled: () => setPrefilled(true),
    // returns an error message, or '' when fine
    validate() {
      if (to.length > 0) return '';
      return "Select at least one 'To' email recipient. The email notification is mandatory.";
    },
    // options passed to the *Service.create(...) calls
    options() {
      return { sendEmail: true, to, cc };
    },
    reset() { setTo([]); setCc([]); setPrefilled(false); },
  };
}

/** Toast text after a request is saved, based on what the server says about the e-mail. */
export function emailResultText(res) {
  const info = res?.email;
  if (!info) return '';
  if (!info.queued) return info.reason ? ` ${info.reason}` : '';
  const n = (info.to?.length || 0) + (info.cc?.length || 0);
  return ` Email is being sent to ${n} ${n === 1 ? 'person' : 'people'}.`;
}

export default function EmailNotifyFooter({ email, children, open = true }) {
  const { people, loading, error } = useEmailRecipients(open && email.active);
  const { user } = useAuth();

  // Mandatory forms start with the DevOps admin(s) already in "To" (you can change it).
  const { mandatory, prefilled, markPrefilled, setTo, to } = email;
  useEffect(() => {
    if (!open || !mandatory || prefilled || loading || people.length === 0) return;
    markPrefilled();
    if (to.length === 0) {
      const admins = people.filter((p) => p.admin && p.id !== user?.id).map((p) => p.id);
      if (admins.length) setTo(admins);
    }
  }, [open, mandatory, prefilled, loading, people]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="w-full flex flex-col gap-3">
      {email.active && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <RecipientBox
            label="To"
            required
            selected={email.to}
            onChange={email.setTo}
            people={people}
            blockedIds={email.cc}
            loading={loading}
            error={error}
            mandatory={email.mandatory}
          />
          <RecipientBox
            label="Cc"
            selected={email.cc}
            onChange={email.setCc}
            people={people}
            blockedIds={email.to}
            loading={loading}
            error={error}
            mandatory={email.mandatory}
          />
          <p className="sm:col-span-2 -mt-1 text-[11px] text-slate-500">
            {email.mandatory ? 'An email is always sent for this request. ' : ''}
            Only the people selected above get this email. Sent from no-reply@axiotechx.com; replies go to you.
          </p>
        </div>
      )}

      <div className="flex flex-col-reverse sm:flex-row sm:items-center sm:justify-end gap-2 sm:gap-3">
        <span className="sm:mr-auto" />
        {children}
      </div>
    </div>
  );
}
