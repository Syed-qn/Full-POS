import { apiClient } from "./apiClient";

// ── Types (mirrored from src/app/marketing/schemas.py) ──────────────────────

export interface CampaignResponse {
  id: number;
  type: string;
  status: string;
  stats: Record<string, unknown>;
}

export interface SegmentResponse {
  id: number;
  name: string;
  last_preview_count: number | null;
}

export interface TemplateResponse {
  id: number;
  meta_template_name: string;
  status: string;
  rejection_reason: string | null;
}

/** Shape returned by GET /campaigns/{id}/stats */
export interface CampaignStatsResponse {
  sent: number;
  delivered: number;
  read: number;
  replied: number;
  converted: number;
  suppressed: number;
  [key: string]: unknown;
}

// ── API functions ────────────────────────────────────────────────────────────

/** GET /api/v1/marketing/campaigns */
export async function fetchCampaigns(): Promise<CampaignResponse[]> {
  return apiClient.get<CampaignResponse[]>("/api/v1/marketing/campaigns");
}

/** GET /api/v1/marketing/segments */
export async function fetchSegments(): Promise<SegmentResponse[]> {
  return apiClient.get<SegmentResponse[]>("/api/v1/marketing/segments");
}

/** GET /api/v1/marketing/templates */
export async function fetchTemplates(): Promise<TemplateResponse[]> {
  return apiClient.get<TemplateResponse[]>("/api/v1/marketing/templates");
}

/** GET /api/v1/marketing/campaigns/{id}/stats */
export async function getCampaignStats(id: number): Promise<CampaignStatsResponse> {
  return apiClient.get<CampaignStatsResponse>(`/api/v1/marketing/campaigns/${id}/stats`);
}
