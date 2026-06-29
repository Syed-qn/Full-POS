import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../lib/apiClient";
import { RidersScreen } from "./RidersScreen";
import * as ridersApi from "../lib/ridersApi";

const riders = [
  { id: 3, name: "Ali Hassan", phone: "+9715", status: "on_delivery" },
  { id: 4, name: "Omar Farouq", phone: "+9716", status: "off_shift" },
];

vi.mock("../lib/ridersApi", async (importOriginal) => {
  const actual = await importOriginal<typeof ridersApi>();
  return {
    ...actual,
    deleteRider: vi.fn(),
    setRiderStatus: vi.fn(),
  };
});

describe("RidersScreen", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url.endsWith("/api/v1/me")) {
          return Promise.resolve(new Response(JSON.stringify({ phone: "+971500000000" }), { status: 200 }));
        }
        return Promise.resolve(new Response(JSON.stringify(riders), { status: 200 }));
      }),
    );
    vi.mocked(ridersApi.deleteRider).mockReset();
    vi.mocked(ridersApi.setRiderStatus).mockReset();
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders rider cards from API", async () => {
    render(<RidersScreen />);
    await waitFor(() => expect(screen.getByText("Ali Hassan")).toBeInTheDocument());
    expect(screen.getByText("Omar Farouq")).toBeInTheDocument();
  });

  it("shows empty state when no riders", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("[]", { status: 200 }));
    render(<RidersScreen />);
    await waitFor(() => expect(screen.getByText(/register your first rider/i)).toBeInTheDocument());
  });

  it("shows a loading skeleton until riders resolve", () => {
    vi.mocked(fetch).mockReturnValue(new Promise(() => {})); // never resolves
    const { container } = render(<RidersScreen />);
    expect(container.querySelector('[aria-busy="true"]')).toBeTruthy();
    expect(screen.queryByText(/register your first rider/i)).not.toBeInTheDocument();
  });

  it("offers deactivation when remove is blocked by payment records", async () => {
    const user = userEvent.setup();
    vi.mocked(ridersApi.deleteRider).mockRejectedValue(
      new ApiError(
        409,
        "This rider has payment records on file — deactivate them instead of removing.",
      ),
    );
    vi.mocked(ridersApi.setRiderStatus).mockResolvedValue({
      ...riders[0],
      status: "deactivated",
    });

    render(<RidersScreen />);
    await waitFor(() => expect(screen.getByText("Ali Hassan")).toBeInTheDocument());

    await user.click(screen.getAllByRole("button", { name: /remove/i })[0]);
    await user.click(screen.getByRole("button", { name: /remove rider/i }));

    expect(ridersApi.deleteRider).toHaveBeenCalledWith(3);
    expect(await screen.findByText(/payment records on file/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /deactivate rider/i }));
    expect(ridersApi.setRiderStatus).toHaveBeenCalledWith(3, "deactivated");
    await waitFor(() => expect(screen.queryByText(/payment records on file/i)).not.toBeInTheDocument());
  });
});
