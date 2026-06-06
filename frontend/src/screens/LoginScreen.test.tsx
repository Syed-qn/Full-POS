import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LoginScreen } from "./LoginScreen";

describe("LoginScreen", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("submits credentials and stores token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ access_token: "jwt-1", token_type: "bearer" }), {
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <LoginScreen />
      </MemoryRouter>,
    );
    await userEvent.type(screen.getByLabelText(/phone/i), "+97150000000");
    await userEvent.type(screen.getByLabelText(/password/i), "password1");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(localStorage.getItem("ops_token")).toBe("jwt-1"));
  });

  it("shows error banner on 401", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "bad credentials" }), { status: 401 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter>
        <LoginScreen />
      </MemoryRouter>,
    );
    await userEvent.type(screen.getByLabelText(/phone/i), "+97150000000");
    await userEvent.type(screen.getByLabelText(/password/i), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(screen.getByText(/bad credentials/i)).toBeInTheDocument());
  });
});
