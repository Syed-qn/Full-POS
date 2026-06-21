import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { OrderDetailDrawer } from "./OrderDetailDrawer";
import type { OrderDetailOut, OrderOut } from "../lib/types";

// Mock Leaflet — jsdom has no canvas / map support
vi.mock("leaflet", () => ({
  default: {
    map: vi.fn(() => ({
      remove: vi.fn(),
      fitBounds: vi.fn(),
    })),
    tileLayer: vi.fn(() => ({ addTo: vi.fn() })),
    polyline: vi.fn(() => ({
      addTo: vi.fn(),
      getBounds: vi.fn(() => ({})),
    })),
    circleMarker: vi.fn(() => ({
      addTo: vi.fn(),
      bindTooltip: vi.fn(() => ({ addTo: vi.fn() })),
    })),
  },
}));

vi.mock("../lib/orderDetailApi");
vi.mock("../lib/ordersApi");

// Import mocked modules so we can set resolved values
import * as orderDetailApi from "../lib/orderDetailApi";
import * as ordersApi from "../lib/ordersApi";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const mockDetail: OrderDetailOut = {
  id: 1,
  order_number: "R1-0001",
  status: "delivered",
  items: [
    {
      dish_number: 110,
      dish_name: "Chicken Biryani",
      qty: 2,
      price_aed: "22.00",
      line_total: "44.00",
    },
  ],
  address: {
    id: 1,
    room_apartment: "Apt 404",
    building: "Marina Tower",
    receiver_name: "Sara Al Rashid",
    additional_details: null,
    latitude: 25.2,
    longitude: 55.2,
  },
  customer: {
    id: 1,
    name: "Sara Al Rashid",
    phone: "+971509876543",
    total_orders: 5,
    total_spend: "220.00",
    first_order_at: "2026-01-01T10:00:00Z",
    last_order_at: "2026-06-10T10:00:00Z",
    marketing_opted_in: true,
  },
  rider: { id: 1, name: "Ahmed Hassan", phone: "+971501111111" },
  subtotal: "44.00",
  delivery_fee_aed: "0.00",
  total: "44.00",
  created_at: "2026-06-10T09:00:00Z",
  delivered_at: "2026-06-10T09:38:00Z",
  sla_deadline: null,
  prep_deadline: null,
  cook_estimate_minutes: null,
  timeline: [
    {
      ts: "2026-06-10T09:10:00Z",
      action: "order_status_transition",
      actor: "manager",
      after: { status: "confirmed" },
    },
    {
      // Auto-dispatch records action "state_transition" with after.status —
      // must still render the status, not the generic action label.
      ts: "2026-06-10T09:40:00Z",
      action: "state_transition",
      actor: "system",
      after: { status: "assigned", rider_id: 7 },
    },
  ],
  chat: [
    { direction: "inbound", text: "I want 2 biryani", ts: 1717660800 },
    { direction: "outbound", text: null, ts: 1717660810 },
  ],
  route: [],
};

