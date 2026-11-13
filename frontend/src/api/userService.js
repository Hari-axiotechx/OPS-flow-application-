import { api } from './apiClient';

export const userService = {
  list() { return api.get('listUsers'); },
  listDevOps() { return api.get('listDevOpsUsers'); },
  // People that can be searched and picked in the To / Cc boxes of the request forms.
  listEmailRecipients() { return api.get('listEmailRecipients'); },
  // Admin only: sends a real test e-mail now and returns the mail server's real answer.
  sendTestEmail(to) { return api.post('sendTestEmail', { to }); },
  updateProfile(fields) { return api.post('updateProfile', fields); },
  approve(id, role, power) { return api.post('adminApproveUser', { id, role, power }); },
  reject(id, reason) { return api.post('adminRejectUser', { id, reason }); },
  create(fields) { return api.post('adminCreateUser', fields); },
  update(id, role, power) { return api.post('adminUpdateUser', { id, role, power }); },
  setActive(id, active) { return api.post('adminDeactivateUser', { id, active }); }
};
