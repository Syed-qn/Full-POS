import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MarketingScreen } from "./MarketingScreen";

const pendingTemplate = {
  id: 2,
  meta_template_name: "promo_pending",
  status: "pending_meta",
  rejection_reason: null,
  body: "Hi {{1}}, pending offer!",
  header: null,
  buttons: null,
};

const rejectedTemplate = {
  id: 4,
  meta_template_name: "promo_rejected",
  status: "rejected",
  rejection_reason: "URLs are not allowed",
  body: "Hi {{1}}, visit https://bad.example",
  header: null,
  buttons: null,
};

describe("MarketingScreen template lifecycle", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: unknown, init?: RequestInit) => {
        const url = typeof input === "string" ? input : (input as Request).url;
        if (url.includes("/api/v1/me"))
          return Promise.resolve(
            new Response(JSON.stringify({ settings: {} }), { status: 200 }),
          );
        if (url.includes("/marketing/templates/") && url.includes("/submit") && init?.method === "POST")
          return Promise.resolve(
            new Response(
              JSON.stringify({
                id: 99,
                meta_template_name: "new_tpl",
                status: "pending_meta",
                rejection_reason: null,
                body: "Hi {{1}}, new!",
              }),
              { status: 200 },
            ),
          );
        if (url.includes("/marketing/templates") && init?.method === "POST") {
          const body = JSON.parse(String(init.body)) as { ephemeral?: boolean };
          return Promise.resolve(
            new Response(
              JSON.stringify({
                id: 99,
                meta_template_name: "new_tpl",
                status: "draft",
                rejection_reason: null,
                body: "Hi {{1}}, new!",
                ephemeral: body.ephemeral ?? false,
              }),
              { status: 201 },
            ),
          );
        }
        if (url.includes("/marketing/templates/4/fix") && init?.method === "POST")
          return Promise.resolve(
            new Response(
              JSON.stringify({
                ...rejectedTemplate,
                status: "draft",
                rejection_reason: null,
                body: "Hi {{1}}, fixed offer without links",
              }),
              { status: 200 },
            ),
          );
        if (url.includes("/marketing/templates"))
          return Promise.resolve(
            new Response(JSON.stringify([pendingTemplate, rejectedTemplate]), {
              status: 200,
            }),
          );
        if (url.includes("/marketing/audience"))
          return Promise.resolve(new Response("[]", { status: 200 }));
        if (url.includes("/marketing/segments"))
          return Promise.resolve(new Response("[]", { status: 200 }));
        return Promise.resolve(new Response("not found", { status: 404 }));
      }),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("shows shimmer on pending template preview", async () => {
    render(<MarketingScreen />);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => {
      const bubble = document.querySelector('[class*="previewShimmer"]');
      expect(bubble).toBeTruthy();
    });
  });

  it("shows approval timeline for rejected template", async () => {
    render(<MarketingScreen />);
    await vi.advanceTimersByTimeAsync(0);
    fireEvent.click(screen.getByTitle("promo_rejected"));
    await waitFor(() =>
      expect(screen.getByText(/meta rejected this template/i)).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /fix with ai/i })).toBeInTheDocument();
  });

  it("fix with AI calls fix endpoint", async () => {
    render(<MarketingScreen />);
    await vi.advanceTimersByTimeAsync(0);
    fireEvent.click(screen.getByTitle("promo_rejected"));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /fix with ai/i })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /fix with ai/i }));
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => {
      const calls = vi.mocked(fetch).mock.calls;
      const fixCall = calls.find(
        ([u, init]) =>
          String(u).includes("/marketing/templates/4/fix") && init?.method === "POST",
      );
      expect(fixCall).toBeTruthy();
    });
  });

  it("create from Today's Special sends ephemeral true", async () => {
    render(<MarketingScreen />);
    await vi.advanceTimersByTimeAsync(0);
    fireEvent.click(screen.getByRole("button", { name: /today's special/i }));
    await vi.advanceTimersByTimeAsync(0);
    fireEvent.click(screen.getByRole("button", { name: /＋ new template/i }));
    await waitFor(() =>
      expect(
        screen.getByText(/removed automatically tonight/i),
      ).toBeInTheDocument(),
    );
    const describeFields = screen.getAllByPlaceholderText(/20% off all biryani/i);
    fireEvent.change(describeFields[describeFields.length - 1], {
      target: { value: "Free dessert with every order today only" },
    });
    const bodyFields = screen.getAllByPlaceholderText(/hi \{\{1\}\}/i);
    fireEvent.change(bodyFields[bodyFields.length - 1], {
      target: {
        value: "Hi {{1}}, free dessert with every order today — reply to order!",
      },
    });
    const submitButtons = screen.getAllByRole("button", { name: /submit for approval/i });
    fireEvent.click(submitButtons[submitButtons.length - 1]);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => {
      const createCall = vi.mocked(fetch).mock.calls.find(
        ([u, init]) =>
          String(u).includes("/marketing/templates") &&
          init?.method === "POST" &&
          !String(u).includes("/draft"),
      );
      expect(createCall).toBeTruthy();
      const body = JSON.parse(String(createCall?.[1]?.body)) as { ephemeral?: boolean };
      expect(body.ephemeral).toBe(true);
    });
  });
});