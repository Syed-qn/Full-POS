import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RidersScreen } from "./RidersScreen";

const riders = [
  { id: 3, name: "Ali Hassan", phone: "+9715", status: "on_delivery" },
  { id: 4, name: "Omar Farouq", phone: "+9716", status: "off_shift" },
];

describe("RidersScreen", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(riders), { status: 200 })));
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
});
