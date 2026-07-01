import { describe, expect, it } from "vitest";
import { mergeOrderDetail, orderOutFromDetail } from "./orderDetailApi";
import type { OrderDetailOut } from "./types";

const sample: OrderDetailOut = {
  id: 9,
  order_number: "ORD-9",
  status: "confirmed",
  items: [
    {
      dish_number: 1,
      dish_name: "Biryani",
      qty: 2,
      price_aed: "45.00",
      line_total: "90.00",
    },
  ],
  address: {
    id: 3,
    room_apartment: "12A",
    building: "Marina Tower",
    receiver_name: "Ali",
    additional_details: null,
    latitude: 25.1,
    longitude: 55.2,
  },
  customer: {
    id: 5,
    name: "Ali",
    phone: "+971500000001",
    total_orders: 3,
    total_spend: "200.00",
    first_order_at: null,
    last_order_at: null,
    marketing_opted_in: true,
  },
  rider: null,
  subtotal: "90.00",
  delivery_fee_aed: "0.00",
  total: "90.00",
  created_at: "2026-07-01T10:00:00Z",
  delivered_at: null,
  sla_deadline: null,
  sla_started_at: "2026-07-01T10:00:00Z",
  prep_deadline: "2026-07-01T10:30:00Z",
  cook_estimate_minutes: 15,
  timeline: [],
  chat: [],
  route: [],
  batch_preview_label: "A",
};

describe("orderOutFromDetail", () => {
  it("maps detail payload to OrderOut for drawer actions", () => {
    const out = orderOutFromDetail(sample);
    expect(out.id).toBe(9);
    expect(out.customer_name).toBe("Ali");
    expect(out.sla_started_at).toBe("2026-07-01T10:00:00Z");
    expect(out.batch_preview).toBe("A");
    expect(out.address).toBe("12A, Marina Tower");
  });
});

describe("mergeOrderDetail", () => {
  it("keeps timeline when a chat-only fetch omits it", () => {
    const prev = {
      ...sample,
      timeline: [
        {
          ts: "2026-07-01T10:05:00Z",
          action: "order_status_transition",
          actor: "manager",
          after: { status: "confirmed" },
        },
      ],
    };
    const next = { ...sample, chat: [{ direction: "inbound" as const, text: "hi", ts: 1 }] };
    const merged = mergeOrderDetail(prev, next, "overview,chat");
    expect(merged.timeline).toHaveLength(1);
    expect(merged.chat).toHaveLength(1);
  });
});