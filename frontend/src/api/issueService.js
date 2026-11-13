import { api } from './apiClient';

// The DEV/QA/UAT "Issue Tracker" module has been removed from the app.
// Only AWS Issues remain (production incidents filed against a specific
// AWS service — EC2, S3, RDS, etc).
export const awsIssueService = {
  list(params = {}) { return api.get('listRecords', { type: 'AWS_ISSUE', ...params }); },
  get(id) { return api.get('getRecord', { id }); },
  create(fields, { sendEmail = true, to = [], cc = [] } = {}) {
    return api.post('createAwsIssue', { fields, sendEmail, emailTo: to, emailCc: cc });
  },
  update(id, fields, newStatus) { return api.post('updateAwsIssue', { id, fields, newStatus }); },
  reopen(id, reason) { return api.post('reopenAwsIssue', { id, reason }); },
  softDelete(id) { return api.post('softDeleteRecord', { id }); }
};