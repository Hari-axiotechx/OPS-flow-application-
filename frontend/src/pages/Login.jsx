import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import PasswordRules, { passwordValid, PASSWORD_RULE_MESSAGE } from '../components/ui/PasswordRules';
import { authService } from '../api/authService';
import Button from '../components/ui/Button';

// Small reusable password input with a show/hide eye toggle.
function PasswordInput({ value, onChange, placeholder, required = true, onFocus, onBlur }) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <input
        required={required}
        type={visible ? 'text' : 'password'}
        value={value}
        onChange={onChange}
        onFocus={onFocus}
        onBlur={onBlur}
        placeholder={placeholder}
        className="w-full border border-ink-200 rounded-lg px-3 py-2 pr-10 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none"
      />
      <button
        type="button"
        tabIndex={-1}
        onClick={() => setVisible(v => !v)}
        aria-label={visible ? 'Hide password' : 'Show password'}
        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-ink-400 hover:text-ink-600"
      >
        {visible ? (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M17.94 17.94A10.94 10.94 0 0 1 12 19c-5 0-9.27-3.11-11-7.5a11.6 11.6 0 0 1 2.94-4.27M9.9 4.24A10.94 10.94 0 0 1 12 4c5 0 9.27 3.11 11 7.5a11.6 11.6 0 0 1-1.66 2.94M14.12 14.12a3 3 0 1 1-4.24-4.24" />
            <line x1="1" y1="1" x2="23" y2="23" />
          </svg>
        ) : (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M1 12s4-7.5 11-7.5S23 12 23 12s-4 7.5-11 7.5S1 12 1 12Z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
        )}
      </button>
    </div>
  );
}

const DOMAIN = '@axiotechx.com';

// Mobile: digits only, and the FIRST digit must be 6, 7, 8 or 9 (other first digits are not accepted).
function cleanMobile(v) {
  return String(v || '').replace(/\D/g, '').replace(/^[0-5]+/, '').slice(0, 10);
}

// Keep only the part before "@" (people sometimes paste the whole address).
function cleanLocal(v) {
  return String(v || '').split('@')[0].replace(/[^a-zA-Z0-9._-]/g, '');
}

// Email box with the company domain fixed at the end — the user only types the name.
function DomainEmailInput({ value, onChange, placeholder = 'Company email', autoFocus = false }) {
  return (
    <div className="w-full flex items-stretch border border-ink-200 rounded-lg overflow-hidden focus-within:border-brand-500 focus-within:ring-1 focus-within:ring-brand-500">
      <input
        required
        autoFocus={autoFocus}
        autoComplete="username"
        value={value}
        onChange={(e) => onChange(cleanLocal(e.target.value))}
        placeholder={placeholder}
        className="flex-1 min-w-0 px-3 py-2 text-sm outline-none"
      />
      <span className="flex items-center px-3 text-sm text-ink-500 bg-ink-50 border-l border-ink-200 select-none whitespace-nowrap">
        {DOMAIN}
      </span>
    </div>
  );
}

// Small round back arrow (icon only, 20% smaller than the page arrows). Turns blue when clicked.
function LoginBackArrow({ onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Go back"
      title="Back"
      className="mb-3 inline-flex items-center justify-center w-[29px] h-[29px] rounded-full border border-ink-200 bg-white text-ink-700 shadow-sm hover:bg-ink-50 active:bg-brand-500 active:border-brand-500 active:text-white focus:outline-none focus-visible:bg-brand-500 focus-visible:border-brand-500 focus-visible:text-white transition-colors"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
        <path d="M19 12H5" />
        <path d="M12 19l-7-7 7-7" />
      </svg>
    </button>
  );
}

