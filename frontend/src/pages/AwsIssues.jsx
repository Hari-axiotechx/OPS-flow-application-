import { useEffect, useMemo, useState } from 'react';
import { useStatusFilter } from '../hooks/useStatusFilter';
import BackArrow from '../components/ui/BackArrow';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { awsIssueService } from '../api/issueService';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Modal from '../components/ui/Modal';
import {
  StatusBadge,
  RecordIdBadge,
  PriorityBadge
} from '../components/ui/Badge';
import { SkeletonRow } from '../components/ui/Skeleton';
import EmptyState from '../components/ui/EmptyState';
import ErrorState from '../components/ui/ErrorState';
import { Field, inputCls, readFileAsDataUrl } from './DeploymentRequests';
import EmailNotifyFooter, { useEmailNotify, emailResultText } from '../components/ui/EmailRecipients';
import { useVoiceForm } from '../voice/useVoiceForm';
import { voiceForms } from '../voice/voiceForms';

const STATUS_FILTERS = ['ALL', 'OPEN', 'IN_PROGRESS', 'RESOLVED'];

/* =========================================================
   500-WORD LIMIT (Error / Message and Impact)
   Typing or pasting stops at 500 words. When the limit is reached an
   "Upload file" option appears so the rest can be attached as a file.
   ========================================================= */
export const MAX_WORDS = 500;
const MAX_FILE_MB = 5;
const FILE_ACCEPT = '.txt,.log,.csv,.pdf,.doc,.docx,.png,.jpg,.jpeg';

export function countWords(text) {
  const m = String(text || '').trim().match(/\S+/g);
  return m ? m.length : 0;
}

// Keeps the first `max` words exactly as typed; anything after is dropped.
function limitWords(text, max) {
  const re = /\S+/g;
  let n = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    n += 1;
    if (n === max) {
      const end = m.index + m[0].length;
      return text.slice(end).trim() ? { text: text.slice(0, end), cut: true } : { text, cut: false };
    }
  }
  return { text, cut: false };
}

