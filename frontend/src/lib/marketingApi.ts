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
  body?: string | null;
  header?: { type?: string; image_url?: string; text?: string } | null;
  footer?: string | null;
  buttons?: { type?: string; label?: string; url?: string }[] | null;
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

// ── WhatsApp template create → approve → broadcast ──────────────────────────

export interface TemplateDraftResponse {
  suggested_name: string;
  body: string;
  footer: string | null;
  examples: string[];
}

export interface BroadcastResponse {
  campaign_id: number;
  queued: number;
  suppressed_cap: number;
  suppressed_optout: number;
  suppressed_window: number;
}

export interface TemplateHeader {
  type: "text" | "IMAGE";
  text?: string;
  image_url?: string;
}

export interface CreateTemplateBody {
  meta_template_name: string;
  body: string;
  footer?: string | null;
  header?: TemplateHeader | null;
  buttons?: Array<Record<string, unknown>> | null;
  language?: string;
  category?: string;
}

/** POST /templates/draft — AI-draft a body from a plain-English offer. */
export async function draftTemplate(input: {
  describe: string;
  with_button?: boolean;
  button_label?: string | null;
  button_url?: string | null;
}): Promise<TemplateDraftResponse> {
  return apiClient.post<TemplateDraftResponse>("/api/v1/marketing/templates/draft", input);
}

/** POST /templates/image — upload a header image, returns a public URL. */
export async function uploadTemplateImage(file: File): Promise<{ url: string }> {
  const form = new FormData();
  form.append("file", file);
  return apiClient.postForm<{ url: string }>("/api/v1/marketing/templates/image", form);
}

/** POST /templates — create a draft template. */
export async function createTemplate(body: CreateTemplateBody): Promise<TemplateResponse> {
  return apiClient.post<TemplateResponse>("/api/v1/marketing/templates", body);
}

/** POST /templates/{id}/submit — submit to Meta for approval. */
export async function submitTemplate(id: number): Promise<TemplateResponse> {
  return apiClient.post<TemplateResponse>(`/api/v1/marketing/templates/${id}/submit`);
}

/** POST /templates/{id}/refresh — re-poll Meta approval status. */
export async function refreshTemplate(id: number): Promise<TemplateResponse> {
  return apiClient.post<TemplateResponse>(`/api/v1/marketing/templates/${id}/refresh`);
}

/** DELETE /templates/{id} — remove a template (Meta + dashboard). */
export async function deleteTemplate(id: number): Promise<void> {
  return apiClient.delete<void>(`/api/v1/marketing/templates/${id}`);
}

/** POST /broadcast — send an approved template to opted-in customers now. */
export async function broadcast(input: {
  template_id: number;
  segment_id?: number | null;
  coupon_value?: string | null;
  type?: string;
}): Promise<BroadcastResponse> {
  return apiClient.post<BroadcastResponse>("/api/v1/marketing/broadcast", input);
}
