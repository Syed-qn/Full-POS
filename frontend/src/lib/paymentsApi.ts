import { apiClient } from "./apiClient";

export interface CredentialsStatus {
  provider: string;
  configured: boolean;
}

export interface BillingSettings {
  service_charge_pct: number;
  packaging_charge_aed: number;
  min_order_aed: number;
}

export interface PaymentTxn {
  id: number;
  order_id?: number;
  status: string;
  provider?: string;
  tender_type?: string;
  amount_aed: string;
  tip_aed?: string;
  channel?: string;
  reference_meta?: string | null;
  wallet_session_id?: string | null;
  provider_charge_id?: string | null;
  refunded_amount_aed?: string;
  order_total_paid_aed?: string;
}

export interface PaymentLinkOut {
  id: number;
  order_id: number;
  token: string;
  amount_aed: string;
  status: string;
  expires_at: string;
  url: string;
}

export interface GiftCardOut {
  id: number;
  code: string;
  balance_aed: string;
  initial_amount_aed?: string;
  status: string;
}

export interface CashDrawerSession {
  id: number;
  status: string;
  opening_float_aed: string;
  closing_count_aed?: string | null;
  variance_aed?: string | null;
  opened_by?: string;
  closed_by?: string | null;
}

export function getPaymentCredentials() {
  return apiClient.get<CredentialsStatus>("/api/v1/payments/credentials");
}

export function setPaymentCredentials(provider: string, secretKey: string) {
  return apiClient.put<CredentialsStatus>("/api/v1/payments/credentials", {
    provider,
    secret_key: secretKey,
  });
}

export function deletePaymentCredentials() {
  return apiClient.delete<void>("/api/v1/payments/credentials");
}

export function getBillingSettings() {
  return apiClient.get<BillingSettings>("/api/v1/payments/billing-settings");
}

export function setBillingSettings(body: Partial<BillingSettings>) {
  return apiClient.put<BillingSettings>("/api/v1/payments/billing-settings", body);
}

export function chargePayment(body: {
  order_id: number;
  tender_type: string;
  amount_aed: string;
  tip_aed?: string;
  channel?: string;
  room_number?: string;
  terminal_id?: string;
  wallet_session_id?: string;
}) {
  return apiClient.post<PaymentTxn>("/api/v1/payments/charge", body);
}

export function createWalletSession(body: {
  order_id: number;
  tender_type: string;
  amount_aed: string;
}) {
  return apiClient.post<{
    session_id: string;
    client_secret?: string;
    tender_type: string;
  }>("/api/v1/payments/wallet-session", body);
}

export function refundPayment(transactionId: number, amount_aed: string) {
  return apiClient.post<{ id: number; status: string; refunded_amount_aed: string }>(
    `/api/v1/payments/${transactionId}/refund`,
    { amount_aed },
  );
}

export function createCreditNote(transactionId: number, amount_aed: string, reason?: string) {
  return apiClient.post(`/api/v1/payments/${transactionId}/credit-note`, {
    amount_aed,
    reason,
  });
}

export function createPaymentLink(orderId: number, amountAed?: string) {
  return apiClient.post<PaymentLinkOut>("/api/v1/payments/links", {
    order_id: orderId,
    amount_aed: amountAed,
  });
}

export function listPaymentLinks(status?: string) {
  const q = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiClient.get<PaymentLinkOut[]>(`/api/v1/payments/links${q}`);
}

export function listOrderPayments(orderId: number) {
  return apiClient.get<{
    order_id: number;
    total_paid_aed: string;
    transactions: PaymentTxn[];
  }>(`/api/v1/orders/${orderId}/payments`);
}

export function chargeDeposit(orderId: number, amount_aed: string) {
  return apiClient.post(`/api/v1/orders/${orderId}/deposit`, { amount_aed });
}

export function markPayLater(orderId: number, amount_aed?: string) {
  return apiClient.post<PaymentTxn>(`/api/v1/orders/${orderId}/pay-later`, {
    amount_aed: amount_aed,
  });
}

export function applyOrderDiscount(
  orderId: number,
  body: {
    discount_type: "manager" | "staff";
    amount_aed: string;
    reason?: string;
    staff_id?: number;
  },
) {
  return apiClient.post(`/api/v1/orders/${orderId}/discounts`, body);
}

export function importSettlement(body: {
  provider?: string;
  provider_payout_id: string;
  amount_aed: string;
  lines: Array<{ provider_charge_id: string; amount_aed: string }>;
  notes?: string;
}) {
  return apiClient.post("/api/v1/payments/reconciliation/import", body);
}

export function getReconciliationReport() {
  return apiClient.get<{
    gateway_txn_count: number;
    matched_line_count: number;
    unmatched_txn_count: number;
    gateway_total_aed: string;
    matched_total_aed: string;
    unmatched_transactions: Array<{
      id: number;
      provider_charge_id: string | null;
      amount_aed: string;
      tender_type: string;
    }>;
  }>("/api/v1/payments/reconciliation/report");
}

export function issueGiftCard(body: { amount_aed: string; pin: string; code?: string }) {
  return apiClient.post<GiftCardOut>("/api/v1/gift-cards/issue", body);
}

export function listGiftCards() {
  return apiClient.get<GiftCardOut[]>("/api/v1/gift-cards");
}

export function redeemGiftCard(body: {
  code: string;
  pin: string;
  order_id: number;
  amount_aed: string;
}) {
  return apiClient.post("/api/v1/gift-cards/redeem", body);
}

export function openCashDrawer(opening_float_aed: string) {
  return apiClient.post<CashDrawerSession>("/api/v1/cash-drawer/sessions", {
    opening_float_aed,
  });
}

export function getCurrentCashDrawer() {
  return apiClient.get<CashDrawerSession>("/api/v1/cash-drawer/sessions/current");
}

export function addCashDrawerEvent(
  sessionId: number,
  body: { type: "cash_in" | "cash_out"; amount_aed: string; reason?: string },
) {
  return apiClient.post(`/api/v1/cash-drawer/sessions/${sessionId}/events`, body);
}

export function closeCashDrawer(sessionId: number, closing_count_aed: string) {
  return apiClient.post<CashDrawerSession>(`/api/v1/cash-drawer/sessions/${sessionId}/close`, {
    closing_count_aed,
  });
}
