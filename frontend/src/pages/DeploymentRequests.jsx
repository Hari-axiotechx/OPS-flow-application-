import { useEffect, useMemo, useState } from 'react';
import { useStatusFilter } from '../hooks/useStatusFilter';
import BackArrow from '../components/ui/BackArrow';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { deploymentService } from '../api/deploymentService';
import { userService } from '../api/userService';

import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Modal from '../components/ui/Modal';
import { StatusBadge, RecordIdBadge } from '../components/ui/Badge';
import { SkeletonRow } from '../components/ui/Skeleton';
import EmptyState from '../components/ui/EmptyState';
import ErrorState from '../components/ui/ErrorState';
import EmailNotifyFooter, { useEmailNotify, emailResultText } from '../components/ui/EmailRecipients';
import { useVoiceForm } from '../voice/useVoiceForm';
import { voiceForms } from '../voice/voiceForms';
import {
  AttachFile, WordLimitTextarea, MultiFileUpload, FutureDateTime,
  countWords, fileToAttachment,
} from '../components/ui/FormBits';

const STATUS_FILTERS = [
  'ALL',
  'REQUESTED',
  'APPROVED',
  'IN_PROGRESS',
  'COMPLETED_SUCCESS',
  'COMPLETED_FAILED',
  'REJECTED',
  'ROLLED_BACK',
];

export default function DeploymentRequests() {
  const [params, setParams] = useSearchParams();

  const statusFilter = useStatusFilter(params, setParams);

  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [devOpsNames, setDevOpsNames] = useState({});

  const navigate = useNavigate();
  const { config, user, refreshConfig } = useAuth();

  const canCreateDeployment =
    user?.role === 'Developer' || user?.role === 'QA';

  async function load() {
    setLoading(true);
    setError(null);

    try {
      const data = await deploymentService.list();
      setRecords(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const refresh = () => load();
    window.addEventListener('opsflow:data-changed', refresh);
    refreshConfig?.();
    userService
      .listDevOps()
      .then((list) =>
        setDevOpsNames(Object.fromEntries((list || []).map((u) => [u.id, u.name])))
      )
      .catch(() => {});
    return () => window.removeEventListener('opsflow:data-changed', refresh);
  }, []);

  useEffect(() => {
    if (params.get('new') === '1') {
      if (canCreateDeployment) setCreateOpen(true);
      const next = new URLSearchParams(params);
      next.delete('new');
      setParams(next, { replace: true });
    }
  }, [params]);

  // Application filter (last item of the filter row). Default = all applications.
  // Kept in the URL like the status filter:  /deployments?app=PG-Desk
  const appFilter = params.get('app') || '';
  function changeApp(value) {
    const next = new URLSearchParams(params);
    if (value) next.set('app', value);
    else next.delete('app');
    setParams(next);
  }
  const appOptions = useMemo(() => {
    const names = [...(config?.applications || [])];
    records.forEach((r) => {
      if (r.Project && !names.some((n) => n.toLowerCase() === String(r.Project).toLowerCase())) names.push(r.Project);
    });
    return names;
  }, [config, records]);

  const filtered = useMemo(() => {
    return records.filter(
      (r) =>
        statusFilter.matches(r.Status) &&
        (!appFilter || String(r.Project || '').toLowerCase() === appFilter.toLowerCase())
    );
  }, [records, statusFilter.selected, appFilter]);

  return (
    <div className="space-y-5 animate-fade-in">

      <div className="flex flex-wrap items-center justify-between gap-3">

        <div>
          <h1 className="text-xl font-bold text-ink-900 flex items-center gap-3">
            <BackArrow />{canCreateDeployment ? 'My Deployment Requests' : 'Deployment Requests'}
          </h1>

          <p className="text-sm text-ink-400 mt-0.5">
            {canCreateDeployment
              ? 'Only the deployments you requested are shown here.'
              : 'Track deployments from request through rollout.'}
          </p>
        </div>

        {canCreateDeployment && (
          <Button onClick={() => setCreateOpen(true)}>
            + New Deployment
          </Button>
        )}
      </div>


      <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => statusFilter.toggle(s)}
            className={`
              shrink-0
              px-3
              py-1.5
              rounded-lg
              text-xs
              font-semibold
              border
              transition-colors

              ${
                statusFilter.isActive(s)
                  ? 'bg-ink-900 text-white border-ink-900'
                  : 'bg-white text-ink-600 border-ink-200 hover:bg-ink-50'
              }
            `}
          >
            {s === 'ALL'
              ? 'All'
              : s.replaceAll('_', ' ')}
          </button>
        ))}

        {/* Application filter — last in the row, default "All applications" */}
        <select
          value={appFilter}
          onChange={(e) => changeApp(e.target.value)}
          aria-label="Filter by application"
          title="Filter by application"
          className="shrink-0 ml-1 px-3 py-1.5 rounded-lg text-xs font-semibold border border-ink-200 bg-white text-ink-600 hover:bg-ink-50 focus:outline-none focus:border-brand-500"
        >
          <option value="">All applications</option>
          {appOptions.map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
      </div>


      {error ? (
        <ErrorState
          message={error}
          onRetry={load}
        />
      ) : (
        <Card className="overflow-hidden">

          <div
            className="
              hidden
              md:flex
              px-4
              py-2.5
              border-b
              border-ink-100
              text-[11px]
              font-semibold
              uppercase
              tracking-wide
              text-ink-400
            "
          >
            <span className="w-32">
              ID
            </span>

            <span className="flex-1">
              Project / Env
            </span>

            <span className="w-40">
              Requested
            </span>

            <span className="w-36">
              Assigned DevOps
            </span>

            <span className="w-32">
              Status
            </span>
          </div>


          <div className="divide-y divide-ink-100">

            {loading &&
              Array.from({ length: 5 }).map((_, i) => (
                <SkeletonRow key={i} />
              ))}


            {!loading &&
              filtered.length === 0 && (
                <EmptyState
                  icon="🚀"
                  title="No deployment requests"
                  description="Create one to get started."
                />
              )}


            {!loading &&
              filtered.map((r) => (
                <button
                  key={r['Record ID']}
                  type="button"
                  onClick={() =>
                    navigate(
                      `/deployments/${r['Record ID']}`
                    )
                  }
                  className="
                    w-full
                    text-left
                    px-4
                    py-3
                    flex
                    flex-col
                    md:flex-row
                    md:items-center
                    gap-1.5
                    md:gap-3
                    hover:bg-ink-50
                  "
                >

                  <span className="md:w-32">
                    <RecordIdBadge
                      id={r['Record ID']}
                    />
                  </span>


                  <span
                    className="
                      flex-1
                      text-sm
                      text-ink-900
                      font-medium
                    "
                  >
                    {r.Project}

                    <span
                      className="
                        text-ink-400
                        font-normal
                      "
                    >
                      {' '}
                      · {r.Environment}
                    </span>
                  </span>


                  <span
                    className="
                      md:w-40
                      text-xs
                      text-ink-400
                      font-mono
                    "
                  >
                    {r.DateTime
                      ? new Date(
                          r.DateTime
                        ).toLocaleString()
                      : '—'}
                  </span>


                  <span className="md:w-36 text-xs text-ink-600 truncate">
                    {r.AssignedDevOpsID
                      ? devOpsNames[r.AssignedDevOpsID] || r.AssignedDevOpsID
                      : '—'}
                  </span>

                  <span className="md:w-32">
                    <StatusBadge
                      status={r.Status}
                    />
                  </span>

                </button>
              ))}
          </div>
        </Card>
      )}


      <DeploymentRequestModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={load}
        config={config}
      />

    </div>
  );
}


