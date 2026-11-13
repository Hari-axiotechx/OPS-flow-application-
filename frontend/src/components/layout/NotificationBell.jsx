import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useNotifications } from '../../context/NotificationContext';

/* =========================================================
   NOTIFICATION BELL (top-right of the header)
   - Yellow bell icon.
   - Red badge with the unread count whenever something new arrives
     (deployment / access request / AWS issue / new user /
     new application …). Shows 99+ above 99.
   - Click a notification → marks it read and opens the record.
   - Bin symbol on each notification → deletes it.
   - Notifications are removed automatically after 2 days (done by the server).
   ========================================================= */

const KIND_STYLE = {
  deployment: { icon: '🚀', dot: 'bg-info' },
  access: { icon: '🔐', dot: 'bg-warning' },
  aws: { icon: '☁️', dot: 'bg-danger' },
  user: { icon: '👤', dot: 'bg-success' },
  application: { icon: '🧩', dot: 'bg-brand-500' },
  email: { icon: '✉️', dot: 'bg-danger' },
  info: { icon: '🔔', dot: 'bg-ink-400' },
};

function timeAgo(iso) {
  if (!iso) return '';
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (Number.isNaN(diff)) return '';
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  return new Date(iso).toLocaleDateString();
}

export default function NotificationBell() {
  const {
    notifications,
    unreadCount,
    loading,
    markAsRead,
    markAllAsRead,
    deleteNotification,
    refreshNotifications,
    speakOn,
    toggleSpeak,
  } = useNotifications();

  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState(null); // null chooses unread when available
  const wrapRef = useRef(null);
  const navigate = useNavigate();

  // Close on outside click / Escape.
  useEffect(() => {
    if (!open) return undefined;
    function onDown(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    }
    function onKey(e) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  function toggle() {
    const nextOpen = !open;
    if (nextOpen) {
      setFilter(null);
      refreshNotifications?.();
    }
    setOpen(nextOpen);
  }

  function openItem(n) {
    if (!n.read) markAsRead(n.id);
    setOpen(false);
    if (n.link) navigate(n.link);
  }

  const activeFilter = filter || (unreadCount > 0 ? 'unread' : 'all');
  const list = activeFilter === 'unread' ? notifications.filter((n) => !n.read) : notifications;
  const badge = unreadCount > 99 ? '99+' : String(unreadCount);

  return (
    <div className="relative" ref={wrapRef}>
      <button
        type="button"
        onClick={toggle}
        className={`
          relative w-10 h-10 rounded-lg border bg-white flex items-center justify-center
          transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-300
          ${open ? 'border-amber-300 bg-amber-50' : 'border-ink-200 hover:bg-amber-50 hover:border-amber-300'}
        `}
        aria-label={unreadCount ? `Notifications, ${unreadCount} unread` : 'Notifications'}
        aria-haspopup="true"
        aria-expanded={open}
        title="Notifications"
      >
        {/* Yellow bell */}
        <svg
          width="21"
          height="21"
          viewBox="0 0 24 24"
          fill="#FACC15"
          stroke="#CA8A04"
          strokeWidth="1.7"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={unreadCount ? 'bell-ring' : ''}
        >
          <path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" fill="none" />
        </svg>

        {/* Red count badge */}
        {unreadCount > 0 && (
          <span
            className="
              absolute -top-1.5 -right-1.5 min-w-[20px] h-5 px-1.5 rounded-full
              isolate bg-red-600 text-white text-[11px] font-bold leading-5 text-center
              ring-2 ring-white shadow-sm
            "
          >
            {badge}
            <span className="absolute inset-0 rounded-full bg-red-500 opacity-60 animate-ping -z-10" />
          </span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Notifications"
          className="
            absolute right-0 top-12 z-50 w-[360px] max-w-[calc(100vw-2rem)]
            rounded-xl border border-ink-200 bg-white shadow-popover overflow-hidden
          "
        >
          {/* Header */}
          <div className="px-4 pt-3.5 pb-2 border-b border-ink-100">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <p className="text-sm font-semibold text-ink-900">Notifications</p>
                {unreadCount > 0 && (
                  <span className="text-[11px] font-semibold text-red-600 bg-red-50 rounded-full px-2 py-0.5">
                    {unreadCount} new
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={toggleSpeak}
                className="text-xs font-medium text-ink-500 hover:text-brand-700"
                title={speakOn ? 'Notifications are read aloud. Click to mute.' : 'Notifications are muted. Click to read aloud.'}
                aria-pressed={speakOn}
              >
                {speakOn ? '🔊 Voice on' : '🔇 Voice off'}
              </button>
              <button
                type="button"
                onClick={markAllAsRead}
                disabled={unreadCount === 0}
                className="text-xs font-medium text-brand-500 hover:text-brand-700 disabled:text-ink-300 disabled:cursor-default"
              >
                Mark all read
              </button>
              </div>
            </div>

            <div className="flex gap-1 mt-2.5">
              {['all', 'unread'].map((f) => (
                <button
                  key={f}
                  type="button"
                  onClick={() => setFilter(f)}
                  className={`text-xs px-2.5 py-1 rounded-md font-medium transition-colors ${
                    activeFilter === f ? 'bg-ink-900 text-white' : 'text-ink-600 hover:bg-ink-50'
                  }`}
                >
                  {f === 'all' ? 'All' : 'Unread'}
                </button>
              ))}
            </div>
          </div>

          {/* List */}
          <div className="max-h-[420px] overflow-y-auto" style={{ scrollbarWidth: 'thin' }}>
            {loading && notifications.length === 0 && (
              <p className="px-4 py-8 text-center text-sm text-ink-400">Loading…</p>
            )}

            {!loading && list.length === 0 && (
              <div className="px-4 py-10 text-center">
                <div className="text-3xl mb-2">🔕</div>
                <p className="text-sm font-medium text-ink-700">
                  {activeFilter === 'unread' ? "You're all caught up" : 'No notifications yet'}
                </p>
                <p className="text-xs text-ink-400 mt-1">
                  New deployment and access requests will appear here.
                </p>
              </div>
            )}

            {list.map((n) => {
              const k = KIND_STYLE[n.kind] || KIND_STYLE.info;
              return (
                <div
                  key={n.id}
                  className={`
                    group w-full flex items-start gap-1 border-b border-ink-100 last:border-b-0
                    transition-colors hover:bg-ink-50 ${n.read ? '' : 'bg-amber-50/60'}
                  `}
                >
                  <button
                    type="button"
                    onClick={() => openItem(n)}
                    className="flex-1 min-w-0 text-left pl-4 py-3 flex gap-3"
                  >
                    <span className="w-9 h-9 rounded-lg bg-white border border-ink-100 flex items-center justify-center text-base shrink-0">
                      {k.icon}
                    </span>
                    <span className="flex-1 min-w-0">
                      <span className="flex items-start justify-between gap-2">
                        <span className={`text-sm leading-snug ${n.read ? 'text-ink-700' : 'font-semibold text-ink-900'}`}>
                          {n.title}
                        </span>
                        {!n.read && <span className="mt-1.5 w-2 h-2 rounded-full bg-red-600 shrink-0" />}
                      </span>
                      {n.message && (
                        <span className="block text-xs text-ink-600 mt-0.5 line-clamp-2">{n.message}</span>
                      )}
                      <span className="block text-[11px] text-ink-400 mt-1">
                        {n.actor ? `${n.actor} · ` : ''}{timeAgo(n.createdAt)}
                      </span>
                    </span>
                  </button>

                  {/* Delete symbol */}
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); deleteNotification(n.id); }}
                    aria-label="Delete notification"
                    title="Delete"
                    className="shrink-0 mt-3 mr-3 w-7 h-7 rounded-md flex items-center justify-center text-ink-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M3 6h18" />
                      <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
                      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                      <path d="M10 11v6" />
                      <path d="M14 11v6" />
                    </svg>
                  </button>
                </div>
              );
            })}
          </div>

          <p className="px-4 py-2 border-t border-ink-100 text-[11px] text-ink-400 text-center">
            Notifications are deleted automatically after 2 days.
          </p>
        </div>
      )}
    </div>
  );
}
