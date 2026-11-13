import { api } from './apiClient';

// Sends what the user said (already converted to text by the browser) to the
// backend, which answers with { speech, intent, route, results, action, focus, ... }.
export const voiceService = {
  // `context` = what is on screen ({ route, recordId, lastRecordId, results }) so "approve it" works.
  // `history` = the last few turns of the conversation, so the AI understands follow-ups.
  command(text, { context, history } = {}) {
    return api.post('voiceCommand', { text, context, history });
  },
  // Guided form filling: current form values + what was just said ->
  // { speech, patch, flow, progress, done }. Never submits anything.
  form(payload) {
    return api.post('voiceForm', payload);
  },
  // Fire-and-forget the moment "Hello Ops" is heard: the server opens its AI connection
  // while the user is still talking, so the answer comes back faster.
  // Short-lived token for the professional speech-to-text service ({ enabled:false } when no key is set).
  sttToken() {
    return api.post('voiceSttToken', {});
  },
  warmup() {
    return api.post('voiceWarmup', {}).catch(() => null);
  },
};
