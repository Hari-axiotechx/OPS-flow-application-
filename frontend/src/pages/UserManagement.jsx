import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import BackArrow from '../components/ui/BackArrow';
import { useToast } from '../context/ToastContext';
import { userService } from '../api/userService';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Modal from '../components/ui/Modal';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import { StatusBadge } from '../components/ui/Badge';
import { SkeletonRow } from '../components/ui/Skeleton';
import EmptyState from '../components/ui/EmptyState';
import ErrorState from '../components/ui/ErrorState';
import PasswordRules, { passwordValid, PASSWORD_RULE_MESSAGE } from '../components/ui/PasswordRules';

const COMPANY_EMAIL_DOMAIN = '@axiotechx.com';

export default function UserManagement() {
  const toast = useToast();
  const navigate = useNavigate();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [approveTarget, setApproveTarget] = useState(null);
  const [rejectTarget, setRejectTarget] = useState(null);
  const [powerTarget, setPowerTarget] = useState(null);
  const [createUserOpen, setCreateUserOpen] = useState(false);

  async function load() {
    setLoading(true); setError(null);
    try { setUsers(await userService.list()); } catch (e) { setError(e.message); } finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  const pending = users.filter(u => u.status === 'PENDING');
  const others = users.filter(u => u.status !== 'PENDING');

  async function toggleActive(u) {
    try { await userService.setActive(u.id, !u.active); toast.success(`${u.name} ${u.active ? 'deactivated' : 'activated'}.`); load(); }
    catch (e) { toast.error(e.message); }
  }
  async function changeRole(u, role) {
    try { await userService.update(u.id, role, role === 'DevOps' ? u.power : false); toast.success(`${u.name}'s role updated.`); load(); }
    catch (e) { toast.error(e.message); }
  }
  async function confirmPower() {
    const u = powerTarget;
    try {
      await userService.update(u.id, u.role, !u.power);
      toast.success(`${u.name}'s admin access ${!u.power ? 'granted' : 'removed'}.`);
      setPowerTarget(null);
      load();
    } catch (e) { toast.error(e.message); }
  }
  async function doReject(reason) {
    try { await userService.reject(rejectTarget.id, reason); toast.success('Registration rejected.'); setRejectTarget(null); load(); }
    catch (e) { toast.error(e.message); }
  }

  if (error) return <ErrorState message={error} onRetry={load} />;

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-ink-900 flex items-center gap-3"><BackArrow />User Management</h1>
          <p className="text-sm text-ink-400 mt-0.5">Approve registrations, assign roles, and manage DevOps admin power. Click a user to open their full profile.</p>
        </div>
        <Button onClick={() => setCreateUserOpen(true)}>Create User</Button>
      </div>

      <section>
        <h2 className="text-sm font-semibold text-ink-700 mb-3">Pending Registrations {pending.length > 0 && <span className="text-warning">({pending.length})</span>}</h2>
        <Card className="divide-y divide-ink-100">
          {loading && Array.from({ length: 2 }).map((_, i) => <SkeletonRow key={i} />)}
          {!loading && pending.length === 0 && <EmptyState icon="✅" title="No pending registrations" />}
          {!loading && pending.map(u => (
            <div key={u.id} className="px-4 py-3.5 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-ink-900">{u.name}</p>
                <p className="text-xs text-ink-400">{u.email}{u.mobile ? ` · ${u.mobile}` : ''}</p>
                {u.requestedRole && <p className="text-[11px] text-brand-600 mt-0.5">Requested role: {u.requestedRole}</p>}
              </div>
              <div className="flex gap-2 flex-wrap">
                <Button size="sm" variant="secondary" onClick={() => navigate(`/users/${u.id}`)}>Review Profile</Button>
                <Button size="sm" onClick={() => setApproveTarget(u)}>Approve</Button>
                <Button size="sm" variant="danger" onClick={() => setRejectTarget(u)}>Reject</Button>
              </div>
            </div>
          ))}
        </Card>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-ink-700 mb-3">Existing Users</h2>
        <Card className="overflow-hidden">
          <div className="hidden md:flex px-4 py-2.5 border-b border-ink-100 text-[11px] font-semibold uppercase tracking-wide text-ink-400">
            <span className="flex-1">User</span><span className="w-36">Role</span><span className="w-24">Admin</span><span className="w-28">Status</span><span className="w-24">Action</span>
          </div>
          <div className="divide-y divide-ink-100">
            {loading && Array.from({ length: 3 }).map((_, i) => <SkeletonRow key={i} />)}
            {!loading && others.map(u => (
              <div
                key={u.id}
                role="link"
                tabIndex={0}
                title="Click to open full profile"
                onClick={() => navigate(`/users/${u.id}`)}
                onKeyDown={(e) => { if (e.key === 'Enter') navigate(`/users/${u.id}`); }}
                className="px-4 py-3 flex flex-col md:flex-row md:items-center gap-2 md:gap-3 cursor-pointer hover:bg-ink-50 transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-ink-900">{u.name}</p>
                  <p className="text-xs text-ink-400">{u.email}{u.mobile ? ` · ${u.mobile}` : ''}</p>
                </div>
                <select value={u.role} onClick={(e) => e.stopPropagation()} onChange={(e) => changeRole(u, e.target.value)} className="md:w-36 border border-ink-200 rounded-lg px-2 py-1.5 text-xs">
                  <option value="Developer">Developer</option><option value="QA">QA</option><option value="DevOps">DevOps</option>
                </select>
                <div className="md:w-24">
                  {u.role === 'DevOps' && (
                    <button onClick={(e) => { e.stopPropagation(); setPowerTarget(u); }} className={`text-xs font-semibold px-2.5 py-1.5 rounded-lg border ${u.power ? 'bg-brand-50 text-brand-600 border-brand-200' : 'bg-white text-ink-500 border-ink-200'}`}>
                      {u.power ? 'Admin ✓' : 'Grant Admin'}
                    </button>
                  )}
                </div>
                <div className="md:w-28"><StatusBadge status={u.active ? 'ACTIVE' : 'INACTIVE'} /></div>
                <div className="md:w-24">
                  <Button size="sm" variant={u.active ? 'ghost' : 'subtle'} onClick={(e) => { e.stopPropagation(); toggleActive(u); }}>{u.active ? 'Deactivate' : 'Activate'}</Button>
                </div>
              </div>
            ))}
            {!loading && others.length === 0 && <EmptyState title="No users yet" />}
          </div>
        </Card>
      </section>

      <ApproveModal user={approveTarget} onClose={() => setApproveTarget(null)} onDone={load} />
      <CreateUserModal
        open={createUserOpen}
        onClose={() => setCreateUserOpen(false)}
        onDone={() => { setCreateUserOpen(false); load(); }}
      />
      <ConfirmDialog
        open={!!powerTarget}
        onClose={() => setPowerTarget(null)}
        onConfirm={confirmPower}
        title={powerTarget?.power ? 'Remove admin access' : 'Give admin access'}
        description={powerTarget?.power
          ? `Do you want to remove admin access from ${powerTarget?.name}?`
          : `Do you want to give admin access to ${powerTarget?.name}?`}
        danger={!!powerTarget?.power}
        confirmLabel="OK"
      />
      <ConfirmDialog open={!!rejectTarget} onClose={() => setRejectTarget(null)} onConfirm={doReject}
        title={`Reject ${rejectTarget?.name}'s registration`} requireReason danger confirmLabel="Reject" />
    </div>
  );
}

