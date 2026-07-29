/** Adding a manager happens in a dialog.
 *
 * The form used to sit permanently above the list — an empty PIN box on screen
 * all day, pushing down the thing the page is actually for.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { ManagerManagementScreen } from "./ManagerManagementScreen";

const MANAGERS = [
  { id: 1, name: "Asfer (Manager)", role: "manager", phone: null, is_active: true, staff_code: 1 },
];

/** Enough rows for the filter to appear. */
const MANY = [
  { id: 1, name: "Asfer Ali", role: "manager", phone: "+97150111", is_active: true, staff_code: 1 },
  { id: 2, name: "Sara Khan", role: "manager", phone: "+97150222", is_active: true, staff_code: 2 },
  { id: 3, name: "Bilal Omar", role: "manager", phone: null, is_active: true, staff_code: 3 },
  { id: 4, name: "Nadia Rauf", role: "manager", phone: null, is_active: true, staff_code: 4 },
  { id: 5, name: "Imran Shah", role: "manager", phone: null, is_active: true, staff_code: 5 },
  { id: 6, name: "Lina Haddad", role: "manager", phone: null, is_active: true, staff_code: 6 },
];

let calls: Array<{ path: string; method: string; body: unknown }>;

function stubApi(opts: { failCreate?: boolean; list?: unknown[] } = {}) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown, init?: RequestInit) => {
      const path = String(url);
      const method = init?.method ?? "GET";
      let body: unknown = null;
      if (typeof init?.body === "string") {
        try {
          body = JSON.parse(init.body);
        } catch {
          body = init.body;
        }
      }
      calls.push({ path, method, body });
      if (method === "POST" && path.includes("/api/v1/staff")) {
        if (opts.failCreate) {
          return new Response(JSON.stringify({ detail: "PIN already in use" }), { status: 409 });
        }
        return new Response(JSON.stringify({ id: 2, name: "Sara", role: "manager" }), {
          status: 201,
        });
      }
      return new Response(JSON.stringify(opts.list ?? MANAGERS), { status: 200 });
    }),
  );
}

function openDialog() {
  return userEvent.click(screen.getByTestId("manager-add-open"));
}

