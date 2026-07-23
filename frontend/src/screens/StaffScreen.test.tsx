import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StaffScreen } from "./StaffScreen";

const staff = [{ id: 1, name: "Ahmed", phone: null, role: "staff" }];

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
            new Response(JSON.stringify({ id: 2, name: "Bilal", phone: null, role: "staff" }), { status: 201 }),
          );
        }
        return Promise.resolve(new Response(JSON.stringify(staff), { status: 200 }));
      }),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("lists staff from the API", async () => {
    render(<StaffScreen />);
    await waitFor(() => expect(screen.getByRole("cell", { name: "Ahmed" })).toBeInTheDocument());
  });

  it("creates a waiter", async () => {
    render(<StaffScreen />);
    await waitFor(() => expect(screen.getByRole("cell", { name: "Ahmed" })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^Name$/i), { target: { value: "Bilal" } });
    fireEvent.change(screen.getByLabelText(/new staff pin/i), { target: { value: "4321" } });
    fireEvent.click(screen.getByRole("button", { name: /add waiter/i }));
    await waitFor(() => expect(screen.getByRole("cell", { name: "Bilal" })).toBeInTheDocument());
  });

  it("clocks a staff member in", async () => {
    render(<StaffScreen />);
    await waitFor(() => expect(screen.getByRole("cell", { name: "Ahmed" })).toBeInTheDocument());
    fireEvent.click(screen.getByText(/clock in/i));
    await waitFor(() => expect(screen.getByText(/clock out/i)).toBeInTheDocument());
  });

  it("shows clock out for a staff member who is already clocked in on load", async () => {
    vi.mocked(fetch).mockImplementation((url: string) => {
      if (String(url).includes("/status")) {
        return Promise.resolve(
          new Response(JSON.stringify({ staff_id: 1, status: "clocked_in" }), { status: 200 }),
        );
      }
      return Promise.resolve(new Response(JSON.stringify(staff), { status: 200 }));
    });
    render(<StaffScreen />);
    await waitFor(() => expect(screen.getByRole("cell", { name: "Ahmed" })).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText(/clock out/i)).toBeInTheDocument());
    expect(screen.queryByText(/clock in/i)).not.toBeInTheDocument();
  });

  it("shows an End break action (not a guaranteed-409 Clock out) for a staff member on break", async () => {
    vi.mocked(fetch).mockImplementation((url: string) => {
      if (String(url).includes("/status")) {
        return Promise.resolve(
          new Response(JSON.stringify({ staff_id: 1, status: "on_break" }), { status: 200 }),
        );
      }
      return Promise.resolve(new Response(JSON.stringify(staff), { status: 200 }));
    });
    render(<StaffScreen />);
    await waitFor(() => expect(screen.getByRole("cell", { name: "Ahmed" })).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText(/end break/i)).toBeInTheDocument());
    expect(screen.queryByText(/^clock out$/i)).not.toBeInTheDocument();
  });

});
