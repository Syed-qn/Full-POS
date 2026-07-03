import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MarketingScreen } from "./MarketingScreen";

describe("MarketingScreen segments tab", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: unknown) => {
        const url = typeof input === "string" ? input : (input as Request).url;
        if (url.includes("/api/v1/me"))
          return Promise.resolve(
            new Response(JSON.stringify({ settings: {} }), { status: 200 }),
          );
        if (url.includes("/marketing/segments/compile"))
          return Promise.resolve(
            new Response(
              JSON.stringify({
                dsl: { all: [{ field: "total_spend", op: "gte", value: 200 }] },
                preview_count: 12,
                plain_english: "customers who spent over AED 200",
              }),
              { status: 200 },
            ),
          );
        if (url.includes("/marketing/segments") && !url.includes("compile"))
          return Promise.resolve(new Response("[]", { status: 200 }));
        if (url.includes("/marketing/templates"))
          return Promise.resolve(new Response("[]", { status: 200 }));
        if (url.includes("/marketing/audience"))
          return Promise.resolve(new Response("[]", { status: 200 }));
        return Promise.resolve(new Response("not found", { status: 404 }));
      }),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("compile shows preview count on segments tab", async () => {
    render(<MarketingScreen />);
    await vi.advanceTimersByTimeAsync(0);
    fireEvent.click(screen.getByRole("button", { name: /^segments$/i }));
    const textarea = screen.getByPlaceholderText(/spent over aed 200/i);
    fireEvent.change(textarea, {
      target: { value: "customers who spent over AED 200" },
    });
    fireEvent.click(screen.getByRole("button", { name: /compile segment/i }));
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() =>
      expect(screen.getByText(/12 customers match/i)).toBeInTheDocument(),
    );
  });
});