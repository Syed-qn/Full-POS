import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import App from "./App";

describe("App routing", () => {
  beforeEach(() => localStorage.clear());

  it("redirects unauthenticated users to /login", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByText(/sign in/i)).toBeInTheDocument();
  });

  it("renders shell when authenticated", () => {
    localStorage.setItem("ops_token", "tok");
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByText("Home")).toBeInTheDocument();
  });
});
