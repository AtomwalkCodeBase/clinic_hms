import { http, API_ENDPOINTS } from "./http";

/** Hospital-level settings (fee ownership, tax, registration fee, logo, storage folder). Admin only. */
export const orgApi = {
  getSettings:    ()      => http.get(API_ENDPOINTS.ORG.SETTINGS),
  updateSettings: (patch) => http.patch(API_ENDPOINTS.ORG.SETTINGS, patch),
};
