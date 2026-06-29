import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

function mockAuthedFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: unknown) => {
      const u = String(url);
      if (u.includes("/onboarding/status")) {
        return Promise.resolve(
          new Response(JSON.stringify({ complete: true, has_menu: true, has_catalog_id: true }), { status: 200 }),
        );
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    }),
  );
}

describe("App routing", () => {
  beforeEach(() => {
    localStorage.clear();
    mockAuthedFetch();
  });
  afterEach(() => vi.restoreAllMocks());

  it("redirects unauthenticated users to /login", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByText("OPS TERMINAL", { exact: false })).toBeInTheDocument();
  });

  it("renders shell when authenticated", async () => {
    localStorage.setItem("ops_token", "tok");
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("Home")).toBeInTheDocument());
  });
});
