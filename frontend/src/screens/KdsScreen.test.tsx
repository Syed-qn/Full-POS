import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { KdsScreen } from "./KdsScreen";

describe("KdsScreen", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
        if (init?.method === "PATCH") {
          return Promise.resolve(
            new Response(JSON.stringify({ id: 1, kitchen_status: "ready" }), { status: 200 }),
          );
        }
        return Promise.resolve(
          new Response(
            JSON.stringify([
              { id: 1, order_id: 10, dish_name: "Kebab", variant_name: null, qty: 2, kitchen_status: "received", notes: null, created_at: new Date().toISOString() },
            ]),
            { status: 200 },
          ),
        );
      }),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows a ticket and bumps it", async () => {
    renderWithProviders(
      <Routes>
        <Route path="/kds/:stationId" element={<KdsScreen />} />
      </Routes>,
      { initialEntries: ["/kds/1"] },
    );

    await waitFor(() => expect(screen.getByText(/kebab/i)).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /bump/i }));
    await waitFor(() => expect(screen.queryByText(/kebab/i)).not.toBeInTheDocument());
  });
});
