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
    await userEvent.type(screen.getByLabelText(/email/i), "owner@biryanihouse.test");
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
    await userEvent.type(screen.getByLabelText(/email/i), "owner@biryanihouse.test");
    await userEvent.type(screen.getByLabelText(/password/i), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign In" }));
    await waitFor(() => expect(screen.getByText(/bad credentials/i)).toBeInTheDocument());
  });

  it("exposes a large staff PIN pad mode", async () => {
    render(<MemoryRouter><LoginScreen /></MemoryRouter>);
    await userEvent.click(screen.getByRole("tab", { name: /staff pin/i }));
    // Staff numbers restart at 1 per branch, so the pad asks for the store too.
    expect(screen.getByLabelText(/store code/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/staff number/i)).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /pin pad/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Digit 5" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in with pin/i })).toBeInTheDocument();
  });

  it("a ?store= pairing link opens the PIN pad with the branch filled in", async () => {
    render(
      <MemoryRouter initialEntries={["/login?location=v6uwmuwv"]}>
        <LoginScreen />
      </MemoryRouter>,
    );
    // No tab click: the link is the pairing, so the pad is where it lands.
    expect(screen.getByLabelText(/store code/i)).toHaveValue("V6UWMUWV");
    expect(screen.getByRole("group", { name: /pin pad/i })).toBeInTheDocument();
  });

  it("names the branch a pairing link resolves to", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ name: "POS MANAGEMENT Deira", lat: 25.2681, lng: 55.3094 }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    render(
      <MemoryRouter initialEntries={["/login?location=V6UWMUWV"]}>
        <LoginScreen />
      </MemoryRouter>,
    );
    // The name is the check a human can actually make; two branches a few
    // streets apart differ only in the third decimal of their coordinates.
    await waitFor(() =>
      expect(screen.getByText("POS MANAGEMENT Deira")).toBeInTheDocument(),
    );
    expect(screen.getByText(/25\.2681, 55\.3094/)).toBeInTheDocument();
  });

  it("flags a link whose coordinates point at a different branch", async () => {
    // Same store key, but the link carries the OTHER Dubai branch's location.
    vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(
        JSON.stringify({ name: "Deira Branch", lat: 25.2681, lng: 55.3094 }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    render(
      <MemoryRouter
        initialEntries={["/login?location=V6UWMUWV&lat=25.2048&lng=55.2708"]}
      >
        <LoginScreen />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("Deira Branch")).toBeInTheDocument());
    expect(screen.getByText(/points .* m away/)).toBeInTheDocument();
  });

  it("stays quiet when the link's coordinates match the branch", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(
        JSON.stringify({ name: "Deira Branch", lat: 25.2681, lng: 55.3094 }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    render(
      <MemoryRouter
        initialEntries={["/login?location=V6UWMUWV&lat=25.2681&lng=55.3094"]}
      >
        <LoginScreen />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("Deira Branch")).toBeInTheDocument());
    expect(screen.queryByText(/points .* m away/)).not.toBeInTheDocument();
  });

  it("refuses to sign in without a store code", async () => {
    render(<MemoryRouter><LoginScreen /></MemoryRouter>);
    await userEvent.click(screen.getByRole("tab", { name: /staff pin/i }));
    await userEvent.type(screen.getByLabelText(/staff number/i), "1");
    await userEvent.click(screen.getByRole("button", { name: "Digit 5" }));
    await userEvent.click(screen.getByRole("button", { name: /sign in with pin/i }));
    await waitFor(() =>
      expect(screen.getByText(/store code for this terminal/i)).toBeInTheDocument(),
    );
  });

  it("remembers the store code only after a successful sign-in", async () => {
    // A fresh Response per call: a body can only be read once, and the
    // store-pairing lookup fires before the login POST.
    const json = (b: unknown) =>
      new Response(JSON.stringify(b), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (url) =>
        String(url).includes("/staff/login")
          ? json({
              access_token: "t", token_type: "bearer", role: "manager",
              staff_id: 42, staff_code: 1, name: "Sara", training_mode: false,
            })
          : json({ name: "Test Branch", lat: 25.2048, lng: 55.2708 }),
      );
    render(<MemoryRouter><LoginScreen /></MemoryRouter>);
    await userEvent.click(screen.getByRole("tab", { name: /staff pin/i }));
    await userEvent.type(screen.getByLabelText(/store code/i), "k7qm4rtb");
    await userEvent.type(screen.getByLabelText(/staff number/i), "1");
    for (const d of ["8", "4", "7", "1"]) {
      await userEvent.click(screen.getByRole("button", { name: `Digit ${d}` }));
    }
    await userEvent.click(screen.getByRole("button", { name: /sign in with pin/i }));

    // The store-pairing lookup also fires, so target the login call specifically.
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some((c) => String(c[0]).includes("/staff/login")),
      ).toBe(true),
    );
    const loginCall = fetchMock.mock.calls.find((c) =>
      String(c[0]).includes("/staff/login"),
    )!;
    const body = JSON.parse(String(loginCall[1]?.body));
    // Upper-cased, and sent as the branch scope alongside the branch-local number.
    expect(body).toMatchObject({ location: "K7QM4RTB", staff_code: 1, pin: "8471" });
    await waitFor(() =>
      expect(localStorage.getItem("pos.store_code")).toBe("K7QM4RTB"),
    );
  });
});

describe("LoginScreen — signup", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  function clickSignUpTab() {
    // Tab labelled SIGN UP
    return userEvent.click(screen.getByRole("tab", { name: /sign up/i }));
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
    await userEvent.type(screen.getByLabelText(/email/i), "owner@biryanihouse.test");
    await userEvent.type(screen.getByLabelText(/password/i), "Admin@1234");
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => expect(localStorage.getItem("ops_token")).toBe("jwt-1"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("shows error when restaurant name is empty on signup", async () => {
    render(<MemoryRouter><LoginScreen /></MemoryRouter>);
    await clickSignUpTab();
    await userEvent.type(screen.getByLabelText(/email/i), "owner@biryanihouse.test");
    await userEvent.type(screen.getByLabelText(/password/i), "Admin@1234");
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));
    await waitFor(() =>
      expect(screen.getByText(/restaurant name is required/i)).toBeInTheDocument(),
    );
  });
});
