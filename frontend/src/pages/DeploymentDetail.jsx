import { useEffect, useState } from 'react';
import DeploymentFlow from '../components/ui/DeploymentFlow';
import BackArrow from '../components/ui/BackArrow';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { deploymentService } from '../api/deploymentService';
import { userService } from '../api/userService';
import { useEmailNotify, useEmailRecipients, emailResultText } from '../components/ui/EmailRecipients';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import Timeline from '../components/ui/Timeline';
import { StatusBadge } from '../components/ui/Badge';
import { SkeletonCard } from '../components/ui/Skeleton';
import ErrorState from '../components/ui/ErrorState';
import { DeploymentRequestModal, inputCls } from './DeploymentRequests';

function parseEnvVarRows(raw) {
  try {
    const parsed = raw ? JSON.parse(raw) : [];
    if (Array.isArray(parsed)) return parsed;
  } catch {
    if (raw) return [{ key: '', value: raw }];
  }
  return [];
}

function parseAttachments(raw) {
  try {
    const o = raw ? JSON.parse(raw) : {};
    return o && typeof o === 'object' ? o : {};
  } catch {
    return {};
  }
}

function FileLink({ file }) {
  if (!file?.data) return null;
  return (
    <a
      href={file.data}
      download={file.name || 'file'}
      className="text-brand-600 hover:underline inline-flex items-center gap-1.5 break-all"
    >
      <span>{file.name || 'Download file'}</span>
      <DownloadIcon />
    </a>
  );
}

function DownloadIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.25"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="w-4 h-4 text-green-600 shrink-0"
    >
      <path d="M12 3v12" />
      <path d="M7.5 10.5 12 15l4.5-4.5" />
      <path d="M4.5 19.5h15" />
    </svg>
  );
}

function CopyButton({ value, label }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy(e) {
    e.stopPropagation();
    if (!value) return;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
      } else {
        throw new Error('no clipboard api');
      }
    } catch {
      const ta = document.createElement('textarea');
      ta.value = value;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand('copy');
      } catch {
        /* best effort — nothing more we can do here */
      }
      ta.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      title={label ? `Copy ${label}` : 'Copy'}
      className="shrink-0 w-6 h-6 flex items-center justify-center rounded-md text-ink-400 hover:text-brand-600 hover:bg-brand-50"
    >
      {copied ? (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="w-3.5 h-3.5 text-green-600"
        >
          <path d="M20 6 9 17l-5-5" />
        </svg>
      ) : (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="w-3.5 h-3.5"
        >
          <rect x="9" y="9" width="12" height="12" rx="2" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
      )}
    </button>
  );
}

function Reveal({ revealed, onToggle, mono, children }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className={mono ? 'font-mono' : ''}>
        {revealed ? children : '••••••••••'}
      </span>
      <button
        type="button"
        onClick={onToggle}
        className="text-[11px] font-semibold text-brand-600 hover:text-brand-700 shrink-0"
      >
        {revealed ? 'Hide' : 'Show'}
      </button>
    </span>
  );
}

