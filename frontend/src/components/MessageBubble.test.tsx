import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MessageBubble } from "./MessageBubble";
import type { MessageOut } from "../lib/types";

const inbound: MessageOut = { id: 1, direction: "inbound", type: "text", payload: { text: "Hi" }, ts: 1717660800 };
const outbound: MessageOut = { id: 2, direction: "outbound", type: "text", payload: { text: "Welcome" }, ts: 1717660830 };

describe("MessageBubble", () => {
  it("renders inbound text on the left", () => {
    render(<MessageBubble message={inbound} />);
    expect(screen.getByText("Hi").closest("[class*='inbound']")).not.toBeNull();
  });
  it("renders outbound text on the right", () => {
    render(<MessageBubble message={outbound} />);
    expect(screen.getByText("Welcome").closest("[class*='outbound']")).not.toBeNull();
  });
  it("shows older numbered menu lines as bullets (matching the customer view)", () => {
    const msg: MessageOut = {
      id: 4, direction: "outbound", type: "text",
      payload: { text: "2. Mutton Biryani — AED 35\n11. Chicken Biryani — AED 28" }, ts: 1717660830,
    };
    const { container } = render(<MessageBubble message={msg} />);
    const txt = container.textContent ?? "";
    expect(txt).toContain("• Mutton Biryani — AED 35");
    expect(txt).toContain("• Chicken Biryani — AED 28");
    expect(txt).not.toContain("2. Mutton");
    expect(txt).not.toContain("11. Chicken");
  });

  it("tags a voice note (type audio) with a mic marker and shows its transcript", () => {
    const msg: MessageOut = {
      id: 5, direction: "inbound", type: "audio",
      payload: { text: "two chicken biryani please", voice: true }, ts: 1717660830,
    };
    const { container } = render(<MessageBubble message={msg} />);
    expect(container.textContent).toContain("Voice");
    expect(container.textContent).toContain("two chicken biryani please");
  });

  it("does NOT tag a normal typed message with the voice marker", () => {
    const { container } = render(<MessageBubble message={inbound} />);
    expect(container.textContent).not.toContain("Voice");
  });

  it("renders WhatsApp *bold* and **bold** as bold, without the asterisks", () => {
    const msg: MessageOut = {
      id: 3, direction: "outbound", type: "text",
      payload: { text: "Here is our *Biryani* and **Curries**" }, ts: 1717660830,
    };
    const { container } = render(<MessageBubble message={msg} />);
    const bolds = Array.from(container.querySelectorAll("strong")).map((b) => b.textContent);
    expect(bolds).toContain("Biryani");
    expect(bolds).toContain("Curries");
    expect(container.textContent).not.toContain("*");
  });
});
