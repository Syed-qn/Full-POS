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
    expect(screen.getByRole("link", { name: /new order/i })).toBeInTheDocument();
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
