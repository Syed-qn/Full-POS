import { describe, it, expect, afterEach } from "vitest";
import fs from "fs";
import os from "os";
import path from "path";
import { openLocalDb, initSchema } from "./db";
import {
  flushLocalPrintJobsAsync,
  getNetworkState,
  listCachedMenu,
  queueLocalPrint,
  queueOfflinePayment,
  resolveConflict,
  saveLocalOrder,
  setNetworkOnline,
  cacheMenuDish,
} from "./offlineStore";
import { FileSpoolPrinter } from "./native/printer";
import { enqueueOp, markOpStatus, readPendingOps } from "./pendingOps";

const tmpFiles: string[] = [];
const tmpDirs: string[] = [];

afterEach(() => {
  for (const f of tmpFiles.splice(0)) fs.rmSync(f, { force: true });
  for (const d of tmpDirs.splice(0)) fs.rmSync(d, { recursive: true, force: true });
});

describe("offlineStore", () => {
  it("caches menu and offline orders", () => {
    const file = path.join(os.tmpdir(), `off-${Date.now()}.sqlite`);
    tmpFiles.push(file);
    const db = openLocalDb(file);
    initSchema(db);
    cacheMenuDish(db, { id: 1, name: "Tea", updated_at: "2026-07-09T00:00:00Z" });
    expect(listCachedMenu(db)).toHaveLength(1);
    const id = saveLocalOrder(db, { items: [{ dish_id: 1, qty: 1 }] }, true);
    expect(id).toBeLessThan(0);
    db.close();
  });

  it("queues offline payment as pending op", () => {
    const file = path.join(os.tmpdir(), `offp-${Date.now()}.sqlite`);
    tmpFiles.push(file);
    const db = openLocalDb(file);
    initSchema(db);
    const pid = queueOfflinePayment(db, { amount_aed: "12.00", tender_type: "cash" });
    expect(pid).toBeTruthy();
    const ops = readPendingOps(db);
    expect(ops.some((o) => o.path.includes("offline-payments"))).toBe(true);
    db.close();
  });

  it("prints KOT/receipt to spool offline", async () => {
    const file = path.join(os.tmpdir(), `offpr-${Date.now()}.sqlite`);
    const spool = path.join(os.tmpdir(), `spool-${Date.now()}`);
    tmpFiles.push(file);
    tmpDirs.push(spool);
    const db = openLocalDb(file);
    initSchema(db);
    queueLocalPrint(db, "kot", "TEST A\n1x Tea");
    queueLocalPrint(db, "receipt", "TOTAL 12.00");
    const printer = new FileSpoolPrinter(spool);
    const result = await flushLocalPrintJobsAsync(db, printer);
    expect(result.printed).toBe(2);
    expect(fs.readdirSync(spool).length).toBe(2);
    db.close();
  });

  it("resolves conflicts retry/discard", () => {
    const file = path.join(os.tmpdir(), `offc-${Date.now()}.sqlite`);
    tmpFiles.push(file);
    const db = openLocalDb(file);
    initSchema(db);
    const id = enqueueOp(db, {
      entity: "orders",
      entityId: null,
      op: "create",
      method: "POST",
      path: "/api/v1/orders",
      payload: {},
    });
    markOpStatus(db, id, "conflict");
    resolveConflict(db, id, "retry");
    expect(readPendingOps(db).find((o) => o.id === id)?.status).toBe("pending");
    markOpStatus(db, id, "conflict");
    resolveConflict(db, id, "discard");
    expect(readPendingOps(db).find((o) => o.id === id)?.status).toBe("synced");
    db.close();
  });

  it("tracks network online/offline", () => {
    const file = path.join(os.tmpdir(), `offn-${Date.now()}.sqlite`);
    tmpFiles.push(file);
    const db = openLocalDb(file);
    initSchema(db);
    setNetworkOnline(db, false, "ECONNREFUSED");
    let st = getNetworkState(db);
    expect(st.online).toBe(false);
    expect(st.last_error).toBe("ECONNREFUSED");
    setNetworkOnline(db, true);
    st = getNetworkState(db);
    expect(st.online).toBe(true);
    db.close();
  });
});
