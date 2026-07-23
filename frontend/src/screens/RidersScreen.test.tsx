import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "../test/render";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../lib/apiClient";
import { RidersScreen } from "./RidersScreen";
import * as ridersApi from "../lib/ridersApi";
import * as ordersApi from "../lib/ordersApi";

const riders = [
  {
    id: 3,
    name: "Ali Hassan",
    phone: "+9715",
    status: "available",
    on_duty: true,
    delivered_24h: 2,
    delivered_lifetime: 40,
    last_lat: null,
    last_lng: null,
    last_location_at: null,
  },
  {
    id: 4,
    name: "Omar Farouq",
    phone: "+9716",
    status: "off_shift",
    on_duty: false,
    delivered_24h: 0,
    delivered_lifetime: 12,
    last_lat: null,
    last_lng: null,
    last_location_at: null,
  },
];

const queueOrders = [
  {
    id: 101,
    order_number: "R1-0101",
    status: "ready",
    customer_name: "Sara",
    customer_phone: "+97150111",
    items: [],
    total_aed: "45.00",
    rider_id: null,
    rider_name: null,
    sla_started_at: new Date(Date.now() - 35 * 60_000).toISOString(),
    prep_deadline: null,
    cook_estimate_minutes: null,
    created_at: new Date().toISOString(),
    address: null,
    lat: null,
    lng: null,
  },
];

const emptyMap = {
  origin: { lat: 25.2, lng: 55.27, name: "HQ" },
  batches: [],
  sla_rings: [],
};

vi.mock("../lib/ridersApi", async (importOriginal) => {
  const actual = await importOriginal<typeof ridersApi>();
  return {
    ...actual,
    deleteRider: vi.fn(),
    setRiderStatus: vi.fn(),
  };
});

vi.mock("../lib/ordersApi", async (importOriginal) => {
  const actual = await importOriginal<typeof ordersApi>();
  return {
    ...actual,
    assignOrder: vi.fn(),
  };
});

vi.mock("../components/LiveOpsMap", () => ({
  LiveOpsMap: ({ fillHeight }: { fillHeight?: boolean }) => (
    <div data-testid="live-ops-map" data-fill={fillHeight ? "1" : "0"}>
      map
    </div>
  ),
}));

describe("RidersScreen", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        const u = String(url);
        if (u.includes("/api/v1/me")) {
          return Promise.resolve(
            new Response(JSON.stringify({ phone: "+971500000000" }), { status: 200 }),
          );
        }
        if (u.includes("/api/v1/dispatch/live-map")) {
          return Promise.resolve(new Response(JSON.stringify(emptyMap), { status: 200 }));
        }
        if (u.includes("/api/v1/orders")) {
          return Promise.resolve(new Response(JSON.stringify(queueOrders), { status: 200 }));
        }
        if (u.includes("/api/v1/riders") || u.endsWith("/riders")) {
          return Promise.resolve(new Response(JSON.stringify(riders), { status: 200 }));
        }
        // riders list is default from useRidersQuery
        return Promise.resolve(new Response(JSON.stringify(riders), { status: 200 }));
      }),
    );
    vi.mocked(ridersApi.deleteRider).mockReset();
    vi.mocked(ridersApi.setRiderStatus).mockReset();
    vi.mocked(ordersApi.assignOrder).mockReset();
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders every rider as a card", async () => {
    renderWithProviders(<RidersScreen />);
    await waitFor(() => expect(screen.getAllByText("Ali Hassan").length).toBeGreaterThan(0));
    expect(screen.getAllByText("Omar Farouq").length).toBeGreaterThan(0);
    expect(screen.getByTestId("riders-stats")).toBeInTheDocument();
  });

  // The unassigned queue, dispatch map, fleet selector, late-risk pill and the
  // bottom action bar were removed from this screen on purpose. Manual rider
  // assignment now lives ONLY in the order detail drawer, so nothing here may
  // call assignOrder.
  it("no longer renders the dispatch ops block or its bottom bar", async () => {
    renderWithProviders(<RidersScreen />);
    await waitFor(() => expect(screen.getAllByText("Ali Hassan").length).toBeGreaterThan(0));
    expect(screen.queryByTestId("riders-ops-layout")).not.toBeInTheDocument();
    expect(screen.queryByTestId("live-ops-map")).not.toBeInTheDocument();
    expect(screen.queryByTestId("dispatch-queue-101")).not.toBeInTheDocument();
    expect(screen.queryByTestId("riders-late-risk")).not.toBeInTheDocument();
    expect(screen.queryByTestId("riders-manual-assign")).not.toBeInTheDocument();
    expect(screen.queryByRole("toolbar", { name: /primary actions/i })).not.toBeInTheDocument();
    expect(ordersApi.assignOrder).not.toHaveBeenCalled();
  });

  it("shows empty state when no riders", async () => {
    vi.mocked(fetch).mockImplementation((url: string) => {
      const u = String(url);
      if (u.includes("/api/v1/orders")) {
        return Promise.resolve(new Response("[]", { status: 200 }));
      }
      if (u.includes("/api/v1/me")) {
        return Promise.resolve(new Response(JSON.stringify({ phone: null }), { status: 200 }));
      }
      return Promise.resolve(new Response("[]", { status: 200 }));
    });
    renderWithProviders(<RidersScreen />);
    await waitFor(() => expect(screen.getByText(/register your first rider/i)).toBeInTheDocument());
  });

  it("shows a loading skeleton until riders resolve", () => {
    vi.mocked(fetch).mockReturnValue(new Promise(() => {})); // never resolves
    const { container } = renderWithProviders(<RidersScreen />);
    expect(container.querySelector('[aria-busy="true"]')).toBeTruthy();
    expect(screen.queryByText(/register your first rider/i)).not.toBeInTheDocument();
  });

  it("offers deactivation when remove is blocked by payment records", async () => {
    const user = userEvent.setup();
    vi.mocked(ridersApi.deleteRider).mockRejectedValue(
      new ApiError(
        409,
        "This rider has payment records on file — deactivate them instead of removing.",
      ),
    );
    vi.mocked(ridersApi.setRiderStatus).mockResolvedValue({
      ...riders[0],
      status: "deactivated",
    } as never);

    renderWithProviders(<RidersScreen />);
    await waitFor(() => expect(screen.getAllByText("Ali Hassan").length).toBeGreaterThan(0));

    // Select Ali so detail RiderCard is in focus (or use any Remove on page)
    const removeButtons = screen.getAllByRole("button", { name: /remove/i });
    await user.click(removeButtons[0]);
    await user.click(screen.getByRole("button", { name: /remove rider/i }));

    expect(ridersApi.deleteRider).toHaveBeenCalledWith(3);
    expect(await screen.findByText(/payment records on file/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /deactivate rider/i }));
    expect(ridersApi.setRiderStatus).toHaveBeenCalledWith(3, "deactivated");
    await waitFor(() =>
      expect(screen.queryByText(/payment records on file/i)).not.toBeInTheDocument(),
    );
  });
});
