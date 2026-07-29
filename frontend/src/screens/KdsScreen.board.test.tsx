/** The kitchen board as a SURFACE: full-bleed for anyone, and a dine-in board
 *  you can mount on its own screen. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { AppShell } from "../components/AppShell";
import { isFullBleedPath } from "../lib/navAccess";
import { KdsScreen } from "./KdsScreen";

const stations = [
  {
    id: 1,
    name: "Grill",
    station_type: "grill",
    kitchen_code: "main",
    printer_ip: null,
    printer_port: null,
    fallback_station_id: null,
    is_active: true,
  },
];

function ticket(over: Record<string, unknown>) {
  return {
    id: 1,
    order_id: 10,
    order_number: "T02",
    order_type: "dine_in",
    order_priority: "normal",
    dish_name: "Kebab",
    variant_name: null,
    qty: 1,
    status: "queued",
    station_id: 1,
    course_number: 1,
    held: false,
    age_seconds: 60,
    created_at: new Date().toISOString(),
    allergens: [],
    modifiers: [],
    note: null,
    source_channel: "pos",
    table_label: "T2",
    ...over,
  };
}

const TICKETS = [
  ticket({ id: 1, order_id: 10, order_number: "T02", order_type: "dine_in", dish_name: "Kebab" }),
  ticket({
    id: 2,
    order_id: 11,
    order_number: "TK-38",
    order_type: "takeaway",
    dish_name: "Fries",
    table_label: null,
  }),
];

function mockFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: unknown) => {
      const path = String(url);
      const body = path.includes("/stations/1/tickets")
        ? TICKETS
        : path.includes("/kds/stations")
          ? stations
          : [];
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    }),
  );
}

/** The tests run under MemoryRouter, so window.location never changes —
 *  this reports the ROUTER's url, which is the thing under test. */
function UrlProbe() {
  const loc = useLocation();
  return <span data-testid="url-probe">{loc.search}</span>;
}

function board(entry: string) {
  return renderWithProviders(
    <>
      <UrlProbe />
      <Routes>
        <Route path="/kds" element={<KdsScreen />} />
        <Route path="/kds/:stationId" element={<KdsScreen />} />
      </Routes>
    </>,
    { initialEntries: [entry] },
  );
}

describe("KDS board", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    localStorage.setItem("ops_token", "restaurant-token");
    mockFetch();
  });
  afterEach(() => vi.restoreAllMocks());

  it("treats every kds route as full bleed", () => {
    expect(isFullBleedPath("/kds")).toBe(true);
    expect(isFullBleedPath("/kds/1")).toBe(true);
    // Not a prefix match on anything that merely starts with the letters.
    expect(isFullBleedPath("/inventory")).toBe(false);
    expect(isFullBleedPath("/")).toBe(false);
  });

  it("gives a manager the same board the cooks see, with no sidebar", async () => {
    // The manager token has no role claim, which is the case that used to get
    // the full dashboard chrome wrapped around a wall display.
    board("/kds");
    await screen.findByTestId("kds-ticket-10");

    expect(screen.queryByRole("navigation", { name: "Main" })).toBeNull();
    // ...and because there is no sidebar, the board must offer its own way out
    // or the screen is a dead end. For a manager that way out is the dashboard
    // — NOT sign out, which would make logging out of the whole dashboard the
    // price of glancing at the pass.
    expect(screen.getByTestId("kds-back-to-dashboard")).toBeInTheDocument();
    expect(screen.queryByTestId("kitchen-signout")).toBeNull();
  });

  it("gives a kitchen login sign out, since it owns no other screen", async () => {
    sessionStorage.setItem("ops_staff_session", JSON.stringify({ role: "kitchen" }));
    board("/kds");
    await screen.findByTestId("kds-ticket-10");

    // A cook has no dashboard to go back to, so "leaving" can only mean signing
    // out — and the dashboard link must not be offered to them.
    expect(screen.getByTestId("kitchen-signout")).toBeInTheDocument();
    expect(screen.queryByTestId("kds-back-to-dashboard")).toBeNull();
  });

  it("shows only dine-in when the board is mounted on the dine-in URL", async () => {
    board("/kds?filter=dine");

    const dineIn = await screen.findByTestId("kds-ticket-10");
    expect(within(dineIn).getByText(/kebab/i)).toBeInTheDocument();
    // A wall screen showing the dine-in pass must not carry takeaway tickets.
    expect(screen.queryByTestId("kds-ticket-11")).toBeNull();
  });

  it("puts the chosen board in the URL so a refresh keeps it", async () => {
    board("/kds");
    await screen.findByTestId("kds-ticket-10");

    await userEvent.click(screen.getByTestId("kds-filter-dine"));
    // Held in the URL, not in state: on a screen nobody is standing at, a
    // choice that dies on refresh dies for good.
    await screen.findByTestId("kds-ticket-10");
    expect(screen.getByTestId("url-probe").textContent).toContain("filter=dine");
    expect(screen.queryByTestId("kds-ticket-11")).toBeNull();
  });

  it("keeps the default board out of the URL", async () => {
    board("/kds?filter=dine");
    await screen.findByTestId("kds-ticket-10");

    await userEvent.click(screen.getByTestId("kds-filter-active"));
    // /kds and /kds?filter=all being two spellings of one board is how you end
    // up with two bookmarks that drift apart.
    expect(screen.getByTestId("url-probe").textContent).not.toContain("filter");
    expect(await screen.findByTestId("kds-ticket-11")).toBeInTheDocument();
  });
});

describe("AppShell", () => {
  it("still renders chrome for an ordinary screen", () => {
    localStorage.setItem("ops_token", "restaurant-token");
    // Positive control for the full-bleed change: the shell itself was not
    // broken, only bypassed on /kds.
    renderWithProviders(<AppShell>content</AppShell>, { initialEntries: ["/inventory"] });
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
  });
});
