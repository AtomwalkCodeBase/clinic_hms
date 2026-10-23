// Thin API client over our authenticated axios instance (services/api.client.js); the urls are in config/api.config.js.
import API_ENDPOINTS from '../../config/api.config';

export const makePedsApi = (http) => ({
  timeline: (awpid, { from, to, view } = {}) =>
    http.get(API_ENDPOINTS.RECORDS.HEALTH_TIMELINE(awpid), { params: { from, to, view } }).then(r => r.data),
  growth: (awpid, indicator) =>
    http.get(API_ENDPOINTS.RECORDS.GROWTH(awpid), { params: { indicator } }).then(r => r.data),
  immunization: (awpid) =>
    http.get(API_ENDPOINTS.RECORDS.IMMUNIZATION(awpid)).then(r => r.data),
  addVaccine: (awpid, body) =>
    http.post(API_ENDPOINTS.RECORDS.IMMUNIZATION(awpid), body).then(r => r.data),
  // clinician only (the server checks the role)
  patchEvent: (eventId, body) => http.patch(API_ENDPOINTS.RECORDS.REVIEW_EVENT(eventId), body).then(r => r.data),
  acknowledgeFlag: (flagId) => http.post(API_ENDPOINTS.RECORDS.ACKNOWLEDGE_RECURRENCE(flagId)).then(r => r.data),
  clinicalSummary: (awpid) => http.get(API_ENDPOINTS.RECORDS.CLINICAL_SUMMARY(awpid)).then(r => r.data),
  rebuild: (awpid) => http.post(API_ENDPOINTS.RECORDS.REBUILD_TIMELINE(awpid)).then(r => r.data),
});
