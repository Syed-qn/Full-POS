import { apiClient, ApiError, TOKEN_KEY } from "./apiClient";
import fixtures from "./fixtures/conversations.json";
import type { ChatCustomerContext, ConversationOut, MessageOut } from "./types";

export async function fetchConversationContext(
  conversationId: number,
): Promise<ChatCustomerContext | null> {
  try {
    return await apiClient.get<ChatCustomerContext>(
      `/api/v1/conversations/${conversationId}/context`,
    );
  } catch (err) {
    if (!import.meta.env.DEV) throw err;
    if (err instanceof ApiError && err.status !== 404) throw err;
    return null; // endpoint not available in fixture/dev mode
  }
}

type Fix = { conversations: ConversationOut[]; messages: Record<string, MessageOut[]> };
const FIX = fixtures as Fix;

// Fixture fallback is a dev-only convenience: the conversation endpoints don't
// exist yet. In production we rethrow so failures surface rather than masking
// with stale data. NOTE: vitest runs with import.meta.env.DEV === true, so
// existing tests still exercise the fixture fallback path.
export async function fetchConversations(): Promise<ConversationOut[]> {
  try {
    return await apiClient.get<ConversationOut[]>("/api/v1/conversations");
  } catch (err) {
    if (!import.meta.env.DEV) throw err;
    if (err instanceof ApiError && err.status !== 404) throw err;
    return FIX.conversations;
  }
}

export async function fetchMessages(conversationId: number): Promise<MessageOut[]> {
  try {
    return await apiClient.get<MessageOut[]>(`/api/v1/conversations/${conversationId}/messages`);
  } catch (err) {
    if (!import.meta.env.DEV) throw err;
    if (err instanceof ApiError && err.status !== 404) throw err;
    return FIX.messages[String(conversationId)] ?? [];
  }
}

export async function setTakeover(conversationId: number, active: boolean): Promise<void> {
  try {
    await apiClient.post(`/api/v1/conversations/${conversationId}/takeover`, { active });
  } catch (err) {
    if (!import.meta.env.DEV) throw err;
    if (err instanceof ApiError && err.status !== 404) throw err;
    // fixture mode: no-op
  }
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export async function fetchMessageMedia(conversationId: number, messageId: number): Promise<Blob> {
  const token = localStorage.getItem(TOKEN_KEY);
  const resp = await fetch(
    `${API_BASE}/api/v1/conversations/${conversationId}/messages/${messageId}/media`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  );
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const data = await resp.json();
      detail = typeof data.detail === "string" ? data.detail : detail;
    } catch {
      /* non-JSON */
    }
    throw new ApiError(resp.status, detail);
  }
  return resp.blob();
}

/** @deprecated Use fetchMessageMedia — kept for older call sites. */
export const fetchMessageAudio = fetchMessageMedia;

export async function sendMessage(conversationId: number, text: string): Promise<void> {
  try {
    await apiClient.post(`/api/v1/conversations/${conversationId}/messages`, { text });
  } catch (err) {
    if (!import.meta.env.DEV) throw err;
    if (err instanceof ApiError && err.status !== 404) throw err;
  }
}
