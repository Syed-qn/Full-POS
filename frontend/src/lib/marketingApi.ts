import { apiClient } from "./apiClient";

// ── Types (mirrored from src/app/marketing/schemas.py) ──────────────────────

export interface CampaignResponse {
  id: number;
  type: string;
  status: string;
  stats: Record<string, unknown>;
  created_at?: string | null;
  scheduled_at?: string | null;
  template_name?: string | null;
  audience_label?: string | null;
  segment_id?: number | null;
  template_id?: number | null;
}

export interface SegmentResponse {
  id: number;
  name: string;
  last_preview_count: number | null;
  plain_english?: string | null;
  updated_at?: string | null;
}

export interface SegmentCompileResponse {
  dsl: Record<string, unknown>;
  preview_count: number;
  plain_english: string;
}

/** One named RFM bucket + live customer count (GET /marketing/audience). */
export interface AudienceSegment {
  key: string;
  label: string;
  count: number;
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

/** POST /api/v1/marketing/segments/compile */
export async function compileSegment(
  plain_english: string,
): Promise<SegmentCompileResponse> {
  return apiClient.post<SegmentCompileResponse>(
    "/api/v1/marketing/segments/compile",
    { plain_english },
  );
}

/** POST /api/v1/marketing/segments/preview */
export async function previewSegment(
  dsl: Record<string, unknown>,
): Promise<{ preview_count: number }> {
  return apiClient.post<{ preview_count: number }>(
    "/api/v1/marketing/segments/preview",
    { dsl },
  );
}

/** POST /api/v1/marketing/segments */
export async function createSegment(body: {
  name: string;
  dsl: Record<string, unknown>;
  plain_english?: string | null;
}): Promise<SegmentResponse> {
  return apiClient.post<SegmentResponse>("/api/v1/marketing/segments", body);
}

/** DELETE /api/v1/marketing/segments/{id} */
export async function deleteSegment(id: number): Promise<void> {
  return apiClient.delete<void>(`/api/v1/marketing/segments/${id}`);
}

/** GET /api/v1/marketing/audience — named RFM buckets with live counts. */
export async function fetchAudience(): Promise<AudienceSegment[]> {
  return apiClient.get<AudienceSegment[]>("/api/v1/marketing/audience");
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

export interface AutomationConfig {
  delay_hours?: number | null;
  lead_minutes?: number | null;
  lapsed_days?: number | null;
  cooldown_days?: number | null;
}

export interface AutomationResponse {
  preset_key: string;
  title: string;
  description: string;
  enabled: boolean;
  template_id: number | null;
  segment_id: number | null;
  segment_name?: string | null;
  config: AutomationConfig;
  stats: Record<string, unknown>;
  last_run_at?: string | null;
  save_blocked: boolean;
  save_blocked_reason?: string | null;
}

export interface AutomationPatch {
  enabled?: boolean;
  template_id?: number | null;
  segment_id?: number | null;
  config?: AutomationConfig;
}

/** GET /api/v1/marketing/automations */
export async function fetchAutomations(): Promise<AutomationResponse[]> {
  return apiClient.get<AutomationResponse[]>("/api/v1/marketing/automations");
}

/** PATCH /api/v1/marketing/automations/{preset_key} */
export async function patchAutomation(
  presetKey: string,
  body: AutomationPatch,
): Promise<AutomationResponse> {
  return apiClient.patch<AutomationResponse>(
    `/api/v1/marketing/automations/${presetKey}`,
    body,
  );
}

export interface BroadcastResponse {
  campaign_id: number;
  queued: number;
  suppressed_cap: number;
  suppressed_optout: number;
  suppressed_window: number;
}

export interface BroadcastScheduleResponse {
  campaign_id: number;
  scheduled_at: string;
  status: string;
  window_warning?: string | null;
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
  ephemeral?: boolean;
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

/** POST /templates/image/generate — AI promo header image. */
export async function generateTemplateImage(input: {
  prompt?: string;
  describe?: string | null;
}): Promise<{ url: string }> {
  return apiClient.post<{ url: string }>(
    "/api/v1/marketing/templates/image/generate",
    input,
  );
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

/** POST /templates/{id}/fix — AI-revise a rejected template (persists draft body). */
export async function fixTemplate(
  id: number,
  hint?: string | null,
): Promise<TemplateResponse> {
  return apiClient.post<TemplateResponse>(`/api/v1/marketing/templates/${id}/fix`, {
    hint: hint ?? null,
  });
}

/** DELETE /templates/{id} — remove a template (Meta + dashboard). */
export async function deleteTemplate(id: number): Promise<void> {
  return apiClient.delete<void>(`/api/v1/marketing/templates/${id}`);
}

/** POST /broadcast — send now or schedule (``scheduled_at`` ISO UTC). */
export async function broadcast(input: {
  template_id: number;
  segment_id?: number | null;
  rfm_segment?: string | null;
  coupon_value?: string | null;
  type?: string;
  scheduled_at?: string | null;
}): Promise<BroadcastResponse | BroadcastScheduleResponse> {
  return apiClient.post<BroadcastResponse | BroadcastScheduleResponse>(
    "/api/v1/marketing/broadcast",
    input,
  );
}

/** DELETE /campaigns/{id} — cancel a scheduled broadcast. */
export async function cancelCampaign(id: number): Promise<void> {
  return apiClient.delete<void>(`/api/v1/marketing/campaigns/${id}`);
}

/** PATCH /campaigns/{id}/schedule — reschedule a queued broadcast. */
export async function rescheduleCampaign(
  id: number,
  scheduled_at: string,
): Promise<BroadcastScheduleResponse> {
  return apiClient.patch<BroadcastScheduleResponse>(
    `/api/v1/marketing/campaigns/${id}/schedule`,
    { scheduled_at },
  );
}
