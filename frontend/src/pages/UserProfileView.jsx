import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import BackArrow from '../components/ui/BackArrow';
import { useToast } from '../context/ToastContext';
import { userService } from '../api/userService';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Avatar from '../components/ui/Avatar';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import { StatusBadge } from '../components/ui/Badge';
import { SkeletonCard } from '../components/ui/Skeleton';
import ErrorState from '../components/ui/ErrorState';
import { ApproveModal } from './UserManagement';

function Item({ label, value, span }) {
  return (
    <div className={span ? 'sm:col-span-2' : ''}>
      <dt className="text-xs text-ink-400 mb-0.5">{label}</dt>
      <dd className="text-sm text-ink-900 font-medium break-words">{value || '—'}</dd>
    </div>
  );
}

function fmt(d) {
  if (!d) return '—';
  const x = new Date(d);
  return Number.isNaN(x.getTime()) ? '—' : x.toLocaleString();
}

/**
 * Admin-only: full profile of one user (opened by clicking a user in User Management,
 * or "Review Profile" on a pending registration).
 * Pending users also get Approve / Reject here.
 */
export default function UserProfileView() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [approveTarget, setApproveTarget] = useState(null);
  const [rejectTarget, setRejectTarget] = useState(null);

  async function load() {
    setLoading(true); setError(null);
    try {
      const all = await userService.list();
      const found = all.find((u) => u.id === id);
      if (!found) throw new Error('User not found.');
      setUser(found);
    } catch (e) { setError(e.message); } finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function doReject(reason) {
    try {
      await userService.reject(rejectTarget.id, reason);
      toast.success('Registration rejected.');
      setRejectTarget(null);
      navigate('/users');
    } catch (e) { toast.error(e.message); }
  }

  if (loading) return <div className="grid gap-4 max-w-3xl"><SkeletonCard /><SkeletonCard /></div>;
  if (error) return <ErrorState message={error} onRetry={load} />;

  const u = user;
  const pending = u.status === 'PENDING';

  return (
    <div className="space-y-5 max-w-3xl animate-fade-in">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-bold text-ink-900 flex items-center gap-3">
          <BackArrow />{pending ? 'Review Profile' : 'User Profile'}
        </h1>
        {pending && (
          <div className="flex gap-2">
            <Button size="sm" onClick={() => setApproveTarget(u)}>Approve</Button>
            <Button size="sm" variant="danger" onClick={() => setRejectTarget(u)}>Reject</Button>
          </div>
        )}
      </div>

      <Card className="p-6">
        <div className="flex items-center gap-5 pb-6 mb-6 border-b border-ink-100">
          <Avatar seed={u.id || u.email || u.name} name={u.name} size={96} className="ring-4 ring-blue-50" />
          <div className="min-w-0">
            <p className="text-lg font-semibold text-ink-900 break-words">{u.name}</p>
            <p className="text-sm text-ink-400 mt-0.5">{u.role || (u.requestedRole ? `Requested: ${u.requestedRole}` : '—')}</p>
            <div className="mt-2">
              {pending
                ? <StatusBadge status="PENDING" />
                : <StatusBadge status={u.active ? 'ACTIVE' : 'INACTIVE'} />}
            </div>
          </div>
        </div>

        <dl className="grid sm:grid-cols-2 gap-x-6 gap-y-4">
          <Item label="User ID" value={u.id} />
          <Item label="Full name" value={u.name} />
          <Item label="Email" value={u.email} />
          <Item label="Mobile number" value={u.mobile} />
          <Item label="Role" value={u.role} />
          <Item label="Requested role" value={u.requestedRole} />
          <Item label="Admin access" value={u.role === 'DevOps' ? (u.power ? 'Yes' : 'No') : 'Not applicable'} />
          <Item label="Registration status" value={u.status} />
          <Item label="Account" value={pending ? 'Waiting for approval' : (u.active ? 'Active' : 'Inactive')} />
          <Item label="Registered on" value={fmt(u.createdAt)} />
        </dl>
      </Card>

      <ApproveModal
        user={approveTarget}
        onClose={() => setApproveTarget(null)}
        onDone={() => navigate('/users')}
      />
      <ConfirmDialog
        open={!!rejectTarget}
        onClose={() => setRejectTarget(null)}
        onConfirm={doReject}
        title={`Reject ${rejectTarget?.name}'s registration`}
        requireReason
        danger
        confirmLabel="Reject"
      />
    </div>
  );
}
