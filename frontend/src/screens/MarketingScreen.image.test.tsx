import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MarketingScreen } from "./MarketingScreen";

describe("MarketingScreen generate image", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: unknown, init?: RequestInit) => {
        const url = typeof input === "string" ? input : (input as Request).url;
        if (url.includes("/templates/image/generate") && init?.method === "POST") {
          return Promise.resolve(
            new Response(
              JSON.stringify({ url: "http://localhost:8000/media/marketing/1/gen_abc.png" }),
              { status: 200 },
            ),
          );
        }
        if (url.includes("/api/v1/me"))
          return Promise.resolve(
            new Response(JSON.stringify({ settings: {} }), { status: 200 }),
          );
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

  it("generate image flow sets header preview after API returns url", async () => {
    render(<MarketingScreen />);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /new template/i })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /new template/i }));
    await vi.advanceTimersByTimeAsync(0);

    const describeField = screen.getAllByPlaceholderText(/20% off all biryani/i)[0];
    fireEvent.change(describeField, { target: { value: "20% off biryani weekend" } });

    fireEvent.click(screen.getByRole("button", { name: /generate image/i }));
    await vi.advanceTimersByTimeAsync(0);
    fireEvent.click(screen.getByRole("button", { name: /generate image/i }));
    await vi.advanceTimersByTimeAsync(0);

    await waitFor(() => expect(screen.getByAltText("header")).toBeInTheDocument());
  });
});