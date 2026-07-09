import { apiClient } from "./apiClient";

export type AiInsight = {
  id: number;
  kind: string;
  title: string;
  summary: string;
  payload: Record<string, unknown>;
  period_start: string | null;
  period_end: string | null;
  created_at: string | null;
};

export function listAiFeatures() {
  return apiClient.get<{
    features: Array<{ key: string; status: string; path?: string; surface?: string }>;
  }>("/api/v1/ai/features");
}

export function listInsights(kind?: string) {
  const q = kind ? `?kind=${encodeURIComponent(kind)}` : "";
  return apiClient.get<AiInsight[]>(`/api/v1/ai/insights${q}`);
}

export function generateDailySales() {
  return apiClient.post<AiInsight>("/api/v1/ai/insights/daily-sales", {});
}

export function generateSalesDrop(days = 7) {
  return apiClient.post<AiInsight>(`/api/v1/ai/insights/sales-drop?days=${days}`, {});
}

export function generateStaffSummary(days = 7) {
  return apiClient.post<AiInsight>(`/api/v1/ai/insights/staff?days=${days}`, {});
}

export function generateSlowMoving(days = 14) {
  return apiClient.post<AiInsight>(`/api/v1/ai/insights/slow-moving?days=${days}`, {});
}

export function generateFoodCost() {
  return apiClient.post<AiInsight>("/api/v1/ai/insights/food-cost", {});
}

export function generateLowStock() {
  return apiClient.post<AiInsight>("/api/v1/ai/insights/low-stock", {});
}

export function generateSegments() {
  return apiClient.post<AiInsight>("/api/v1/ai/segments", {});
}

export function generateBundles() {
  return apiClient.post<AiInsight>("/api/v1/ai/bundles", {});
}

export function generateFestival(festival: string, offer?: string) {
  return apiClient.post<AiInsight>("/api/v1/ai/festival", { festival, offer });
}

export function suggestReviewReply(body: {
  comment?: string;
  score?: number;
  escalate?: boolean;
}) {
  return apiClient.post<{
    id: number;
    suggested_reply: string;
    sentiment: string;
    escalated: boolean;
  }>("/api/v1/ai/reviews/reply", body);
}

export function listReviewReplies() {
  return apiClient.get<
    Array<{
      id: number;
      score: number | null;
      sentiment: string;
      suggested_reply: string;
      escalated: boolean;
      original_comment: string | null;
    }>
  >("/api/v1/ai/reviews");
}

export function escalateNegativeReviews() {
  return apiClient.post<{ scanned: number; created: number }>("/api/v1/ai/reviews/escalate", {});
}

export function translateMenu() {
  return apiClient.post<{ count: number }>("/api/v1/ai/translate", {
    all_menu: true,
    target_lang: "ar",
  });
}

export function listReservations() {
  return apiClient.get<
    Array<{
      id: number;
      status: string;
      party_size: number;
      guest_name: string | null;
      ai_summary: string | null;
      requested_for: string | null;
    }>
  >("/api/v1/ai/reservations");
}

export function createReservation(body: {
  party_size: number;
  requested_for: string;
  guest_name?: string;
  phone?: string;
  notes?: string;
}) {
  return apiClient.post("/api/v1/ai/reservations", body);
}

export function startCall(caller_phone?: string) {
  return apiClient.post<{ id: number; status: string; transcript: Array<{ role: string; text: string }> }>(
    "/api/v1/ai/calls",
    { caller_phone },
  );
}

export function turnCall(sessionId: number, text: string) {
  return apiClient.post<{
    id: number;
    status: string;
    outcome: string | null;
    transcript: Array<{ role: string; text: string }>;
  }>(`/api/v1/ai/calls/${sessionId}/turn`, { text });
}

export function listCalls() {
  return apiClient.get<
    Array<{
      id: number;
      status: string;
      caller_phone: string | null;
      outcome: string | null;
      ai_summary: string | null;
    }>
  >("/api/v1/ai/calls");
}

export function getCombos() {
  return apiClient.get<{ combos: Array<{ items: string[]; ai_message: string }> }>(
    "/api/v1/ai/combos",
  );
}

export function abandonedCopy(cartSummary?: string) {
  const q = cartSummary ? `?cart_summary=${encodeURIComponent(cartSummary)}` : "";
  return apiClient.post<{ body: string }>(`/api/v1/ai/abandoned-copy${q}`, {});
}

export function reorderPrompt() {
  return apiClient.post<{ body: string }>("/api/v1/ai/reorder-prompt", {});
}
