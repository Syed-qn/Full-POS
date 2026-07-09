import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { KdsScreen } from "./KdsScreen";

const ticket = {
  id: 1,
  order_id: 10,
  order_number: "R1-0001",
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
  urgency: "ok",
  is_delayed: false,
  estimated_ready_at: new Date(Date.now() + 20 * 60000).toISOString(),
  course_number: 1,
};

describe("KdsScreen", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        const u = String(url);
        const method = (init?.method ?? "GET").toUpperCase();
        if (u.includes("/api/v1/kds/stations") && !u.includes("/tickets") && method === "GET") {
          return Promise.resolve(
            new Response(
              JSON.stringify([
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
              ]),
              { status: 200 },
            ),
          );
        }
        if (u.includes("/tickets") && method === "GET") {
          return Promise.resolve(new Response(JSON.stringify([ticket]), { status: 200 }));
        }
        if (method === "PATCH" || method === "POST") {
          return Promise.resolve(
            new Response(
              JSON.stringify({ ...ticket, kitchen_status: "ready", packaging_checked: true }),
              { status: 200 },
            ),
          );
        }
        if (u.includes("ready-for-pickup")) {
          return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
        }
        if (u.includes("performance") || u.includes("printer-status")) {
          return Promise.resolve(
            new Response(
              JSON.stringify(
                u.includes("performance")
                  ? {
                      ticket_count: 1,
                      bumped_count: 1,
                      late_ticket_count: 0,
                      avg_prep_minutes: 5,
                      by_station: [],
                    }
                  : [],
              ),
              { status: 200 },
            ),
          );
        }
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows a ticket with allergens, modifiers, timer and bumps it", async () => {
    renderWithProviders(
      <Routes>
        <Route path="/kds/:stationId" element={<KdsScreen />} />
      </Routes>,
      { initialEntries: ["/kds/1"] },
    );

    await waitFor(() => expect(screen.getByText(/kebab/i)).toBeInTheDocument());
    expect(screen.getByTestId("kds-allergens")).toHaveTextContent(/dairy/i);
    expect(screen.getByTestId("kds-modifiers")).toHaveTextContent(/chili/i);
    expect(screen.getByTestId("kds-timer")).toBeInTheDocument();
    expect(screen.getByTestId("kds-eta")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /bump/i }));
    await waitFor(() => expect(screen.queryByText(/kebab/i)).not.toBeInTheDocument());
  });
});
