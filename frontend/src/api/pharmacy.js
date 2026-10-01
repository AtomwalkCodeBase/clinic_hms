import { http, API_ENDPOINTS } from "./http";

export const pharmacyApi = {
  /** Dispense from a stock batch against a prescription item: { prescription_item, stock, quantity }. */
  dispense:     (body) => http.post(API_ENDPOINTS.PHARMACY.DISPENSE, body),
  /** Receive stock into a batch (creates the batch or tops up an existing one). */
  receiveStock: (body) => http.post(API_ENDPOINTS.PHARMACY.STOCK, body),
};