// ---------- Environment variable input (upload .env OR key & value) ----------


const envInputCls =
  'w-full border border-ink-200 rounded-lg px-3 py-2 text-sm font-mono ' +
  'focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none';
const MAX_ENV_FILES = 3;

const newEnvRow = () => ({
  id: `envvar_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
  key: '',
  value: '',
});

/**
 * Parse the text of a .env file into [{ id, key, value }].
 * Skips blank lines and # comments, supports `export KEY=value`,
 * and strips matching surrounding quotes from the value.
 */
function parseEnvText(text) {
  const rows = [];

  String(text || '')
    .replace(/^\uFEFF/, '')
    .split(/\r?\n/)
    .forEach((rawLine) => {
      let line = rawLine.trim();
      if (!line || line.startsWith('#')) return;

      if (line.startsWith('export ')) line = line.slice(7).trim();

      const eq = line.indexOf('=');
      if (eq <= 0) return;

      const key = line.slice(0, eq).trim();
      let value = line.slice(eq + 1).trim();

      if (
        value.length >= 2 &&
        ((value.startsWith('"') && value.endsWith('"')) ||
          (value.startsWith("'") && value.endsWith("'")))
      ) {
        value = value.slice(1, -1);
      }

      rows.push({ ...newEnvRow(), key, value });
    });

  return rows;
}

/**
 * Environment variable input with two options:
 *   1. "Upload .env file"  -> user picks a file, it is parsed into key/value rows
 *   2. "Key & Value"       -> user types KEY and value rows manually
 *
 * Controlled component:
 *   mode      : 'file' | 'keyvalue'
 *   rows      : [{ id, key, value }]
 *   fileName  : name of the uploaded file ('' when none)
 *   onChange  : (patch) => void   patch may contain { mode, rows, fileName }
 */
function EnvVarInput({ mode, rows, file, onChange }) {
  const [error, setError] = useState('');
  const [reading, setReading] = useState(false);

  function switchMode(next) {
    if (next === mode) return;
    setError('');
    // Each option starts clean so the two inputs never mix.
    onChange({ mode: next, rows: [newEnvRow()], files: [] });
  }

  // Any file type is accepted — files are attached as-is (not parsed).
  async function handleFile(e) {
    const picked = Array.from(e.target.files || []);
    e.target.value = '';
    if (picked.length === 0) return;
    setError('');
    const room = MAX_ENV_FILES - file.length;
    if (room <= 0) {
      setError(`You can upload at most ${MAX_ENV_FILES} environment variable files.`);
      return;
    }
    const chosen = picked.slice(0, room);
    setReading(true);
    try {
      const attachments = [];
      for (const f of chosen) attachments.push(await fileToAttachment(f));
      onChange({ files: [...file, ...attachments] });
      if (picked.length > room) {
        setError(`Only ${MAX_ENV_FILES} files are allowed — the extra ${picked.length - room} file(s) were not added.`);
      }
    } catch (err) {
      setError(err.message || 'Could not read file.');
    } finally {
      setReading(false);
    }
  }

  function removeFile(index) {
    setError('');
    onChange({ files: file.filter((_, i) => i !== index) });
  }

  function setRow(id, field, value) {
    onChange({
      rows: rows.map((r) => (r.id === id ? { ...r, [field]: value } : r)),
    });
  }

  function addRow() {
    onChange({ rows: [...rows, newEnvRow()] });
  }

  function removeRow(id) {
    if (rows.length <= 1) return;
    onChange({ rows: rows.filter((r) => r.id !== id) });
  }

  const tab = (active) =>
    `flex-1 py-2 rounded-lg text-xs font-semibold border transition-colors ${
      active
        ? 'bg-ink-900 text-white border-ink-900'
        : 'bg-white text-ink-600 border-ink-200 hover:bg-ink-50'
    }`;

  return (
    <div className="space-y-3">
      {/* Option picker */}
      <div className="flex gap-1.5">
        <button
          type="button"
          onClick={() => switchMode('file')}
          className={tab(mode === 'file')}
        >
          📎 Upload a file
        </button>
        <button
          type="button"
          onClick={() => switchMode('keyvalue')}
          className={tab(mode === 'keyvalue')}
        >
          ⌨️ Key &amp; Value
        </button>
      </div>

      {/* Option 1 — Upload (any file) */}
      {mode === 'file' && (
        <div>
          {file.map((attachment, index) => (
            <div key={`${index}-${attachment.name}`} className="mb-2 flex items-center justify-between gap-2 border border-ink-200 rounded-lg px-3 py-2 text-sm bg-ink-50">
              <span className="truncate text-ink-800 font-sans">📄 {attachment.name}</span>
              <button
                type="button"
                onClick={() => removeFile(index)}
                className="text-xs font-semibold text-red-600 hover:text-red-700 shrink-0"
              >
                Remove
              </button>
            </div>
          ))}
          {file.length < MAX_ENV_FILES && (
            <label
              className={`${envInputCls} font-sans flex items-center justify-center gap-2 border-dashed text-ink-500 cursor-pointer hover:bg-ink-50`}
            >
              {reading ? 'Reading files…' : file.length ? '📎 Add another file' : '📎 Click to upload files'}
              <input
                type="file"
                multiple
                onChange={handleFile}
                disabled={reading}
                className="hidden"
              />
            </label>
          )}

          <p className="mt-1 text-[11px] text-ink-400 font-sans">
            {file.length} of {MAX_ENV_FILES} files · Any file type. Max 5MB each.
          </p>
        </div>
      )}

      {/* Option 2 — Key & Value */}
      {mode === 'keyvalue' && (
        <div className="space-y-2">
          {rows.map((row) => (
            <div key={row.id} className="flex items-center gap-2">
              <input
                value={row.key}
                onChange={(e) => setRow(row.id, 'key', e.target.value)}
                placeholder="KEY"
                className={envInputCls}
              />

              <input
                type="text"
                autoComplete="off"
                value={row.value}
                onChange={(e) => setRow(row.id, 'value', e.target.value)}
                placeholder="value"
                className={envInputCls}
              />

              <button
                type="button"
                onClick={() => removeRow(row.id)}
                disabled={rows.length === 1}
                className="shrink-0 w-8 h-8 flex items-center justify-center rounded-lg border border-ink-200 text-ink-500 hover:bg-red-50 hover:text-red-600 hover:border-red-300 disabled:opacity-30 disabled:cursor-not-allowed"
              >
                ×
              </button>
            </div>
          ))}

          <button
            type="button"
            onClick={addRow}
            className="w-full py-2 rounded-lg border border-dashed border-ink-200 text-xs font-semibold text-brand-600 hover:bg-brand-50 hover:border-brand-300"
          >
            + Add Key
          </button>
        </div>
      )}

      {error && <p className="text-[11px] text-danger">{error}</p>}
    </div>
  );
}

const EMPTY_ENV_VAR_ROW = newEnvRow;

const GITHUB_URL_SUGGESTION = 'https://github.com/1988techie/';
const newPairRow = () => ({
  id: `pair_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
  key: '',
  value: '',
});
// Everything that only exists for a Backend deployment (cleared when switching to Frontend).
const backendOnlyReset = () => ({
  dbChange: false,
  dbChangeDetails: '',
  dbChangeFileName: '',
  dbChangeFileData: '',
  dbFiles: [],
  thirdPartyApiChange: false,
  thirdPartyApiDetails: '',
  thirdPartyFile: null,
  thirdPartyPairs: [newPairRow()],
  thirdPartyTab: 'text',
  envVarChange: false,
  envVarMode: 'keyvalue',
  envFiles: [],
  envVars: [EMPTY_ENV_VAR_ROW()],
});

