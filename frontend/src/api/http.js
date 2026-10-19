/** api/http.js */

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
