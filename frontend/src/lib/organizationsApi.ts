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
