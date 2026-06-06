import { apiClient, ApiError } from "./apiClient";
import fixtures from "./fixtures/conversations.json";
import type { ConversationOut, MessageOut } from "./types";

type Fix = { conversations: ConversationOut[]; messages: Record<string, MessageOut[]> };
const FIX = fixtures as Fix;

export async function fetchConversations(): Promise<ConversationOut[]> {
  try {
    return await apiClient.get<ConversationOut[]>("/api/v1/conversations");
  } catch (err) {
    if (err instanceof ApiError && err.status !== 404) throw err;
    return FIX.conversations;
  }
}

export async function fetchMessages(conversationId: number): Promise<MessageOut[]> {
  try {
    return await apiClient.get<MessageOut[]>(`/api/v1/conversations/${conversationId}/messages`);
  } catch (err) {
    if (err instanceof ApiError && err.status !== 404) throw err;
    return FIX.messages[String(conversationId)] ?? [];
  }
}

export async function setTakeover(conversationId: number, active: boolean): Promise<void> {
  try {
    await apiClient.post(`/api/v1/conversations/${conversationId}/takeover`, { active });
  } catch (err) {
    if (err instanceof ApiError && err.status !== 404) throw err;
    // fixture mode: no-op
  }
}

export async function sendMessage(conversationId: number, text: string): Promise<void> {
  try {
    await apiClient.post(`/api/v1/conversations/${conversationId}/messages`, { text });
  } catch (err) {
    if (err instanceof ApiError && err.status !== 404) throw err;
  }
}
