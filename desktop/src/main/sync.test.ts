import { describe, it, expect, vi, beforeEach } from "vitest";
import { openLocalDb, initSchema } from "./db";
import { pullSync } from "./sync";
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
});
