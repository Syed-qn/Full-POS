import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TicketDetailDrawer } from "./TicketDetailDrawer";
import type { Ticket } from "../lib/types";

const ticket: Ticket = {
  id: 7,
  customer_id: 1,
  order_id: 10,
  source_message: "My food arrived cold",
  evidence: null,
  category: "quality",
  status: "open",
  assigned_to: null,
  resolution_action: null,
  resolution_amount_aed: null,
  replacement_order_id: null,
  resolution_note: null,
  resolved_at: null,
  created_at: "2026-06-28T10:00:00Z",
};

describe("TicketDetailDrawer", () => {
  beforeEach(() => {
    // Fresh Response per call — a Response body can only be read once, and the
    // drawer fetches the wallet on mount before the resolve POST.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() =>
        Promise.resolve(
          new Response(JSON.stringify({ ...ticket, status: "resolved" }), { status: 200 }),
        ),
      ),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows the customer message", () => {
    render(<TicketDetailDrawer ticket={ticket} onResolved={() => {}} />);
    expect(screen.getByText("My food arrived cold")).toBeInTheDocument();
  });

  it("disables Refund to Wallet without an amount and note", () => {
    render(<TicketDetailDrawer ticket={ticket} onResolved={() => {}} />);
    expect(screen.getByRole("button", { name: /refund to wallet/i })).toBeDisabled();
    expect(screen.getByText(/required\. type a resolution note/i)).toBeInTheDocument();
    expect(screen.getAllByText("Required").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Required for refund")).toBeInTheDocument();
  });

  it("enables Refund to Wallet only once amount and note are set", () => {
    render(<TicketDetailDrawer ticket={ticket} onResolved={() => {}} />);
    const refundBtn = screen.getByRole("button", { name: /refund to wallet/i });

    fireEvent.change(screen.getByLabelText(/resolution note/i), { target: { value: "Refunded" } });
    expect(refundBtn).toBeDisabled(); // amount still empty

    fireEvent.change(screen.getByLabelText(/refund amount/i), { target: { value: "12.50" } });
    expect(refundBtn).not.toBeDisabled();
  });

  it("calls the resolve API and onResolved when Mark Resolved is clicked", async () => {
    const onResolved = vi.fn();
    render(<TicketDetailDrawer ticket={ticket} onResolved={onResolved} />);

    fireEvent.change(screen.getByLabelText(/resolution note/i), { target: { value: "All good" } });
    fireEvent.click(screen.getByRole("button", { name: /mark resolved/i }));

    await waitFor(() => expect(onResolved).toHaveBeenCalled());
    const fetchMock = vi.mocked(fetch);
    // A wallet GET fires on mount for context; assert the resolve POST happened too.
    const resolveCall = fetchMock.mock.calls.find((c) =>
      String(c[0]).includes("/api/v1/tickets/7/resolve"),
    );
    expect(resolveCall).toBeTruthy();
  });

  it("enables Create replacement order once a note is entered (order-linked ticket)", () => {
    render(<TicketDetailDrawer ticket={ticket} onResolved={() => {}} />);
    const btn = screen.getByRole("button", { name: /create replacement order/i });
    expect(btn).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/resolution note/i), { target: { value: "remaking" } });
    expect(btn).not.toBeDisabled();
  });

  it("disables Create replacement when the complaint has no linked order", () => {
    render(<TicketDetailDrawer ticket={{ ...ticket, order_id: null }} onResolved={() => {}} />);
    fireEvent.change(screen.getByLabelText(/resolution note/i), { target: { value: "remaking" } });
    expect(screen.getByRole("button", { name: /create replacement order/i })).toBeDisabled();
  });

  it("hides action buttons for a resolved ticket", () => {
    render(
      <TicketDetailDrawer
        ticket={{ ...ticket, status: "resolved", resolution_action: "wallet_refund", resolution_amount_aed: "20.00" }}
        onResolved={() => {}}
      />,
    );
    expect(screen.queryByRole("button", { name: /refund to wallet/i })).not.toBeInTheDocument();
    expect(screen.getByText(/wallet refund/i)).toBeInTheDocument();
  });
});
