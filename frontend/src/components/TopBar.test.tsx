import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TopBar } from "./TopBar";

describe("TopBar staff switch", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ id: 1, name: "Test Resto" }), { status: 200 }),
      ),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("opens staff switch modal from Staff button", async () => {
    render(
      <MemoryRouter>
        <TopBar />
      </MemoryRouter>,
    );
    const btn = screen.getByTestId("topbar-staff-switch");
    expect(btn).toBeEnabled();
    await userEvent.click(btn);
    expect(screen.getByTestId("staff-switch-modal")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /switch staff/i })).toBeInTheDocument();
  });
});
