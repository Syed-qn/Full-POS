import { describe, expect, it } from "vitest";
import { ticketUrgency } from "./kdsApi";

describe("ticketUrgency", () => {
  const now = new Date("2026-07-07T12:00:00Z");

  it("returns ok for a fresh ticket", () => {
    const createdAt = new Date("2026-07-07T11:58:00Z").toISOString(); // 2 min old
    expect(ticketUrgency(createdAt, now)).toBe("ok");
  });

  it("returns warning at 8+ minutes", () => {
    const createdAt = new Date("2026-07-07T11:51:00Z").toISOString(); // 9 min old
    expect(ticketUrgency(createdAt, now)).toBe("warning");
  });

  it("returns late at 15+ minutes", () => {
    const createdAt = new Date("2026-07-07T11:40:00Z").toISOString(); // 20 min old
    expect(ticketUrgency(createdAt, now)).toBe("late");
  });

  it("boundary: exactly 8 minutes is warning, exactly 15 is late", () => {
    expect(ticketUrgency(new Date("2026-07-07T11:52:00Z").toISOString(), now)).toBe("warning");
    expect(ticketUrgency(new Date("2026-07-07T11:45:00Z").toISOString(), now)).toBe("late");
  });
});