function emptyDeploymentForm() {
  return {
    project: '',
    component: 'Frontend',
    environment: 'PROD',
    dateTime: minDateTimeLocal(),
    githubUrl: '',
    githubBranch: '',
    appVersion: '',
    githubCommit: '',
    rollbackBranch: '',

    ...backendOnlyReset(),

    applicationChangeDetails: '',
    additionalInfo: '',
    assignedDevOpsId: '',
  };
}

function formFromDeploymentRecord(record) {
  const parsedDate = record.DateTime ? new Date(record.DateTime) : null;
  const pad = (value) => String(value).padStart(2, '0');
  const dateTime = parsedDate && !Number.isNaN(parsedDate.getTime())
    ? `${parsedDate.getFullYear()}-${pad(parsedDate.getMonth() + 1)}-${pad(parsedDate.getDate())}T${pad(parsedDate.getHours())}:${pad(parsedDate.getMinutes())}`
    : '';
  const scheduledDateTime = dateTime && dateTime >= minDateTimeLocal()
    ? dateTime
    : minDateTimeLocal();
  let attachments = {};
  try {
    attachments = record.Attachments ? JSON.parse(record.Attachments) : {};
  } catch {
    attachments = {};
  }
  let envVars = [];
  try {
    const parsed = record.EnvVarDetails ? JSON.parse(record.EnvVarDetails) : [];
    if (Array.isArray(parsed)) envVars = parsed.map((row) => ({ ...newEnvRow(), ...row }));
  } catch {
    envVars = [];
  }
  const envFiles = attachments.envFiles || (attachments.envFile ? [attachments.envFile] : []);
  const dbFiles = attachments.dbFiles || (
    record.DBChangeFileData && record.DBChangeFileName
      ? [{ name: record.DBChangeFileName, data: record.DBChangeFileData }]
      : []
  );
  const thirdPartyFile = attachments.thirdPartyFiles?.[0] || null;
  const thirdPartyPairs = (attachments.thirdPartyPairs || []).map((pair) => ({ ...newPairRow(), ...pair }));
  return {
    ...emptyDeploymentForm(),
    project: record.Project || '',
    component: record.Component || 'Frontend',
    environment: record.Environment || 'PROD',
    dateTime: scheduledDateTime,
    githubUrl: record.GitHubURL || '',
    githubBranch: record.GitHubBranch || '',
    githubCommit: record.GitHubCommit || '',
    rollbackBranch: record.RollbackBranch || '',
    dbChange: String(record.DBChange) === 'true',
    dbChangeDetails: record.DBChangeDetails || '',
    dbChangeFileName: record.DBChangeFileName || '',
    dbChangeFileData: record.DBChangeFileData || '',
    dbFiles,
    thirdPartyApiChange: String(record.ThirdPartyAPIChange) === 'true',
    thirdPartyApiDetails: record.ThirdPartyAPIDetails || '',
    thirdPartyFile,
    thirdPartyPairs: thirdPartyPairs.length ? thirdPartyPairs : [newPairRow()],
    thirdPartyTab: thirdPartyFile ? 'file' : thirdPartyPairs.length ? 'pairs' : 'text',
    envVarChange: String(record.EnvVarChange) === 'true',
    envVarMode: envFiles.length && !envVars.length ? 'file' : 'keyvalue',
    envFiles,
    envVars: envVars.length ? envVars : [EMPTY_ENV_VAR_ROW()],
    applicationChangeDetails: record.ApplicationChangeDetails || '',
    additionalInfo: record.AdditionalInfo || '',
  };
}

