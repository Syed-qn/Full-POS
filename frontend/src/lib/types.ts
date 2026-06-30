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
  /** Rider's own On duty / Off duty switch (native app). False = off duty: no new
   * assignments (keeps any active run). Defaults true on older backends. */
  on_duty?: boolean;
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
  catalog_retailer_id?: string | null;
  // Meta Commerce catalogue product fields.
  image_url?: string | null;
  sale_price_aed?: string | null;
  fb_product_category?: string | null;
  condition?: string;
  meta_status?: string;
  brand?: string | null;
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
  resale_of_order_id?: number | null;
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
  notes?: string | null;
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

// ── Dispatch explainability (assignments.algorithm_score) ────────────────────

export type DispatchEngine = "ortools" | "greedy";

export type DispatchRejectionReason =
  | "sla_risk"
  | "proximity"
  | "max_per_batch"
  | "no_rider"
  | "no_geo"
  | "priority_solo"
  | "hold_matured_solo";

export interface DispatchPerStopOut {
  order_id: number;
  projected_min: number;
  route_min?: number;
  buffer_min?: number;
}

export interface DispatchRejectionOut {
  order_id: number;
  reason: DispatchRejectionReason | string;
  projected_min?: number;
}

/** Rich explainability payload persisted on assignments.algorithm_score. */
export interface AlgorithmScoreOut {
  engine: DispatchEngine;
  engine_fallback?: boolean;
  route_sequence?: number[];
  total_est_min?: number;
  per_stop?: DispatchPerStopOut[];
  rejections?: DispatchRejectionOut[];
  zone?: string | null;
  batch_reason?: string | null;
  /** Legacy greedy scoring breakdown (distance + workload composite). */
  distance_km?: number;
  workload_score?: number;
  on_time_pct?: number;
  composite?: number;
  /** OR-Tools commit path may use projected_min map keyed by order id string. */
  projected_min?: Record<string, number>;
}

/** Order-detail alias — same shape as algorithm_score when backend exposes it. */
export type DispatchExplainOut = AlgorithmScoreOut;

export interface DispatchKpisOut {
  /** Share of dispatched trips with more than one stop (0–100). */
  batch_rate_pct: number;
  /** Mean stops per dispatched batch/run. */
  avg_stops: number;
  /** Share of assignments that fell back to greedy engine (0–100). */
  engine_fallback_pct: number;
  /** Optional reporting window label from the API (e.g. "today"). */
  window?: string;
}

export interface LiveMapStopOut {
  order_id: number;
  order_number: string;
  sequence: number;
  lat: number;
  lng: number;
  sla_deadline?: string | null;
}

export interface LiveMapBatchOut {
  batch_id: number;
  rider_id: number;
  rider_name?: string | null;
  status: string;
  color: string;
  stops: LiveMapStopOut[];
  polyline: number[][];
  total_est_min?: number | null;
}

export interface SlaRingOut {
  order_id: number;
  order_number: string;
  lat: number;
  lng: number;
  sla_deadline: string;
  minutes_remaining: number;
  urgency: "safe" | "warn" | "critical" | string;
  radius_km: number;
}

export interface LiveOpsMapOut {
  origin: { lat: number; lng: number; name?: string };
  batches: LiveMapBatchOut[];
  sla_rings: SlaRingOut[];
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
  convo_summary?: string | null;
  /** Pre-assignment batch preview label ("A", "B", …) when orders will batch together. */
  batch_preview_label?: string | null;
  /** Dispatch explainability from assignments.algorithm_score (when assigned). */
  dispatch_explain?: DispatchExplainOut | null;
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
  resale_of_order_id?: number | null;
}

export interface CustomerProfileOut extends CustomerDetailOut {
  usual_order_time: string | null;
  tags: Record<string, unknown>;
  addresses: AddressDetailOut[];
  recent_orders: OrderSummaryOut[];
  /** Loyalty tier ("gold"|"silver"|"bronze") or null when none/auto-empty. */
  loyalty_tier?: string | null;
  /** True when a manager has pinned the tier (auto-recompute paused). */
  loyalty_tier_locked?: boolean;
}