function CreateUserModal({ open, onClose, onDone }) {
  const toast = useToast();
  const [form, setForm] = useState({ name: '', emailLocal: '', mobile: '', password: '', role: 'Developer', power: false });
  const [loading, setLoading] = useState(false);

  function close() {
    if (loading) return;
    setForm({ name: '', emailLocal: '', mobile: '', password: '', role: 'Developer', power: false });
    onClose();
  }

  async function submit(e) {
    e.preventDefault();
    if (!passwordValid(form.password)) {
      toast.error(PASSWORD_RULE_MESSAGE);
      return;
    }
    setLoading(true);
    try {
      await userService.create({
        ...form,
        email: `${form.emailLocal.trim()}${COMPANY_EMAIL_DOMAIN}`,
      });
      toast.success('User created. An account notification has been emailed to them.');
      setForm({ name: '', emailLocal: '', mobile: '', password: '', role: 'Developer', power: false });
      onDone();
    } catch (error) {
      toast.error(error.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal open={open} onClose={close} title="Create User" width="max-w-xl"
      footer={<><Button type="button" variant="secondary" onClick={close}>Cancel</Button><Button type="submit" form="create-user-form" loading={loading}>Create User</Button></>}>
      <form id="create-user-form" onSubmit={submit} className="space-y-4">
        <p className="text-sm text-ink-500">The account will be active immediately. Enter the initial password for the new user.</p>
        <label className="block text-xs font-medium text-ink-600">
          Full name
          <input required maxLength={30} value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            className="mt-1 w-full border border-ink-200 rounded-lg px-3 py-2 text-sm" />
        </label>
        <label className="block text-xs font-medium text-ink-600">
          Company email
          <span className="mt-1 flex w-full items-stretch overflow-hidden rounded-lg border border-ink-200">
            <input required type="text" maxLength={254 - COMPANY_EMAIL_DOMAIN.length} value={form.emailLocal}
              onChange={(e) => setForm((f) => ({ ...f, emailLocal: e.target.value.replace(/[^a-zA-Z0-9._+-]/g, '') }))}
              className="min-w-0 flex-1 px-3 py-2 text-sm outline-none" />
            <span className="flex items-center border-l border-ink-200 bg-ink-50 px-3 text-sm text-ink-500 select-none">
              {COMPANY_EMAIL_DOMAIN}
            </span>
          </span>
        </label>
        <label className="block text-xs font-medium text-ink-600">
          Mobile number
          <input required type="tel" maxLength={12} value={form.mobile} onChange={(e) => setForm((f) => ({ ...f, mobile: e.target.value }))}
            placeholder="10-digit number" className="mt-1 w-full border border-ink-200 rounded-lg px-3 py-2 text-sm" />
        </label>
        <label className="block text-xs font-medium text-ink-600">
          Initial password
          <input required type="password" autoComplete="new-password" value={form.password}
            onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
            className="mt-1 w-full border border-ink-200 rounded-lg px-3 py-2 text-sm" />
          <PasswordRules password={form.password} />
        </label>
        <label className="block text-xs font-medium text-ink-600">
          Role
          <select value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value, power: false }))}
            className="mt-1 w-full border border-ink-200 rounded-lg px-3 py-2 text-sm">
            <option value="Developer">Developer</option><option value="QA">QA</option><option value="DevOps">DevOps</option>
          </select>
        </label>
        {form.role === 'DevOps' && (
          <label className="flex items-center gap-2 text-sm text-ink-700">
            <input type="checkbox" checked={form.power} onChange={(e) => setForm((f) => ({ ...f, power: e.target.checked }))} />
            Grant DevOps Admin power
          </label>
        )}
      </form>
    </Modal>
  );
}