function minDateTimeLocal() {
  const d = new Date();
  d.setSeconds(0, 0);
  d.setMinutes(d.getMinutes() + 1);
  const minutesUntilQuarterHour = (15 - (d.getMinutes() % 15)) % 15;
  d.setMinutes(d.getMinutes() + minutesUntilQuarterHour);
  const pad = (n) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024; // 5MB

export function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error('Could not read file.'));
    reader.readAsDataURL(file);
  });
}

// ---------- Third Party API details: Text (max 250 words) | Upload a file | Key & Values ----------

function ThirdPartyApiInput({ form, set }) {
  const tab = form.thirdPartyTab || 'text';
  const pairs = form.thirdPartyPairs;

  const filled = {
    text: !!form.thirdPartyApiDetails.trim(),
    file: !!form.thirdPartyFile,
    pairs: pairs.some((p) => p.key.trim()),
  };

  const tabCls = (active) =>
    `flex-1 py-2 rounded-lg text-xs font-semibold border transition-colors ${
      active
        ? 'bg-ink-900 text-white border-ink-900'
        : 'bg-white text-ink-600 border-ink-200 hover:bg-ink-50'
    }`;
  const dot = (on) => (on ? <span className="ml-1 text-green-500">●</span> : null);

  function setPair(id, field, value) {
    set('thirdPartyPairs', pairs.map((p) => (p.id === id ? { ...p, [field]: value } : p)));
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-1.5">
        <button type="button" onClick={() => set('thirdPartyTab', 'text')} className={tabCls(tab === 'text')}>
          📝 Text{dot(filled.text)}
        </button>
        <button type="button" onClick={() => set('thirdPartyTab', 'file')} className={tabCls(tab === 'file')}>
          📎 Upload a file{dot(filled.file)}
        </button>
        <button type="button" onClick={() => set('thirdPartyTab', 'pairs')} className={tabCls(tab === 'pairs')}>
          ⌨️ Key &amp; Values{dot(filled.pairs)}
        </button>
      </div>

      {tab === 'text' && (
        <WordLimitTextarea
          value={form.thirdPartyApiDetails}
          onChange={(v) => set('thirdPartyApiDetails', v)}
          limit={250}
          rows={3}
          placeholder="Which third-party API(s) are affected and how?"
        />
      )}

      {tab === 'file' && (
        <div>
          {form.thirdPartyFile ? (
            <div className="flex items-center justify-between gap-2 border border-ink-200 rounded-lg px-3 py-2 text-sm bg-ink-50">
              <span className="truncate text-ink-800">📄 {form.thirdPartyFile.name}</span>
              <button
                type="button"
                onClick={() => set('thirdPartyFile', null)}
                className="text-xs font-semibold text-red-600 hover:text-red-700 shrink-0"
              >
                Remove
              </button>
            </div>
          ) : (
            <label className={`${inputCls} flex items-center justify-center gap-2 border-dashed text-ink-500 cursor-pointer hover:bg-ink-50`}>
              📎 Click to upload a file
              <input
                type="file"
                className="hidden"
                onChange={async (e) => {
                  const f = e.target.files?.[0];
                  e.target.value = '';
                  if (!f) return;
                  try {
                    set('thirdPartyFile', await fileToAttachment(f));
                  } catch (err) {
                    window.alert(err.message);
                  }
                }}
              />
            </label>
          )}
          <p className="mt-1 text-[11px] text-ink-400">Any file type. Max 5MB.</p>
        </div>
      )}

      {tab === 'pairs' && (
        <div className="space-y-2">
          {pairs.map((p) => (
            <div key={p.id} className="flex items-center gap-2">
              <input
                value={p.key}
                onChange={(e) => setPair(p.id, 'key', e.target.value)}
                placeholder="KEY"
                className={envInputCls}
              />
              <input
                autoComplete="off"
                value={p.value}
                onChange={(e) => setPair(p.id, 'value', e.target.value)}
                placeholder="value"
                className={envInputCls}
              />
              <button
                type="button"
                disabled={pairs.length === 1}
                onClick={() => set('thirdPartyPairs', pairs.filter((x) => x.id !== p.id))}
                className="shrink-0 w-8 h-8 flex items-center justify-center rounded-lg border border-ink-200 text-ink-500 hover:bg-red-50 hover:text-red-600 hover:border-red-300 disabled:opacity-30 disabled:cursor-not-allowed"
              >
                ×
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={() => set('thirdPartyPairs', [...pairs, newPairRow()])}
            className="w-full py-2 rounded-lg border border-dashed border-ink-200 text-xs font-semibold text-brand-600 hover:bg-brand-50 hover:border-brand-300"
          >
            + Add Key
          </button>
        </div>
      )}

      <p className="text-[11px] text-ink-400">
        Fill in at least one of the three options. A green dot means that option has content.
      </p>
    </div>
  );
}

export function DeploymentRequestModal({
  open,
  onClose,
  onCreated,
  config,
  initialRecord = null,
}) {
  const toast = useToast();
  const { user } = useAuth();

  const canAssignDevOps = user?.role === 'DevOps';

  const [form, setForm] = useState(emptyDeploymentForm());

  const email = useEmailNotify(open, { mandatory: true });

  const [loading, setLoading] = useState(false);
  const [conflict, setConflict] = useState(null);

  const [devOpsUsers, setDevOpsUsers] = useState([]);
  const [devOpsLoading, setDevOpsLoading] = useState(false);

  const [githubSuggestionOpen, setGithubSuggestionOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    setForm(initialRecord ? formFromDeploymentRecord(initialRecord) : emptyDeploymentForm());
    setConflict(null);
  }, [open, initialRecord?.['Record ID']]);

  useEffect(() => {
    if (!open || !canAssignDevOps) return;

    let active = true;

    setDevOpsLoading(true);

    userService
      .listDevOps()
      .then((users) => {
        if (active) {
          setDevOpsUsers(users || []);
        }
      })
      .catch((err) => {
        toast.error(err.message);
      })
      .finally(() => {
        if (active) {
          setDevOpsLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [open, canAssignDevOps]);

  function set(key, value) {
    setForm((current) => ({
      ...current,
      [key]: value,
    }));
  }

  // Voice assistant ("Hello Ops, create a deployment") fills this form while it is open.
  // It can never submit: only the Submit Request button below does that.
  useVoiceForm('DEPLOYMENT', {
    open,
    form,
    reset: () => {
      setForm(emptyDeploymentForm());
      setConflict(null);
    },
    close: onClose,
    apply: (patch) =>
      setForm((current) => {
        const { envVarsAdd, ...rest } = patch;
        const next = { ...current, ...rest };
        if (rest.component === 'Frontend') {
          Object.assign(next, backendOnlyReset());
        }
        if (Array.isArray(envVarsAdd) && envVarsAdd.length) {
          const kept = next.envVars.filter((r) => r.key || r.value);
          next.envVarMode = 'keyvalue';
          next.envFiles = [];
          next.envVars = [...kept, ...envVarsAdd.map((r) => ({ ...newEnvRow(), key: r.key, value: r.value }))];
        }
        return next;
      }),
  });

  async function submit(e) {
    e.preventDefault();

    if (!/T\d\d:\d\d$/.test(form.dateTime || '')) {
      toast.error('Please select both the deployment date and time.');
      return;
    }

    if (form.dateTime && form.dateTime < minDateTimeLocal()) {
      toast.error(
        'Deployment date & time cannot be in the past. Please pick the current date/time or later.'
      );
      return;
    }

    if (!form.project) return toast.error('Project / App is required.');
    if (!form.dateTime) return toast.error('Date & Time is required.');
    if (!form.githubUrl.trim()) return toast.error('GitHub Repository URL is required.');
    if (!form.githubBranch.trim()) return toast.error('GitHub Branch is required.');

    if (countWords(form.applicationChangeDetails) > 500) {
      return toast.error('Application Change Details must be 500 words or fewer.');
    }
    if (countWords(form.additionalInfo) > 500) {
      return toast.error('Additional Information must be 500 words or fewer.');
    }

    if (form.component === 'Backend') {
      if (form.dbChange && form.dbFiles.length === 0) {
        return toast.error('Please upload the DB / Schema change file(s).');
      }

      if (form.thirdPartyApiChange) {
        if (countWords(form.thirdPartyApiDetails) > 250) {
          return toast.error('Third Party API text must be 250 words or fewer.');
        }
        const pairs = form.thirdPartyPairs.filter((p) => p.key.trim());
        if (pairs.some((p) => !p.value.trim())) {
          return toast.error('Every Third Party API key needs a value.');
        }
        if (!form.thirdPartyApiDetails.trim() && !form.thirdPartyFile && pairs.length === 0) {
          return toast.error('Please add the Third Party API details (text, a file, or key & values).');
        }
      }

      if (form.envVarChange) {
        if (form.envVarMode === 'file') {
          if (!form.envFiles.length) return toast.error('Please upload at least one environment variable file.');
          if (form.envFiles.length > MAX_ENV_FILES) return toast.error(`You can upload at most ${MAX_ENV_FILES} environment variable files.`);
        } else {
          const filled = form.envVars.filter((r) => r.key.trim());
          if (filled.length === 0) {
            return toast.error('Please add at least one environment variable.');
          }
          if (filled.some((r) => !r.value.trim())) {
            return toast.error('Every environment variable needs a value.');
          }
        }
      }
    }

    const emailError = email.validate();
    if (emailError) return toast.error(emailError);

    setLoading(true);

    try {
      const envVarDetails = JSON.stringify(
        form.envVarMode === 'file'
          ? []
          : form.envVars
              .filter((row) => row.key.trim() || row.value.trim())
              .map((row) => ({ key: row.key.trim(), value: row.value }))
      );

      const backend = form.component === 'Backend';
      const attachments = {
        ...(backend && form.dbChange && form.dbFiles.length ? { dbFiles: form.dbFiles } : {}),
        ...(backend && form.thirdPartyApiChange && form.thirdPartyFile ? { thirdPartyFiles: [form.thirdPartyFile] } : {}),
        ...(backend && form.thirdPartyApiChange
          ? { thirdPartyPairs: form.thirdPartyPairs.filter((p) => p.key.trim()).map((p) => ({ key: p.key.trim(), value: p.value })) }
          : {}),
        ...(backend && form.envVarChange && form.envVarMode === 'file' && form.envFiles.length ? { envFiles: form.envFiles } : {}),
      };

      const payload = {
        ...form,
        envVarDetails,
        attachments,
        dbChangeFileName: form.dbFiles.map((f) => f.name).join(', ').slice(0, 255),
        assignedDevOpsId: canAssignDevOps
          ? form.assignedDevOpsId
          : '',
      };
      delete payload.envVars;
      delete payload.envVarMode;
      delete payload.dbFiles;
      delete payload.thirdPartyFile;
      delete payload.thirdPartyPairs;
      delete payload.thirdPartyTab;
      delete payload.envFiles;
      const res = initialRecord
        ? await deploymentService.resubmit(initialRecord['Record ID'], payload, email.options())
        : await deploymentService.create(payload, email.options());

      if (res.conflict) {
        setConflict(
          res.conflict.message
        );
      }

      toast.success(
        initialRecord
          ? `${res.record['Record ID']} resubmitted.${emailResultText(res)}`
          : `${res.record['Record ID']} created.${emailResultText(res)}`
      );

      if (!initialRecord) voiceForms.submitted('DEPLOYMENT', res.record['Record ID']);
      onCreated();
      onClose();

      setForm(emptyDeploymentForm());
      email.reset();

    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={initialRecord ? `Edit & Resubmit ${initialRecord['Record ID']}` : 'New Deployment Request'}
      width="max-w-[1400px]"
      variant="brand"
      footer={
        <EmailNotifyFooter email={email} open={open}>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" form="deployment-request-form" loading={loading}>
              {initialRecord ? 'Resubmit Request' : 'Submit Request'}
            </Button>
          </div>
        </EmailNotifyFooter>
      }
    >
      {conflict && (
        <div
          className="
            mb-3
            text-xs
            bg-warning-bg
            text-warning-text
            rounded-lg
            px-3
            py-2
          "
        >
          ⚠️ Potential deployment conflict —{' '}
          {conflict}
        </div>
      )}

      <form
        id="deployment-request-form"
        className="space-y-4"
        onSubmit={submit}
      >

        <div className="grid grid-cols-2 gap-3">
          <Field
            label="Project / App"
            required
          >
            <select
              required
              value={form.project}
              onChange={(e) =>
                set(
                  'project',
                  e.target.value
                )
              }
              className={inputCls}
            >
              <option value="">
                Select…
              </option>

              {(config?.applications || []).map(
                (application) => (
                  <option
                    key={application}
                    value={application}
                  >
                    {application}
                  </option>
                )
              )}
            </select>
          </Field>

          <Field
            label="Frontend / Backend"
            required
          >
            <select
              value={form.component}
              onChange={(e) => {
                const nextComponent = e.target.value;

                setForm((current) => ({
                  ...current,
                  component: nextComponent,
                  ...(nextComponent === 'Frontend' ? backendOnlyReset() : {}),
                }));
              }}
              className={inputCls}
            >
              <option>
                Frontend
              </option>

              <option>
                Backend
              </option>
            </select>
          </Field>

          <Field
            label="Environment"
            required
          >
            <select
              value={form.environment}
              onChange={(e) =>
                set(
                  'environment',
                  e.target.value
                )
              }
              className={inputCls}
            >
              {(config?.environments || []).map(
                (environment) => (
                  <option
                    key={environment}
                    value={environment}
                  >
                    {environment}
                  </option>
                )
              )}
            </select>
          </Field>

          <Field
            label="Date & Time"
            required
          >
            <FutureDateTime
              value={form.dateTime}
              onChange={(v) => set('dateTime', v)}
            />
            <p className="mt-1 text-[11px] text-ink-400">
              Past dates and past times are hidden — only the current time or later can be selected.
            </p>
          </Field>

        </div>

        <Field label="GitHub Repository URL" required>
          <div className="relative">
            <input
              required
              type="text"
              autoComplete="off"
              value={form.githubUrl}
              onFocus={() => setGithubSuggestionOpen(true)}
              onBlur={() => setGithubSuggestionOpen(false)}
              onChange={(e) => set('githubUrl', e.target.value)}
              placeholder="Enter repository URL"
              className={inputCls}
            />
            {githubSuggestionOpen && (
              <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-lg border border-ink-200 bg-white shadow-lg">
                <button
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => {
                    set('githubUrl', GITHUB_URL_SUGGESTION);
                    setGithubSuggestionOpen(false);
                  }}
                  className="w-full px-3 py-2 text-left text-sm text-ink-700 hover:bg-brand-50"
                >
                  {GITHUB_URL_SUGGESTION}
                </button>
              </div>
            )}
          </div>
        </Field>

        <div className="grid grid-cols-2 gap-3">

          <Field label="GitHub Branch" required>
            <input
              required
              value={form.githubBranch}
              onChange={(e) =>
                set(
                  'githubBranch',
                  e.target.value
                )
              }
              placeholder="Branch name"
              className={inputCls}
            />
          </Field>

          <Field label="Application Version">
            <input
              value={form.appVersion}
              onChange={(e) =>
                set(
                  'appVersion',
                  e.target.value
                )
              }
              placeholder="e.g. v1.0"
              className={inputCls}
            />
          </Field>

        </div>

        <div className="grid grid-cols-2 gap-3">

          <Field label="Commit ID">
            <input
              value={form.githubCommit}
              onChange={(e) =>
                set(
                  'githubCommit',
                  e.target.value
                )
              }
              placeholder="e.g. a1b2c3d"
              className={`${inputCls} font-mono`}
            />
          </Field>

          <Field label="Rollback Branch">
            <input
              value={form.rollbackBranch}
              onChange={(e) =>
                set(
                  'rollbackBranch',
                  e.target.value
                )
              }
              placeholder="Branch to roll back to if this deployment fails"
              className={`${inputCls} font-mono`}
            />
          </Field>

        </div>

        {form.component === 'Backend' && (
          <>
            <ToggleField
              label="DB / Schema Change"
              required
              value={form.dbChange}
              onChange={(value) =>
                set(
                  'dbChange',
                  value
                )
              }
            />

            {form.dbChange && (
              <Field label="DB / Schema Change Files (up to 10)" required>
                <MultiFileUpload
                  files={form.dbFiles}
                  onChange={(files) => set('dbFiles', files)}
                  max={10}
                />
              </Field>
            )}

            <ToggleField
              label="Third Party API Change"
              required
              value={form.thirdPartyApiChange}
              onChange={(value) =>
                set(
                  'thirdPartyApiChange',
                  value
                )
              }
            />

            {form.thirdPartyApiChange && (
              <Field label="Third Party API Details" required>
                <ThirdPartyApiInput form={form} set={set} />
              </Field>
            )}

            <ToggleField
              label="Environment Variable Change"
              required
              value={form.envVarChange}
              onChange={(value) =>
                setForm((current) => ({
                  ...current,
                  envVarChange: value,
                  ...(value
                    ? {}
                    : {
                        envVarMode: 'keyvalue',
                        envFiles: [],
                        envVars: [EMPTY_ENV_VAR_ROW()],
                      }),
                }))
              }
            />

            {form.envVarChange && (
              <Field label="Environment Variable Details" required>
                <EnvVarInput
                  mode={form.envVarMode}
                  rows={form.envVars}
                  file={form.envFiles}
                  onChange={(patch) =>
                    setForm((current) => ({
                      ...current,
                      ...(patch.mode !== undefined && { envVarMode: patch.mode }),
                      ...(patch.rows !== undefined && { envVars: patch.rows }),
                      ...(patch.files !== undefined && { envFiles: patch.files }),
                    }))
                  }
                />
              </Field>
            )}
          </>
        )}

        {canAssignDevOps && (
          <DevOpsPicker
            users={devOpsUsers}
            loading={devOpsLoading}
            value={form.assignedDevOpsId}
            onChange={(value) =>
              set(
                'assignedDevOpsId',
                value
              )
            }
          />
        )}

        <Field label="Application Change Details">
          <WordLimitTextarea
            value={form.applicationChangeDetails}
            onChange={(v) => set('applicationChangeDetails', v)}
            limit={500}
            rows={3}
          />
        </Field>

        <Field label="Additional Information">
          <WordLimitTextarea
            value={form.additionalInfo}
            onChange={(v) => set('additionalInfo', v)}
            limit={500}
            rows={3}
          />
        </Field>

      </form>
    </Modal>
  );
}


function DevOpsPicker({
  users,
  loading,
  value,
  onChange,
}) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);

  const selected =
    users.find(
      (user) => user.id === value
    );

  const filtered =
    users.filter((user) =>
      [
        user.name,
        user.email,
        user.mobile,
      ].some((field) =>
        String(field || '')
          .toLowerCase()
          .includes(
            query.toLowerCase()
          )
      )
    );

  return (
    <Field label="Assigned DevOps">

      <div className="relative">

        <button
          type="button"
          onClick={() =>
            setOpen((current) => !current)
          }
          className={`
            ${inputCls}
            text-left
            flex
            items-center
            justify-between
            gap-2
            bg-white
          `}
        >

          <span
            className={
              selected
                ? 'text-ink-900'
                : 'text-ink-400'
            }
          >
            {selected
              ? selected.name
              : 'Select a DevOps person…'}
          </span>

          <span className="text-ink-400">
            ⌄
          </span>

        </button>

        {open && (
          <div
            className="
              absolute
              z-40
              mt-1
              w-full
              bg-white
              border
              border-ink-200
              rounded-xl2
              shadow-popover
              overflow-hidden
            "
          >

            <div
              className="
                p-2
                border-b
                border-ink-100
              "
            >
              <input
                autoFocus
                value={query}
                onChange={(e) =>
                  setQuery(
                    e.target.value
                  )
                }
                placeholder="Search name, email or mobile…"
                className={inputCls}
              />
            </div>

            <div
              className="
                max-h-52
                overflow-y-auto
              "
            >

              <button
                type="button"
                onClick={() => {
                  onChange('');
                  setOpen(false);
                }}
                className="
                  w-full
                  text-left
                  px-3
                  py-2.5
                  text-xs
                  text-ink-500
                  hover:bg-ink-50
                "
              >
                Unassigned
              </button>

              {loading && (
                <div
                  className="
                    px-3
                    py-3
                    text-xs
                    text-ink-400
                  "
                >
                  Loading DevOps users…
                </div>
              )}

              {!loading &&
                filtered.length === 0 && (
                  <div
                    className="
                      px-3
                      py-3
                      text-xs
                      text-ink-400
                    "
                  >
                    No matching active
                    DevOps users.
                  </div>
                )}

              {!loading &&
                filtered.map((user) => (
                  <button
                    type="button"
                    key={user.id}
                    onClick={() => {
                      onChange(user.id);
                      setOpen(false);
                      setQuery('');
                    }}
                    className="
                      w-full
                      text-left
                      px-3
                      py-2.5
                      hover:bg-brand-50
                      border-t
                      border-ink-100
                    "
                  >

                    <p
                      className="
                        text-sm
                        font-medium
                        text-ink-900
                      "
                    >
                      {user.name}
                    </p>

                    <p
                      className="
                        text-[11px]
                        text-ink-400
                      "
                    >
                      {user.email}

                      {user.mobile
                        ? ` · ${user.mobile}`
                        : ''}
                    </p>

                  </button>
                ))}
            </div>

          </div>
        )}

      </div>
    </Field>
  );
}


export const inputCls = `
  w-full
  border
  border-ink-200
  rounded-lg
  px-3
  py-2
  text-sm
  focus:border-brand-500
  focus:ring-1
  focus:ring-brand-500
  outline-none
`;


export function Field({
  label,
  required,
  children,
}) {
  return (
    <div>

      <label
        className="
          block
          text-xs
          font-medium
          text-ink-600
          mb-1.5
        "
      >
        {label}{' '}

        {required && (
          <span className="text-danger">
            *
          </span>
        )}

      </label>

      {children}

    </div>
  );
}


export function ToggleField({
  label,
  value,
  onChange,
  required,
}) {
  return (
    <div>

      <label
        className="
          block
          text-xs
          font-medium
          text-ink-600
          mb-1.5
        "
      >
        {label}{required && <span className="text-danger"> *</span>}
      </label>

      <div className="flex gap-1.5">

        <button
          type="button"
          onClick={() => onChange(true)}
          className={`
            flex-1
            py-2
            rounded-lg
            text-xs
            font-semibold
            border
            transition-all
            duration-150
            focus:outline-none

            ${
              value
                ? `
                  bg-blue-600
                  text-white
                  border-blue-600
                  shadow-sm
                `
                : `
                  bg-blue-50
                  text-blue-700
                  border-blue-200
                  hover:bg-blue-100
                  hover:border-blue-300
                `
            }
          `}
        >
          Yes
        </button>

        <button
          type="button"
          onClick={() => onChange(false)}
          className={`
            flex-1
            py-2
            rounded-lg
            text-xs
            font-semibold
            border
            transition-all
            duration-150
            focus:outline-none

            ${
              !value
                ? `
                  bg-red-100
                  text-red-700
                  border-red-300
                  shadow-sm
                  hover:bg-red-600
                  hover:text-white
                  hover:border-red-600
                `
                : `
                  bg-white
                  text-ink-500
                  border-ink-200
                  hover:bg-red-50
                  hover:text-red-600
                  hover:border-red-300
                `
            }
          `}
        >
          No
        </button>

      </div>
    </div>
  );
}