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
          new Response(
            JSON.stringify({ complete: true, has_menu: true, has_catalog_id: true }),
            { status: 200 },
          ),
        );
      }
      if (u.includes("/api/v1/me") || u.endsWith("/me")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              id: 1,
              name: "Test Restaurant",
              email: "owner@test.ae",
              lat: 25.2,
              lng: 55.2,
              settings: {},
            }),
            { status: 200 },
          ),
        );
      }
      if (u.includes("/api/v1/ordering/customers")) {
        return Promise.resolve(new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 }));
      }
      if (u.includes("/api/v1/orders") || u.includes("/api/v1/tickets") || u.includes("/api/v1/riders")) {
        return Promise.resolve(new Response("[]", { status: 200 }));
      }
      if (u.includes("/api/v1/dispatch/kpis") || u.includes("/dispatch/kpis")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              batch_rate_pct: 0,
              avg_stops: 0,
              engine_fallback_pct: 0,
              late_risk_count: 0,
              window: "1h",
            }),
            { status: 200 },
          ),
        );
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    }),
  );
}

describe("App routing", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
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
    expect(screen.getByText("Full POS", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign In" })).toBeInTheDocument();
  });

  it("renders shell when authenticated", async () => {
    localStorage.setItem("ops_token", "tok");
    sessionStorage.setItem("ops_onboarding_complete", "1");
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/settings"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByText("Sign out")).toBeInTheDocument());
    expect(screen.getByText("FULL POS")).toBeInTheDocument();
    // TopBar + PageHeader both title the screen
    expect(screen.getAllByRole("heading", { name: "Settings" }).length).toBeGreaterThan(0);
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
      expect(screen.getAllByRole("heading", { name: "Customers" }).length).toBeGreaterThan(0),
    );
    expect(
      fetchSpy.mock.calls.some(([url]) => String(url).includes("/onboarding/status")),
    ).toBe(false);
  });
});
