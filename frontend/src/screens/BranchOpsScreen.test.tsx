import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { BranchOpsScreen } from "./BranchOpsScreen";

vi.mock("../components/LocationPickerModal", () => ({
  LocationPickerModal: ({
    onSave,
    onClose,
  }: {
    onSave: (lat: number, lng: number) => void;
    onClose: () => void;
  }) => (
    <div data-testid="location-picker-modal">
      <button type="button" onClick={() => onSave(25.20111, 55.27111)}>
        Mock save map
      </button>
      <button type="button" onClick={onClose}>
        Mock close map
      </button>
    </div>
  ),
}));

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function fakeOrgToken(orgId: number): string {
  return `header.${btoa(JSON.stringify({ sub: String(orgId), aud: "org" }))}.sig`;
}

describe("BranchOpsScreen", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("ops_org_token", fakeOrgToken(7));
    vi.stubGlobal(
      "fetch",
      vi.fn((url: unknown, init?: RequestInit) => {
        const path = String(url);
        if (path.endsWith("/api/v1/organizations/bootstrap") && init?.method === "POST") {
          return Promise.resolve(
            json({
              id: 7,
              name: "Test Org",
              created: false,
              restaurant_id: 1,
              access_token: fakeOrgToken(7),
              token_type: "bearer",
            }),
          );
        }
        if (path.endsWith("/api/v1/organizations/branches") && init?.method === "POST") {
          return Promise.resolve(json({ id: 13, name: "Jumeirah", lat: 25.2, lng: 55.25 }, 201));
        }
        if (path.endsWith("/api/v1/organizations/branches")) {
          return Promise.resolve(
            json([
              { id: 11, name: "Downtown", lat: 25.2, lng: 55.27 },
              { id: 12, name: "Marina", lat: 25.08, lng: 55.14 },
            ]),
          );
        }
        if (path.includes("/rollup-sales")) {
          return Promise.resolve(
            json({
              total_gross_sales_aed: "4200.00",
              branches: [
                { restaurant_id: 11, name: "Downtown", gross_sales_aed: "2800.00" },
                { restaurant_id: 12, name: "Marina", gross_sales_aed: "1400.00" },
              ],
            }),
          );
        }
        if (path.includes("/inventory-summary")) {
          return Promise.resolve(
            json({
              total_inventory_value_aed: "900.00",
              total_low_stock_count: 3,
              branches: [
                {
                  restaurant_id: 11,
                  restaurant_name: "Downtown",
                  inventory_value_aed: "600.00",
                  low_stock_count: 1,
                },
                {
                  restaurant_id: 12,
                  restaurant_name: "Marina",
                  inventory_value_aed: "300.00",
                  low_stock_count: 2,
                },
              ],
            }),
          );
        }
        if (path.includes("/branch-comparison")) {
          return Promise.resolve(
            json([
              {
                restaurant_id: 11,
                restaurant_name: "Downtown",
                order_count: 32,
                revenue_aed: "2800.00",
              },
              {
                restaurant_id: 12,
                restaurant_name: "Marina",
                order_count: 18,
                revenue_aed: "1400.00",
              },
            ]),
          );
        }
        if (path.includes("/stock-transfers")) {
          return Promise.resolve(
            json({ id: 44, status: "draft", from_restaurant_id: 11, to_restaurant_id: 12 }, 201),
          );
        }
        return Promise.resolve(json({}));
      }),
    );
  });

  afterEach(() => vi.restoreAllMocks());

  it("shows branch cards and header actions only (no inline stock section)", async () => {
    renderWithProviders(<BranchOpsScreen />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Branches" })).toBeInTheDocument());
    expect(await screen.findByText("AED 4,200.00")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Downtown" })).toBeInTheDocument();
    // Header order: Stock transfer then + Add branch
    expect(screen.getByRole("button", { name: /^stock transfer$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^\+ add branch$/i })).toBeInTheDocument();
    // Not on the main page until dialog opens
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens stock transfer dialog from header before add branch", async () => {
    renderWithProviders(<BranchOpsScreen />);
    await screen.findByRole("cell", { name: "Downtown" });

    fireEvent.click(screen.getByRole("button", { name: /^stock transfer$/i }));
    expect(screen.getByRole("dialog", { name: /stock transfer/i })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("From branch"), { target: { value: "11" } });
    fireEvent.change(screen.getByLabelText("To branch"), { target: { value: "12" } });
    fireEvent.change(screen.getByLabelText("Ingredient"), { target: { value: "Rice" } });
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "5.000" } });
    fireEvent.click(screen.getByRole("button", { name: /create transfer/i }));
    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/organizations/7/stock-transfers"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("opens add-branch dialog and creates a branch", async () => {
    renderWithProviders(<BranchOpsScreen />);
    await screen.findByRole("cell", { name: "Downtown" });

    fireEvent.click(screen.getByRole("button", { name: /^\+ add branch$/i }));
    expect(screen.getByRole("dialog", { name: /add branch/i })).toBeInTheDocument();

    // A branch has no login of its own, so the dialog asks for a name and a
    // place and nothing else.
    expect(screen.queryByLabelText(/login email/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/login password/i)).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Branch name"), { target: { value: "Jumeirah" } });
    fireEvent.change(screen.getByLabelText("Latitude"), { target: { value: "25.20" } });
    fireEvent.change(screen.getByLabelText("Longitude"), { target: { value: "55.25" } });
    fireEvent.click(screen.getByRole("button", { name: /^add branch$/i }));
    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/organizations/branches"),
        expect.objectContaining({ method: "POST" }),
      ),
    );

    // And no credential is smuggled into the request body.
    const call = vi
      .mocked(fetch)
      .mock.calls.find(
        ([url, init]) =>
          String(url).includes("/api/v1/organizations/branches") &&
          (init as RequestInit)?.method === "POST",
      );
    const body = JSON.parse(String((call?.[1] as RequestInit).body));
    expect(body).toMatchObject({ name: "Jumeirah", lat: 25.2, lng: 55.25 });
    expect(body.email).toBeUndefined();
    expect(body.password).toBeUndefined();
  });
});
