import Constants from "expo-constants";

const API_BASE = (Constants.expoConfig?.extra?.apiBase as string) ?? "";

export type Stop = {
  orderId: number;
  orderNumber: string;
  sequence: number;
  customerName: string | null;
  customerPhone: string | null;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  codAmount: number;
  delivered: boolean;
  doNotCall: boolean;
};

export type Run = {
  batchId: number | null;
  status: string | null; // "planned" | "picked_up" | null
  stops: Stop[];
};

export type Delivered = {
  success: boolean;
  batchComplete: boolean;
  nextOrderId: number | null;
};

async function req<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!resp.ok) {
    let detail = `${resp.status}`;
    try {
      const j = await resp.json();
      if (j?.detail) detail = j.detail;
    } catch {
      /* keep status */
    }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

export const getOrders = (token: string) => req<Run>("/api/v1/rider-app/orders", token);

export const pickup = (token: string) =>
  req<Run>("/api/v1/rider-app/orders/pickup", token, { method: "POST" });

export const markDelivered = (token: string, orderId: number) =>
  req<Delivered>(`/api/v1/rider-app/orders/${orderId}/delivered`, token, { method: "POST" });

export const registerPushToken = (token: string, pushToken: string) =>
  req<{ success: boolean }>("/api/v1/rider-app/push-token", token, {
    method: "POST",
    body: JSON.stringify({ push_token: pushToken }),
  });

export const mapsLink = (lat: number, lon: number) =>
  `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`;
