import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import { notificationService } from '../api/notificationService';
import { useAuth } from './AuthContext';
import { useToast } from './ToastContext';
import { announce, isSpeakEnabled, setSpeakEnabled } from '../voice/announce';

const NotificationContext = createContext(null);

// How often to check the server for new notifications while logged in.
const POLL_MS = 8000;

export function NotificationProvider({ children }) {
  const { user, refreshConfig } = useAuth();
  const toast = useToast();

  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [speakOn, setSpeakOn] = useState(isSpeakEnabled);

  // Remember what we've already seen so we only toast truly new items.
  const seenIds = useRef(new Set());
  const toastRef = useRef(toast);
  const refreshConfigRef = useRef(refreshConfig);
  toastRef.current = toast;
  refreshConfigRef.current = refreshConfig;
  const firstLoad = useRef(true);

  const load = useCallback(async () => {
    if (!user) return;
    try {
      const data = await notificationService.list(50);
      const items = data?.items || [];

      if (!firstLoad.current) {
        const fresh = items.filter((n) => !n.read && !seenIds.current.has(n.id));
        if (fresh.length === 1) {
          toastRef.current?.info?.(`🔔 ${fresh[0].title}`);
        } else if (fresh.length > 1) {
          toastRef.current?.info?.(`🔔 ${fresh.length} new notifications`);
        }
        // Read the new notification(s) aloud.
        if (fresh.length === 1) {
          announce(fresh[0].speech || `New notification. ${fresh[0].title}. ${fresh[0].message || ''}`);
        } else if (fresh.length > 1) {
          const titles = fresh.slice(0, 3).map((n) => n.title).join('. ');
          announce(`You have ${fresh.length} new notifications. ${titles}.`);
        }
        // A new application was added → reload dropdown options.
        if (fresh.some((n) => n.kind === 'application')) {
          refreshConfigRef.current?.();
        }
      }
      items.forEach((n) => seenIds.current.add(n.id));
      firstLoad.current = false;

      setNotifications(items);
      setUnreadCount(data?.unreadCount || 0);
    } catch (error) {
      // Never break the page because notifications failed.
      console.error('Failed to load notifications:', error);
    }
  }, [user]);

  // Start / stop polling with the login session.
  useEffect(() => {
    if (!user) {
      setNotifications([]);
      setUnreadCount(0);
      seenIds.current = new Set();
      firstLoad.current = true;
      return undefined;
    }

    setLoading(true);
    load().finally(() => setLoading(false));

    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') load();
    }, POLL_MS);

    const onFocus = () => load();
    window.addEventListener('focus', onFocus);

    return () => {
      clearInterval(timer);
      window.removeEventListener('focus', onFocus);
    };
  }, [user, load]);

  const markAsRead = useCallback(async (id) => {
    let wasUnread = false;
    setNotifications((cur) =>
      cur.map((n) => {
        if (n.id === id && !n.read) {
          wasUnread = true;
          return { ...n, read: true };
        }
        return n;
      })
    );
    if (wasUnread) setUnreadCount((c) => Math.max(0, c - 1));
    try {
      await notificationService.markRead(id);
    } catch (e) {
      load();
    }
  }, [load]);

  // The delete (bin) symbol: removes the notification for good.
  const deleteNotification = useCallback(async (id) => {
    try {
      await notificationService.remove(id);
      const target = notifications.find((n) => n.id === id);
      setNotifications((cur) => cur.filter((n) => n.id !== id));
      seenIds.current.add(id);
      if (target && !target.read) setUnreadCount((count) => Math.max(0, count - 1));
    } catch (e) {
      toastRef.current?.error?.(e.message || 'Could not delete notification.');
      await load();
    }
  }, [load, notifications]);

  const markAllAsRead = useCallback(async () => {
    setNotifications((cur) => cur.map((n) => ({ ...n, read: true })));
    setUnreadCount(0);
    try {
      await notificationService.markAllRead();
    } catch (e) {
      load();
    }
  }, [load]);

  const toggleSpeak = useCallback(() => {
    setSpeakOn((cur) => {
      setSpeakEnabled(!cur);
      return !cur;
    });
  }, []);

  const toggleNotifications = useCallback(() => setIsOpen((o) => !o), []);
  const closeNotifications = useCallback(() => setIsOpen(false), []);

  const value = useMemo(
    () => ({
      notifications,
      unreadCount,
      loading,
      isOpen,
      speakOn,
      toggleSpeak,
      markAsRead,
      markAllAsRead,
      deleteNotification,
      toggleNotifications,
      closeNotifications,
      refreshNotifications: load,
    }),
    [notifications, unreadCount, loading, isOpen, speakOn, toggleSpeak, markAsRead, markAllAsRead, deleteNotification,
      toggleNotifications, closeNotifications, load]
  );

  return (
    <NotificationContext.Provider value={value}>
      {children}
    </NotificationContext.Provider>
  );
}

export function useNotifications() {
  const context = useContext(NotificationContext);
  if (!context) {
    throw new Error('useNotifications must be used inside NotificationProvider');
  }
  return context;
}
