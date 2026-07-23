import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StaffScreen } from "./StaffScreen";

const staff = [{ id: 1, name: "Ahmed", phone: null, role: "waiter" }];

describe("StaffScreen", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        if (String(url).includes("/clock")) {
          return Promise.resolve(
            new Response(JSON.stringify({ id: 1, type: "clock_in", at: "2026-07-08T10:00:00Z" }), { status: 200 }),
          );
        }
        if (init?.method === "POST") {
          return Promise.resolve(
            new Response(JSON.stringify({ id: 2, name: "Bilal", phone: null, role: "waiter" }), { status: 201 }),
          );
        }
        return Promise.resolve(new Response(JSON.stringify(staff), { status: 200 }));
      }),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("lists waiters from the API", async () => {
    render(<StaffScreen />);
    await waitFor(() => expect(screen.getByRole("cell", { name: "Ahmed" })).toBeInTheDocument());
  });

  it("creates a waiter from the dialog", async () => {
    render(<StaffScreen />);
    await waitFor(() => expect(screen.getByRole("cell", { name: "Ahmed" })).toBeInTheDocument());
    // Open the add-waiter dialog first.
    fireEvent.click(screen.getByRole("button", { name: /\+ add waiter/i }));
    fireEvent.change(screen.getByLabelText(/^Name$/i), { target: { value: "Bilal" } });
    fireEvent.change(screen.getByLabelText(/new staff pin/i), { target: { value: "4321" } });
    fireEvent.click(screen.getByRole("button", { name: /^add waiter$/i }));
    await waitFor(() => expect(screen.getByRole("cell", { name: "Bilal" })).toBeInTheDocument());
  });
});
