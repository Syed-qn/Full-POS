import { describe, it, expect, vi, beforeEach } from "vitest";
import { openLocalDb, initSchema } from "./db";
import { pullSync, pushSync } from "./sync";
import { enqueueOp, readPendingOps } from "./pendingOps";
import type Database from "better-sqlite3";

let db: Database.Database;

beforeEach(() => {
  db = openLocalDb(":memory:");
  initSchema(db);
});

describe("pullSync", () => {
  it("upserts fetched dishes into local_menu and advances the cursor", async () => {
    const fakeFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        { id: 42, name: "Chicken Biryani", updated_at: "2026-07-07T10:00:00Z" },
      ],
    });

    await pullSync(db, "http://api.test", fakeFetch as unknown as typeof fetch, "tok");

    const rows = db.prepare("SELECT * FROM local_menu").all() as Array<{
      dish_id: number;
      payload: string;
    }>;
    expect(rows).toHaveLength(1);
    expect(JSON.parse(rows[0].payload).name).toBe("Chicken Biryani");

    const state = db
      .prepare("SELECT * FROM sync_state WHERE entity = 'menu'")
      .get() as { last_cursor: string };
    expect(state.last_cursor).toBe("2026-07-07T10:00:00Z");

    expect(fakeFetch).toHaveBeenCalledWith(
      "http://api.test/api/v1/menu/dishes",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer tok" }),
      }),
    );
  });

  it("does not throw when offline (fetch rejects)", async () => {
    const fakeFetch = vi.fn().mockRejectedValue(new Error("network down"));
    await expect(
      pullSync(db, "http://api.test", fakeFetch as unknown as typeof fetch, "tok"),
    ).resolves.toBeUndefined();
  });
});

describe("pushSync", () => {
  it("replays a pending op with an Idempotency-Key header and marks it synced", async () => {
    const id = enqueueOp(db, {
      entity: "orders",
      entityId: 7,
      op: "update",
      method: "PATCH",
      path: "/api/v1/orders/7/status",
      payload: { status: "preparing" },
    });
    const fakeFetch = vi.fn().mockResolvedValue({ ok: true, status: 200 });

    await pushSync(db, "http://api.test", fakeFetch as unknown as typeof fetch, "tok");

    expect(fakeFetch).toHaveBeenCalledWith(
      "http://api.test/api/v1/orders/7/status",
      expect.objectContaining({
        method: "PATCH",
        headers: expect.objectContaining({
          Authorization: "Bearer tok",
          "Idempotency-Key": id,
          "Content-Type": "application/json",
        }),
      }),
    );
    const rows = readPendingOps(db);
    expect(rows.find((r) => r.id === id)?.status).toBe("synced");
  });

  it("marks an op conflict (not retried) on a 409 response", async () => {
    const id = enqueueOp(db, {
      entity: "orders",
      entityId: 8,
      op: "update",
      method: "PATCH",
      path: "/api/v1/orders/8/status",
      payload: { status: "preparing" },
    });
    const fakeFetch = vi.fn().mockResolvedValue({ ok: false, status: 409 });

    await pushSync(db, "http://api.test", fakeFetch as unknown as typeof fetch, "tok");

    const rows = readPendingOps(db);
    expect(rows.find((r) => r.id === id)?.status).toBe("conflict");
  });

  it("retries a failed op on the next pushSync call (not stranded forever)", async () => {
    const id = enqueueOp(db, {
      entity: "orders",
      entityId: 9,
      op: "update",
      method: "PATCH",
      path: "/api/v1/orders/9/status",
      payload: { status: "preparing" },
    });
    const flakyFetch = vi
      .fn()
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce({ ok: true, status: 200 });

    await pushSync(db, "http://api.test", flakyFetch as unknown as typeof fetch, "tok");
    expect(readPendingOps(db).find((r) => r.id === id)?.status).toBe("failed");

    await pushSync(db, "http://api.test", flakyFetch as unknown as typeof fetch, "tok");
    expect(readPendingOps(db).find((r) => r.id === id)?.status).toBe("synced");
    expect(flakyFetch).toHaveBeenCalledTimes(2);
  });
});
