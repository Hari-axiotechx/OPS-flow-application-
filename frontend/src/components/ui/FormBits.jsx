import { useState } from 'react';
import Modal from './Modal';
import Button from './Button';

export const MAX_FILE_BYTES = 5 * 1024 * 1024; // 5MB per file

const inputCls =
  'w-full border border-ink-200 rounded-lg px-3 py-2 text-sm ' +
  'focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none';

function localDateValue(date) {
  const pad = (value) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function localDateTimeValue(date) {
  const pad = (value) => String(value).padStart(2, '0');
  return `${localDateValue(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function parseLocalDate(value, withTime) {
  if (!value) return null;
  const [datePart, timePart = '00:00'] = value.split('T');
  const [year, month, day] = datePart.split('-').map(Number);
  const [hour, minute] = withTime ? timePart.split(':').map(Number) : [12, 0];
  const parsed = new Date(year, month - 1, day, hour, minute);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function minDateTimeLocal() {
  const date = new Date();
  date.setSeconds(0, 0);
  date.setMinutes(date.getMinutes() + 1);
  date.setMinutes(date.getMinutes() + ((15 - (date.getMinutes() % 15)) % 15));
  return localDateTimeValue(date);
}

function displayDate(date) {
  return date.toLocaleDateString(undefined, {
    weekday: 'short',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  });
}

function CalendarPicker({ value, onChange, dateOnly = false, minDate }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [visibleMonth, setVisibleMonth] = useState(() => new Date());
  const currentValue = parseLocalDate(value, !dateOnly);
  const minimumDate = minDate ? parseLocalDate(minDate, false) : null;
  const minimumDateValue = minimumDate ? localDateValue(minimumDate) : '';
  const todayValue = localDateValue(new Date());
  const [draftDatePart, draftTimePart = '00:00'] = draft.split('T');
  const [hour, minute] = draftTimePart.split(':').map(Number);
  const isDraftValid = dateOnly
    ? !!draftDatePart && (!minimumDateValue || draftDatePart >= minimumDateValue)
    : draft >= minDateTimeLocal();

  function openPicker() {
    const initial = value || (dateOnly ? localDateValue(new Date()) : minDateTimeLocal());
    const initialDate = parseLocalDate(initial, !dateOnly) || new Date();
    setDraft(initial);
    setVisibleMonth(new Date(initialDate.getFullYear(), initialDate.getMonth(), 1));
    setOpen(true);
  }

  function selectDate(date) {
    const nextDate = localDateValue(date);
    setDraft(dateOnly ? nextDate : `${nextDate}T${draftTimePart || '00:00'}`);
  }

  function changeTime(nextHour, nextMinute) {
    setDraft(`${draftDatePart}T${String(nextHour).padStart(2, '0')}:${String(nextMinute).padStart(2, '0')}`);
  }

  function commit() {
    if (!isDraftValid) return;
    onChange(draft);
    setOpen(false);
  }

  const firstDay = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth(), 1);
  const offset = (firstDay.getDay() + 6) % 7;
  const calendarStart = new Date(firstDay.getFullYear(), firstDay.getMonth(), 1 - offset);
  const calendarDays = Array.from({ length: 42 }, (_, index) =>
    new Date(calendarStart.getFullYear(), calendarStart.getMonth(), calendarStart.getDate() + index)
  );
  const draftDate = parseLocalDate(draft, !dateOnly);
  const selectedDate = draftDate ? localDateValue(draftDate) : '';

  return (
    <>
      <button
        type="button"
        onClick={openPicker}
        aria-haspopup="dialog"
        aria-label={dateOnly ? 'Choose date' : 'Choose date and time'}
        className={`${inputCls} flex min-h-10 items-center justify-between gap-3 bg-white text-left hover:border-brand-400`}
      >
        <span className={value ? 'text-ink-900' : 'text-ink-400'}>
          {currentValue
            ? dateOnly
              ? displayDate(currentValue)
              : `${displayDate(currentValue)} · ${currentValue.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
            : dateOnly ? 'Choose a date' : 'Choose date and time'}
        </span>
        <span aria-hidden="true" className="text-brand-600">▦</span>
      </button>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={dateOnly ? 'Choose a date' : 'Choose date & time'}
        width="max-w-md"
        maxHeight="max-h-[90vh]"
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
            <Button type="button" onClick={commit} disabled={!isDraftValid}>OK</Button>
          </div>
        }
      >
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={() => setVisibleMonth(new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() - 1, 1))}
              aria-label="Previous month"
              className="flex h-9 w-9 items-center justify-center rounded-lg border border-ink-200 text-lg text-ink-600 hover:bg-ink-50"
            >
              ‹
            </button>
            <div className="text-center">
              <p className="font-semibold text-ink-900">
                {visibleMonth.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}
              </p>
              <p className="text-xs text-ink-400">
                {draftDate ? `Selected: ${displayDate(draftDate)}` : 'Select a date'}
              </p>
            </div>
            <button
              type="button"
              onClick={() => setVisibleMonth(new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + 1, 1))}
              aria-label="Next month"
              className="flex h-9 w-9 items-center justify-center rounded-lg border border-ink-200 text-lg text-ink-600 hover:bg-ink-50"
            >
              ›
            </button>
          </div>

          <div className="grid grid-cols-7 gap-1 text-center">
            {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((day) => (
              <span key={day} className="py-1 text-xs font-semibold text-ink-400">{day}</span>
            ))}
            {calendarDays.map((day) => {
              const dateValue = localDateValue(day);
              const inMonth = day.getMonth() === visibleMonth.getMonth();
              const selected = dateValue === selectedDate;
              const isToday = dateValue === todayValue;
              const disabled = !!minimumDateValue && dateValue < minimumDateValue;
              return (
                <button
                  key={dateValue}
                  type="button"
                  disabled={disabled}
                  onClick={() => selectDate(day)}
                  aria-pressed={selected}
                  aria-label={`${displayDate(day)}${isToday ? ', today' : ''}`}
                  className={`relative mx-auto flex h-10 w-10 items-center justify-center rounded-xl text-sm transition
                    ${selected ? 'bg-brand-600 font-semibold text-white shadow-md shadow-brand-600/20' : ''}
                    ${!selected && inMonth ? 'text-ink-800 hover:bg-brand-50' : ''}
                    ${!selected && !inMonth ? 'text-ink-300 hover:bg-ink-50' : ''}
                    ${!selected && isToday ? 'ring-1 ring-brand-400' : ''}
                    ${disabled ? 'cursor-not-allowed opacity-30 hover:bg-transparent' : ''}`}
                >
                  {day.getDate()}
                  {isToday && !selected && <span className="absolute bottom-1 h-1 w-1 rounded-full bg-brand-500" />}
                </button>
              );
            })}
          </div>

          {!dateOnly && (
            <div className="rounded-xl border border-ink-100 bg-ink-50 p-4">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-sm font-semibold text-ink-800">Time</p>
                <p className="text-xs text-ink-500">15-minute intervals</p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <label className="text-xs font-medium text-ink-500">
                  Hour
                  <select
                    value={Number.isFinite(hour) ? hour : 0}
                    onChange={(event) => changeTime(Number(event.target.value), Number.isFinite(minute) ? minute : 0)}
                    className={`${inputCls} mt-1 bg-white`}
                  >
                    {Array.from({ length: 24 }, (_, index) => (
                      <option key={index} value={index}>{String(index).padStart(2, '0')}</option>
                    ))}
                  </select>
                </label>
                <label className="text-xs font-medium text-ink-500">
                  Minute
                  <select
                    value={Number.isFinite(minute) ? minute : 0}
                    onChange={(event) => changeTime(Number.isFinite(hour) ? hour : 0, Number(event.target.value))}
                    className={`${inputCls} mt-1 bg-white`}
                  >
                    {[0, 15, 30, 45].map((item) => (
                      <option key={item} value={item}>{String(item).padStart(2, '0')}</option>
                    ))}
                  </select>
                </label>
              </div>
            </div>
          )}
        </div>
      </Modal>
    </>
  );
}

