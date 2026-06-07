import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SettingsScreen } from "./SettingsScreen";

const me = {
  id: 1, name: "Test Resto", phone: "+9714", lat: 25.2, lng: 55.2,
  settings: { max_orders_per_batch: 3, max_items_per_order: 20 },
};

describe("SettingsScreen", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (String(url).includes("/me")) {
        return Promise.resolve(new Response(JSON.stringify(me), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify(me), { status: 200 }));
    }));
  });
  afterEach(() => vi.restoreAllMocks());

  it("loads current batching settings", async () => {
    render(<SettingsScreen />);
    // Navigate to batching tab
    await waitFor(() => screen.getByRole("button", { name: /batching/i }));
    await userEvent.click(screen.getByRole("button", { name: /batching/i }));
    await waitFor(() => expect((screen.getByLabelText(/orders per batch/i) as HTMLInputElement).value).toBe("3"));
  });

  it("PATCHes settings on save", async () => {
    const spy = vi.mocked(fetch);
    render(<SettingsScreen />);
    // Navigate to batching tab
    await waitFor(() => screen.getByRole("button", { name: /batching/i }));
    await userEvent.click(screen.getByRole("button", { name: /batching/i }));
    await waitFor(() => screen.getByLabelText(/orders per batch/i));
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() =>
      expect(spy.mock.calls.some(([u, i]) => String(u).includes("/settings") && i?.method === "PATCH")).toBe(true),
    );
  });

  it("shows restaurant name in general tab", async () => {
    render(<SettingsScreen />);
    await waitFor(() => expect((screen.getByDisplayValue("Test Resto") as HTMLInputElement).value).toBe("Test Resto"));
  });
});
