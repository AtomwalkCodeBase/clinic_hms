import { http, API_ENDPOINTS } from "./http";

export const billingApi = {
  /** Record a payment against an invoice: { invoice, amount, payment_mode, transaction_ref }. */
  recordPayment: (payment) => http.post(API_ENDPOINTS.BILLING.PAYMENTS, payment),
};
