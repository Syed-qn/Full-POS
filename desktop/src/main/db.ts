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
      updated_at TEXT NOT NULL,
      offline_created INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS local_payments (
      client_payment_id TEXT PRIMARY KEY,
      payload TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'queued',
      created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS local_print_jobs (
      id TEXT PRIMARY KEY,
      kind TEXT NOT NULL CHECK (kind IN ('kot', 'receipt')),
      payload TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      created_at TEXT NOT NULL,
      printed_at TEXT
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

    CREATE TABLE IF NOT EXISTS network_state (
      id INTEGER PRIMARY KEY CHECK (id = 1),
      online INTEGER NOT NULL DEFAULT 1,
      last_online_at TEXT,
      last_offline_at TEXT,
      last_error TEXT
    );

    INSERT OR IGNORE INTO network_state (id, online) VALUES (1, 1);
  `);
}
