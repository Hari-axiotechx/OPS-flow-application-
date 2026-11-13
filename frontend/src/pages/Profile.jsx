import { useEffect, useState } from 'react';
import BackArrow from '../components/ui/BackArrow';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { userService } from '../api/userService';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Modal from '../components/ui/Modal';
import Avatar from '../components/ui/Avatar';
import PasswordRules, { passwordValid, PASSWORD_RULE_MESSAGE } from '../components/ui/PasswordRules';
import { inputCls, Field } from './DeploymentRequests';

export default function Profile() {
  const { user, updateUser } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();

  const [form, setForm] = useState({
    name: '',
    mobile: '',
    currentPassword: '',
    newPassword: '',
    confirmPassword: ''
  });

  const [saving, setSaving] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [passwordSaving, setPasswordSaving] = useState(false);
  const [passwordError, setPasswordError] = useState('');

  useEffect(() => {
    if (!user) return;

    setForm(f => ({
      ...f,
      name: user.name || '',
      mobile: user.mobile || ''
    }));

  }, [user]);

  function set(k, v) {
    setForm(f => ({
      ...f,
      [k]: v
    }));
  }

  function closePasswordModal() {
    setPasswordOpen(false);
    setPasswordError('');
    setForm((current) => ({
      ...current,
      currentPassword: '',
      newPassword: '',
      confirmPassword: ''
    }));
  }

  function setPasswordField(key, value) {
    set(key, value);
    setPasswordError('');
  }

  async function saveProfile(e) {
    e.preventDefault();

    setSaving(true);

    try {
      const res = await userService.updateProfile({
        name: form.name,
        mobile: form.mobile
      });

      updateUser(res.user);

      toast.success(
        'Profile updated successfully.'
      );

      // Give the toast a beat to show, then take the user back to
      // whichever page they came from.
      setTimeout(() => navigate(-1), 700);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function changePassword(e) {
    e.preventDefault();
    if (!form.currentPassword) {
      setPasswordError('Enter your current password.');
      return;
    }
    if (!passwordValid(form.newPassword)) {
      setPasswordError(PASSWORD_RULE_MESSAGE);
      return;
    }
    if (!form.confirmPassword) {
      setPasswordError('Confirm your new password.');
      return;
    }
    if (form.newPassword !== form.confirmPassword) {
      setPasswordError('The new password and confirmation do not match.');
      return;
    }

    setPasswordError('');
    setPasswordSaving(true);
    try {
      const res = await userService.updateProfile({
        currentPassword: form.currentPassword,
        newPassword: form.newPassword,
        confirmPassword: form.confirmPassword
      });
      updateUser(res.user);
      setForm((current) => ({
        ...current,
        currentPassword: '',
        newPassword: '',
        confirmPassword: ''
      }));
      setPasswordOpen(false);
      setPasswordError('');
      toast.success('Password changed successfully.');
    } catch (err) {
      toast.error(err.message);
    } finally {
      setPasswordSaving(false);
    }
  }

  if (!user) return null;

  return (
    <div className="max-w-5xl space-y-6 animate-fade-in">

      <div>
        <h1 className="text-xl font-bold text-ink-900 flex items-center gap-3">
          <BackArrow />My Profile
        </h1>

        <p className="text-sm text-ink-400 mt-0.5">
          Manage your account details and password.
        </p>
      </div>

      <form
        onSubmit={saveProfile}
        className="space-y-5"
      >

        <Card className="p-6">

          <h2 className="text-sm font-semibold text-ink-900 mb-4">
            Account details
          </h2>

          {/* =================================================
              PROFILE AVATAR
              Auto-generated per user — no photo upload.
             ================================================= */}
          <div className="flex items-center gap-5 pb-6 mb-6 border-b border-ink-100">

            <Avatar
              seed={user.id || user.email || user.name}
              name={user.name}
              size={96}
              className="ring-4 ring-blue-50"
            />

            <div className="min-w-0">

              <p className="text-sm font-semibold text-ink-900">
                {user.name || 'User'}
              </p>

              <p className="text-sm text-ink-400 mt-0.5">
                {user.role || '—'}
              </p>

              <p className="text-xs text-ink-400 mt-2">
                Your avatar is generated automatically from your account and can't be changed.
              </p>

            </div>

          </div>

          <div className="grid md:grid-cols-2 gap-4">

            <Field
              label="Full name"
              required
            >
              <input
                required
                value={form.name}
                onChange={e =>
                  set('name', e.target.value)
                }
                className={inputCls}
              />
            </Field>

            <Field label="Email">
              <input
                value={user.email || ''}
                disabled
                className={`${inputCls} bg-ink-50 text-ink-400 cursor-not-allowed`}
              />
            </Field>

            <Field
              label="Mobile number"
              required
            >
              <input
                required
                inputMode="numeric"
                maxLength={10}
                value={form.mobile}
                onChange={e =>
                  set(
                    'mobile',
                    e.target.value
                      .replace(/\D/g, '')
                      .slice(0, 10)
                  )
                }
                className={inputCls}
              />
            </Field>

            <Field label="User ID">
              <input
                value={user.id || ''}
                disabled
                className={`${inputCls} bg-ink-50 text-ink-400 cursor-not-allowed font-mono`}
              />
            </Field>

          </div>

          <div className="grid md:grid-cols-3 gap-4 mt-4">

            <Info
              label="Role"
              value={user.role || '—'}
            />

            <Info
              label="Account status"
              value={user.status || '—'}
            />

            <Info
              label="Admin access"
              value={
                user.power
                  ? 'DevOps Admin'
                  : 'Standard'
              }
            />

            <Info
              label="Created"
              value={
                user.createdAt
                  ? new Date(
                      user.createdAt
                    ).toLocaleString()
                  : '—'
              }
            />

            <Info
              label="Last updated"
              value={
                user.updatedAt
                  ? new Date(
                      user.updatedAt
                    ).toLocaleString()
                  : '—'
              }
            />

          </div>

        </Card>

        <div>
          <Button type="button" variant="secondary" onClick={() => setPasswordOpen(true)}>
            Change Password
          </Button>
        </div>

        <div className="flex justify-end">

          <Button
            loading={saving}
            type="submit"
            size="lg"
          >
            Save changes
          </Button>

        </div>

      </form>

      <Modal
        open={passwordOpen}
        onClose={closePasswordModal}
        title="Change Password"
        width="max-w-xl"
        footer={
          <>
            <Button type="button" variant="secondary" onClick={closePasswordModal}>
              Cancel
            </Button>
            <Button type="submit" form="change-password-form" loading={passwordSaving}>
              Update Password
            </Button>
          </>
        }
      >
        <form id="change-password-form" onSubmit={changePassword} className="space-y-4">
          <Field label="Current password" required>
            <input
              type="password"
              value={form.currentPassword}
              onChange={(e) => setPasswordField('currentPassword', e.target.value)}
              className={inputCls}
              autoComplete="current-password"
            />
          </Field>

          <Field label="New password" required>
            <input
              type="password"
              value={form.newPassword}
              onChange={(e) => setPasswordField('newPassword', e.target.value)}
              className={inputCls}
              autoComplete="new-password"
            />
            <PasswordRules password={form.newPassword} />
          </Field>

          <Field label="Confirm new password" required>
            <input
              type="password"
              value={form.confirmPassword}
              onChange={(e) => setPasswordField('confirmPassword', e.target.value)}
              className={inputCls}
              autoComplete="new-password"
            />
            {form.confirmPassword && form.newPassword !== form.confirmPassword && (
              <p className="mt-1 text-[11px] text-red-600">
                The new password and confirmation do not match.
              </p>
            )}
          </Field>
          {passwordError && (
            <p role="alert" className="text-sm text-red-600">
              {passwordError}
            </p>
          )}
        </form>
      </Modal>

    </div>
  );
}

function Info({ label, value }) {
  return (
    <div>
      <p className="text-xs text-ink-400 mb-0.5">
        {label}
      </p>

      <p className="text-sm font-medium text-ink-900">
        {value}
      </p>
    </div>
  );
}
