import { apiClient } from "./apiClient";

export type TaxSettings = {
  trn: string | null;
  legal_name: string | null;
  legal_name_ar: string | null;
  tax_pricing_mode: "inclusive" | "exclusive" | string;
  default_vat_rate: string;
  simplified_invoice_threshold_aed: string;
  data_retention_days: number;
  buyer_trn_required_for_b2b: boolean;
  e_invoice_enabled: boolean;
  asp_provider: string;
  asp_api_key_set?: boolean;
};

export function getTaxSettings() {
  return apiClient.get<TaxSettings>("/api/v1/compliance/tax-settings");
}

export function patchTaxSettings(body: Partial<TaxSettings> & { asp_api_key?: string }) {
  return apiClient.patch<TaxSettings>("/api/v1/compliance/tax-settings", body);
}

export function getComplianceInvoice(
  orderId: number,
  params?: { document_type?: string; buyer_trn?: string },
) {
  const q = new URLSearchParams();
  if (params?.document_type) q.set("document_type", params.document_type);
  if (params?.buyer_trn) q.set("buyer_trn", params.buyer_trn);
  const qs = q.toString();
  return apiClient.get<Record<string, unknown>>(
    `/api/v1/compliance/invoices/${orderId}${qs ? `?${qs}` : ""}`,
  );
}

export function getStructuredInvoice(orderId: number) {
  return apiClient.get<Record<string, unknown>>(
    `/api/v1/compliance/invoices/${orderId}/structured`,
  );
}

export function listRefundNotes() {
  return apiClient.get<
    Array<{
      id: number;
      refund_note_number: string;
      order_id: number;
      amount_aed: string;
      vat_amount_aed: string;
      reason: string | null;
      issued_at: string | null;
    }>
  >("/api/v1/compliance/refund-notes");
}

export function createRefundNote(body: {
  order_id: number;
  amount_aed: string | number;
  reason?: string;
  transaction_id?: number;
}) {
  return apiClient.post<{
    id: number;
    refund_note_number: string;
    amount_aed: string;
  }>("/api/v1/compliance/refund-notes", body);
}

export function getRefundNoteDoc(id: number) {
  return apiClient.get<Record<string, unknown>>(`/api/v1/compliance/refund-notes/${id}`);
}

export function getEInvoiceReadiness() {
  return apiClient.get<{
    ready: boolean;
    e_invoice_enabled: boolean;
    asp_provider: string;
    asp_credentials_configured: boolean;
    structured_profile: string;
    missing_fields: string[];
    notes: string;
  }>("/api/v1/compliance/e-invoice/readiness");
}

export function transmitEInvoice(body: {
  order_id: number;
  document_type?: string;
  buyer_trn?: string;
}) {
  return apiClient.post<{
    id: number;
    status: string;
    external_id: string | null;
    asp_provider: string;
    error: string | null;
  }>("/api/v1/compliance/e-invoice/transmit", body);
}

export function listEInvoiceTransmissions() {
  return apiClient.get<
    Array<{
      id: number;
      order_id: number;
      status: string;
      asp_provider: string;
      external_id: string | null;
      document_type: string;
      error: string | null;
      transmitted_at: string | null;
    }>
  >("/api/v1/compliance/e-invoice/transmissions");
}

export function runRetention(body?: { dry_run?: boolean; retention_days?: number }) {
  return apiClient.post<{
    id: number;
    status: string;
    retention_days: number;
    purged_counts: Record<string, number>;
    notes: string | null;
  }>("/api/v1/compliance/retention/run", body ?? { dry_run: true });
}

export function listRetentionRuns() {
  return apiClient.get<
    Array<{
      id: number;
      status: string;
      retention_days: number;
      purged_counts: Record<string, number>;
      notes: string | null;
      created_at: string | null;
    }>
  >("/api/v1/compliance/retention/runs");
}

export function accountantExport(startDate: string, endDate: string, format: "json" | "csv" = "json") {
  return apiClient.get<{
    format: string;
    summary: {
      order_count: number;
      net_total_aed: string;
      vat_total_aed: string;
      gross_total_aed: string;
      refund_note_count: number;
      credit_note_count: number;
    };
    trn: string | null;
    csv?: string;
    orders?: unknown[];
  }>(
    `/api/v1/compliance/accountant-export?start_date=${startDate}&end_date=${endDate}&format=${format}`,
  );
}
