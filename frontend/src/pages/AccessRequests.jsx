import { useEffect, useMemo, useState } from 'react';
import { useStatusFilter } from '../hooks/useStatusFilter';
import BackArrow from '../components/ui/BackArrow';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { accessService } from '../api/accessService';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Modal from '../components/ui/Modal';
import { StatusBadge, RecordIdBadge } from '../components/ui/Badge';
import { SkeletonRow } from '../components/ui/Skeleton';
import EmptyState from '../components/ui/EmptyState';
import ErrorState from '../components/ui/ErrorState';
import EmailNotifyFooter, { useEmailNotify, emailResultText } from '../components/ui/EmailRecipients';
import { countWords, DatePicker, WordLimitTextarea } from '../components/ui/FormBits';
import { Field, inputCls } from './DeploymentRequests';
import { useVoiceForm } from '../voice/useVoiceForm';
import { voiceForms } from '../voice/voiceForms';

const STATUS_FILTERS = [
  'ALL',
  'REQUESTED',
  'APPROVED',
  'IN_PROGRESS',
  'ACCESS_GIVEN',
  'REJECTED'
];

// Fixed Access Type options for the request form (kept as-is per spec,
// independent of whatever is seeded in the ACCESS_TYPE config table).
const ACCESS_TYPES = [
  'AWS',
  'S3',
  'RDS',
  'IAM',
  'Database',
  'Server / EC2',
  'Kubernetes',
  'CI/CD',
  'Application',
  'Monitoring',
  'Cloud Console',
  'Other'
];

// Structured Access Level options (replaces the old free-text
// "Permission Needed" input with a fixed dropdown).
const ACCESS_LEVELS = [
  'Read Only',
  'Read / Write',
];

// Duration (Days) options — includes a "Custom" entry so the user can
// type any exact number of days instead of only picking a preset.
const DURATION_DAY_OPTIONS = [1, 3, 7, 15, 30, 60, 90];

function addDaysToNowLocal(days) {
  const now = new Date();
  const future = new Date(now.getTime() + days * 24 * 60 * 60 * 1000);
  const offset = future.getTimezoneOffset();
  const local = new Date(future.getTime() - offset * 60000);

  return local.toISOString().slice(0, 10);
}

function getCurrentDateTime() {
  const now = new Date();

  return now.toLocaleString('en-IN', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true
  });
}

function getCurrentDateLocal() {
  const now = new Date();
  const offset = now.getTimezoneOffset();
  const local = new Date(now.getTime() - offset * 60000);

  return local.toISOString().slice(0, 10);
}