export function ApproveModal({ user, onClose, onDone }) {
  const toast = useToast();
  const [role, setRole] = useState('Developer');
  const [power, setPower] = useState(false);
  const [loading, setLoading] = useState(false);

  // Pre-fill with whatever role the person requested at sign-up, if any.
  useEffect(() => { if (user) setRole(user.requestedRole || 'Developer'); }, [user]);

  async function submit() {
    setLoading(true);
    try { await userService.approve(user.id, role, power); toast.success(`${user.name} approved as ${role}.`); onDone(); onClose(); }
    catch (e) { toast.error(e.message); } finally { setLoading(false); }
  }

  return (
    <Modal open={!!user} onClose={onClose} title={`Approve ${user?.name}`}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={loading} onClick={submit}>Approve</Button></>}>
      <div className="space-y-4">
        <div>
          <label className="block text-xs font-medium text-ink-600 mb-1.5">Assign Role</label>
          <select value={role} onChange={(e) => setRole(e.target.value)} className="w-full border border-ink-200 rounded-lg px-3 py-2 text-sm">
            <option value="Developer">Developer</option><option value="QA">QA</option><option value="DevOps">DevOps</option>
          </select>
        </div>
        {role === 'DevOps' && (
          <label className="flex items-center gap-2 text-sm text-ink-700">
            <input type="checkbox" checked={power} onChange={(e) => setPower(e.target.checked)} />
            Grant DevOps Admin power (normally only one user should have this)
          </label>
        )}
      </div>
    </Modal>
  );
}
