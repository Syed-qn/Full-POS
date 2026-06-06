import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MessageBubble } from "./MessageBubble";
import type { MessageOut } from "../lib/types";

const inbound: MessageOut = { id: 1, direction: "inbound", type: "text", payload: { text: "Hi" }, ts: 1717660800 };
const outbound: MessageOut = { id: 2, direction: "outbound", type: "text", payload: { text: "Welcome" }, ts: 1717660830 };

describe("MessageBubble", () => {
  it("renders inbound text on the left", () => {
    render(<MessageBubble message={inbound} />);
    expect(screen.getByText("Hi").parentElement?.className).toContain("inbound");
  });
  it("renders outbound text on the right", () => {
    render(<MessageBubble message={outbound} />);
    expect(screen.getByText("Welcome").parentElement?.className).toContain("outbound");
  });
});