export function DatePicker({ value, onChange, min }) {
  return <CalendarPicker value={value} onChange={onChange} dateOnly minDate={min} />;
}

export function DateTimePicker({ value, onChange }) {
  return <CalendarPicker value={value} onChange={onChange} minDate={minDateTimeLocal()} />;
}

export function countWords(text) {
  const t = String(text || '').trim();
  return t ? t.split(/\s+/).length : 0;
}

function readAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error('Could not read file.'));
    reader.readAsDataURL(file);
  });
}

/** Reads a File into { name, data } (data = base64 data URL). Throws a friendly Error if > 5MB. */
export async function fileToAttachment(file) {
  if (file.size > MAX_FILE_BYTES) {
    throw new Error(`"${file.name}" is too large (max 5MB).`);
  }
  return { name: file.name, data: await readAsDataUrl(file) };
}

/**
 * One "Attach file" button (bottom-right of a box). Shows the chosen file name with a Remove link.
 *   file: { name, data } | null
 */
export function AttachFile({ file, onChange, label = 'Attach file' }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function pick(e) {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (!f) return;
    setError('');
    setBusy(true);
    try {
      onChange(await fileToAttachment(f));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-1.5 flex flex-col items-end gap-1">
      {file ? (
        <div className="inline-flex items-center gap-2 max-w-full border border-ink-200 rounded-lg px-2.5 py-1.5 text-xs bg-ink-50">
          <span className="truncate text-ink-800">📄 {file.name}</span>
          <button
            type="button"
            onClick={() => { setError(''); onChange(null); }}
            className="font-semibold text-red-600 hover:text-red-700 shrink-0"
          >
            Remove
          </button>
        </div>
      ) : (
        <label className="inline-flex items-center gap-1.5 cursor-pointer rounded-lg border border-dashed border-ink-300 px-2.5 py-1.5 text-xs font-semibold text-brand-600 hover:bg-brand-50">
          {busy ? 'Reading file…' : `📎 ${label}`}
          <input type="file" className="hidden" onChange={pick} disabled={busy} />
        </label>
      )}
      {error && <p className="text-[11px] text-danger">{error}</p>}
    </div>
  );
}

/**
 * Textarea with a live word counter. Over the limit -> red border + error message below the box.
 * Pass `file` + `onFileChange` to show the single "Attach file" option at the bottom-right.
 */
export function WordLimitTextarea({
  value, onChange, limit, rows = 3, placeholder, file, onFileChange, fileLabel, required = false,
}) {
  const words = countWords(value);
  const over = words > limit;
  return (
    <div>
      <textarea
        rows={rows}
        required={required}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={`${inputCls} ${over ? '!border-red-500 focus:!border-red-500 focus:!ring-red-500' : ''}`}
      />
      <div className="mt-1 flex items-start justify-between gap-3">
        <div className="min-w-0">
          {over && (
            <p className="text-[11px] text-danger">
              Too long: {words} words. Maximum allowed is {limit} words — please shorten it by {words - limit}.
            </p>
          )}
        </div>
        <span className={`text-[11px] shrink-0 ${over ? 'text-danger font-semibold' : 'text-ink-400'}`}>
          {words} / {limit} words
        </span>
      </div>
      {onFileChange && <AttachFile file={file} onChange={onFileChange} label={fileLabel} />}
    </div>
  );
}

/**
 * Up to `max` files. Each row shows its position number (1, 2, 3 …) — the NUMBER STAYS where it is
 * while the user moves the FILE up or down with the arrows.
 *   files: [{ name, data }]
 */
export function MultiFileUpload({ files, onChange, max = 10 }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function pick(e) {
    const picked = Array.from(e.target.files || []);
    e.target.value = '';
    if (picked.length === 0) return;
    setError('');
    const room = max - files.length;
    if (room <= 0) {
      setError(`You can upload at most ${max} files.`);
      return;
    }
    const chosen = picked.slice(0, room);
    setBusy(true);
    try {
      const read = [];
      for (const f of chosen) read.push(await fileToAttachment(f));
      onChange([...files, ...read]);
      if (picked.length > room) setError(`Only ${max} files are allowed — the extra ${picked.length - room} file(s) were not added.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function move(i, dir) {
    const j = i + dir;
    if (j < 0 || j >= files.length) return;
    const next = files.slice();
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  }

  function remove(i) {
    setError('');
    onChange(files.filter((_, idx) => idx !== i));
  }

  const arrowCls =
    'w-7 h-7 flex items-center justify-center rounded-md border border-ink-200 text-ink-500 ' +
    'hover:bg-ink-50 disabled:opacity-30 disabled:cursor-not-allowed';

  return (
    <div className="space-y-2">
      {files.length > 0 && (
        <ol className="space-y-1.5">
          {files.map((f, i) => (
            <li key={`${i}-${f.name}`} className="flex items-center gap-2 border border-ink-200 rounded-lg px-2.5 py-1.5 bg-ink-50">
              <span className="w-6 shrink-0 text-xs font-bold text-ink-500 text-right">{i + 1}.</span>
              <span className="flex-1 min-w-0 truncate text-sm text-ink-800">📄 {f.name}</span>
              <button type="button" className={arrowCls} disabled={i === 0} onClick={() => move(i, -1)} title="Move up" aria-label="Move up">▲</button>
              <button type="button" className={arrowCls} disabled={i === files.length - 1} onClick={() => move(i, 1)} title="Move down" aria-label="Move down">▼</button>
              <button type="button" onClick={() => remove(i)} className="text-xs font-semibold text-red-600 hover:text-red-700 shrink-0 px-1">Remove</button>
            </li>
          ))}
        </ol>
      )}

      {files.length < max && (
        <label className={`${inputCls} flex items-center justify-center gap-2 border-dashed text-ink-500 cursor-pointer hover:bg-ink-50`}>
          {busy ? 'Reading files…' : files.length === 0 ? '📎 Click to upload schema / DB change files' : '📎 Add another file'}
          <input type="file" multiple className="hidden" onChange={pick} disabled={busy} />
        </label>
      )}

      <p className="text-[11px] text-ink-400">
        {files.length} of {max} files · Max 5MB each. Use ▲ ▼ to change the order — the numbers stay fixed.
      </p>
      {error && <p className="text-[11px] text-danger">{error}</p>}
    </div>
  );
}

// ---------------------------------------------------------------------
// Date & time that can never be in the past
// ---------------------------------------------------------------------

/** Native date/time picker that prevents past dates and limits selections to 15-minute intervals. */
export function FutureDateTime({ value, onChange }) {
  return <DateTimePicker value={value} onChange={onChange} />;
}