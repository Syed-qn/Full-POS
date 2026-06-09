import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LoginScreen } from "./LoginScreen";

const tokenResponse = () =>
  new Response(JSON.stringify({ access_token: "jwt-1", token_type: "bearer" }), { status: 200 });

describe("LoginScreen — login", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("submits credentials and stores token", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(tokenResponse()));
    render(<MemoryRouter><LoginScreen /></MemoryRouter>);
    await userEvent.type(screen.getByLabelText(/phone/i), "+97150000000");
    await userEvent.type(screen.getByLabelText(/password/i), "password1");
    // "Sign In" submit button (title-case) vs "SIGN IN" tab — exact match distinguishes them
    await userEvent.click(screen.getByRole("button", { name: "Sign In" }));
    await waitFor(() => expect(localStorage.getItem("ops_token")).toBe("jwt-1"));
  });

  it("shows error banner on 401", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "bad credentials" }), { status: 401 }),
      ),
    );
    render(<MemoryRouter><LoginScreen /></MemoryRouter>);
    await userEvent.type(screen.getByLabelText(/phone/i), "+97150000000");
    await userEvent.type(screen.getByLabelText(/password/i), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign In" }));
    await waitFor(() => expect(screen.getByText(/bad credentials/i)).toBeInTheDocument());
  });
});

describe("LoginScreen — signup", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  function clickSignUpTab() {
    // Two "sign up" buttons exist: the tab and the hint link — pick the tab (first).
    return userEvent.click(screen.getAllByRole("button", { name: /sign up/i })[0]);
  }

  it("sign up tab shows restaurant name field", async () => {
    render(<MemoryRouter><LoginScreen /></MemoryRouter>);
    await clickSignUpTab();
    expect(screen.getByLabelText(/restaurant name/i)).toBeInTheDocument();
  });

  it("signup calls /auth/signup then /auth/login and stores token", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 1 }), { status: 200 }))
      .mockResolvedValueOnce(tokenResponse());
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><LoginScreen /></MemoryRouter>);
    await clickSignUpTab();
    await userEvent.type(screen.getByLabelText(/restaurant name/i), "Biryani House");
    await userEvent.type(screen.getByLabelText(/phone/i), "+97150000000");
    await userEvent.type(screen.getByLabelText(/password/i), "Admin@1234");
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => expect(localStorage.getItem("ops_token")).toBe("jwt-1"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("shows error when restaurant name is empty on signup", async () => {
    render(<MemoryRouter><LoginScreen /></MemoryRouter>);
    await clickSignUpTab();
    await userEvent.type(screen.getByLabelText(/phone/i), "+97150000000");
    await userEvent.type(screen.getByLabelText(/password/i), "Admin@1234");
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));
    await waitFor(() =>
      expect(screen.getByText(/restaurant name is required/i)).toBeInTheDocument(),
    );
  });
});