function WordLimitField({ rows = 3, value, onChange, fileName, onFile, onClearFile }) {
  const [cut, setCut] = useState(false);
  const [fileError, setFileError] = useState('');
  const [busy, setBusy] = useState(false);
  const words = countWords(value);
  const full = words >= MAX_WORDS;
  const showUpload = full || cut || !!fileName;

  function handleText(e) {
    const { text, cut: wasCut } = limitWords(e.target.value, MAX_WORDS);
    setCut(wasCut);
    onChange(text);
  }

  async function handleFile(e) {
    const file = e.target.files && e.target.files[0];
    e.target.value = '';
    if (!file) return;
    setFileError('');
    if (file.size > MAX_FILE_MB * 1024 * 1024) {
      setFileError(`File is too large. Maximum ${MAX_FILE_MB} MB.`);
      return;
    }
    setBusy(true);
    try {
      onFile(file.name, await readFileAsDataUrl(file));
    } catch (err) {
      setFileError(err.message || 'Could not read the file.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <textarea
        required
        rows={rows}
        value={value}
        onChange={handleText}
        className={inputCls}
      />

      <div className="flex items-center justify-between mt-1">
        <span className={`text-[11px] ${full ? 'text-amber-600 font-semibold' : 'text-ink-400'}`}>
          {words} / {MAX_WORDS} words
        </span>
      </div>

      {showUpload && (
        <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5">
          <p className="text-xs text-amber-800">
            {full || cut
              ? `The ${MAX_WORDS}-word limit is reached. If you need to write more, upload it as a file.`
              : 'Attached file:'}
          </p>

          <div className="mt-2 flex flex-wrap items-center gap-2">
            <label className="inline-flex items-center gap-1.5 cursor-pointer text-xs font-semibold px-3 py-1.5 rounded-lg border border-ink-200 bg-white text-ink-700 hover:bg-ink-50">
              {busy ? 'Reading…' : fileName ? 'Replace file' : 'Upload file'}
              <input type="file" accept={FILE_ACCEPT} onChange={handleFile} className="hidden" />
            </label>

            {fileName && (
              <span className="inline-flex items-center gap-2 text-xs text-ink-700 bg-white border border-ink-200 rounded-lg px-2.5 py-1.5">
                📎 <span className="max-w-[220px] truncate">{fileName}</span>
                <button
                  type="button"
                  onClick={onClearFile}
                  className="text-ink-400 hover:text-red-600 font-bold"
                  aria-label="Remove file"
                  title="Remove file"
                >
                  ×
                </button>
              </span>
            )}

            <span className="text-[11px] text-ink-400">txt, log, csv, pdf, doc, docx, png, jpg · max {MAX_FILE_MB} MB</span>
          </div>

          {fileError && <p className="text-xs text-red-600 mt-1.5">{fileError}</p>}
        </div>
      )}
    </div>
  );
}

// Common AWS services offered in the "Service" dropdown. This is a
// suggestion list, not a hard enum — the field is a searchable text
// input (via <datalist>), so the user can always type a custom service
// that isn't in this list.
export const AWS_SERVICES = [
  'EC2', 'S3', 'RDS', 'Lambda', 'VPC', 'IAM', 'CloudFront', 'Route 53',
  'ECS', 'EKS', 'DynamoDB', 'CloudWatch', 'SNS', 'SQS', 'API Gateway',
  'Elastic Beanstalk', 'ELB / ALB', 'EBS', 'CloudFormation', 'KMS',
  'Secrets Manager', 'ElastiCache', 'Redshift', 'Kinesis',
  'Step Functions', 'SES', 'WAF', 'ACM', 'CodePipeline', 'CodeBuild',
  'CodeDeploy', 'Auto Scaling', 'Elastic IP', 'NAT Gateway', 'EFS',
  'Athena', 'Glue', 'CloudTrail', 'Systems Manager', 'Other'
];

export default function AwsIssues() {
  const [params, setParams] = useSearchParams();
  const statusFilter = useStatusFilter(params, setParams);

  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);

  const navigate = useNavigate();
  const { config, user, refreshConfig } = useAuth();

  async function load() {
    setLoading(true);
    setError(null);

    try {
      setRecords(await awsIssueService.list());
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
  }, []);

  // Dashboard "+ New" menu links here with ?new=1 — open the create form.
  useEffect(() => {
    if (params.get('new') === '1') {
      if (user?.role === 'DevOps') setCreateOpen(true);
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

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-ink-900 flex items-center gap-3">
            <BackArrow />AWS Issues
          </h1>

          <p className="text-sm text-ink-400 mt-0.5">
            PROD only — managed exclusively by DevOps.
          </p>
        </div>

        {/* Only DevOps users can create AWS Issues */}
        {user.role === 'DevOps' && (
          <Button onClick={() => setCreateOpen(true)}>
            + New AWS Issue
          </Button>
        )}
      </div>

      <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
        {STATUS_FILTERS.map((s) => (
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
                icon="☁️"
                title="No AWS issues"
                description="Hopefully it stays that way."
              />
            )}

            {!loading &&
              filtered.map((r) => (
                <button
                  key={r['Record ID']}
                  onClick={() =>
                    navigate(`/aws-issues/${r['Record ID']}`)
                  }
                  className="w-full text-left px-4 py-3 flex flex-col md:flex-row md:items-center gap-1.5 md:gap-3 hover:bg-ink-50"
                >
                  <span className="md:w-32">
                    <RecordIdBadge id={r['Record ID']} />
                  </span>

                  {r.Service && (
                    <span className="shrink-0 text-[11px] font-semibold uppercase tracking-wide text-brand-600 bg-brand-50 border border-brand-200 rounded-md px-1.5 py-0.5">
                      {r.Service}
                    </span>
                  )}

                  <span className="flex-1 text-sm text-ink-900 font-medium truncate">
                    {r.ErrorMessage}{' '}
                    <span className="text-ink-400 font-normal">
                      · {r.Project}
                    </span>
                  </span>

                  <PriorityBadge priority={r.Priority} />

                  <span className="md:w-32">
                    <StatusBadge status={r.Status} />
                  </span>
                </button>
              ))}
          </div>
        </Card>
      )}

      <CreateAwsIssueModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={load}
        config={config}
      />
    </div>
  );
}

function CreateAwsIssueModal({
  open,
  onClose,
  onCreated,
  config
}) {
  const toast = useToast();

  const [form, setForm] = useState({
    project: '',
    service: '',
    priority: 'High',
    errorMessage: '',
    impact: '',
    errorFileName: '',
    errorFileData: '',
    impactFileName: '',
    impactFileData: ''
  });

  const email = useEmailNotify(open);
  const [loading, setLoading] = useState(false);

  function set(k, v) {
    setForm((f) => ({
      ...f,
      [k]: v
    }));
  }

  function resetForm() {
    setForm({
      project: '',
      service: '',
      priority: 'High',
      errorMessage: '',
      impact: '',
      errorFileName: '',
      errorFileData: '',
      impactFileName: '',
      impactFileData: ''
    });
  }

  // Voice assistant ("Hello Ops, report an AWS issue") fills this form while it is open.
  // It can never submit: only the Submit Issue button does that.
  useVoiceForm('AWS_ISSUE', {
    open,
    form,
    reset: resetForm,
    close: onClose,
    apply: (patch) => setForm((f) => ({ ...f, ...patch }))
  });

  async function submit(e) {
    e.preventDefault();

    if (!form.project) return toast.error('Project / App is required.');
    if (!form.service.trim()) return toast.error('Service is required.');
    if (!form.errorMessage.trim()) return toast.error('Error / Message is required.');
    if (!form.impact.trim()) return toast.error('Impact is required.');
    if (countWords(form.errorMessage) > MAX_WORDS) return toast.error(`Error / Message is over ${MAX_WORDS} words. Shorten it or upload a file.`);
    if (countWords(form.impact) > MAX_WORDS) return toast.error(`Impact is over ${MAX_WORDS} words. Shorten it or upload a file.`);

    const emailError = email.validate();
    if (emailError) return toast.error(emailError);

    setLoading(true);

    try {
      const res = await awsIssueService.create(form, email.options());

      toast.success(`${res.record['Record ID']} created.${emailResultText(res)}`);

      voiceForms.submitted('AWS_ISSUE', res.record['Record ID']);
      onCreated();
      onClose();
      resetForm();
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
      title="New AWS Issue"
      variant="brand"
      footer={
        <EmailNotifyFooter email={email} open={open}>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>

          <Button type="submit" form="aws-issue-form" loading={loading}>
            Submit Issue
          </Button>
        </EmailNotifyFooter>
      }
    >
      <form id="aws-issue-form" className="space-y-4" onSubmit={submit}>
        <Field label="Project / App" required>
          <select
            required
            value={form.project}
            onChange={(e) => set('project', e.target.value)}
            className={inputCls}
          >
            <option value="">Select…</option>

            {(config?.applications || []).map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Service" required>
            <input
              required
              list="aws-service-options"
              value={form.service}
              onChange={(e) => set('service', e.target.value)}
              placeholder="Search or type…"
              className={inputCls}
            />
            <datalist id="aws-service-options">
              {AWS_SERVICES.map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
            <p className="text-[11px] text-ink-400 mt-1">
              Pick from the list or type a custom service.
            </p>
          </Field>

          <Field label="Priority" required>
            <select
              value={form.priority}
              onChange={(e) =>
                set('priority', e.target.value)
              }
              className={inputCls}
            >
              {(
                config?.priorities || [
                  'Low',
                  'Medium',
                  'High',
                  'Critical'
                ]
              ).map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <Field label="Error / Message" required>
          <WordLimitField
            rows={3}
            value={form.errorMessage}
            onChange={(v) => set('errorMessage', v)}
            fileName={form.errorFileName}
            onFile={(name, data) => setForm((f) => ({ ...f, errorFileName: name, errorFileData: data }))}
            onClearFile={() => setForm((f) => ({ ...f, errorFileName: '', errorFileData: '' }))}
          />
        </Field>

        <Field label="Impact" required>
          <WordLimitField
            rows={3}
            value={form.impact}
            onChange={(v) => set('impact', v)}
            fileName={form.impactFileName}
            onFile={(name, data) => setForm((f) => ({ ...f, impactFileName: name, impactFileData: data }))}
            onClearFile={() => setForm((f) => ({ ...f, impactFileName: '', impactFileData: '' }))}
          />
        </Field>
      </form>
    </Modal>
  );
}