export default function DeploymentDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user, isAdmin, config } = useAuth();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [dialog, setDialog] = useState(null);
  const [editOpen, setEditOpen] = useState(false);
  // To / Cc picker for deployment status-change emails.
  const OUTCOME_STATUSES = ['REJECTED', 'COMPLETED_SUCCESS', 'COMPLETED_FAILED', 'ROLLED_BACK'];
  const outcomeOpen = !!dialog && OUTCOME_STATUSES.includes(dialog.newStatus);
  const email = useEmailNotify(outcomeOpen, { mandatory: true });
  const { people: mailPeople, loading: mailLoading } = useEmailRecipients(outcomeOpen);
  const [devOpsUsers, setDevOpsUsers] = useState([]);
  const [assigning, setAssigning] = useState(false);

  const [reassignTarget, setReassignTarget] = useState('');

  const [revealed, setRevealed] = useState({ dbDetails: false, thirdParty: false, envVars: {} });

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setData(await deploymentService.get(id));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // Refresh when the voice assistant changes a status.
    const refresh = () => load();
    window.addEventListener('opsflow:data-changed', refresh);
    return () => window.removeEventListener('opsflow:data-changed', refresh);
  }, [id]);

  useEffect(() => {
    // Loaded for everyone (not just admins) so the Audit Timeline and the
    // "Assigned DevOps" field can resolve an id like "USR-000002" to a
    // name for anyone viewing the request, not only admins.
    userService.listDevOps().then(setDevOpsUsers).catch(() => {});
  }, []);

  useEffect(() => {
    if (data?.record) {
      setReassignTarget(data.record.AssignedDevOpsID || '');
    }
  }, [data?.record?.AssignedDevOpsID]);

  // Pre-select To = requester + assigned DevOps + admin(s) (you can change it); Cc starts empty.
  useEffect(() => {
    const rec = data?.record;
    if (!outcomeOpen || !rec || mailLoading || mailPeople.length === 0) return;
    const involved = new Set([rec.RequesterID, rec.AssignedDevOpsID].filter(Boolean));
    const ids = mailPeople
      .filter((p) => p.id !== user?.id && (involved.has(p.id) || p.admin))
      .map((p) => p.id);
    email.setTo(ids);
    email.setCc([]);
  }, [outcomeOpen, mailLoading, mailPeople.length, data?.record?.['Record ID']]); // eslint-disable-line react-hooks/exhaustive-deps

  async function doAction(newStatus, reason, emailOptions) {
    try {
      const res = await deploymentService.updateStatus(id, newStatus, reason, emailOptions);
      toast.success(`Status updated to ${newStatus.replaceAll('_', ' ')}.${emailResultText(res)}`);
      setDialog(null);
      load();
    } catch (e) {
      toast.error(e.message);
    }
  }

  if (loading) {
    return (
      <div className="grid gap-4 max-w-3xl">
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }

  if (error) {
    return <ErrorState message={error} onRetry={load} />;
  }

  const r = data.record;
  const isDevOps = user?.role === 'DevOps';
  const canResubmit = ['Developer', 'QA'].includes(user?.role)
    && r.RequesterID === user.id
    && r.Status === 'REJECTED';
  const envVarRows = parseEnvVarRows(r.EnvVarDetails);
  const att = parseAttachments(r.Attachments);
  const envFiles = att.envFiles || (att.envFile ? [att.envFile] : []);
  const dbFiles = att.dbFiles || [];
  const apiPairs = att.thirdPartyPairs || [];

  const assignedName = r.AssignedDevOpsID
    ? devOpsUsers.find((u) => u.id === r.AssignedDevOpsID)?.name ||
      r.AssignedDevOpsID
    : '';
  const showAssignment =
    !!assignedName || !['REQUESTED', 'REJECTED'].includes(r.Status);

  function downloadDetails() {
    const lines = [
      `Deployment ${r['Record ID']} — ${r.Project} / ${r.Environment} / ${r.Component}`,
      `Status: ${r.Status}`,
      `Scheduled: ${r.DateTime ? new Date(r.DateTime).toLocaleString() : '—'}`,
      '',
    ];

    if (String(r.DBChange) === 'true') {
      lines.push('== DB / Schema Change ==');
      if (r.DBChangeFileName) {
        lines.push(`File attached: ${r.DBChangeFileName} (use the Download File link on this page)`);
      }
      lines.push(r.DBChangeDetails || (r.DBChangeFileName ? '' : '(no details provided)'));
      lines.push('');
    }

    if (String(r.ThirdPartyAPIChange) === 'true') {
      lines.push('== Third Party API Change ==');
      lines.push(r.ThirdPartyAPIDetails || '(no details provided)');
      lines.push('');
    }

    if (String(r.EnvVarChange) === 'true') {
      lines.push('== Environment Variable Change ==');
      if (envVarRows.length === 0) {
        lines.push('(no details provided)');
      } else {
        envVarRows.forEach((row) => {
          lines.push(`${row.key || '(no key)'} = ${row.value}`);
        });
      }
      lines.push('');
    }

    if (r.AdditionalInfo) {
      lines.push('== Additional Info ==');
      lines.push(r.AdditionalInfo);
    }

    const blob = new Blob([lines.join('\n')], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${r['Record ID']}-details.txt`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  const actions = [];

  if (isDevOps) {
    if (r.Status === 'REQUESTED') {
      actions.push({
        label: 'Approve',
        variant: 'primary',
        onClick: () => doAction('APPROVED'),
      });
      actions.push({
        label: 'Reject',
        variant: 'danger',
        onClick: () =>
          setDialog({
            newStatus: 'REJECTED',
            title: 'Reject deployment',
            requireReason: true,
            maxReasonLength: 100,
            danger: true,
            confirmLabel: 'Reject',
          }),
      });
    }

    if (r.Status === 'APPROVED') {
      actions.push({
        label: 'Start Deployment',
        variant: 'primary',
        onClick: () => doAction('IN_PROGRESS'),
      });
    }

    if (r.Status === 'IN_PROGRESS') {
      actions.push({
        label: 'Mark Success',
        variant: 'primary',
        onClick: () =>
          setDialog({
            newStatus: 'COMPLETED_SUCCESS',
            title: 'Mark deployment as success',
            description: 'Was this deployment completed successfully? Do you want to mark it as Success?',
            confirmLabel: 'Yes',
            cancelLabel: 'No',
          }),
      });
      actions.push({
        label: 'Mark Failed',
        variant: 'danger',
        onClick: () =>
          setDialog({
            newStatus: 'COMPLETED_FAILED',
            title: 'Mark deployment failed',
            requireReason: true,
            danger: true,
            confirmLabel: 'Mark Failed',
          }),
      });
      actions.push({
        label: 'Rollback',
        variant: 'secondary',
        onClick: () =>
          setDialog({
            newStatus: 'ROLLED_BACK',
            title: 'Roll back deployment',
            requireReason: true,
            confirmLabel: 'Roll Back',
          }),
      });
    }

  }

  actions.push({ label: 'Download Details', variant: 'ghost', onClick: downloadDetails });
  if (canResubmit) {
    actions.push({ label: 'Edit & Resubmit', variant: 'primary', onClick: () => setEditOpen(true) });
  }

  return (
    <div className="space-y-5 max-w-6xl animate-fade-in">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-xl font-bold text-ink-900 font-mono flex items-center gap-3">
              <BackArrow />{r['Record ID']}
            </h1>
            <StatusBadge status={r.Status} />

            {showAssignment && (
              <span
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${
                  assignedName
                    ? 'bg-brand-50 border-brand-100 text-brand-700'
                    : 'bg-ink-50 border-ink-100 text-ink-400'
                }`}
              >
                <span>👤</span>
                <span className="text-ink-400">Assigned DevOps:</span>
                <span className={assignedName ? 'font-semibold' : ''}>
                  {assignedName || 'Not assigned yet'}
                </span>
              </span>
            )}
          </div>
        </div>

        <div className="flex gap-2 flex-wrap">
          {actions.map((a) => (
            <Button
              key={a.label}
              variant={a.variant}
              size="sm"
              onClick={a.onClick}
            >
              {a.label}
            </Button>
          ))}
        </div>
      </div>

      <DeploymentFlow
        status={r.Status}
        rejectionReason={r.RejectionReason}
        audit={data.audit}
        createdAt={r.CreatedAt}
        requestedBy={r.RequesterID}
      />

      <div className="space-y-5">
        <div className="space-y-5">
          <Card className="p-5">
            <h3 className="text-sm font-semibold text-ink-900 mb-3">
              Request Details
            </h3>

            <dl className="grid grid-cols-2 gap-4 text-sm">
              <DL label="Project / App" value={r.Project || '—'} />
              <DL label="Environment" value={r.Environment || '—'} />
              <DL label="Component" value={r.Component || '—'} />
              <DL
                label="Scheduled"
                value={
                  r.DateTime ? new Date(r.DateTime).toLocaleString() : '—'
                }
              />

              <DL
                label="GitHub Repository URL"
                value={
                  r.GitHubURL ? (
                    <span className="inline-flex items-center gap-1.5 max-w-full">
                      <a
                        href={r.GitHubURL}
                        target="_blank"
                        rel="noreferrer"
                        className="text-brand-600 hover:underline break-all"
                      >
                        {r.GitHubURL}
                      </a>
                      <CopyButton value={r.GitHubURL} label="GitHub URL" />
                    </span>
                  ) : (
                    '—'
                  )
                }
              />

              <DL
                label="GitHub Branch"
                value={
                  r.GitHubBranch ? (
                    <span className="inline-flex items-center gap-1.5">
                      <span className="font-mono text-xs bg-ink-50 border border-ink-100 rounded-lg px-2 py-1 text-ink-800">
                        {r.GitHubBranch}
                      </span>
                      <CopyButton value={r.GitHubBranch} label="GitHub branch" />
                    </span>
                  ) : (
                    '—'
                  )
                }
              />

              <DL
                label="Commit ID"
                value={
                  r.GitHubCommit ? (
                    <span className="font-mono">{r.GitHubCommit}</span>
                  ) : (
                    '—'
                  )
                }
              />

              <DL
                label="Rollback Branch"
                value={
                  r.RollbackBranch ? (
                    <span className="inline-flex items-center gap-1.5">
                      <span className="font-mono text-xs bg-ink-50 border border-ink-100 rounded-lg px-2 py-1 text-ink-800">
                        {r.RollbackBranch}
                      </span>
                      <CopyButton value={r.RollbackBranch} label="rollback branch" />
                    </span>
                  ) : (
                    '—'
                  )
                }
              />

              <DL
                label="DB / Schema Change"
                value={String(r.DBChange) === 'true' ? 'Yes' : 'No'}
              />

              {String(r.DBChange) === 'true' && (
                <DL
                  label="Details / File"
                  span
                  value={
                    <div className="space-y-1">
                      {dbFiles.length > 0 && (
                        <ol className="space-y-1">
                          {dbFiles.map((f, i) => (
                            <li key={i} className="flex items-center gap-2">
                              <span className="w-6 text-right text-xs font-bold text-ink-500">{i + 1}.</span>
                              <FileLink file={f} />
                            </li>
                          ))}
                        </ol>
                      )}
                      {dbFiles.length === 0 && r.DBChangeFileData && (
                        <a
                          href={r.DBChangeFileData}
                          download={r.DBChangeFileName || 'db-change-file'}
                          className="text-brand-600 hover:underline inline-flex items-center gap-1.5"
                        >
                          <span>{r.DBChangeFileName || 'Download file'}</span>
                          <DownloadIcon />
                        </a>
                      )}
                      {r.DBChangeDetails ? (
                        <Reveal
                          revealed={revealed.dbDetails}
                          onToggle={() =>
                            setRevealed((s) => ({ ...s, dbDetails: !s.dbDetails }))
                          }
                        >
                          {r.DBChangeDetails}
                        </Reveal>
                      ) : !r.DBChangeFileData && dbFiles.length === 0 ? (
                        '—'
                      ) : null}
                    </div>
                  }
                />
              )}

              <DL
                label="Third Party API Change"
                value={String(r.ThirdPartyAPIChange) === 'true' ? 'Yes' : 'No'}
              />

              {String(r.ThirdPartyAPIChange) === 'true' && (
                <DL
                  label="Details"
                  span
                  value={
                    r.ThirdPartyAPIDetails || apiPairs.length > 0 || att.thirdPartyFiles?.length ? (
                      <div className="space-y-2">
                        {r.ThirdPartyAPIDetails && (
                          <Reveal
                            revealed={revealed.thirdParty}
                            onToggle={() =>
                              setRevealed((s) => ({ ...s, thirdParty: !s.thirdParty }))
                            }
                          >
                            {r.ThirdPartyAPIDetails}
                          </Reveal>
                        )}
                        {(att.thirdPartyFiles || []).map((f, i) => (
                          <div key={i}><FileLink file={f} /></div>
                        ))}
                        {apiPairs.length > 0 && (
                          <div className="space-y-1.5">
                            {apiPairs.map((p, i) => (
                              <div key={i} className="grid grid-cols-1 sm:grid-cols-2 gap-2 font-mono text-xs">
                                <div className="bg-ink-50 border border-ink-100 rounded-lg px-3 py-2 text-ink-900 truncate">{p.key}</div>
                                <div className="bg-ink-50 border border-ink-100 rounded-lg px-3 py-2 text-ink-700 truncate">
                                  {revealed.envVars[`api${i}`] ? p.value : '••••••••••'}
                                  <button
                                    type="button"
                                    onClick={() =>
                                      setRevealed((st) => ({
                                        ...st,
                                        envVars: { ...st.envVars, [`api${i}`]: !st.envVars[`api${i}`] },
                                      }))
                                    }
                                    className="ml-2 font-sans text-[11px] font-semibold text-brand-600 hover:text-brand-700"
                                  >
                                    {revealed.envVars[`api${i}`] ? 'Hide' : 'Show'}
                                  </button>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ) : (
                      '—'
                    )
                  }
                />
              )}

              <DL
                label="Env Var Change"
                value={String(r.EnvVarChange) === 'true' ? 'Yes' : 'No'}
              />

              {String(r.EnvVarChange) === 'true' && (
                <DL
                  label="Details"
                  span
                  value={
                    envVarRows.length === 0 ? (
                      envFiles.length ? (
                        <div className="space-y-1">
                          {envFiles.map((file, i) => (
                            <div key={`${i}-${file.name}`}><FileLink file={file} /></div>
                          ))}
                        </div>
                      ) : '—'
                    ) : (
                      <div className="space-y-2">
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px] font-semibold uppercase tracking-wide text-ink-400">
                          <span>Key</span>
                          <span className="hidden sm:block">Value</span>
                        </div>

                        {envVarRows.map((row, i) => (
                          <div
                            key={i}
                            className="grid grid-cols-1 sm:grid-cols-2 gap-2"
                          >
                            {/* Key box */}
                            <div className="flex items-center justify-between gap-2 font-mono text-xs bg-ink-50 border border-ink-100 rounded-lg px-3 py-2 min-w-0">
                              <span className="text-ink-900 truncate">
                                {row.key || '—'}
                              </span>
                              {row.key && (
                                <CopyButton value={row.key} label="key" />
                              )}
                            </div>

                            {/* Value box */}
                            <div className="flex items-center justify-between gap-2 font-mono text-xs bg-ink-50 border border-ink-100 rounded-lg px-3 py-2 min-w-0">
                              <span className="text-ink-700 truncate">
                                {revealed.envVars[i] ? row.value : '••••••••••'}
                              </span>
                              <span className="inline-flex items-center gap-1.5 shrink-0">
                                <button
                                  type="button"
                                  onClick={() =>
                                    setRevealed((st) => ({
                                      ...st,
                                      envVars: {
                                        ...st.envVars,
                                        [i]: !st.envVars[i],
                                      },
                                    }))
                                  }
                                  className="font-sans text-[11px] font-semibold text-brand-600 hover:text-brand-700"
                                >
                                  {revealed.envVars[i] ? 'Hide' : 'Show'}
                                </button>
                                {row.value && (
                                  <CopyButton value={row.value} label="value" />
                                )}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )
                  }
                />
              )}

              {(r.ApplicationChangeDetails || att.appChangeFile) && (
                <DL
                  label="Application Change Details"
                  span
                  value={
                    <div className="space-y-1">
                      {r.ApplicationChangeDetails && <div className="whitespace-pre-wrap">{r.ApplicationChangeDetails}</div>}
                      <FileLink file={att.appChangeFile} />
                    </div>
                  }
                />
              )}
              {(r.AdditionalInfo || att.additionalFile) && (
                <DL
                  label="Additional Info"
                  span
                  value={
                    <div className="space-y-1">
                      {r.AdditionalInfo && <div className="whitespace-pre-wrap">{r.AdditionalInfo}</div>}
                      <FileLink file={att.additionalFile} />
                    </div>
                  }
                />
              )}
              {r.FailureReason && (
                <DL label="Failure Reason" value={r.FailureReason} span />
              )}
              {r.RollbackReason && (
                <DL label="Rollback Reason" value={r.RollbackReason} span />
              )}
            </dl>
          </Card>

          <Card className="p-5">
            <h3 className="text-sm font-semibold text-ink-900 mb-3">
              Audit Timeline
            </h3>
            <Timeline entries={data.audit} users={devOpsUsers} />
          </Card>
        </div>

        <div className="space-y-5">
          <Card className="p-5">
            <h3 className="text-sm font-semibold text-ink-900 mb-3">
              Assignment
            </h3>

            <dl className="space-y-3 text-sm">
              <DL label="Requester" value={r.RequesterID} />
              <DL
                label="Assigned DevOps"
                value={
                  devOpsUsers.find((u) => u.id === r.AssignedDevOpsID)
                    ?.name ||
                  r.AssignedDevOpsID ||
                  'Unassigned'
                }
              />
              <DL
                label="Created"
                value={new Date(r.CreatedAt).toLocaleString()}
              />
              <DL
                label="Last Updated"
                value={
                  r.UpdatedAt ? new Date(r.UpdatedAt).toLocaleString() : '—'
                }
              />
            </dl>

            {isAdmin && devOpsUsers.length > 0 && (
              <div className="mt-4 pt-4 border-t border-ink-100">
                <label className="block text-xs font-medium text-ink-600 mb-1.5">
                  Assign deployment
                </label>

                <select
                  disabled={assigning}
                  value={reassignTarget}
                  onChange={(e) => setReassignTarget(e.target.value)}
                  className={`${inputCls} w-full`}
                >
                  <option value="">Select DevOps user…</option>
                  {devOpsUsers.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name} — {u.email}
                    </option>
                  ))}
                </select>

                <div className="flex justify-end items-center gap-2 mt-2">
                  <Button
                    size="sm"
                    loading={assigning}
                    disabled={
                      !reassignTarget ||
                      reassignTarget === (r.AssignedDevOpsID || '')
                    }
                    onClick={async () => {
                      setAssigning(true);
                      try {
                        await deploymentService.reassign(id, reassignTarget);
                        toast.success('Deployment assigned.');
                        await load();
                      } catch (err) {
                        toast.error(err.message);
                      } finally {
                        setAssigning(false);
                      }
                    }}
                  >
                    Save
                  </Button>
                </div>
              </div>
            )}
          </Card>
        </div>
      </div>

      <ConfirmDialog
        open={!!dialog}
        onClose={() => setDialog(null)}
        onConfirm={(reason, emailOptions) => doAction(dialog.newStatus, reason, emailOptions)}
        email={outcomeOpen ? email : undefined}
        title={dialog?.title}
        description={dialog?.description}
        cancelLabel={dialog?.cancelLabel}
        requireReason={dialog?.requireReason}
        maxReasonLength={dialog?.maxReasonLength}
        danger={dialog?.danger}
        confirmLabel={dialog?.confirmLabel}
      />
      <DeploymentRequestModal
        open={editOpen}
        onClose={() => setEditOpen(false)}
        onCreated={load}
        config={config}
        initialRecord={editOpen ? r : null}
      />

    </div>
  );
}

export function DL({ label, value, span }) {
  return (
    <div className={span ? 'col-span-2' : ''}>
      <dt className="text-xs text-ink-400 mb-0.5">{label}</dt>
      <dd className="text-ink-900 font-medium break-words">{value}</dd>
    </div>
  );
}
