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
  const fetchMock: ReturnType<typeof vi.fn> = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url);
    calls.push(`${init?.method ?? "GET"} ${u}`);
    // The server rejects a call with no bearer. Modelling that is the whole
    // point here: a stub that answers unauthenticated requests would pass just
    // as happily with the wrong token, proving nothing about which one is used.
    const auth = (init?.headers as Record<string, string> | undefined)?.Authorization;
    if (!auth) return new Response(JSON.stringify({ detail: "missing token" }), { status: 401 });
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
    sessionStorage.clear();
    localStorage.setItem("ops_token", "owner-jwt");
  });
  afterEach(() => vi.restoreAllMocks());

  it("selects the branch actually in use, with no placeholder option", async () => {
    stubApi({ meId: 1 });
    render(<BranchSwitcher />);

    const trigger = await screen.findByRole("combobox", { name: /branch/i });
    await waitFor(() => expect(trigger).toHaveTextContent("La Cafe"));

    // A "Switch branch…" prompt never tells you where you already are.
    expect(screen.queryByText(/switch branch/i)).not.toBeInTheDocument();

    // The list is a popup now, so it exists only once opened — which is also
    // what keeps the top bar from rendering every branch on every page.
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    await userEvent.click(trigger);
    expect(screen.getAllByRole("option")).toHaveLength(2);
  });

  it("marks the main branch in the list", async () => {
    stubApi({ meId: 1 });
    render(<BranchSwitcher />);

    await userEvent.click(await screen.findByRole("combobox", { name: /branch/i }));

    // "Main" is a badge beside the name rather than "(Main)" inside it, so it
    // reads as a property of the branch and not as part of what it is called.
    expect(screen.getByRole("option", { name: "La Cafe Main" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "La Cafe 2" })).toBeInTheDocument();
  });

  it("marks which branch you are on, so the list is not a guess", async () => {
    stubApi({ meId: 2 });
    render(<BranchSwitcher />);

    const trigger = await screen.findByRole("combobox", { name: /branch/i });
    await waitFor(() => expect(trigger).toHaveTextContent("La Cafe 2"));
    await userEvent.click(trigger);

    expect(screen.getByRole("option", { name: "La Cafe 2" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("option", { name: "La Cafe Main" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("shows the current branch when the session is on a non-main store", async () => {
    stubApi({ meId: 2 });
    render(<BranchSwitcher />);

    const trigger = await screen.findByRole("combobox", { name: /branch/i });
    await waitFor(() => expect(trigger).toHaveTextContent("La Cafe 2"));
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
    await userEvent.click(await screen.findByRole("combobox", { name: /branch/i }));
    await userEvent.click(screen.getByRole("option", { name: "La Cafe 2" }));

    await waitFor(() => expect(localStorage.getItem("ops_token")).toBe("branch-jwt"));
    expect(calls).toContain("POST /api/v1/organizations/branches/2/session");
    expect(reload).toHaveBeenCalled();
  });

  it("picking the branch you are already on does not reload the dashboard", async () => {
    const calls = stubApi({ meId: 1 });
    const reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, reload },
    });

    render(<BranchSwitcher />);
    const trigger = await screen.findByRole("combobox", { name: /branch/i });
    await waitFor(() => expect(trigger).toHaveTextContent("La Cafe"));
    await userEvent.click(trigger);
    await userEvent.click(screen.getByRole("option", { name: "La Cafe Main" }));

    // Closing the menu is the whole effect. A full page reload to land back
    // where you already were is seconds of blank screen for nothing.
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(reload).not.toHaveBeenCalled();
    expect(calls.some((c) => c.includes("/session"))).toBe(false);
  });

  it("closes on Escape without switching", async () => {
    stubApi({ meId: 1 });
    const reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, reload },
    });

    render(<BranchSwitcher />);
    await userEvent.click(await screen.findByRole("combobox", { name: /branch/i }));
    expect(screen.getByRole("listbox")).toBeInTheDocument();

    // Opening the list to look at it must not be a way to change branch.
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(reload).not.toHaveBeenCalled();
  });

  it("is on screen immediately after the reload, not seconds later", async () => {
    // Switching hard-reloads the page. Without a cache the control renders
    // nothing until /branches returns, which against a remote DB measured ~3.5s
    // — the field visibly disappeared and came back on every switch.
    sessionStorage.setItem("pos.branches", JSON.stringify(BRANCHES));
    sessionStorage.setItem("pos.branch_current", "2");

    let resolveBranches: (v: Response) => void = () => {};
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).includes("/organizations/branches")) {
          return new Promise<Response>((r) => {
            resolveBranches = r;
          });
        }
        return new Response(JSON.stringify({ id: 2, name: "La Cafe 2" }), { status: 200 });
      }),
    );

    render(<BranchSwitcher />);

    // Rendered from cache while /branches is still in flight, already showing
    // the branch that was switched to.
    const trigger = screen.getByRole("combobox", { name: /branch/i });
    expect(trigger).toHaveTextContent("La Cafe 2");

    resolveBranches(new Response(JSON.stringify(BRANCHES), { status: 200 }));
    await waitFor(() => expect(trigger).toHaveTextContent("La Cafe 2"));
  });

  it("keeps rendering when a refresh fails, instead of vanishing", async () => {
    sessionStorage.setItem("pos.branches", JSON.stringify(BRANCHES));
    vi.stubGlobal("fetch", vi.fn(async () => new Response("nope", { status: 500 })));

    render(<BranchSwitcher />);
    const trigger = screen.getByRole("combobox", { name: /branch/i });
    // Give the failed fetches time to settle; the control must survive them.
    await waitFor(() => expect(trigger).toBeInTheDocument());
  });

  it("ignores a corrupt cache rather than throwing during render", async () => {
    sessionStorage.setItem("pos.branches", "{not json");
    stubApi({ meId: 1 });
    render(<BranchSwitcher />);
    expect(await screen.findByRole("combobox", { name: /branch/i })).toBeInTheDocument();
  });

  it("works with only the owner token, no org token", async () => {
    // The org token (ops_org_token) is minted by the Branches screen's
    // bootstrap call. The top bar renders on every page, so it usually has no
    // org token at all — authenticating with it made the switcher 401 and
    // silently render nothing everywhere except the Branches page itself.
    localStorage.removeItem("ops_org_token");
    const calls = stubApi({ meId: 1 });

    render(<BranchSwitcher />);
    expect(await screen.findByRole("combobox", { name: /branch/i })).toBeInTheDocument();

    expect(calls).toContain("GET /api/v1/organizations/branches");
    const branchCall = vi
      .mocked(fetch)
      .mock.calls.find(([u]) => String(u).includes("/organizations/branches"));
    expect((branchCall?.[1] as RequestInit).headers).toMatchObject({
      Authorization: "Bearer owner-jwt",
    });
  });

  it("does not offer a closed branch", async () => {
    // Three, so two remain open and the switcher still renders — with only one
    // open branch left it hides entirely, which is the next test.
    stubApi({
      branches: [
        BRANCHES[0],
        { id: 3, name: "La Cafe 3", is_main: false, has_login: false, email: null },
        { ...BRANCHES[1], is_active: false },
      ],
      meId: 1,
    });
    render(<BranchSwitcher />);

    const trigger = await screen.findByRole("combobox", { name: /branch/i });
    await waitFor(() => expect(trigger).toHaveTextContent("La Cafe"));
    await userEvent.click(trigger);

    // The server refuses to mint a token for a closed branch, so listing it
    // would only produce an option that errors on click.
    expect(screen.queryByRole("option", { name: "La Cafe 2" })).toBeNull();
    expect(screen.getByRole("option", { name: "La Cafe Main" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "La Cafe 3" })).toBeInTheDocument();
  });

  it("keeps showing branches when the server omits is_active", async () => {
    // An older server sends no such field. Treating that as closed would hide
    // every branch and silently remove the switcher altogether.
    stubApi({ meId: 1 });
    render(<BranchSwitcher />);

    await userEvent.click(await screen.findByRole("combobox", { name: /branch/i }));
    expect(screen.getAllByRole("option")).toHaveLength(2);
  });

  it("renders nothing when only one branch is still open", async () => {
    stubApi({ branches: [BRANCHES[0], { ...BRANCHES[1], is_active: false }], meId: 1 });
    const { container } = render(<BranchSwitcher />);
    // A picker with one usable entry is just a control that can go wrong.
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("renders nothing for a single-branch account", async () => {
    stubApi({ branches: [BRANCHES[0]], meId: 1 });
    const { container } = render(<BranchSwitcher />);
    // Give the two fetches a chance to resolve before asserting emptiness.
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
