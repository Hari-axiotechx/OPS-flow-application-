import { api } from './apiClient';

export const accessService = {
  list(params = {}) { return api.get('listRecords', { type: 'ACCESS', ...params }); },
  get(id) { return api.get('getRecord', { id }); },
  create(fields, { sendEmail = true, to = [], cc = [] } = {}) {
    return api.post('createAccess', { fields, sendEmail, emailTo: to, emailCc: cc });
  },
  updateStatus(id, newStatus, reason, { sendEmail = true, to = [], cc = [] } = {}) {
    return api.post('updateAccessStatus', {
      id, newStatus, reason, sendEmail, emailTo: to, emailCc: cc,
    });
  },
  softDelete(id) { return api.post('softDeleteRecord', { id }); }
};
