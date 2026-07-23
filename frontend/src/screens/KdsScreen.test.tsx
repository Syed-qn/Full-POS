import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { KdsScreen, groupTicketsByOrder } from "./KdsScreen";
import type { KdsTicketItem } from "../lib/kdsApi";

const stations = [
  {
    id: 1,
    name: "Grill",
    station_type: "grill",
    kitchen_code: "main",
    printer_ip: null,
    printer_port: null,
    fallback_station_id: null,
    is_active: true,
  },
  {
    id: 2,
    name: "Fry",
    station_type: "fry",
    kitchen_code: "main",
    printer_ip: null,
    printer_port: null,
    fallback_station_id: null,
    is_active: true,
  },
];

/** Two lines of the SAME order — they must collapse into one card. */
const grillTicket = {
  id: 1,
  order_id: 10,
  order_number: "T02",
  order_type: "dine_in",
  order_priority: "rush",
  dish_name: "Kebab",
  variant_name: null,
  qty: 2,
  kitchen_status: "received",
  notes: "no onion",
  created_at: new Date().toISOString(),
  kitchen_received_at: new Date().toISOString(),
  allergens: ["dairy"],
  selected_modifiers: [{ name: "extra chili" }],
  packaging_checked: false,
  quality_checked: false,
  missing_item_confirmed: false,
  age_seconds: 120,
  age_minutes: 2,
  urgency: "ok" as const,
  is_delayed: false,
  estimated_ready_at: new Date(Date.now() + 20 * 60000).toISOString(),
  course_number: 1,
  course_held: false,
  station_id: 1,
};

const fryTicket = {
  ...grillTicket,
  id: 2,
  dish_name: "Fries",
  qty: 1,
  notes: null,
  allergens: [],
  selected_modifiers: [],
  age_seconds: 600,
  age_minutes: 10,
  urgency: "warning" as const,
  is_delayed: true,
  course_number: 2,
  course_held: true,
  station_id: 2,
};

function mockFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const u = String(url);
      const method = (init?.method ?? "GET").toUpperCase();
      if (u.includes("/api/v1/kds/stations") && !u.includes("/tickets") && method === "GET") {
        return Promise.resolve(new Response(JSON.stringify(stations), { status: 200 }));
      }
      if (u.includes("/stations/1/tickets")) {
        return Promise.resolve(new Response(JSON.stringify([grillTicket]), { status: 200 }));
      }
      if (u.includes("/stations/2/tickets")) {
        return Promise.resolve(new Response(JSON.stringify([fryTicket]), { status: 200 }));
      }
      if (u.includes("ready-for-pickup")) {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (u.includes("printer-status")) {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (u.includes("performance")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              ticket_count: 1,
              bumped_count: 1,
              late_ticket_count: 0,
              avg_prep_minutes: 5,
              by_station: [],
            }),
            { status: 200 },
          ),
        );
      }
      if (method === "PATCH" || method === "POST") {
        return Promise.resolve(
          new Response(JSON.stringify({ ...grillTicket, kitchen_status: "ready" }), {
            status: 200,
          }),
        );
      }
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    }),
  );
}

describe("groupTicketsByOrder", () => {
  it("collapses lines of one order into a card using worst urgency and oldest age", () => {
    const cards = groupTicketsByOrder([grillTicket, fryTicket] as KdsTicketItem[]);
    expect(cards).toHaveLength(1);
    expect(cards[0].orderNumber).toBe("T02");
    expect(cards[0].items).toHaveLength(2);
    // worst of ok/warning, oldest of 120/600
    expect(cards[0].urgency).toBe("warning");
    expect(cards[0].ageSeconds).toBe(600);
    expect(cards[0].allReady).toBe(false);
  });

  it("keeps separate orders as separate cards, rush first", () => {
    const normal = { ...grillTicket, id: 9, order_id: 11, order_number: "TK-0038", order_priority: "normal" };
    const cards = groupTicketsByOrder([normal, grillTicket] as KdsTicketItem[]);
    expect(cards.map((c) => c.orderNumber)).toEqual(["T02", "TK-0038"]);
  });
});

