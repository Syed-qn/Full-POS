import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CouponsScreen } from "./CouponsScreen";

const coupons = [
  {
    id: 1, code: "SAVE-ABC123", kind: "multi_use", discount_type: "fixed",
    discount_aed: "10.00", percent: null, max_discount_aed: null, min_order_aed: "0.00",
    applies_to: "whole_order", per_customer_limit: null, total_redemption_limit: null,
    status: "active", valid_from: null, expires_at: null, created_at: "2026-06-28T10:00:00Z",
  },
];

describe("CouponsScreen", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        if (init?.method === "POST") {
          return Promise.resolve(
            new Response(JSON.stringify(coupons[0]), { status: 201 }),
          );
        }
        return Promise.resolve(new Response(JSON.stringify(coupons), { status: 200 }));
      }),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("lists coupons from the API", async () => {
    render(<CouponsScreen />);
    await waitFor(() => expect(screen.getByText("SAVE-ABC123")).toBeInTheDocument());
    expect(screen.getByText("AED 10.00")).toBeInTheDocument();
  });

  it("shows empty state when no coupons", async () => {
    vi.mocked(fetch).mockImplementation((url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Promise.resolve(new Response(JSON.stringify(coupons[0]), { status: 201 }));
      }
      return Promise.resolve(new Response("[]", { status: 200 }));
    });
    render(<CouponsScreen />);
    await waitFor(() => expect(screen.getByText(/create one above/i)).toBeInTheDocument());
  });

  it("shows load error when list fails", async () => {
    vi.mocked(fetch).mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify({ detail: "missing token" }), { status: 401 })),
    );
    render(<CouponsScreen />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("missing token"));
  });

  it("disables create until a positive value is entered", async () => {
    vi.mocked(fetch).mockImplementation((url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Promise.resolve(new Response(JSON.stringify(coupons[0]), { status: 201 }));
      }
      return Promise.resolve(new Response("[]", { status: 200 }));
    });
    render(<CouponsScreen />);
    const createBtn = await screen.findByRole("button", { name: /create coupon/i });
    expect(createBtn).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/amount \(aed\)/i), { target: { value: "10" } });
    expect(createBtn).not.toBeDisabled();
  });

  it("posts a new coupon on create", async () => {
    render(<CouponsScreen />);
    fireEvent.change(await screen.findByLabelText(/amount \(aed\)/i), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: /create coupon/i }));
    await waitFor(() => {
      const posted = vi.mocked(fetch).mock.calls.find(
        (c) => String(c[0]).endsWith("/api/v1/coupons") && (c[1] as RequestInit)?.method === "POST",
      );
      expect(posted).toBeTruthy();
    });
  });
});