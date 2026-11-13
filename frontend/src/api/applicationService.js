import { api } from './apiClient';

export const applicationService = {
  list() {
    return api.get('listApplications');
  },
  // Admin only (DevOps + power). Returns { record, config }.
  add(name, date) {
    return api.post('adminAddApplication', { name, date });
  },
  // Admin only (DevOps + power). Soft-deletes a custom application
  // (the ones seeded by default can't be removed). Returns { config }.
  remove(name) {
    return api.post('adminRemoveApplication', { name });
  },
};