export default function AccessRequests() {
  const [params, setParams] = useSearchParams();
  const statusFilter = useStatusFilter(params, setParams);
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);
  const navigate = useNavigate();
  const { config, refreshConfig, user } = useAuth();
  const isRequester = user?.role === 'Developer' || user?.role === 'QA';

  async function load() {
    setLoading(true);
    setError(null);

    try {
      setRecords(await accessService.list());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // Pick up applications an admin may have just added.
    refreshConfig?.();
    // Refresh when the voice assistant changes a status.
    const refresh = () => load();
    window.addEventListener('opsflow:data-changed', refresh);
    return () => window.removeEventListener('opsflow:data-changed', refresh);
  }, []);

  // Dashboard "+ New" menu links here with ?new=1 — open the create form.
  useEffect(() => {
    if (params.get('new') === '1') {
      if (true) setCreateOpen(true);
      const next = new URLSearchParams(params);
      next.delete('new');
      setParams(next, { replace: true });
    }
  }, [params]);

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
      if (r.Project && !names.some((name) => name.toLowerCase() === String(r.Project).toLowerCase())) {
        names.push(r.Project);
      }
    });
    return names;
  }, [config, records]);

  const filtered = useMemo(
    () => records.filter((r) =>
      statusFilter.matches(r.Status) &&
      (!appFilter || String(r.Project || '').toLowerCase() === appFilter.toLowerCase())
    ),
    [records, statusFilter.selected, appFilter]
  );

  function expiryLabel(r) {
    if (r.Status !== 'ACCESS_GIVEN' || !r.ExpiryDate) return null;

    const days = Math.ceil(
      (new Date(r.ExpiryDate).getTime() - Date.now()) / 86400000
    );

    if (days <= 0) {
      return (
        <span className="text-xs font-semibold text-danger">
          Expired
        </span>
      );
    }

    return (
      <span
        className={`text-xs font-semibold ${
          days <= 10 ? 'text-warning' : 'text-ink-400'
        }`}
      >
        {days} days remaining
      </span>
    );
  }

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-ink-900 flex items-center gap-3">
            <BackArrow />{isRequester ? 'My Access Requests' : 'Access Requests'}
          </h1>

          <p className="text-sm text-ink-400 mt-0.5">
            {isRequester
              ? 'Only the access requests you raised are shown here.'
              : 'RDS, IAM, EC2, S3, and other access grants.'}
          </p>
        </div>

        <Button onClick={() => setCreateOpen(true)}>
          + New Access Request
        </Button>
      </div>

      <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
        {STATUS_FILTERS.map(s => (
          <button
            key={s}
            onClick={() => statusFilter.toggle(s)}
            className={`shrink-0 px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors
            ${
              statusFilter.isActive(s)
                ? 'bg-ink-900 text-white border-ink-900'
                : 'bg-white text-ink-600 border-ink-200 hover:bg-ink-50'
            }`}
          >
            {s === 'ALL' ? 'All' : s.replaceAll('_', ' ')}
          </button>
        ))}
        <select
          value={appFilter}
          onChange={(e) => changeApp(e.target.value)}
          aria-label="Filter by application"
          title="Filter by application"
          className="shrink-0 ml-1 px-3 py-1.5 rounded-lg text-xs font-semibold border border-ink-200 bg-white text-ink-600 hover:bg-ink-50 focus:outline-none focus:border-brand-500"
        >
          <option value="">All applications</option>
          {appOptions.map((application) => (
            <option key={application} value={application}>{application}</option>
          ))}
        </select>
      </div>

      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : (
        <Card className="overflow-hidden">
          <div className="divide-y divide-ink-100">
            {loading &&
              Array.from({ length: 5 }).map((_, i) => (
                <SkeletonRow key={i} />
              ))}

            {!loading && filtered.length === 0 && (
              <EmptyState
                icon="🔑"
                title="No access requests"
              />
            )}

            {!loading &&
              filtered.map(r => (
                <button
                  key={r['Record ID']}
                  onClick={() =>
                    navigate(`/access/${r['Record ID']}`)
                  }
                  className="w-full text-left px-4 py-3 flex flex-col md:flex-row md:items-center gap-1.5 md:gap-3 hover:bg-ink-50"
                >
                  <span className="md:w-32">
                    <RecordIdBadge id={r['Record ID']} />
                  </span>

                  <span className="flex-1 text-sm text-ink-900 font-medium">
                    {r.AccessType}{' '}
                    <span className="text-ink-400 font-normal">
                      · {r.Project} · {r.Environment}
                    </span>
                  </span>

                  {expiryLabel(r)}

                  <span className="md:w-32">
                    <StatusBadge status={r.Status} />
                  </span>
                </button>
              ))}
          </div>
        </Card>
      )}

      <CreateAccessModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={load}
        config={config}
      />
    </div>
  );
}

function emptyAccessForm() {
  return {
    accessType: '',
    project: '',
    environment: 'PROD',
    requestedDateTime: getCurrentDateTime(),
    userResource: '',
    accessLevel: 'Read Only',
    customAccessLevel: '',
    durationDays: 7,
    customDays: '',
    reason: '',
    expiryDate: addDaysToNowLocal(7)
  };
}

