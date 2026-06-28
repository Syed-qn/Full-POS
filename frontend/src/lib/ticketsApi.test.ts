import { afterEach, describe, expect, it, vi } from "vitest";
import { getTicket, listTickets, resolveTicket } from "./ticketsApi";
import type { Ticket } from "./types";

const ticket: Ticket = {
  id: 7,
  customer_id: 1,
  order_id: 10,
  source_message: "My food was cold",
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

describe("ticketsApi", () => {
  afterEach(() => vi.restoreAllMocks());

  it("lists tickets filtered by status", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify([ticket]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const out = await listTickets("open");

    expect(out).toHaveLength(1);
    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/tickets?status=open");
  });

  it("fetches a single ticket by id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(ticket), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await getTicket(7);

    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/tickets/7");
  });

  it("resolveTicket POSTs the body to the resolve endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(ticket), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await resolveTicket(7, { action: "wallet_refund", note: "sorry", amount: "12.50" });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/v1/tickets/7/resolve");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      action: "wallet_refund",
      note: "sorry",
      amount: "12.50",
    });
  });
});
