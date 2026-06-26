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
  /** Deliveries completed in the current 08:00→08:00 shift window. */
  delivered_24h: number;
  /** Deliveries completed all-time. */
  delivered_lifetime: number;
  /** Latest known position (most recent WhatsApp location ping), or null. */
  last_lat: number | null;
  last_lng: number | null;
  /** ISO timestamp of the latest location ping, or null if never shared. */
  last_location_at: string | null;
}

export interface RiderLocationOut {
  lat: number;
  lng: number;
  ts: string;
}

export interface VariantOut {
  name: string;
  price_aed: string;
  dish_number: number | null;
}

export interface DishOut {
  id: number;
  dish_number: number | null;
  name: string;
  price_aed: string | null;
  category: string | null;
  description: string | null;
  is_available: boolean;
  variants?: VariantOut[];
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
  /** ISO 8601 — distance-driven kitchen "plate by" deadline (null if no drop-off pin). */
  prep_deadline: string | null;
  /** Estimated cook minutes; "start by" = prep_deadline − this. */
  cook_estimate_minutes: number | null;
  created_at: string;
  address: string | null;
  lat: number | null;
  lng: number | null;
  /** Rider-trip batching: when this order shares a trip with others, batch_size > 1
   *  and batch_order_numbers lists every order on the trip (in delivery sequence). */
  batch_id?: number | null;
  batch_size?: number | null;
  batch_order_numbers?: string[];
  /** Pre-assignment forecast: a label ("A","B",…) shared by still-unassigned
   *  orders that will batch together by proximity. Null when it would ride alone. */
  batch_preview?: string | null;
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

// ── Order Detail (rich view) ─────────────────────────────────────────────────

export interface OrderItemDetailOut {
  dish_number: number;
  dish_name: string;
  variant_name?: string | null;
  qty: number;
  price_aed: string;
  line_total: string;
}

export interface AddressDetailOut {
  id: number;
  room_apartment: string | null;
  building: string | null;
  receiver_name: string | null;
  additional_details: string | null;
  latitude: number | null;
  longitude: number | null;
}

export interface CustomerDetailOut {
  id: number;
  name: string | null;
  phone: string;
  total_orders: number;
  total_spend: string;
  first_order_at: string | null;
  last_order_at: string | null;
  marketing_opted_in: boolean;
}

export interface RiderDetailOut {
  id: number;
  name: string;
  phone: string;
}

export interface TimelineEventOut {
  ts: string;
  action: string;
  actor: string;
  after: Record<string, unknown> | null;
}

export interface ChatMessageOut {
  direction: "inbound" | "outbound";
  text: string | null;
  ts: number;
}

export interface GpsPingOut {
  latitude: number;
  longitude: number;
  ts: string;
}

export interface OrderDetailOut {
  id: number;
  order_number: string;
  status: OrderStatus;
  items: OrderItemDetailOut[];
  address: AddressDetailOut | null;
  customer: CustomerDetailOut;
  rider: RiderDetailOut | null;
  subtotal: string;
  delivery_fee_aed: string;
  total: string;
  created_at: string;
  delivered_at: string | null;
  sla_deadline: string | null;
  prep_deadline: string | null;
  cook_estimate_minutes: number | null;
  timeline: TimelineEventOut[];
  chat: ChatMessageOut[];
  route: GpsPingOut[];
}

export interface CustomerPatchIn {
  name?: string | null;
  phone?: string | null;
  marketing_opted_in?: boolean | null;
}

export interface AddressPatchIn {
  room_apartment?: string | null;
  building?: string | null;
  receiver_name?: string | null;
  additional_details?: string | null;
}

export interface OrderSummaryOut {
  id: number;
  order_number: string;
  status: OrderStatus;
  total: string;
  created_at: string;
}

export interface CustomerProfileOut extends CustomerDetailOut {
  usual_order_time: string | null;
  tags: Record<string, unknown>;
  addresses: AddressDetailOut[];
  recent_orders: OrderSummaryOut[];
}

export interface CustomerListOut {
  items: CustomerDetailOut[];
  limit: number;
  offset: number;
}
