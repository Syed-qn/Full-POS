import { describe, it, expect, beforeEach } from "vitest";
import { openLocalDb, initSchema } from "./db";
import { enqueueOp, readPendingOps, markOpStatus } from "./pendingOps";
import type Database from "better-sqlite3";

let db: Database.Database;

beforeEach(() => {
  db = openLocalDb(":memory:");
  initSchema(db);
});

describe("pendingOps", () => {
  it("enqueues and reads back in FIFO order", () => {
    const id1 = enqueueOp(db, {
      entity: "orders",
      entityId: 1,
      op: "update",
      method: "PATCH",
      path: "/api/v1/orders/1/status",
      payload: { status: "preparing" },
    });
    const id2 = enqueueOp(db, {
      entity: "orders",
      entityId: 2,
      op: "create",
      method: "POST",
      path: "/api/v1/orders",
      payload: { customer_id: 5 },
    });
    const rows = readPendingOps(db);
    expect(rows.map((r) => r.id)).toEqual([id1, id2]);
    expect(rows[0].status).toBe("pending");
  });

  it("preserves insertion order when created_at timestamps collide", () => {
    const originalNow = Date.now;
    Date.now = () => 1_700_000_000_000; // freeze the clock: identical ISO timestamps
    let id1: string;
    let id2: string;
    let id3: string;
    try {
      id1 = enqueueOp(db, {
        entity: "orders",
        entityId: 1,
        op: "update",
        method: "PATCH",
        path: "/api/v1/orders/1/status",
        payload: {},
      });
      id2 = enqueueOp(db, {
        entity: "orders",
        entityId: 2,
        op: "update",
        method: "PATCH",
        path: "/api/v1/orders/2/status",
        payload: {},
      });
      id3 = enqueueOp(db, {
        entity: "orders",
        entityId: 3,
        op: "update",
        method: "PATCH",
        path: "/api/v1/orders/3/status",
        payload: {},
      });
    } finally {
      Date.now = originalNow;
    }
    const rows = readPendingOps(db);
    expect(rows.map((r) => r.createdAt)).toEqual([
      rows[0].createdAt,
      rows[0].createdAt,
      rows[0].createdAt,
    ]); // confirms the timestamps really did collide
    expect(rows.map((r) => r.id)).toEqual([id1, id2, id3]); // insertion order preserved via rowid tiebreak
  });

  it("marks an op's status", () => {
    const id = enqueueOp(db, {
      entity: "orders",
      entityId: 1,
      op: "update",
      method: "PATCH",
      path: "/api/v1/orders/1/status",
      payload: {},
    });
    markOpStatus(db, id, "synced");
    const rows = readPendingOps(db);
    expect(rows.find((r) => r.id === id)?.status).toBe("synced");
  });
});