// mode: 'login' | 'register' | 'forgot-request' | 'forgot-verify'
export default function Login() {
  const [mode, setMode] = useState('login');
  const [form, setForm] = useState({ name: '', email: '', password: '', confirmPassword: '', mobile: '', role: 'Developer' });
  const [emailLocal, setEmailLocal] = useState('');
  const [loginLocal, setLoginLocal] = useState('');
  const [forgotLocal, setForgotLocal] = useState('');
  const [registrationFocus, setRegistrationFocus] = useState('');
  const [forgot, setForgot] = useState({ email: '', otp: '', newPassword: '', confirmPassword: '' });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { login } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();

  function set(k, v) { setForm(f => ({ ...f, [k]: v })); setError(''); }
  function setForgotField(k, v) { setForgot(f => ({ ...f, [k]: v })); setError(''); }

  function switchMode(next) {
    setMode(next);
    setError('');
    setRegistrationFocus('');
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      if (mode === 'login') {
        await login(`${loginLocal}${DOMAIN}`, form.password);
        navigate('/');
      } else if (mode === 'register') {
        if (!form.name.trim()) {
          setRegistrationFocus('name');
          setError('Please enter your full name.');
          setLoading(false);
          return;
        }
        if (!emailLocal.trim()) {
          setRegistrationFocus('email');
          setError('Please enter your company email address.');
          setLoading(false);
          return;
        }
        if (!form.email.trim().toLowerCase().endsWith('@axiotechx.com')) {
          setRegistrationFocus('email');
          setError('Only @axiotechx.com email addresses can register.');
          setLoading(false);
          return;
        }
        if (!/^[6-9]\d{9}$/.test(form.mobile)) {
          setRegistrationFocus('mobile');
          setError('Enter a valid 10-digit mobile number starting with 6, 7, 8 or 9.');
          setLoading(false);
          return;
        }
        if (!passwordValid(form.password)) {
          setRegistrationFocus('password');
          setError(PASSWORD_RULE_MESSAGE);
          setLoading(false);
          return;
        }
        if (form.password !== form.confirmPassword) {
          setRegistrationFocus('confirmPassword');
          setError("Passwords don't match.");
          setLoading(false);
          return;
        }
        await authService.register(form.name, form.email, form.password, form.mobile, form.role);
        toast.success('Registration submitted — an admin will approve your account.');
        setMode('login');
        setLoginLocal(emailLocal);
        setEmailLocal('');
        setForm(f => ({ ...f, name: '', email: '', password: '', confirmPassword: '', mobile: '', role: 'Developer' }));
      } else if (mode === 'forgot-request') {
        await authService.requestPasswordReset(`${forgotLocal}${DOMAIN}`);
        toast.success('If that email is registered, a reset code has been sent to it.');
        setMode('forgot-verify');
      } else if (mode === 'forgot-verify') {
        if (!passwordValid(forgot.newPassword)) {
          setError(PASSWORD_RULE_MESSAGE);
          setLoading(false);
          return;
        }
        if (forgot.newPassword !== forgot.confirmPassword) {
          setError("Passwords don't match.");
          setLoading(false);
          return;
        }
        await authService.resetPassword(`${forgotLocal}${DOMAIN}`, forgot.otp, forgot.newPassword);
        toast.success('Password updated — sign in with your email.');
        setLoginLocal(forgotLocal);
        setForm(f => ({ ...f, password: '' }));
        setForgotLocal('');
        setForgot({ email: '', otp: '', newPassword: '', confirmPassword: '' });
        setMode('login');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const titles = {
    login: 'Sign in',
    register: 'Create an account',
    'forgot-request': 'Reset your password',
    'forgot-verify': 'Enter your code'
  };
  const subtitles = {
    login: 'Deployment, access and issue tracking in one place.',
    register: 'New accounts require admin approval.',
    'forgot-request': "We'll email a one-time code to your account's email address.",
    'forgot-verify': `Enter the code we sent to ${forgotLocal ? forgotLocal + DOMAIN : 'your email'} and choose a new password.`
  };

  return (
    <div className="min-h-screen relative flex items-center justify-center px-4 overflow-hidden bg-[#0B1030]">
      {/* Decorative gradient background */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute inset-0 bg-gradient-to-br from-[#2E4CDB] via-[#5A31D8] to-[#0B1030]" />
        <div className="absolute -top-24 -left-24 h-96 w-96 rounded-full bg-[#8B5CF6] opacity-40 blur-3xl" />
        <div className="absolute -bottom-32 -right-16 h-[28rem] w-[28rem] rounded-full bg-[#22D3EE] opacity-30 blur-3xl" />
        <div className="absolute top-1/3 right-1/4 h-72 w-72 rounded-full bg-[#F472B6] opacity-20 blur-3xl" />
      </div>

      <div className="relative w-full max-w-sm">
        <div className="flex items-center gap-2.5 justify-center mb-8">
          <div className="h-10 w-10 rounded-xl bg-[#2563EB] flex items-center justify-center text-white font-bold shadow-lg shadow-blue-900/30">OPS</div>
          <span className="font-extrabold text-2xl text-white tracking-tight">OPSFlow</span>
        </div>

        <div className="bg-white/95 backdrop-blur border border-white/40 rounded-2xl shadow-2xl p-6">
          {mode !== 'login' && mode !== 'register' && (
            <LoginBackArrow onClick={() => switchMode(mode === 'forgot-verify' ? 'forgot-request' : 'login')} />
          )}

          <h1 className="text-lg font-semibold text-ink-900">{titles[mode]}</h1>
          <p className="text-sm text-ink-400 mt-0.5 mb-5">{subtitles[mode]}</p>

          <form onSubmit={handleSubmit} className="space-y-3.5">
            {mode === 'login' && (
              <>
                <div>
                  <label className="block text-xs font-medium text-ink-600 mb-1.5">Email</label>
                  <DomainEmailInput value={loginLocal} onChange={(v) => { setLoginLocal(v); setError(''); }} autoFocus />
                </div>
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="block text-xs font-medium text-ink-600">Password</label>
                    <button type="button" onClick={() => switchMode('forgot-request')} className="text-xs text-brand-600 hover:text-brand-700 font-medium">
                      Forgot password?
                    </button>
                  </div>
                  <PasswordInput value={form.password} onChange={(e) => set('password', e.target.value)} />
                </div>
              </>
            )}

            {mode === 'register' && (
              <>
                <div>
                  <label className="block text-xs font-medium text-ink-600 mb-1.5">Full name</label>
                  <input required value={form.name} onFocus={() => setRegistrationFocus('name')}
                    onChange={(e) => set('name', e.target.value)}
                    className="w-full border border-ink-200 rounded-lg px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none" />
                  {registrationFocus === 'name' && (
                    <p className="text-[11px] text-ink-400 mt-1">Enter your first and last name.</p>
                  )}
                </div>
                <div>
                  <label className="block text-xs font-medium text-ink-600 mb-1.5">Email</label>
                  <div
                    onFocus={() => setRegistrationFocus('email')}
                    className="w-full flex items-stretch border border-ink-200 rounded-lg overflow-hidden focus-within:border-brand-500 focus-within:ring-1 focus-within:ring-brand-500"
                  >
                    <input required value={emailLocal}
                      onChange={(e) => {
                        const v = e.target.value.replace(/[^a-zA-Z0-9._-]/g, '');
                        setEmailLocal(v);
                        set('email', v ? `${v}@axiotechx.com` : '');
                      }}
                      placeholder="Company email"
                      className="flex-1 min-w-0 px-3 py-2 text-sm outline-none" />
                    <span className="flex items-center px-3 text-sm text-ink-500 bg-ink-50 border-l border-ink-200 select-none whitespace-nowrap">
                      @axiotechx.com
                    </span>
                  </div>
                  {registrationFocus === 'email' && (
                    <p className="text-[11px] text-ink-400 mt-1">Only @axiotechx.com email addresses can register.</p>
                  )}
                  {registrationFocus === 'email' && (
                    <p className="text-[11px] mt-1.5 rounded-md bg-amber-50 border border-amber-200 text-amber-800 px-2 py-1.5">
                    ⚠️ Please enter your email correctly. Approval updates, notifications and password-reset codes are sent to this address — if it is wrong, you will not receive them.
                    </p>
                  )}
                </div>
                <div>
                  <label className="block text-xs font-medium text-ink-600 mb-1.5">Mobile number</label>
                  <input required type="tel" inputMode="numeric" maxLength={10} value={form.mobile}
                    onFocus={() => setRegistrationFocus('mobile')}
                    onChange={(e) => set('mobile', cleanMobile(e.target.value))}
                    placeholder="10-digit mobile number"
                    className="w-full border border-ink-200 rounded-lg px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none" />
                  {registrationFocus === 'mobile' && (
                    <p className={`text-[11px] mt-1 ${form.mobile && form.mobile.length < 10 ? 'text-red-600' : 'text-ink-400'}`}>
                      {form.mobile && form.mobile.length < 10
                        ? `Enter all 10 digits (${form.mobile.length}/10).`
                        : 'Must be 10 digits and start with 6, 7, 8 or 9.'}
                    </p>
                  )}
                </div>
                <div>
                  <label className="block text-xs font-medium text-ink-600 mb-1.5">Password</label>
                  <PasswordInput value={form.password} onFocus={() => setRegistrationFocus('password')}
                    onChange={(e) => set('password', e.target.value)} />
                  {registrationFocus === 'password' && <PasswordRules password={form.password} />}
                </div>
                <div>
                  <label className="block text-xs font-medium text-ink-600 mb-1.5">Re-enter password</label>
                  <PasswordInput value={form.confirmPassword} onFocus={() => setRegistrationFocus('confirmPassword')}
                    onChange={(e) => set('confirmPassword', e.target.value)} />
                  {registrationFocus === 'confirmPassword' && (
                    <p className={`text-[11px] mt-1 ${form.confirmPassword === form.password ? 'text-green-600' : 'text-red-600'}`}>
                      {form.confirmPassword
                        ? form.confirmPassword === form.password ? '✓ Passwords match' : "✗ Passwords don't match"
                        : 'Re-enter the same password to confirm it.'}
                    </p>
                  )}
                </div>
                <div>
                  <label className="block text-xs font-medium text-ink-600 mb-1.5">Role</label>
                  <select required value={form.role} onFocus={() => setRegistrationFocus('role')}
                    onChange={(e) => set('role', e.target.value)}
                    className="w-full border border-ink-200 rounded-lg px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none bg-white">
                    <option value="Developer">Developer (DEV)</option>
                    <option value="QA">QA</option>
                    <option value="DevOps">DevOps</option>
                  </select>
                  {registrationFocus === 'role' && (
                    <p className="text-[11px] text-ink-400 mt-1">This is the role you're requesting — an admin confirms it on approval.</p>
                  )}
                </div>
              </>
            )}

            {mode === 'forgot-request' && (
              <div>
                <label className="block text-xs font-medium text-ink-600 mb-1.5">Email</label>
                <DomainEmailInput value={forgotLocal} onChange={(v) => { setForgotLocal(v); setError(''); }} autoFocus />
              </div>
            )}

            {mode === 'forgot-verify' && (
              <>
                <div>
                  <label className="block text-xs font-medium text-ink-600 mb-1.5">6-digit code</label>
                  <input required value={forgot.otp} onChange={(e) => setForgotField('otp', e.target.value)}
                    inputMode="numeric" maxLength={6} placeholder="123456"
                    className="w-full border border-ink-200 rounded-lg px-3 py-2 text-sm tracking-[0.3em] text-center font-mono focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-ink-600 mb-1.5">New password</label>
                  <PasswordInput value={forgot.newPassword} onChange={(e) => setForgotField('newPassword', e.target.value)} />
                  <PasswordRules password={forgot.newPassword} />
                </div>
                <div>
                  <label className="block text-xs font-medium text-ink-600 mb-1.5">Confirm new password</label>
                  <PasswordInput value={forgot.confirmPassword} onChange={(e) => setForgotField('confirmPassword', e.target.value)} />
                </div>
                <button
                  type="button"
                  onClick={async () => {
                    setError('');
                    try { await authService.requestPasswordReset(`${forgotLocal}${DOMAIN}`); toast.success('A new code has been sent.'); }
                    catch (e) { setError(e.message); }
                  }}
                  className="text-xs text-brand-600 hover:text-brand-700 font-medium"
                >
                  Didn't get a code? Resend
                </button>
              </>
            )}

            {error && <div className="text-xs text-danger-text bg-danger-bg rounded-lg px-3 py-2">{error}</div>}

            <Button type="submit" loading={loading} className="w-full !bg-gradient-to-r !from-brand-500 !to-[#8B5CF6] hover:!opacity-90" size="lg">
              {mode === 'login' && 'Sign in'}
              {mode === 'register' && 'Submit registration'}
              {mode === 'forgot-request' && 'Send code'}
              {mode === 'forgot-verify' && 'Update password'}
            </Button>
          </form>

          {(mode === 'login' || mode === 'register') && (
            <button
              onClick={() => switchMode(mode === 'login' ? 'register' : 'login')}
              className="w-full text-center text-xs text-ink-500 hover:text-brand-600 mt-4 font-medium"
            >
              {mode === 'login' ? (
                <>
                  Don't have an account?{' '}
                  <span className="text-[#F97316] hover:text-[#EA580C] font-bold text-sm underline underline-offset-2">Register</span>
                </>
              ) : 'Already have an account? Sign in'}
            </button>
          )}
        </div>

        <p className="text-center text-[11px] text-white/50 mt-6">© {new Date().getFullYear()} OPSFlow</p>
      </div>
    </div>
  );
}