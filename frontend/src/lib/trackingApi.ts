export interface TrackingLocationOut {
  latitude: number;
  longitude: number;
  updatedAt: string;
  accuracy?: number | null;
  speed?: number | null;
  heading?: number | null;
  status: string;
}

export interface PublicTrackingOut {
  orderId: number;
  orderNumber: string;
  status: string;
  trackingUrl: string;
  lastUpdatedAt: string | null;
  location: TrackingLocationOut | null;
}

export interface RiderTrackingOut {
  orderId: number;
  orderNumber: string;
  status: string;
  riderName: string | null;
  customerName: string | null;
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

async function trackingRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, init);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text || `${resp.status}`);
  }
  return resp.json() as Promise<T>;
}

export function fetchPublicTracking(trackingToken: string): Promise<PublicTrackingOut> {
  return trackingRequest<PublicTrackingOut>(`/api/v1/track/${trackingToken}`);
}

export function fetchPublicTrackingLocation(trackingToken: string): Promise<TrackingLocationOut> {
  return trackingRequest<TrackingLocationOut>(`/api/v1/track/${trackingToken}/location`);
}

export function fetchRiderTracking(riderToken: string): Promise<RiderTrackingOut> {
  return trackingRequest<RiderTrackingOut>(`/api/v1/rider-track/${riderToken}`);
}

export function postRiderLocation(
  orderId: number,
  riderToken: string,
  body: {
    latitude: number;
    longitude: number;
    accuracy?: number | null;
    speed?: number | null;
    heading?: number | null;
  },
): Promise<{ success: true }> {
  return trackingRequest<{ success: true }>(`/api/v1/orders/${orderId}/location`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${riderToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
}

export function stopRiderTracking(
  orderId: number,
  riderToken: string,
): Promise<{ success: true }> {
  return trackingRequest<{ success: true }>(`/api/v1/orders/${orderId}/tracking/stop`, {
    method: "POST",
    headers: { Authorization: `Bearer ${riderToken}` },
  });
}
