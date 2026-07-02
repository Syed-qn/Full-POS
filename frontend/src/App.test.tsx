import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { queryClient } from "./lib/queryClient";
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
      if (u.includes("/api/v1/ordering/customers")) {
        return Promise.resolve(new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 }));
      }
      if (u.includes("/api/v1/orders") || u.includes("/api/v1/tickets") || u.includes("/api/v1/riders")) {
        return Promise.resolve(new Response("[]", { status: 200 }));
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
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByText("OPS TERMINAL", { exact: false })).toBeInTheDocument();
  });

  it("renders shell when authenticated", async () => {
    localStorage.setItem("ops_token", "tok");
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByText("Home")).toBeInTheDocument());
  });

  it("renders immediately when onboarding is already cached", async () => {
    localStorage.setItem("ops_token", "tok");
    sessionStorage.setItem("ops_onboarding_complete", "1");
    const fetchSpy = vi.mocked(globalThis.fetch);
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/customers"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Customers" })).toBeInTheDocument(),
    );
    expect(
      fetchSpy.mock.calls.some(([url]) => String(url).includes("/onboarding/status")),
    ).toBe(false);
  });
});
