import { describe, it, expect, afterEach } from "vitest";
import fs from "fs";
import os from "os";
import path from "path";
import { openLocalDb, initSchema } from "./db";

const tmpFiles: string[] = [];

afterEach(() => {
  for (const f of tmpFiles.splice(0)) fs.rmSync(f, { force: true });
});

describe("initSchema", () => {
  it("creates local_menu, local_orders, pending_ops, sync_state tables", () => {
    const file = path.join(os.tmpdir(), `posdb-${Date.now()}.sqlite`);
    tmpFiles.push(file);
    const db = openLocalDb(file);
    initSchema(db);
    const tables = db
      .prepare("SELECT name FROM sqlite_master WHERE type='table'")
      .all()
      .map((r: { name: string }) => r.name);
    expect(tables).toEqual(
      expect.arrayContaining([
        "local_menu",
        "local_orders",
        "pending_ops",
        "sync_state",
      ]),
    );
    db.close();
  });
});
