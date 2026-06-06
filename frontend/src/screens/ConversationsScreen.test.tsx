import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConversationsScreen } from "./ConversationsScreen";

describe("ConversationsScreen", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nf", { status: 404 })));
  });
  afterEach(() => vi.restoreAllMocks());

  it("lists conversations from fixtures", async () => {
    render(<ConversationsScreen />);
    await waitFor(() => expect(screen.getByText("+971501234567")).toBeInTheDocument());
  });

  it("opens a thread and shows takeover toggle", async () => {
    render(<ConversationsScreen />);
    await waitFor(() => screen.getByText("+971501234567"));
    await userEvent.click(screen.getByText("+971501234567"));
    await waitFor(() => expect(screen.getByText("I want to order biryani")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /take over/i })).toBeInTheDocument();
  });

  it("activating takeover shows the control banner", async () => {
    render(<ConversationsScreen />);
    await waitFor(() => screen.getByText("+971501234567"));
    await userEvent.click(screen.getByText("+971501234567"));
    await userEvent.click(screen.getByRole("button", { name: /take over/i }));
    await waitFor(() => expect(screen.getByText(/you are controlling this conversation/i)).toBeInTheDocument());
  });
});
