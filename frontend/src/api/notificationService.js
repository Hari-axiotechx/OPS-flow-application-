import { api } from './apiClient';

// Server-side notifications (stored in Postgres, so they reach the right
// person on any browser / any machine).
export const notificationService = {
  list(limit = 50) {
    return api.get('listNotifications', { limit });
  },
  markRead(id) {
    return api.post('markNotificationRead', { id });
  },
  remove(id) {
    return api.post('deleteNotification', { id });
  },
  markAllRead() {
    return api.post('markAllNotificationsRead');
  },
};