import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BranchSwitcher } from "./BranchSwitcher";

const BRANCHES = [
  { id: 1, name: "La Cafe", is_main: true, has_login: false, email: null },
  { id: 2, name: "La Cafe 2", is_main: false, has_login: false, email: null },
];

/** Answer /branches, /me and the session exchange; record what was asked. */
function stubApi(opts: { branches?: unknown[]; meId?: number } = {}) {
  const calls: string[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url);
    calls.push(`${init?.method ?? "GET"} ${u}`);
    if (u.includes("/organizations/branches") && u.includes("/session")) {
      return new Response(
        JSON.stringify({ access_token: "branch-jwt", name: "La Cafe 2", restaurant_id: 2 }),
        { status: 200 },
      );
    }
    if (u.includes("/organizations/branches")) {
      return new Response(JSON.stringify(opts.branches ?? BRANCHES), { status: 200 });
    }
    if (u.includes("/api/v1/me")) {
      return new Response(JSON.stringify({ id: opts.meId ?? 1, name: "La Cafe" }), {
        status: 200,
      });
    }
    return new Response("{}", { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

describe("BranchSwitcher", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("ops_token", "owner-jwt");
  });
  afterEach(() => vi.restoreAllMocks());

  it("selects the branch actually in use, with no placeholder option", async () => {
    stubApi({ meId: 1 });
    render(<BranchSwitcher />);

    const select = (await screen.findByRole("combobox", { name: /branch/i })) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("1"));

    // A "Switch branch…" prompt never tells you where you already are.
    expect(screen.queryByText(/switch branch/i)).not.toBeInTheDocument();
    expect(select.querySelectorAll("option")).toHaveLength(2);
  });

  it("marks the main branch in the list", async () => {
    stubApi({ meId: 1 });
    render(<BranchSwitcher />);

    expect(await screen.findByRole("option", { name: "La Cafe (Main)" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "La Cafe 2" })).toBeInTheDocument();
  });

  it("shows the current branch when the session is on a non-main store", async () => {
    stubApi({ meId: 2 });
    render(<BranchSwitcher />);

    const select = (await screen.findByRole("combobox", { name: /branch/i })) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("2"));
  });

  it("swaps the token for the picked branch", async () => {
    const calls = stubApi({ meId: 1 });
    // The component hard-reloads after switching; jsdom has no navigation.
    const reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, reload },
    });

    render(<BranchSwitcher />);
    const select = await screen.findByRole("combobox", { name: /branch/i });
    await userEvent.selectOptions(select, "2");

    await waitFor(() => expect(localStorage.getItem("ops_token")).toBe("branch-jwt"));
    expect(calls).toContain("POST /api/v1/organizations/branches/2/session");
    expect(reload).toHaveBeenCalled();
  });

  it("renders nothing for a single-branch account", async () => {
    stubApi({ branches: [BRANCHES[0]], meId: 1 });
    const { container } = render(<BranchSwitcher />);
    // Give the two fetches a chance to resolve before asserting emptiness.
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
