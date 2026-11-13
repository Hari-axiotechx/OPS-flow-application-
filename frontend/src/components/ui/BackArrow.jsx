import { useLocation, useNavigate } from 'react-router-dom';

/**
 * Round back arrow that sits IN FRONT of a page title / record id (e.g.  ←  DEP-000030).
 * Goes to the previous page; if there is none (new tab / refresh) it goes up one level.
 * Not shown on the Dashboard.
 */
export default function BackArrow({ className = '' }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  if (pathname === '/') return null;

  function goBack() {
    if (window.history.state && window.history.state.idx > 0) {
      navigate(-1);
    } else {
      const parent = pathname.split('/').filter(Boolean).slice(0, -1).join('/');
      navigate('/' + parent);
    }
  }

  return (
    <button
      type="button"
      onClick={goBack}
      aria-label="Go back"
      title="Back"
      className={`shrink-0 inline-flex items-center justify-center w-[29px] h-[29px] rounded-full border border-ink-200 bg-white text-ink-700 shadow-sm hover:bg-ink-50 hover:text-ink-900 active:bg-brand-500 active:border-brand-500 active:text-white focus:outline-none focus-visible:bg-brand-500 focus-visible:border-brand-500 focus-visible:text-white transition-colors ${className}`}
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
        <path d="M19 12H5" />
        <path d="M12 19l-7-7 7-7" />
      </svg>
    </button>
  );
}
