import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConversationRow } from "./ConversationRow";
import type { ConversationOut } from "../lib/types";

function conv(overrides: Partial<ConversationOut> = {}): ConversationOut {
  return {
    id: 1,
    phone: "+918220958384",
    counterpart: "customer",
    manual_takeover: false,
    last_message_preview: "hi",
    unread: false,
    ...overrides,
  } as ConversationOut;
}

describe("ConversationRow AI/human pill", () => {
  it("shows an AI pill when the AI is handling the chat", () => {
    render(
      <ConversationRow conversation={conv({ manual_takeover: false })} selected={false} onClick={() => {}} />,
    );
    expect(screen.getByText(/AI/)).toBeInTheDocument();
    expect(screen.queryByText(/Human/)).not.toBeInTheDocument();
  });

  it("shows a Human pill when the chat is escalated to manual takeover", () => {
    render(
      <ConversationRow conversation={conv({ manual_takeover: true })} selected={false} onClick={() => {}} />,
    );
    expect(screen.getByText(/Human/)).toBeInTheDocument();
    expect(screen.queryByText(/AI/)).not.toBeInTheDocument();
  });
});
