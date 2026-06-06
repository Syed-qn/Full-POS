import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OrdersScreen } from "./OrdersScreen";

describe("OrdersScreen", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nf", { status: 404 })));
  });
  afterEach(() => vi.restoreAllMocks());

  it("lists orders from fixtures", async () => {
    render(<MemoryRouter><OrdersScreen /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText("Ali Hassan")).toBeInTheDocument());
    expect(screen.getByText("Omar Farouq")).toBeInTheDocument();
  });

  it("opens detail drawer on row click", async () => {
    render(<MemoryRouter><OrdersScreen /></MemoryRouter>);
    await waitFor(() => screen.getByText("Ali Hassan"));
    await userEvent.click(screen.getByText("Ali Hassan"));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
  });

  it("filters to empty with a no-match message", async () => {
    render(<MemoryRouter><OrdersScreen /></MemoryRouter>);
    await waitFor(() => screen.getByText("Ali Hassan"));
    await userEvent.type(screen.getByPlaceholderText(/search/i), "#9999");
    await waitFor(() => expect(screen.getByText(/no orders match/i)).toBeInTheDocument());
  });
});