function CreateAccessModal({
  open,
  onClose,
  onCreated,
  config
}) {
  const toast = useToast();

  const [form, setForm] = useState({
    accessType: '',
    project: '',
    environment: 'PROD',
    requestedDateTime: getCurrentDateTime(),
    userResource: '',
    accessLevel: 'Read Only',
    customAccessLevel: '',
    durationDays: 7,
    customDays: '',
    reason: '',
    expiryDate: addDaysToNowLocal(7)
  });

  const email = useEmailNotify(open, { mandatory: true });

  const [loading, setLoading] = useState(false);

  // Update current date/time whenever the modal is opened
  useEffect(() => {
    if (open) {
      const currentDisplayDateTime = getCurrentDateTime();

      setForm(f => ({
        ...f,
        requestedDateTime: currentDisplayDateTime,
        expiryDate: addDaysToNowLocal(
          f.durationDays === 'Custom' ? Number(f.customDays) || 0 : f.durationDays
        )
      }));
    }
  }, [open]);

  // Picking a preset number of days recalculates the expiry date
  // automatically. Picking "Custom" reveals a free-entry days input.
  function setDurationDays(value) {
    const days = value === 'Custom' ? Number(form.customDays) || 0 : Number(value);

    setForm(f => ({
      ...f,
      durationDays: value,
      expiryDate: addDaysToNowLocal(days)
    }));
  }

  // Free typing in the custom-days box also recalculates the expiry date live.
  function setCustomDays(value) {
    const days = Number(value) || 0;

    setForm(f => ({
      ...f,
      customDays: value,
      expiryDate: days > 0 ? addDaysToNowLocal(days) : f.expiryDate
    }));
  }

  function set(k, v) {
    setForm(f => ({
      ...f,
      [k]: v
    }));
  }

  // Voice assistant ("Hello Ops, I need access to S3") fills this form while it is open.
  // It can never submit: only the Submit Request button does that.
  useVoiceForm('ACCESS', {
    open,
    form,
    reset: () => setForm(emptyAccessForm()),
    close: onClose,
    apply: (patch) =>
      setForm(f => {
        const next = { ...f, ...patch };
        if ('durationDays' in patch || 'customDays' in patch) {
          const days =
            next.durationDays === 'Custom' ? Number(next.customDays) || 0 : Number(next.durationDays);
          if (days > 0) next.expiryDate = addDaysToNowLocal(days);
        }
        return next;
      })
  });

  async function submit(e) {
    e.preventDefault();

    if (form.accessLevel === 'Custom' && !form.customAccessLevel.trim()) {
      toast.error('Please describe the custom access level needed.');
      return;
    }

    if (form.durationDays === 'Custom' && !(Number(form.customDays) > 0)) {
      toast.error('Please enter a valid number of days.');
      return;
    }

    if (!form.accessType) {
      toast.error('Access Type is required.');
      return;
    }

    if (!form.project) {
      toast.error('Project / App is required.');
      return;
    }

    if (!form.userResource.trim()) {
      toast.error('User / Resource is required.');
      return;
    }

    if (!form.reason.trim()) {
      toast.error('Reason is required.');
      return;
    }

    if (countWords(form.reason) > 250) {
      toast.error('Reason must be 250 words or fewer.');
      return;
    }

    if (!form.expiryDate) {
      toast.error('Please set an expiry date.');
      return;
    }

    if (form.expiryDate < getCurrentDateLocal()) {
      toast.error('Expiry date cannot be in the past.');
      return;
    }

    const emailError = email.validate();
    if (emailError) {
      toast.error(emailError);
      return;
    }

    setLoading(true);

    // "Access Level" is the structured replacement for the old free-text
    // "Permission Needed" field, so it's sent to the backend under the
    // same `permission` key the API/DB already expects.
    const permission =
      form.accessLevel === 'Custom'
        ? `Custom - ${form.customAccessLevel.trim()}`
        : form.accessLevel;

    const payload = {
      ...form,
      permission
    };

    try {
      const res = await accessService.create(payload, email.options());

      toast.success(`${res.record['Record ID']} created.${emailResultText(res)}`);

      voiceForms.submitted('ACCESS', res.record['Record ID']);
      onCreated();
      onClose();
      email.reset();

      const currentDisplayDateTime = getCurrentDateTime();

      setForm({
        accessType: '',
        project: '',
        environment: 'PROD',
        requestedDateTime: currentDisplayDateTime,
        userResource: '',
        accessLevel: 'Read Only',
        customAccessLevel: '',
        durationDays: 7,
        customDays: '',
        reason: '',
        expiryDate: addDaysToNowLocal(7)
      });
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
      title="New Access Request"
      variant="brand"
      footer={
        <EmailNotifyFooter email={email} open={open}>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" form="access-request-form" loading={loading}>
              Submit Request
            </Button>
          </div>
        </EmailNotifyFooter>
      }
    >
      <form
        id="access-request-form"
        className="space-y-4"
        onSubmit={submit}
      >
        {/* First row */}
        <div className="grid grid-cols-3 gap-3">

          {/* Access Type */}
          <Field
            label="Access Type"
            required
          >
            <select
              required
              value={form.accessType}
              onChange={(e) =>
                set('accessType', e.target.value)
              }
              className={inputCls}
            >
              <option value="">
                Select…
              </option>

              {ACCESS_TYPES.map(a => (
                <option
                  key={a}
                  value={a}
                >
                  {a}
                </option>
              ))}
            </select>
          </Field>

          {/* Project / App */}
          <Field
            label="Project / App"
            required
          >
            <select
              required
              value={form.project}
              onChange={(e) =>
                set('project', e.target.value)
              }
              className={inputCls}
            >
              <option value="">
                Select…
              </option>

              {(config?.applications || []).map(a => (
                <option
                  key={a}
                  value={a}
                >
                  {a}
                </option>
              ))}
            </select>
          </Field>

          {/* Environment */}
          <Field
            label="Environment"
            required
          >
            <select
              value={form.environment}
              onChange={(e) =>
                set('environment', e.target.value)
              }
              className={inputCls}
            >
              {(config?.environments || []).map(e => (
                <option
                  key={e}
                  value={e}
                >
                  {e}
                </option>
              ))}
            </select>
          </Field>

        </div>

        {/* User / Resource */}
        <Field
          label="User / Resource needing access"
          required
        >
          <input
            required
            value={form.userResource}
            onChange={(e) =>
              set('userResource', e.target.value)
            }
            className={inputCls}
          />
        </Field>

        {/* Access Level / Duration (Days) row (structured, replaces the
            old free-text "Permission Needed" input, and no more
            Temporary / Permanent — just number of days) */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">

          {/* Access Level */}
          <Field
            label="Access Level"
            required
          >
            <select
              required
              value={form.accessLevel}
              onChange={(e) =>
                set('accessLevel', e.target.value)
              }
              className={inputCls}
            >
              {ACCESS_LEVELS.map(lvl => (
                <option
                  key={lvl}
                  value={lvl}
                >
                  {lvl}
                </option>
              ))}
            </select>
          </Field>

          {/* Duration (Days) */}
          <Field
            label="Duration (Days)"
            required
          >
            <select
              required
              value={form.durationDays}
              onChange={(e) =>
                setDurationDays(
                  e.target.value === 'Custom' ? 'Custom' : Number(e.target.value)
                )
              }
              className={inputCls}
            >
              {DURATION_DAY_OPTIONS.map(d => (
                <option
                  key={d}
                  value={d}
                >
                  {d} {d === 1 ? 'day' : 'days'}
                </option>
              ))}

              <option value="Custom">
                Custom…
              </option>
            </select>
          </Field>

          <Field
            label="Expiry Date"
            required
          >
            <DatePicker
              value={form.expiryDate}
              min={getCurrentDateLocal()}
              onChange={(value) => set('expiryDate', value)}
            />
          </Field>

        </div>

        {/* Custom access level detail - only shown when "Custom" is picked */}
        {form.accessLevel === 'Custom' && (
          <Field
            label="Describe Custom Access"
            required
          >
            <input
              required
              value={form.customAccessLevel}
              onChange={(e) =>
                set('customAccessLevel', e.target.value)
              }
              placeholder="e.g. Read/Write on S3 bucket only"
              className={inputCls}
            />
          </Field>
        )}

        {/* Custom days entry - only shown when Duration (Days) = Custom.
            Gives the user full freedom to type any exact number of days. */}
        {form.durationDays === 'Custom' && (
          <Field
            label="Enter Number of Days"
            required
          >
            <input
              type="number"
              min="1"
              required
              value={form.customDays}
              onChange={(e) =>
                setCustomDays(e.target.value)
              }
              placeholder="e.g. 45"
              className={inputCls}
            />
          </Field>
        )}

        {/* Reason */}
        <Field
          label="Reason"
          required
        >
          <WordLimitTextarea
            required
            limit={250}
            rows={3}
            value={form.reason}
            onChange={(value) => set('reason', value)}
            placeholder="Explain why this access is needed."
          />
        </Field>

      </form>
    </Modal>
  );
}