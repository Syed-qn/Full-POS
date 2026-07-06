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
