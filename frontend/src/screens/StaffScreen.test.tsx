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
    await waitFor(() => expect(screen.getByText("Ahmed")).toBeInTheDocument());
  });

  it("creates a staff member", async () => {
    render(<StaffScreen />);
    await waitFor(() => expect(screen.getByText("Ahmed")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: "Bilal" } });
    fireEvent.change(screen.getByLabelText(/pin/i), { target: { value: "4321" } });
    fireEvent.click(screen.getByText(/add staff/i));
    await waitFor(() => expect(screen.getByText("Bilal")).toBeInTheDocument());
  });

  it("clocks a staff member in", async () => {
    render(<StaffScreen />);
    await waitFor(() => expect(screen.getByText("Ahmed")).toBeInTheDocument());
    fireEvent.click(screen.getByText(/clock in/i));
    await waitFor(() => expect(screen.getByText(/clock out/i)).toBeInTheDocument());
  });
});
