import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { createTestQueryClient } from "../test/render";
import { beforeEach, describe, expect, it } from "vitest";
import { NavSidebar } from "./NavSidebar";

function renderNav(path = "/") {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="*" element={<NavSidebar />} />
          <Route path="/login" element={<div>LOGIN PAGE</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function fakeJwt(payload: Record<string, unknown>): string {
  const part = (o: unknown) =>
    btoa(JSON.stringify(o)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${part({ alg: "none", typ: "JWT" })}.${part(payload)}.sig`;
}

describe("NavSidebar identity label", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("names an email/password session Owner, not Manager", () => {
    // aud=manager with no role claim is the /auth/login token, and that
    // credential lives on the restaurant row — i.e. the owner. Labelling it
    // "Manager" told the owner they were a lesser role than they are.
    localStorage.setItem("ops_token", fakeJwt({ sub: "1", aud: "manager" }));
    renderNav("/");
    expect(screen.getByText(/^owner$/i)).toBeInTheDocument();
    expect(screen.queryByText(/^manager$/i)).not.toBeInTheDocument();
  });

  it("still shows the real role for a staff PIN session", () => {
    localStorage.setItem("ops_token", fakeJwt({ sub: "9", aud: "staff", role: "manager" }));
    renderNav("/");
    expect(screen.getByText(/^manager$/i)).toBeInTheDocument();
    expect(screen.queryByText(/^owner$/i)).not.toBeInTheDocument();
  });
});

describe("NavSidebar logout", () => {
  beforeEach(() => localStorage.clear());

  it("clears the token and navigates to /login", () => {
    localStorage.setItem("ops_token", "tok");
    renderNav("/");

    fireEvent.click(screen.getByRole("button", { name: /sign out/i }));

    expect(localStorage.getItem("ops_token")).toBeNull();
    expect(screen.getByText("LOGIN PAGE")).toBeInTheDocument();
  });

  it("lists daily screens first including Floor Plan", () => {
    renderNav("/");
    expect(screen.getByRole("link", { name: /live ops/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /floor plan/i })).toHaveAttribute("href", "/floor");
    // New Order is hidden for the owner/manager nav (null role here) — they take
    // orders through the till surfaces. It used to render as an inert "coming
    // soon" row, which this asserted; now it is not in the sidebar at all.
    expect(screen.queryByRole("link", { name: /new order/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/new order/i)).not.toBeInTheDocument();
    // Owner/manager (null role) see Manage as Admin
    expect(screen.getByRole("button", { name: /admin/i })).toBeInTheDocument();
  });

  it("offers Inventory as a real link, not a Soon pill", () => {
    // The screen, its route and its API were all already built; only the
    // LIVE_ROUTES flag still marked it unshipped, so it rendered as an inert
    // row nobody could open.
    renderNav("/");
    expect(screen.getByRole("link", { name: /inventory/i })).toHaveAttribute(
      "href",
      "/inventory",
    );
    expect(screen.queryByLabelText(/inventory, coming soon/i)).not.toBeInTheDocument();
  });

  it("collapses navigation width and keeps accessible names on icon-only links", () => {
    renderNav("/");
    const nav = screen.getByRole("navigation", { name: /main/i });
    expect(nav).toHaveAttribute("data-collapsed", "false");

    const collapse = screen.getByRole("button", { name: /collapse navigation/i });
    expect(collapse).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(collapse);

    expect(nav).toHaveAttribute("data-collapsed", "true");
    expect(screen.getByRole("button", { name: /expand navigation/i })).toHaveAttribute(
      "aria-expanded",
      "false",
    );

    // Icon-only mode still exposes labels via aria-label/title for keyboard + AT.
    const liveOps = screen.getByRole("link", { name: /live ops/i });
    expect(liveOps).toHaveAttribute("aria-label", "Live Ops");
    expect(liveOps).toHaveAttribute("title", "Live Ops");
    expect(screen.getByRole("link", { name: /floor plan/i })).toBeInTheDocument();
  });

  it("group heads expose aria-expanded for keyboard expand/collapse", () => {
    renderNav("/");
    const daily = screen.getByRole("button", { name: /daily/i });
    expect(daily).toHaveAttribute("aria-expanded", "true");
    expect(daily).toHaveAttribute("aria-controls", "nav-group-daily");
  });
});
