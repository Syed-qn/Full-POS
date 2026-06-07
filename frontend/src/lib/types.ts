export interface RestaurantOut {
  id: number;
  name: string;
  phone: string;
  lat: number;
  lng: number;
  settings: Record<string, unknown>;
}

export interface TokenOut {
  access_token: string;
  token_type: string;
}

export type RiderStatus = "available" | "on_delivery" | "off_shift" | "deactivated";

export interface RiderOut {
  id: number;
  name: string;
  phone: string;
  status: RiderStatus;
}

export interface DishOut {
  id: number;
  dish_number: number | null;
  name: string;
  price_aed: string | null;
  category: string | null;
  description: string | null;
  is_available: boolean;
}

export interface DiffOut {
  price_changes: Array<Record<string, unknown>>;
  added: Array<Record<string, unknown>>;
  removed: Array<Record<string, unknown>>;
  conflicts: Array<Record<string, unknown>>;
}

export interface MenuOut {
  id: number;
  version: number;
  status: string;
  dishes: DishOut[];
}

export interface MenuWithDiffOut extends MenuOut {
  diff_vs_active: DiffOut | null;
}

// FSM states from src/app/ordering/fsm.py
export type OrderStatus =
  | "draft"
  | "pending_confirmation"
  | "confirmed"
  | "preparing"
  | "ready"
  | "assigned"
  | "picked_up"
  | "arriving"
  | "delivered"
  | "cancelled"
  | "undeliverable"
  | "on_resale"
  | "resold"
  | "written_off";

export interface OrderItemOut {
  dish_number: number | null;
  name: string;
  qty: number;
  price_aed: string;
}

export interface OrderOut {
  id: number;
  order_number?: string;
  status: OrderStatus;
  customer_name: string;
  customer_phone: string;
  items: OrderItemOut[];
  total_aed: string;
  rider_id: number | null;
  rider_name: string | null;
  /** ISO 8601 — when the 40-min SLA clock started (order confirmed). */
  sla_started_at: string | null;
  created_at: string;
  address: string | null;
  lat: number | null;
  lng: number | null;
}

export interface ConversationOut {
  id: number;
  phone: string;
  counterpart: string;
  manual_takeover: boolean;
  last_message_preview: string | null;
  unread: boolean;
  updated_at: string;
}

export interface MessageOut {
  id: number;
  direction: "inbound" | "outbound";
  type: string;
  payload: Record<string, unknown>;
  ts: number;
}
