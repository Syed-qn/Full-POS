import Database from "better-sqlite3";

export function openLocalDb(filePath: string): Database.Database {
  return new Database(filePath);
}

export function initSchema(db: Database.Database): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS local_menu (
      dish_id INTEGER PRIMARY KEY,
      payload TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS local_orders (
      order_id INTEGER PRIMARY KEY,
      payload TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS pending_ops (
      id TEXT PRIMARY KEY,
      entity TEXT NOT NULL,
      entity_id INTEGER,
      op TEXT NOT NULL CHECK (op IN ('create', 'update')),
      method TEXT NOT NULL,
      path TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'synced', 'failed', 'conflict')),
      attempts INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS sync_state (
      entity TEXT PRIMARY KEY,
      last_synced_at TEXT,
      last_cursor TEXT
    );
  `);
}
