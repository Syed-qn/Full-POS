import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TicketsScreen } from "./TicketsScreen";

const tickets = [
  {
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
  },
  {
    id: 8,
    customer_id: 2,
    order_id: 11,
    source_message: "Missing a drink",
    evidence: null,
    category: "missing_item",
    status: "in_progress",
    assigned_to: null,
    resolution_action: null,
    resolution_amount_aed: null,
    replacement_order_id: null,
    resolution_note: null,
    resolved_at: null,
    created_at: "2026-06-28T11:00:00Z",
  },
];

describe("TicketsScreen", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(tickets), { status: 200 })));
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders ticket rows from the API", async () => {
    render(<TicketsScreen />);
    await waitFor(() => expect(screen.getByText("My food arrived cold")).toBeInTheDocument());
    expect(screen.getByText("Missing a drink")).toBeInTheDocument();
  });

  it("shows empty state when there are no tickets", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("[]", { status: 200 }));
    render(<TicketsScreen />);
    await waitFor(() => expect(screen.getByText(/no open complaints/i)).toBeInTheDocument());
  });

  it("shows a loading skeleton until tickets resolve", () => {
    vi.mocked(fetch).mockReturnValue(new Promise(() => {})); // never resolves
    const { container } = render(<TicketsScreen />);
    expect(container.querySelector('[aria-busy="true"]')).toBeTruthy();
    expect(screen.queryByText(/no open complaints/i)).not.toBeInTheDocument();
  });
});


describe("TicketsScreen phone search", () => {
  it("passes the phone query to the API on search", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response("[]", { status: 200 })),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<TicketsScreen />);
    await waitFor(() => screen.getByLabelText(/search complaints by phone/i));
    fireEvent.change(screen.getByLabelText(/search complaints by phone/i), { target: { value: "777001" } });
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("phone=777001"))).toBe(true),
    );
    vi.restoreAllMocks();
  });
});
