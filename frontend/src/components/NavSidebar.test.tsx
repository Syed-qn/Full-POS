import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { createTestQueryClient } from "../test/render";
import { beforeEach, describe, expect, it } from "vitest";
import { NavSidebar } from "./NavSidebar";

describe("NavSidebar logout", () => {
  beforeEach(() => localStorage.clear());

  it("clears the token and navigates to /login", () => {
    localStorage.setItem("ops_token", "tok");
    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route path="/" element={<NavSidebar />} />
            <Route path="/login" element={<div>LOGIN PAGE</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: /sign out/i }));

    expect(localStorage.getItem("ops_token")).toBeNull();
    expect(screen.getByText("LOGIN PAGE")).toBeInTheDocument();
  });
});
