import { useEffect, useState } from 'react';
import BackArrow from '../components/ui/BackArrow';
import { useParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { accessService } from '../api/accessService';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import Timeline from '../components/ui/Timeline';
import { StatusBadge } from '../components/ui/Badge';
import RejectionNotice from '../components/ui/RejectionNotice';
import { SkeletonCard } from '../components/ui/Skeleton';
import ErrorState from '../components/ui/ErrorState';
import { useEmailNotify, useEmailRecipients, emailResultText } from '../components/ui/EmailRecipients';
import { DL } from './DeploymentDetail';

export default function AccessDetail() {
  const { id } = useParams();
  const { user } = useAuth();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [dialog, setDialog] = useState(null);
  const emailOpen = !!dialog && ['ACCESS_GIVEN', 'REJECTED'].includes(dialog.newStatus);
  const email = useEmailNotify(emailOpen, { mandatory: true });
  const { people: mailPeople, loading: mailLoading } = useEmailRecipients(emailOpen);

  async function load() {
    setLoading(true); setError(null);
    try { setData(await accessService.get(id)); } catch (e) { setError(e.message); } finally { setLoading(false); }
  }
  useEffect(() => {
    load();
    // Refresh when the voice assistant changes a status.
    const refresh = () => load();
    window.addEventListener('opsflow:data-changed', refresh);
    return () => window.removeEventListener('opsflow:data-changed', refresh);
  }, [id]);

  useEffect(() => {
    if (!emailOpen || !data?.record || mailLoading || mailPeople.length === 0) return;
    const rec = data.record;
    const ids = mailPeople
      .filter((person) => person.id !== user?.id && (person.id === rec.RequesterID || person.admin))
      .map((person) => person.id);
    email.setTo(ids);
    email.setCc([]);
  }, [emailOpen, mailLoading, mailPeople.length, data?.record?.['Record ID']]); // eslint-disable-line react-hooks/exhaustive-deps

  async function doAction(newStatus, reason, emailOptions) {
    try {
      const result = await accessService.updateStatus(id, newStatus, reason, emailOptions);
      toast.success(`Status updated to ${newStatus.replaceAll('_', ' ')}.${emailResultText(result)}`);
      setDialog(null);
      load();
    }
    catch (e) { toast.error(e.message); }
  }
  if (loading) return <div className="grid gap-4"><SkeletonCard /><SkeletonCard /></div>;
  if (error) return <ErrorState message={error} onRetry={load} />;

  const r = data.record;
  const isDevOps = user.role === 'DevOps';
  const actions = [];
  if (isDevOps) {
    if (r.Status === 'REQUESTED') {
      actions.push({ label: 'Approve', variant: 'primary', onClick: () => doAction('APPROVED') });
      actions.push({ label: 'Reject', variant: 'danger', onClick: () => setDialog({ newStatus: 'REJECTED', title: 'Reject access request', requireReason: true, danger: true, confirmLabel: 'Reject' }) });
    }
    if (r.Status === 'APPROVED') actions.push({ label: 'Start Processing', variant: 'primary', onClick: () => doAction('IN_PROGRESS') });
    if (r.Status === 'IN_PROGRESS') actions.push({ label: 'Mark Access Given', variant: 'primary', onClick: () => setDialog({ newStatus: 'ACCESS_GIVEN', title: 'Mark access as given', description: 'Has the access been given to the requester? Do you want to mark it as Access Given?', confirmLabel: 'Yes', cancelLabel: 'No' }) });
  }
  const days = r.ExpiryDate ? Math.ceil((new Date(r.ExpiryDate).getTime() - Date.now()) / 86400000) : null;

  return (
    <div className="space-y-5 w-full max-w-none animate-fade-in">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-xl font-bold text-ink-900 font-mono flex items-center gap-3"><BackArrow />{r['Record ID']}</h1>
            <StatusBadge status={r.Status} />
          </div>
        </div>
        <div className="flex gap-2 flex-wrap">{actions.map(a => <Button key={a.label} variant={a.variant} size="sm" onClick={a.onClick}>{a.label}</Button>)}</div>
      </div>

      {r.Status === 'REJECTED' && <RejectionNotice reason={r.RejectionReason} />}

      {days !== null && r.Status === 'ACCESS_GIVEN' && (
        <div className={`text-sm rounded-lg px-3 py-2 inline-block ${days <= 3 ? 'bg-danger-bg text-danger-text' : days <= 10 ? 'bg-warning-bg text-warning-text' : 'bg-info-bg text-info-text'}`}>
          {days <= 0 ? 'Access has expired' : `${days} days remaining before expiry`}
        </div>
      )}

      <div className="grid lg:grid-cols-4 gap-5">
        <div className="lg:col-span-3 min-w-0 space-y-5">
          <Card className="p-5">
            <h3 className="text-sm font-semibold text-ink-900 mb-3">Request Details</h3>
            <dl className="grid grid-cols-2 gap-4 text-sm">
              <DL label="Access Type" value={r.AccessType || '—'} />
              <DL label="Project / App" value={r.Project || '—'} />
              <DL label="Environment" value={r.Environment || '—'} />
              <DL label="User / Resource" value={r.UserResource} />
              <DL label="Permission Needed" value={r.Permission} />
              <DL label="Expiry Date" value={r.ExpiryDate || 'No expiry'} />
              <DL label="Reason" value={r.Reason} span />
            </dl>
          </Card>
          <Card className="p-5">
            <h3 className="text-sm font-semibold text-ink-900 mb-3">Audit Timeline</h3>
            <Timeline entries={data.audit} />
          </Card>
        </div>
        <div className="min-w-0">
          <Card className="p-5">
            <h3 className="text-sm font-semibold text-ink-900 mb-3">Info</h3>
            <dl className="space-y-3 text-sm">
              <DL label="Requester" value={r.RequesterID} />
              <DL label="Created" value={new Date(r.CreatedAt).toLocaleString()} />
              <DL label="Last Updated" value={r.UpdatedAt ? new Date(r.UpdatedAt).toLocaleString() : '—'} />
            </dl>
          </Card>
        </div>
      </div>

      <ConfirmDialog open={!!dialog} onClose={() => setDialog(null)} onConfirm={(reason, emailOptions) => doAction(dialog.newStatus, reason, emailOptions)}
        email={emailOpen ? email : undefined}
        title={dialog?.title} description={dialog?.description} cancelLabel={dialog?.cancelLabel} requireReason={dialog?.requireReason} danger={dialog?.danger} confirmLabel={dialog?.confirmLabel} />
    </div>
  );
}
