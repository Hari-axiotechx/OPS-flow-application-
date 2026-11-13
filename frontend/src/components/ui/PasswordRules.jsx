export function passwordChecks(password) {
  const value = String(password || '');
  return [
    { ok: value.length >= 8, text: 'At least 8 characters' },
    { ok: /[A-Z]/.test(value), text: '1 capital letter (A–Z)' },
    { ok: /\d/.test(value), text: '1 number (0–9)' },
    { ok: /[^A-Za-z0-9]/.test(value), text: '1 special character (e.g. ! @ # $ %)' },
  ];
}

export const passwordValid = (password) => passwordChecks(password).every((check) => check.ok);

export const PASSWORD_RULE_MESSAGE =
  'Password must be at least 8 characters and include 1 capital letter, 1 number and 1 special character.';

export default function PasswordRules({ password }) {
  const checks = passwordChecks(password);
  return (
    <ul className="mt-1.5 space-y-0.5">
      {checks.map((check) => (
        <li
          key={check.text}
          className={`text-[11px] flex items-center gap-1.5 ${
            !password ? 'text-ink-400' : check.ok ? 'text-green-600' : 'text-red-600'
          }`}
        >
          <span className="w-3 text-center font-bold">{check.ok ? '✓' : password ? '✗' : '•'}</span>
          {check.text}
        </li>
      ))}
    </ul>
  );
}