describe("KdsScreen", () => {
  beforeEach(mockFetch);
  afterEach(() => vi.restoreAllMocks());

  it("renders the ALL board merging every station into one order card", async () => {
    renderWithProviders(
      <Routes>
        <Route path="/kds" element={<KdsScreen />} />
        <Route path="/kds/:stationId" element={<KdsScreen />} />
      </Routes>,
      { initialEntries: ["/kds"] },
    );

    const card = await screen.findByTestId("kds-ticket-10");
    // one card, both station lines inside it
    expect(within(card).getByText(/kebab/i)).toBeInTheDocument();
    expect(within(card).getByText(/fries/i)).toBeInTheDocument();
    expect(within(card).getByText("T02")).toBeInTheDocument();
    expect(within(card).getByText("DINE")).toBeInTheDocument();
    expect(within(card).getByText("⚡RUSH")).toBeInTheDocument();
    expect(within(card).getByTestId("kds-timer")).toHaveTextContent(/^\d+:\d{2}$/);
    expect(within(card).getByTestId("kds-eta")).toBeInTheDocument();
    expect(within(card).getByTestId("kds-allergens")).toHaveTextContent("DAIRY");
    expect(within(card).getByTestId("kds-modifiers")).toHaveTextContent(/chili/i);
    expect(within(card).getByTestId("kds-note")).toHaveTextContent(/no onion/i);
    // worst urgency of the two lines
    expect(card).toHaveAttribute("data-urgency", "warning");
    // held course is marked
    expect(within(screen.getByTestId("kds-item-2")).getByText("HELD")).toBeInTheDocument();
    // line numbers (replaced the old C<course> tags — course_number is never
    // set to anything but 1, so the badge carried no information)
    expect(within(card).getByText("1")).toBeInTheDocument();
    expect(within(card).getByText("2")).toBeInTheDocument();

    // The "N tickets" label was removed with the chrome strip it lived on —
    // the ACTIVE filter chip carries the same count now.
    expect(screen.getByTestId("kds-filter-active")).toHaveTextContent("1");
    expect(screen.getByTestId("kds-counters")).toHaveTextContent("All 1");
    expect(screen.getByTestId("kds-counters")).toHaveTextContent("Rush 1");
    expect(screen.getByTestId("kds-counters")).toHaveTextContent("Late 0");
  });

  it("filters to a single station when the route carries a station id", async () => {
    renderWithProviders(
      <Routes>
        <Route path="/kds" element={<KdsScreen />} />
        <Route path="/kds/:stationId" element={<KdsScreen />} />
      </Routes>,
      { initialEntries: ["/kds/1"] },
    );

    // The station filter UI was removed, but the /kds/:stationId route still
    // scopes the board server-side — only station 1's line shows.
    const card = await screen.findByTestId("kds-ticket-10");
    expect(within(card).getByText(/kebab/i)).toBeInTheDocument();
    expect(within(card).queryByText(/fries/i)).not.toBeInTheDocument();
  });

  it("bumps a ticket off the board and recalls it via ↺ Bumped", async () => {
    renderWithProviders(
      <Routes>
        <Route path="/kds" element={<KdsScreen />} />
        <Route path="/kds/:stationId" element={<KdsScreen />} />
      </Routes>,
      { initialEntries: ["/kds/1"] },
    );

    await screen.findByTestId("kds-ticket-10");
    const recall = screen.getByTestId("kds-recall-bumped");
    expect(recall).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: /⇄ Bump/ }));
    await waitFor(() => expect(screen.queryByTestId("kds-ticket-10")).not.toBeInTheDocument());
    expect(recall).toBeEnabled();

    await userEvent.click(recall);
    await waitFor(() => expect(screen.getByTestId("kds-ticket-10")).toBeInTheDocument());
  });

  it("marks a ticket ready in place, showing the READY state", async () => {
    renderWithProviders(
      <Routes>
        <Route path="/kds/:stationId" element={<KdsScreen />} />
      </Routes>,
      { initialEntries: ["/kds/1"] },
    );

    await screen.findByTestId("kds-ticket-10");
    await userEvent.click(screen.getByRole("button", { name: /✓ Ready/ }));
    const card = await screen.findByTestId("kds-ticket-10");
    await waitFor(() => expect(within(card).getByText("✓ READY")).toBeInTheDocument());
    expect(within(card).getByRole("button", { name: /Served — Bump/ })).toBeInTheDocument();
  });

  it("supports expo view query stub (ready pickup emphasis)", async () => {
    renderWithProviders(
      <Routes>
        <Route path="/kds" element={<KdsScreen />} />
        <Route path="/kds/:stationId" element={<KdsScreen />} />
      </Routes>,
      { initialEntries: ["/kds?view=expo"] },
    );

    await waitFor(() =>
      expect(screen.getByTestId("kds-screen")).toHaveAttribute("data-view", "expo"),
    );
    expect(screen.getByTestId("kds-expo-banner")).toBeInTheDocument();
    expect(screen.getByTestId("kds-pickup")).toBeInTheDocument();
  });
});
