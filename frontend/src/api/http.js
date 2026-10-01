/**
 * api/http.js
 * -----------
 * The one place pages/components reach the backend from. Domain modules in this folder
 * (org.js, encounter.js, …) wrap services/api.client.js + config/api.config.js so that:
 *   - URLs and HTTP verbs live next to each other, not scattered through JSX
 *   - a component calls `encounterApi.sign(id)`, not `apiClient.post(API_ENDPOINTS.OPD.ENCOUNTER_SIGN(id), {})`
 *
 * The wrappers return the raw axios response (so existing `res.data?.data` handling keeps working);
 * use `unwrap(res)` for the standard `{ success, message, data }` envelope (see core/response.py).
 * Errors are the normalised `{ message, errors, status, data }` object from api.client.js.
 */

import apiClient from "../services/api.client";
import API_ENDPOINTS from "../config/api.config";

export { apiClient, API_ENDPOINTS };

/** `{ data: { success, message, data } }` → the inner `data` (or the body itself when it has no envelope). */
export function unwrap(response) {
  const body = response?.data;
  return body?.data !== undefined ? body.data : body;
}

export const http = {
  get:    (url, config)       => apiClient.get(url, config),
  post:   (url, body, config) => apiClient.post(url, body, config),
  patch:  (url, body, config) => apiClient.patch(url, body, config),
  put:    (url, body, config) => apiClient.put(url, body, config),
  delete: (url, config)       => apiClient.delete(url, config),
};
