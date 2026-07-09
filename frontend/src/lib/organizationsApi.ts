import { ApiError } from "./apiClient";
import type {
  BranchComparisonOut,
  OrganizationBranchIn,
  OrganizationBranchOut,
  OrganizationInventorySummaryOut,
  OrganizationRollupSalesOut,
  StockTransferIn,
  StockTransferOut,
  TokenOut,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";
export const ORG_TOKEN_KEY = "ops_org_token";

export function getOrgToken(): string | null {
  return localStorage.getItem(ORG_TOKEN_KEY);
}

export function setOrgToken(token: string | null): void {
  if (token) {
    localStorage.setItem(ORG_TOKEN_KEY, token);
  } else {
    localStorage.removeItem(ORG_TOKEN_KEY);
  }
}

function decodeBase64Url(value: string): string {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "=");
  return atob(padded);
}

export function getOrgIdFromToken(token = getOrgToken()): number | null {
  if (!token) return null;
  const [, payload] = token.split(".");
  if (!payload) return null;
  try {
    const claims = JSON.parse(decodeBase64Url(payload)) as { sub?: unknown };
    const orgId = Number(claims.sub);
    return Number.isFinite(orgId) ? orgId : null;
  } catch {
    return null;
  }
}

function authHeaders(): Record<string, string> {
  const token = getOrgToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function parseError(resp: Response): Promise<string> {
  let detail = resp.statusText;
  try {
    const data = await resp.json();
    detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
  } catch {
    // Non-JSON error body.
  }
  return detail;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  authenticated = true,
): Promise<T> {
  const headers: Record<string, string> = authenticated ? { ...authHeaders() } : {};
  let payload: BodyInit | undefined;
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  const resp = await fetch(`${API_BASE}${path}`, { method, headers, body: payload });
  if (!resp.ok) {
    if (resp.status === 401) setOrgToken(null);
    throw new ApiError(resp.status, await parseError(resp));
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

async function authRequest(path: string, body: unknown): Promise<void> {
  const token = await request<TokenOut>("POST", path, body, false);
  setOrgToken(token.access_token);
}

export function loginOrganization(ownerEmail: string, password: string): Promise<void> {
  return authRequest("/api/v1/organizations/login", {
    owner_email: ownerEmail,
    password,
  });
}

export function signupOrganization(name: string, ownerEmail: string, password: string): Promise<void> {
  return authRequest("/api/v1/organizations/signup", {
    name,
    owner_email: ownerEmail,
    password,
  });
}

function query(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, value);
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

export function listBranches(): Promise<OrganizationBranchOut[]> {
  return request<OrganizationBranchOut[]>("GET", "/api/v1/organizations/branches");
}

export function createBranch(body: OrganizationBranchIn): Promise<OrganizationBranchOut> {
  return request<OrganizationBranchOut>("POST", "/api/v1/organizations/branches", body);
}

export function getRollupSales(targetDate: string): Promise<OrganizationRollupSalesOut> {
  return request<OrganizationRollupSalesOut>(
    "GET",
    `/api/v1/organizations/rollup-sales${query({ target_date: targetDate })}`,
  );
}

export function getBranchComparison(
  organizationId: number,
  startDate: string,
  endDate: string,
): Promise<BranchComparisonOut[]> {
  return request<BranchComparisonOut[]>(
    "GET",
    `/api/v1/organizations/${organizationId}/branch-comparison${query({
      start_date: startDate,
      end_date: endDate,
    })}`,
  );
}

export function getOrganizationInventorySummary(): Promise<OrganizationInventorySummaryOut> {
  return request<OrganizationInventorySummaryOut>("GET", "/api/v1/organizations/inventory-summary");
}

export function createStockTransfer(organizationId: number, body: StockTransferIn): Promise<StockTransferOut> {
  return request<StockTransferOut>("POST", `/api/v1/organizations/${organizationId}/stock-transfers`, body);
}

export function completeStockTransfer(transferId: number): Promise<StockTransferOut> {
  return request<StockTransferOut>("POST", `/api/v1/stock-transfers/${transferId}/complete`);
}

export function getOrgMe() {
  return request<{
    id: number;
    name: string;
    royalty_pct: string;
    default_currency: string;
    default_locale: string;
    settings: Record<string, unknown>;
  }>("GET", "/api/v1/organizations/me");
}

export function patchOrgMe(body: {
  royalty_pct?: string | number;
  default_currency?: string;
  default_locale?: string;
  settings?: Record<string, unknown>;
}) {
  return request("PATCH", "/api/v1/organizations/me", body);
}

export function patchBranch(
  restaurantId: number,
  body: {
    name?: string;
    region?: string;
    currency?: string;
    locale?: string;
    is_central_kitchen?: boolean;
  },
) {
  return request("PATCH", `/api/v1/organizations/branches/${restaurantId}`, body);
}

export function createOrgMenuItem(body: {
  name: string;
  base_price_aed: string;
  category?: string;
  name_ar?: string;
  dish_number?: number;
}) {
  return request<{ id: number; name: string; base_price_aed: string }>(
    "POST",
    "/api/v1/organizations/menu-items",
    body,
  );
}

export function listOrgMenuItems() {
  return request<
    Array<{
      id: number;
      name: string;
      name_ar?: string | null;
      category?: string | null;
      base_price_aed: string;
      is_active: boolean;
    }>
  >("GET", "/api/v1/organizations/menu-items");
}

export function setBranchPrice(body: {
  org_menu_item_id: number;
  restaurant_id: number;
  price_aed: string;
}) {
  return request("POST", "/api/v1/organizations/branch-prices", body);
}

export function requestMenuPublish(body?: {
  target_restaurant_ids?: number[];
  org_menu_item_ids?: number[];
  notes?: string;
}) {
  return request<{ id: number; status: string }>("POST", "/api/v1/organizations/menu-publish", body ?? {});
}

export function decideMenuPublish(jobId: number, approve: boolean) {
  return request<{ id: number; status: string; result?: Record<string, unknown> }>(
    "POST",
    `/api/v1/organizations/menu-publish/${jobId}/decide`,
    { approve, approved_by: "hq" },
  );
}

export function getRoyaltyReport(startDate: string, endDate: string) {
  return request<{
    royalty_pct: number;
    total_revenue_aed: string;
    total_royalty_aed: string;
    branches: Array<{
      restaurant_name: string;
      revenue_aed: string;
      royalty_aed: string;
    }>;
  }>("GET", `/api/v1/organizations/royalty${query({ start_date: startDate, end_date: endDate })}`);
}

export function getRegionReport(startDate: string, endDate: string) {
  return request<
    Array<{
      region: string;
      branch_count: number;
      order_count: number;
      revenue_aed: string;
    }>
  >("GET", `/api/v1/organizations/region-report${query({ start_date: startDate, end_date: endDate })}`);
}

export function createOrgCustomer(body: { phone: string; name?: string; preferred_locale?: string }) {
  return request("POST", "/api/v1/organizations/customers", body);
}

export function listOrgCustomers() {
  return request<
    Array<{
      id: number;
      phone: string;
      name?: string | null;
      loyalty_points: number;
      total_spend_aed: string;
    }>
  >("GET", "/api/v1/organizations/customers");
}

export function creditOrgLoyalty(body: { phone: string; points: number; spend_aed?: string }) {
  return request("POST", "/api/v1/organizations/loyalty/credit", body);
}

export function createOrgPromotion(body: {
  code: string;
  title: string;
  discount_aed: string;
  target_restaurant_ids?: number[];
}) {
  return request<{ id: number; code: string }>("POST", "/api/v1/organizations/promotions", body);
}

export function pushOrgPromotion(promoId: number) {
  return request("POST", `/api/v1/organizations/promotions/${promoId}/push`);
}

export function createOrgMember(body: {
  email: string;
  name: string;
  role: string;
  branch_ids?: number[];
}) {
  return request("POST", "/api/v1/organizations/members", body);
}

export function listOrgMembers() {
  return request<
    Array<{ id: number; email: string; name: string; role: string; branch_ids: number[] }>
  >("GET", "/api/v1/organizations/members");
}

export function createCentralKitchenRequest(body: {
  from_restaurant_id: number;
  items: Array<Record<string, unknown>>;
  notes?: string;
}) {
  return request<{ id: number; status: string }>(
    "POST",
    "/api/v1/organizations/central-kitchen/requests",
    body,
  );
}

export function listCentralKitchenRequests() {
  return request<
    Array<{
      id: number;
      status: string;
      from_restaurant_id: number;
      central_kitchen_id: number;
      items: unknown[];
    }>
  >("GET", "/api/v1/organizations/central-kitchen/requests");
}

export function updateCentralKitchenStatus(requestId: number, status: string) {
  return request("POST", `/api/v1/organizations/central-kitchen/requests/${requestId}/status`, {
    status,
  });
}

export function bulkUpdateBranches(body: {
  restaurant_ids: number[];
  action: string;
  payload: Record<string, unknown>;
}) {
  return request("POST", "/api/v1/organizations/bulk-update", body);
}
