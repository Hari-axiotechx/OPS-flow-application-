import { useEffect, useState } from 'react';
import BackArrow from '../components/ui/BackArrow';
import { useParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { awsIssueService } from '../api/issueService';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import Timeline from '../components/ui/Timeline';
import { StatusBadge, PriorityBadge } from '../components/ui/Badge';
import { SkeletonCard } from '../components/ui/Skeleton';
import ErrorState from '../components/ui/ErrorState';
import { DL } from './DeploymentDetail';
import { inputCls } from './DeploymentRequests';

export default function AwsIssueDetail() {
  const { id } = useParams();
  const { isAdmin } = useAuth();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [form, setForm] = useState({ rootCause: '', whatWasDone: '', resolution: '' });
  const [saving, setSaving] = useState(false);
  const [reopenOpen, setReopenOpen] = useState(false);

  async function load() {
    setLoading(true); setError(null);
    try {
      const d = await awsIssueService.get(id);
      setData(d);
      setForm({ rootCause: d.record.RootCause || '', whatWasDone: d.record.WhatWasDone || '', resolution: d.record.Resolution || '' });
    } catch (e) { setError(e.message); } finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [id]);

  async function save(newStatus) {
    setSaving(true);
    try { await awsIssueService.update(id, form, newStatus); toast.success(newStatus ? `Status updated to ${newStatus.replaceAll('_', ' ')}.` : 'Saved.'); load(); }
    catch (e) { toast.error(e.message); } finally { setSaving(false); }
  }

  async function doReopen(reason) {
    try { await awsIssueService.reopen(id, reason); toast.success('AWS issue reopened.'); setReopenOpen(false); load(); }
    catch (e) { toast.error(e.message); }
  }

  if (loading) return <div className="grid gap-4"><SkeletonCard /><SkeletonCard /></div>;
  if (error) return <ErrorState message={error} onRetry={load} />;

  const r = data.record;
  const readOnly = r.Status === 'RESOLVED';

  return (
    <div className="space-y-5 w-full max-w-none animate-fade-in">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-xl font-bold text-ink-900 font-mono flex items-center gap-3"><BackArrow />{r['Record ID']}</h1>
            <StatusBadge status={r.Status} /><PriorityBadge priority={r.Priority} />
          </div>
        </div>
        <div className="flex gap-2 flex-wrap">
          {r.Status === 'OPEN' && <Button size="sm" onClick={() => save('IN_PROGRESS')} loading={saving}>Start Progress</Button>}
          {r.Status === 'IN_PROGRESS' && <Button size="sm" onClick={() => save('RESOLVED')} loading={saving}>Mark Resolved</Button>}
          {readOnly && isAdmin && <Button size="sm" variant="secondary" onClick={() => setReopenOpen(true)}>Reopen</Button>}
        </div>
      </div>

      {readOnly && <div className="text-xs bg-neutral-bg text-neutral-text rounded-lg px-3 py-2 inline-block">This AWS issue is resolved and read-only. Only a DevOps Admin can reopen it.</div>}

      <Card className="p-5">
        <h3 className="text-sm font-semibold text-ink-900 mb-3">Report</h3>
        <dl className="grid grid-cols-2 gap-4 text-sm">
          <DL label="Project / App" value={r.Project || '—'} />
          <DL label="Environment" value={r.Environment || 'PROD'} />
          <DL label="Service" value={r.Service || '—'} />
          <DL label="Priority" value={r.Priority} />
          <DL label="Error / Message" value={r.ErrorMessage} span />
          {r.ErrorFileName && r.ErrorFileData && (
            <DL label="Error / Message file" span value={<a href={r.ErrorFileData} download={r.ErrorFileName} className="text-brand-600 underline">⬇ {r.ErrorFileName}</a>} />
          )}
          <DL label="Symptoms" value={r.Symptoms || '—'} span />
          <DL label="Impact" value={r.Impact || '—'} span />
          {r.ImpactFileName && r.ImpactFileData && (
            <DL label="Impact file" span value={<a href={r.ImpactFileData} download={r.ImpactFileName} className="text-brand-600 underline">⬇ {r.ImpactFileName}</a>} />
          )}
        </dl>
      </Card>

      <Card className="p-5">
        <h3 className="text-sm font-semibold text-ink-900 mb-3">Investigation</h3>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-ink-600 mb-1.5">Root Cause</label>
            <textarea disabled={readOnly} rows={2} value={form.rootCause} onChange={(e) => setForm(f => ({ ...f, rootCause: e.target.value }))} className={inputCls + ' disabled:bg-ink-50'} />
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-600 mb-1.5">What Was Done</label>
            <textarea disabled={readOnly} rows={2} value={form.whatWasDone} onChange={(e) => setForm(f => ({ ...f, whatWasDone: e.target.value }))} className={inputCls + ' disabled:bg-ink-50'} />
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-600 mb-1.5">Resolution</label>
            <textarea disabled={readOnly} rows={2} value={form.resolution} onChange={(e) => setForm(f => ({ ...f, resolution: e.target.value }))} className={inputCls + ' disabled:bg-ink-50'} />
          </div>
          {!readOnly && <Button size="sm" variant="secondary" loading={saving} onClick={() => save(null)}>Save Changes</Button>}
        </div>
      </Card>

      <Card className="p-5">
        <h3 className="text-sm font-semibold text-ink-900 mb-3">Audit Timeline</h3>
        <Timeline entries={data.audit} />
      </Card>

      <ConfirmDialog open={reopenOpen} onClose={() => setReopenOpen(false)} onConfirm={doReopen}
        title="Reopen AWS issue" requireReason confirmLabel="Reopen" />
    </div>
  );
}