// ── Loyalty (settings) ───────────────────────────────────────────────────────

/** Threshold a customer must meet to qualify for a tier. */
export interface LoyaltyTierThreshold {
  min_orders: number;
  min_spend_aed: number;
  max_recency_days: number;
}

/** Reward granted to a tier; null means the tier earns no recurring reward. */
export interface LoyaltyTierReward {
  discount_aed: number;
  every_n_orders: number;
}

export interface LoyaltyConfig {
  enabled: boolean;
  /** Fraction of order value earned as credit, 0..1 (UI shows it as a percent). */
  earn_rate: number;
  earn_max_per_order_aed: number;
  credit_ttl_days: number;
  tiers: {
    gold: LoyaltyTierThreshold;
    silver: LoyaltyTierThreshold;
    bronze: LoyaltyTierThreshold;
  };
  tier_rewards: {
    gold: LoyaltyTierReward | null;
    silver: LoyaltyTierReward | null;
    bronze: LoyaltyTierReward | null;
  };
  demotion_grace_days: number;
  scope_includes_catalog: boolean;
}

export interface CustomerListOut {
  items: CustomerDetailOut[];
  limit: number;
  offset: number;
}

// ── Complaint tickets & customer wallet ──────────────────────────────────────

export type TicketStatus = "open" | "in_progress" | "resolved";

export type TicketResolutionAction =
  | "wallet_refund"
  | "replacement"
  | "resolved_no_action";

export interface Ticket {
  id: number;
  customer_id: number;
  customer_phone?: string | null;
  customer_name?: string | null;
  order_id: number | null;
  source_message: string | null;
  evidence: unknown[] | null;
  category: string | null;
  status: TicketStatus;
  assigned_to: string | null;
  resolution_action: TicketResolutionAction | null;
  resolution_amount_aed: string | null;
  replacement_order_id: number | null;
  resolution_note: string | null;
  resolved_at: string | null;
  created_at: string;
}

export type TicketResolveAction =
  | "wallet_refund"
  | "replacement"
  | "create_replacement"
  | "resolved_no_action";

export interface ResolveTicketIn {
  action: TicketResolveAction;
  note: string;
  amount?: string;
  replacement_order_id?: number;
}

export interface WalletBalance {
  customer_id: number;
  balance_aed: string;
  available_aed: string;
  status: string;
}

export interface WalletEntry {
  id: number;
  amount_aed: string;
  type: string;
  status: string;
  order_id: number | null;
  ticket_id: number | null;
  reason_note: string | null;
  created_by: string | null;
  created_at: string;
}

export interface ChatOrder {
  id: number;
  order_number: string;
  status: string;
  total_aed: string;
  created_at: string;
}

export interface ChatCustomerContext {
  customer_id: number | null;
  name: string | null;
  phone: string;
  wallet_balance_aed: string;
  wallet_available_aed: string;
  wallet_status: string | null;
  recent_orders: ChatOrder[];
}

export type CouponDiscountType = "fixed" | "percent";
export type CouponKind = "single_use" | "multi_use";

export interface Coupon {
  id: number;
  code: string;
  kind: CouponKind;
  discount_type: CouponDiscountType;
  discount_aed: string | null;
  percent: string | null;
  max_discount_aed: string | null;
  min_order_aed: string;
  applies_to: string;
  per_customer_limit: number | null;
  total_redemption_limit: number | null;
  status: string;
  valid_from: string | null;
  expires_at: string | null;
  created_at: string;
}

export interface CouponCreateIn {
  discount_type: CouponDiscountType;
  discount_value: string;
  kind?: CouponKind;
  min_order_aed?: string;
  max_discount_aed?: string;
  per_customer_limit?: number;
  total_redemption_limit?: number;
  expires_at?: string;
  code?: string;
}
