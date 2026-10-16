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
});
