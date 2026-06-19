export interface TrackingLocationOut {
  latitude: number;
  longitude: number;
  updatedAt: string;
  accuracy?: number | null;
  speed?: number | null;
  heading?: number | null;
  status: string;
}

export interface TrackingPoint {
  latitude: number;
  longitude: number;
  label?: string | null;
}

export interface PublicTrackingOut {
  orderId: number;
  orderNumber: string;
  status: string;
  trackingUrl: string;
  lastUpdatedAt: string | null;
  location: TrackingLocationOut | null;
  restaurant?: TrackingPoint | null;
  destination?: TrackingPoint | null;
}

export interface RiderTrackingOut {
  orderId: number;
  orderNumber: string;
  status: string;
  riderName: string | null;
  customerName: string | null;
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

/** Error that carries the HTTP status + parsed `detail` so callers can show a
 *  friendly state (e.g. 410 → "tracking ended") instead of raw JSON. */
export class TrackingError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "TrackingError";
    this.status = status;
    this.detail = detail;
  }
}

async function trackingRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, init);
  if (!resp.ok) {
    const text = await resp.text();
    let detail = text || `${resp.status}`;
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      /* not JSON — keep raw text */
    }
    throw new TrackingError(resp.status, detail);
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
