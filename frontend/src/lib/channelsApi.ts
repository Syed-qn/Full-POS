import { apiClient } from "./apiClient";

export interface ChannelConfig {
  enabled: boolean;
  accepting: boolean;
  commission_pct: number;
  mode: string; // mock | live
  api_key?: string | null;
  api_key_set?: boolean;
  api_secret_set?: boolean;
  access_token_set?: boolean;
  store_id?: string | null;
  base_url?: string | null;
  webhook_secret_set?: boolean;
  /** Tenant public webhook: /api/v1/public/store/{slug}/aggregators/{provider}/webhook */
  webhook_url?: string | null;
  /** Partner path requiring restaurant X-API-Key */
  partner_webhook_url?: string | null;
  credential_hint?: string | null;
  order_url?: string | null;
  slug?: string | null;
}

export interface ChannelsOut {
  channels: Record<string, ChannelConfig>;
  providers: string[];
  public_slug?: string | null;
  order_links: Record<string, string>;
  /** Multi-tenant isolation note from API */
  tenant_scope?: string;
}

export interface SyncResult {
  provider: string;
  success: boolean;
  action: string;
  detail?: string | null;
  items_touched: number;
}

export interface CommissionRow {
  channel: string;
  order_count: number;
  gross_revenue_aed: string;
  commission_pct: number;
  commission_aed: string;
  net_revenue_aed: string;
}

export interface ProfitRow extends CommissionRow {
  food_cost_pct: number;
  estimated_food_cost_aed: string;
  estimated_profit_aed: string;
}

export interface InboxOrder {
  id: number;
  order_number: string;
  status: string;
  total_aed: string;
  source_channel: string;
  aggregator_source?: string | null;
  aggregator_order_ref?: string | null;
  order_type: string;
  created_at?: string | null;
}

export interface SettlementOut {
  id: number;
  provider: string;
  period_start: string;
  period_end: string;
  order_count: number;
  gross_revenue_aed: string;
  commission_aed: string;
  net_aed: string;
  status: string;
  external_ref?: string | null;
  notes?: string | null;
}

export function fetchChannels() {
  return apiClient.get<ChannelsOut>("/api/v1/aggregators/channels");
}

export function updateChannels(
  channels: Record<
    string,
    Partial<ChannelConfig> & {
      api_key?: string | null;
      api_secret?: string | null;
      webhook_secret?: string | null;
      access_token?: string | null;
    }
  >,
) {
  return apiClient.put<ChannelsOut>("/api/v1/aggregators/channels", { channels });
}

export function providerLiveHealth(provider: string) {
  return apiClient.post<{
    provider: string;
    mode: string;
    success: boolean;
    detail?: string | null;
  }>(`/api/v1/aggregators/${encodeURIComponent(provider)}/live-health`, {});
}

export function pauseChannel(channel: string) {
  return apiClient.post<ChannelsOut>(`/api/v1/aggregators/channels/${channel}/pause`, {});
}

export function resumeChannel(channel: string) {
  return apiClient.post<ChannelsOut>(`/api/v1/aggregators/channels/${channel}/resume`, {});
}

export function ensurePublicSlug(slug?: string) {
  return apiClient.post<ChannelsOut>("/api/v1/aggregators/public-slug", { slug: slug || null });
}

export function syncMenu(providers?: string[]) {
  return apiClient.post<SyncResult[]>("/api/v1/aggregators/sync/menu", {
    providers: providers ?? null,
  });
}

export function syncStock(providers?: string[]) {
  return apiClient.post<SyncResult[]>("/api/v1/aggregators/sync/stock", {
    providers: providers ?? null,
  });
}

export function syncPrice(providers?: string[]) {
  return apiClient.post<SyncResult[]>("/api/v1/aggregators/sync/price", {
    providers: providers ?? null,
  });
}

export function fetchReconciliation(startDate: string, endDate: string) {
  return apiClient.get<
    Record<
      string,
      {
        order_count: number;
        revenue_aed: string;
        commission_pct: number;
        commission_aed: string;
        net_aed: string;
      }
    >
  >(`/api/v1/aggregators/reconciliation?start_date=${startDate}&end_date=${endDate}`);
}

export function fetchCommissionReport(startDate: string, endDate: string) {
  return apiClient.get<{ rows: CommissionRow[] }>(
    `/api/v1/aggregators/reports/commission?start_date=${startDate}&end_date=${endDate}`,
  );
}

export function fetchProfitReport(startDate: string, endDate: string) {
  return apiClient.get<{ rows: ProfitRow[] }>(
    `/api/v1/aggregators/reports/profit?start_date=${startDate}&end_date=${endDate}`,
  );
}

export function fetchChannelInbox(channel?: string) {
  const qs = channel ? `?channel=${encodeURIComponent(channel)}` : "";
  return apiClient.get<{ orders: InboxOrder[] }>(`/api/v1/aggregators/inbox${qs}`);
}

export function fetchSettlements(provider?: string) {
  const qs = provider ? `?provider=${encodeURIComponent(provider)}` : "";
  return apiClient.get<SettlementOut[]>(`/api/v1/aggregators/settlements${qs}`);
}

export function createSettlement(body: {
  provider: string;
  period_start: string;
  period_end: string;
  order_count: number;
  gross_revenue_aed: string;
  commission_aed: string;
  net_aed?: string;
  external_ref?: string;
}) {
  return apiClient.post<SettlementOut>("/api/v1/aggregators/settlements", body);
}

/** Public unauthenticated storefront menu. */
export function fetchPublicStoreMenu(slug: string, channel = "website") {
  return apiClient.get<
    Array<{
      id: number;
      dish_number?: number | null;
      name: string;
      description?: string | null;
      price_aed: string;
      category?: string | null;
      image_url?: string | null;
      is_available: boolean;
    }>
  >(`/api/v1/public/store/${encodeURIComponent(slug)}/menu?channel=${encodeURIComponent(channel)}`);
}

export function placePublicStoreOrder(
  slug: string,
  body: {
    customer_phone: string;
    customer_name?: string;
    items: Array<{ dish_id: number; qty: number }>;
    channel?: string;
    table_id?: number;
    notes?: string;
  },
) {
  return apiClient.post<{
    id: number;
    order_number: string;
    status: string;
    source_channel: string;
    total_aed: string;
  }>(`/api/v1/public/store/${encodeURIComponent(slug)}/orders`, body);
}