describe("ManagerManagementScreen", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("ops_token", "owner-jwt");
    stubApi();
  });
  afterEach(() => vi.restoreAllMocks());

  it("keeps the form out of the page until asked for", async () => {
    renderWithProviders(<ManagerManagementScreen />);
    await screen.findByText("Asfer (Manager)");

    // The PIN box is the tell: it must not be sitting on screen unprompted.
    expect(screen.queryByTestId("manager-form-pin")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await openDialog();
    expect(screen.getByRole("dialog", { name: /add a manager/i })).toBeInTheDocument();
    expect(screen.getByTestId("manager-form-pin")).toBeInTheDocument();
  });

  it("creates the manager and refreshes the list", async () => {
    renderWithProviders(<ManagerManagementScreen />);
    await screen.findByText("Asfer (Manager)");
    await openDialog();

    await userEvent.type(screen.getByTestId("manager-form-name"), "Sara");
    await userEvent.type(screen.getByTestId("manager-form-pin"), "4821");
    await userEvent.click(screen.getByTestId("manager-form-submit"));

    await waitFor(() => {
      const post = calls.find((c) => c.method === "POST");
      expect(post?.body).toMatchObject({ name: "Sara", pin: "4821", phone: null });
    });
    // Closing on success is what tells the owner it worked.
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // ...and the list is re-read rather than left showing yesterday's roster.
    expect(calls.filter((c) => c.method === "GET").length).toBeGreaterThan(1);
  });

  it("will not submit a PIN shorter than four digits", async () => {
    renderWithProviders(<ManagerManagementScreen />);
    await screen.findByText("Asfer (Manager)");
    await openDialog();

    await userEvent.type(screen.getByTestId("manager-form-name"), "Sara");
    await userEvent.type(screen.getByTestId("manager-form-pin"), "12");
    expect(screen.getByTestId("manager-form-submit")).toBeDisabled();

    // Positive control: the button is gated on the PIN, not stuck off.
    await userEvent.type(screen.getByTestId("manager-form-pin"), "34");
    expect(screen.getByTestId("manager-form-submit")).toBeEnabled();
  });

  it("keeps what was typed when the server rejects it", async () => {
    stubApi({ failCreate: true });
    renderWithProviders(<ManagerManagementScreen />);
    await screen.findByText("Asfer (Manager)");
    await openDialog();

    await userEvent.type(screen.getByTestId("manager-form-name"), "Sara");
    await userEvent.type(screen.getByTestId("manager-form-pin"), "4821");
    await userEvent.click(screen.getByTestId("manager-form-submit"));

    // Re-entering a name and PIN because the server said no is how a PIN gets
    // mistyped the second time.
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByTestId("manager-form-name")).toHaveValue("Sara");
    expect(within(dialog).getByTestId("manager-form-pin")).toHaveValue("4821");
  });

  it("edits in the same dialog, prefilled, with the PIN left blank", async () => {
    renderWithProviders(<ManagerManagementScreen />);
    await screen.findByText("Asfer (Manager)");

    await userEvent.click(screen.getByTestId("manager-edit-1"));

    const dialog = await screen.findByRole("dialog", { name: /edit asfer/i });
    expect(within(dialog).getByTestId("manager-form-name")).toHaveValue("Asfer (Manager)");
    // A prefilled PIN box would imply the current PIN is readable. It is not.
    expect(within(dialog).getByTestId("manager-form-pin")).toHaveValue("");
    // ...and a blank PIN must still be savable, since it means "keep it".
    expect(within(dialog).getByTestId("manager-form-submit")).toBeEnabled();
  });

  it("sends only the fields that changed", async () => {
    renderWithProviders(<ManagerManagementScreen />);
    await screen.findByText("Asfer (Manager)");
    await userEvent.click(screen.getByTestId("manager-edit-1"));

    await userEvent.clear(screen.getByTestId("manager-form-name"));
    await userEvent.type(screen.getByTestId("manager-form-name"), "Asfer Ali");
    await userEvent.click(screen.getByTestId("manager-form-submit"));

    await waitFor(() => {
      const patch = calls.find((c) => c.method === "PATCH" || c.method === "PUT");
      expect(patch?.body).toEqual({ name: "Asfer Ali" });
    });
    // Untouched fields must not ride along — resending a blank PIN here would
    // reset the manager's PIN every time someone fixed a typo in their name.
    const patch = calls.find((c) => c.method === "PATCH" || c.method === "PUT");
    expect(patch?.body).not.toHaveProperty("pin");
    expect(patch?.body).not.toHaveProperty("phone");
  });

  it("rejects a too-short PIN on edit as well as on add", async () => {
    renderWithProviders(<ManagerManagementScreen />);
    await screen.findByText("Asfer (Manager)");
    await userEvent.click(screen.getByTestId("manager-edit-1"));

    // Blank means keep, but a typed PIN is still a real PIN.
    await userEvent.type(screen.getByTestId("manager-form-pin"), "12");
    expect(screen.getByTestId("manager-form-submit")).toBeDisabled();
  });

  it("shows a table skeleton while loading, not a bare Loading line", async () => {
    let release: (r: Response) => void = () => {};
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((r) => {
            release = r;
          }),
      ),
    );
    const { container } = renderWithProviders(<ManagerManagementScreen />);

    // The header is already on screen, so the page does not jump when rows land.
    expect(screen.getByRole("columnheader", { name: /^name$/i })).toBeInTheDocument();
    expect(container.querySelectorAll("[class*='sk']").length).toBeGreaterThan(0);

    release(new Response(JSON.stringify(MANAGERS), { status: 200 }));
    expect(await screen.findByText("Asfer (Manager)")).toBeInTheDocument();
    // The shimmer is gone once the rows are real, not left running underneath.
    expect(container.querySelectorAll("[class*='sk']").length).toBe(0);
  });

  it("shows the filter as soon as there is anything to filter", async () => {
    // It was briefly gated on a list of more than five, which meant an owner
    // with one manager could not see the control at all.
    renderWithProviders(<ManagerManagementScreen />);
    await screen.findByText("Asfer (Manager)");
    expect(screen.getByTestId("manager-filter")).toBeInTheDocument();
  });

  it("hides the filter only when there is nobody to filter", async () => {
    stubApi({ list: [] });
    renderWithProviders(<ManagerManagementScreen />);
    await screen.findByText(/no managers yet/i);
    expect(screen.queryByTestId("manager-filter")).not.toBeInTheDocument();
  });

  it("lists managers as a table, matching the other staff screens", async () => {
    stubApi({ list: MANY });
    renderWithProviders(<ManagerManagementScreen />);
    await screen.findByText("Asfer Ali");

    for (const col of [/^name$/i, /^sign-in no\.$/i, /^phone$/i, /^actions$/i]) {
      expect(screen.getByRole("columnheader", { name: col })).toBeInTheDocument();
    }
    // One row per manager, plus the header row.
    expect(screen.getAllByRole("row")).toHaveLength(MANY.length + 1);

    // A manager with no phone gets a dash, not an empty cell that reads as a
    // rendering bug.
    const bilal = screen.getByText("Bilal Omar").closest("tr")!;
    expect(within(bilal).getAllByText("—")).toHaveLength(1);
    expect(within(bilal).getByText("3")).toBeInTheDocument();
  });

  it("keeps Edit and Remove on one line in the actions cell", async () => {
    renderWithProviders(<ManagerManagementScreen />);
    await screen.findByText("Asfer (Manager)");

    const edit = screen.getByTestId("manager-edit-1");
    const remove = screen.getByTestId("manager-delete-1");
    // Both in the one flex span. Whether it WRAPS is a stylesheet question and
    // jsdom does not apply CSS modules, so getComputedStyle would pass against
    // an empty string and prove nothing.
    expect(edit.parentElement).toBe(remove.parentElement);
    expect(edit.parentElement?.className).toMatch(/rowActions/);
  });

  it("filters by name, sign-in number and phone", async () => {
    stubApi({ list: MANY });
    renderWithProviders(<ManagerManagementScreen />);
    await screen.findByText("Asfer Ali");

    const filter = screen.getByTestId("manager-filter");
    await userEvent.type(filter, "sara");
    expect(screen.getByText("Sara Khan")).toBeInTheDocument();
    expect(screen.queryByText("Asfer Ali")).not.toBeInTheDocument();
    // Header row plus the one match.
    expect(screen.getAllByRole("row")).toHaveLength(2);

    // Case-insensitive, and matches mid-string rather than only a prefix.
    await userEvent.clear(filter);
    await userEvent.type(filter, "HADDAD");
    expect(screen.getByText("Lina Haddad")).toBeInTheDocument();

    await userEvent.clear(filter);
    await userEvent.type(filter, "50222");
    expect(screen.getByText("Sara Khan")).toBeInTheDocument();
    expect(screen.queryByText("Bilal Omar")).not.toBeInTheDocument();

    // Clearing it brings everyone back — the filter must not be one-way.
    await userEvent.clear(filter);
    expect(screen.getByText("Asfer Ali")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(MANY.length + 1);
  });

  it("says so when nothing matches, instead of showing an empty card", async () => {
    stubApi({ list: MANY });
    renderWithProviders(<ManagerManagementScreen />);
    await screen.findByText("Asfer Ali");

    await userEvent.type(screen.getByTestId("manager-filter"), "zzzz");
    expect(screen.getByText(/no manager matches/i)).toBeInTheDocument();
    // Not the "No managers yet" empty state — there ARE managers, just none here.
    expect(screen.queryByText(/no managers yet/i)).not.toBeInTheDocument();
  });

  it("confirms removal in a dialog, not a browser alert", async () => {
    // window.confirm is a no-op in jsdom that returns undefined, so if the
    // screen still used it this delete would silently never fire — and in a
    // real browser it would be an unstyled OS box.
    const confirmSpy = vi.spyOn(window, "confirm");
    renderWithProviders(<ManagerManagementScreen />);
    await screen.findByText("Asfer (Manager)");

    await userEvent.click(screen.getByTestId("manager-delete-1"));
    expect(confirmSpy).not.toHaveBeenCalled();

    const dialog = await screen.findByRole("alertdialog", { name: /remove asfer/i });
    // Nothing is deleted merely by asking.
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);

    await userEvent.click(within(dialog).getByRole("button", { name: /remove manager/i }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });

  it("cancelling the removal dialog deletes nothing", async () => {
    renderWithProviders(<ManagerManagementScreen />);
    await screen.findByText("Asfer (Manager)");

    await userEvent.click(screen.getByTestId("manager-delete-1"));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: /cancel/i }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
  });

  it("closes on Escape without creating anything", async () => {
    renderWithProviders(<ManagerManagementScreen />);
    await screen.findByText("Asfer (Manager)");
    await openDialog();

    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });
});
