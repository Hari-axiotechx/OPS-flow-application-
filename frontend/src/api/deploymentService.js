import { api } from './apiClient';

// Notifications for deployments are now created by the backend (every
// DevOps user is notified of a new request, the requester is notified of
// every status change, etc.). The old localStorage-based notifications
// only worked when sender and receiver used the same browser.

export const deploymentService = {
  list(params = {}) {
    return api.get('listRecords', { type: 'DEPLOYMENT', ...params });
  },

  get(id) {
    return api.get('getRecord', { id });
  },

  // `sendEmail` remains in the payload for compatibility; the backend always sends.
  // `to` / `cc` = user ids picked in the form's To / Cc boxes.
  create(fields, { sendEmail = true, to = [], cc = [] } = {}) {
    return api.post('createDeployment', { fields, sendEmail, emailTo: to, emailCc: cc });
  },

  resubmit(id, fields, { sendEmail = true, to = [], cc = [] } = {}) {
    return api.post('resubmitDeployment', { id, fields, sendEmail, emailTo: to, emailCc: cc });
  },

  // For Success / Failed / Rolled back, `options` = { sendEmail, to, cc } from useEmailNotify().options()
  updateStatus(id, newStatus, reason, { sendEmail, to, cc } = {}) {
    const body = { id, newStatus, reason };
    if (to !== undefined) {
      body.sendEmail = sendEmail !== false;
      body.emailTo = to;
      body.emailCc = cc || [];
    }
    return api.post('updateDeploymentStatus', body);
  },

  updateDetails(id, fields) {
    return api.post('updateDeployment', { id, fields });
  },

  reassign(id, newDevOpsId) {
    return api.post('reassignDeployment', { id, newDevOpsId });
  },

  softDelete(id) {
    return api.post('softDeleteRecord', { id });
  },
};