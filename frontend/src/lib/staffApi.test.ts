import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clockStaff, createStaff, getHours, getTipPool, listStaff } from "./staffApi";

describe("staffApi", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        if (String(url).endsWith("/clock")) {
          return Promise.resolve(
            new Response(JSON.stringify({ id: 1, type: "clock_in", at: "2026-07-08T10:00:00Z" }), { status: 200 }),
          );
        }
        if (String(url).includes("/hours")) {
          return Promise.resolve(
            new Response(JSON.stringify({ staff_id: 1, date: "2026-07-08", hours: 8, overtime_hours: 0 }), { status: 200 }),
          );
        }
        if (String(url).includes("/tip-pool")) {
          return Promise.resolve(new Response(JSON.stringify({ "1": "12.50" }), { status: 200 }));
        }
        if (init?.method === "POST") {
          return Promise.resolve(
            new Response(JSON.stringify({ id: 1, name: "Ahmed", phone: null, role: "staff" }), { status: 201 }),
          );
        }
        return Promise.resolve(
          new Response(JSON.stringify([{ id: 1, name: "Ahmed", phone: null, role: "staff" }]), { status: 200 }),
        );
      }),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("lists staff", async () => {
    const rows = await listStaff();
    expect(rows).toHaveLength(1);
    expect(rows[0].name).toBe("Ahmed");
  });

  it("creates a staff member", async () => {
    const created = await createStaff({ name: "Ahmed", pin: "1234", role: "staff" });
    expect(created.id).toBe(1);
  });

  it("clocks in", async () => {
    const event = await clockStaff(1, "clock_in");
    expect(event.type).toBe("clock_in");
  });

  it("gets hours with overtime", async () => {
    const hours = await getHours(1, "2026-07-08");
    expect(hours.overtime_hours).toBe(0);
  });

  it("gets tip pool as a map", async () => {
    const pool = await getTipPool("2026-07-01", "2026-07-08");
    expect(pool["1"]).toBe("12.50");
  });
});