const mockBasicOrder: OrderOut = {
  id: 1,
  order_number: "R1-0001",
  status: "delivered",
  customer_name: "Sara Al Rashid",
  customer_phone: "+971509876543",
  items: [{ dish_number: 110, name: "Chicken Biryani", qty: 2, price_aed: "22.00" }],
  total_aed: "44.00",
  rider_id: 1,
  rider_name: "Ahmed Hassan",
  sla_started_at: null,
  prep_deadline: null,
  cook_estimate_minutes: null,
  created_at: "2026-06-10T09:00:00Z",
  address: "Apt 404, Marina Tower",
  lat: 25.2,
  lng: 55.2,
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderDrawer(orderId: number | null = 1) {
  return render(
    <MemoryRouter>
      <OrderDetailDrawer orderId={orderId} onClose={() => {}} />
    </MemoryRouter>,
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("OrderDetailDrawer", () => {
  beforeEach(() => {
    // jsdom does not implement scrollIntoView — stub it so ChatTab doesn't throw
    window.HTMLElement.prototype.scrollIntoView = vi.fn();

    vi.mocked(orderDetailApi.fetchOrderDetail).mockResolvedValue(mockDetail);
    vi.mocked(ordersApi.fetchOrder).mockResolvedValue(mockBasicOrder);
  });

  // 1. Overview tab renders items when open
  it("Overview tab renders items after loading", async () => {
    renderDrawer(1);
    await waitFor(() =>
      expect(screen.getByText("Chicken Biryani")).toBeInTheDocument(),
    );
    // Quantity is shown as a badge ("2×"); dish numbers are not shown to staff.
    expect(screen.getByText("2×")).toBeInTheDocument();
    expect(screen.queryByText("110.")).not.toBeInTheDocument();
    // "AED 44.00" appears multiple times (line_total, subtotal, total) — just verify presence
    expect(screen.getAllByText("AED 44.00").length).toBeGreaterThanOrEqual(1);
  });

  // 2. Tab switching — timeline panel becomes visible
  it("switches to Timeline tab and shows timeline events", async () => {
    renderDrawer(1);
    await waitFor(() => screen.getByText("Chicken Biryani"));

    fireEvent.click(screen.getByRole("tab", { name: /timeline/i }));
    // A status transition surfaces the actual new status, not a generic label
    expect(screen.getByText("Status → Confirmed")).toBeInTheDocument();
    // Auto-dispatch (state_transition / after.status) is surfaced the same way
    expect(screen.getByText("Status → Assigned")).toBeInTheDocument();
  });

  // 2b. Tab switching — chat panel becomes visible
  it("switches to Chat tab", async () => {
    renderDrawer(1);
    await waitFor(() => screen.getByText("Chicken Biryani"));

    fireEvent.click(screen.getByRole("tab", { name: /chat/i }));
    expect(screen.getByText("I want 2 biryani")).toBeInTheDocument();
  });

  // 2c. Tab switching — customer panel becomes visible
  it("switches to Customer tab and shows profile link", async () => {
    renderDrawer(1);
    await waitFor(() => screen.getByText("Chicken Biryani"));

    fireEvent.click(screen.getByRole("tab", { name: /customer/i }));
    expect(screen.getByText(/open full profile/i)).toBeInTheDocument();
  });

  // 3. Customer Save button disabled when no changes
  it("Customer Save button is disabled when form is unchanged", async () => {
    renderDrawer(1);
    await waitFor(() => screen.getByText("Chicken Biryani"));

    fireEvent.click(screen.getByRole("tab", { name: /customer/i }));

    const saveBtn = screen.getByRole("button", { name: /save changes/i });
    expect(saveBtn).toBeDisabled();
  });

  // 5. Customer Save button enabled after input change
  it("Customer Save button becomes enabled after editing Name", async () => {
    renderDrawer(1);
    await waitFor(() => screen.getByText("Chicken Biryani"));

    fireEvent.click(screen.getByRole("tab", { name: /customer/i }));

    // Both Name and Receiver Name have "Sara Al Rashid" — take the first (Name field)
    const nameInputs = screen.getAllByDisplayValue("Sara Al Rashid");
    const nameInput = nameInputs[0];
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, "Sara Al Rashidi");

    const saveBtn = screen.getByRole("button", { name: /save changes/i });
    expect(saveBtn).not.toBeDisabled();
  });

  // 4. Empty route: map wrapper not rendered in timeline tab
  it("does not render map wrapper when route is empty", async () => {
    // mockDetail already has route: []
    renderDrawer(1);
    await waitFor(() => screen.getByText("Chicken Biryani"));

    fireEvent.click(screen.getByRole("tab", { name: /timeline/i }));

    // The map wrapper heading should not be present
    expect(screen.queryByText("Delivery Route")).not.toBeInTheDocument();
  });

  // 5. Chat shows inbound message text
  it("Chat tab shows inbound message text", async () => {
    renderDrawer(1);
    await waitFor(() => screen.getByText("Chicken Biryani"));

    fireEvent.click(screen.getByRole("tab", { name: /chat/i }));
    expect(screen.getByText("I want 2 biryani")).toBeInTheDocument();
  });

  // 6. Non-text outbound message renders placeholder
  it("Chat tab renders [📤 automated] placeholder for null outbound text", async () => {
    renderDrawer(1);
    await waitFor(() => screen.getByText("Chicken Biryani"));

    fireEvent.click(screen.getByRole("tab", { name: /chat/i }));
    expect(screen.getByText("[📤 automated]")).toBeInTheDocument();
  });

  // 7. orderId=null: nothing rendered (drawer is closed)
  it("renders nothing when orderId is null", () => {
    renderDrawer(null);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
