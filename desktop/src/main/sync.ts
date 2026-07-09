import type Database from "better-sqlite3";
import { readPendingOps, markOpStatus, type PendingOp } from "./pendingOps";
import { setNetworkOnline } from "./offlineStore";

interface DishPayload {
  id: number;
  updated_at: string;
  [key: string]: unknown;
}

interface OrderPayload {
  id: number;
  updated_at?: string;
  created_at?: string;
  [key: string]: unknown;
}

function getCursor(db: Database.Database, entity: string): string | null {
  const row = db
    .prepare(`SELECT last_cursor FROM sync_state WHERE entity = ?`)
    .get(entity) as { last_cursor: string } | undefined;
  return row?.last_cursor ?? null;
}

function setCursor(db: Database.Database, entity: string, cursor: string): void {
  db.prepare(
    `INSERT INTO sync_state (entity, last_synced_at, last_cursor)
     VALUES (@entity, @now, @cursor)
     ON CONFLICT(entity) DO UPDATE SET last_synced_at = @now, last_cursor = @cursor`,
  ).run({ entity, now: new Date().toISOString(), cursor });
}

export async function pullSync(
  db: Database.Database,
  apiBase: string,
  fetchImpl: typeof fetch,
  token: string,
): Promise<void> {
  await pullMenu(db, apiBase, fetchImpl, token);
  await pullOrders(db, apiBase, fetchImpl, token);
}

async function pullMenu(
  db: Database.Database,
  apiBase: string,
  fetchImpl: typeof fetch,
  token: string,
): Promise<void> {
  const cursor = getCursor(db, "menu");
  const url = new URL("/api/v1/menu/dishes", apiBase);
  if (cursor) url.searchParams.set("updated_since", cursor);

  let resp: Response;
  try {
    resp = await fetchImpl(url.toString(), {
      headers: { Authorization: `Bearer ${token}` },
    });
    setNetworkOnline(db, true);
  } catch (e) {
    setNetworkOnline(db, false, e instanceof Error ? e.message : "offline");
    return;
  }
  if (!resp.ok) return;

  const dishes = (await resp.json()) as DishPayload[];
  const upsert = db.prepare(
    `INSERT INTO local_menu (dish_id, payload, updated_at)
     VALUES (@dish_id, @payload, @updated_at)
     ON CONFLICT(dish_id) DO UPDATE SET payload = @payload, updated_at = @updated_at`,
  );
  let maxUpdatedAt = cursor;
  const tx = db.transaction((rows: DishPayload[]) => {
    for (const dish of rows) {
      upsert.run({
        dish_id: dish.id,
        payload: JSON.stringify(dish),
        updated_at: dish.updated_at,
      });
      if (!maxUpdatedAt || dish.updated_at > maxUpdatedAt) {
        maxUpdatedAt = dish.updated_at;
      }
    }
  });
  tx(dishes);

  if (maxUpdatedAt) setCursor(db, "menu", maxUpdatedAt);
}

async function pullOrders(
  db: Database.Database,
  apiBase: string,
  fetchImpl: typeof fetch,
  token: string,
): Promise<void> {
  const cursor = getCursor(db, "orders");
  const url = new URL("/api/v1/orders", apiBase);
  url.searchParams.set("limit", "100");
  if (cursor) url.searchParams.set("updated_since", cursor);

  let resp: Response;
  try {
    resp = await fetchImpl(url.toString(), {
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    return;
  }
  if (!resp.ok) return;

  const orders = (await resp.json()) as OrderPayload[];
  const upsert = db.prepare(
    `INSERT INTO local_orders (order_id, payload, updated_at, offline_created)
     VALUES (@order_id, @payload, @updated_at, 0)
     ON CONFLICT(order_id) DO UPDATE SET payload = @payload, updated_at = @updated_at`,
  );
  let maxCursor = cursor;
  const tx = db.transaction((rows: OrderPayload[]) => {
    for (const order of rows) {
      const updated = order.updated_at || order.created_at || new Date().toISOString();
      upsert.run({
        order_id: order.id,
        payload: JSON.stringify(order),
        updated_at: updated,
      });
      if (!maxCursor || updated > maxCursor) maxCursor = updated;
    }
  });
  tx(orders);
  if (maxCursor) setCursor(db, "orders", maxCursor);
}

export async function pushSync(
  db: Database.Database,
  apiBase: string,
  fetchImpl: typeof fetch,
  token: string,
): Promise<void> {
  const ops = readPendingOps(db).filter(
    (op) => op.status === "pending" || op.status === "failed",
  );
  for (const op of ops) {
    await pushOne(db, apiBase, fetchImpl, token, op);
  }
}

async function pushOne(
  db: Database.Database,
  apiBase: string,
  fetchImpl: typeof fetch,
  token: string,
  op: PendingOp,
): Promise<void> {
  try {
    const resp = await fetchImpl(new URL(op.path, apiBase).toString(), {
      method: op.method,
      headers: {
        Authorization: `Bearer ${token}`,
        "Idempotency-Key": op.id,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(op.payload),
    });
    setNetworkOnline(db, true);
    if (resp.status === 409) {
      markOpStatus(db, op.id, "conflict");
      return;
    }
    if (!resp.ok) {
      markOpStatus(db, op.id, "failed");
      return;
    }
    markOpStatus(db, op.id, "synced");
    // mark local offline payment applied
    if (op.path.includes("offline-payments")) {
      const pid = (op.payload as { client_payment_id?: string })?.client_payment_id;
      if (pid) {
        db.prepare(`UPDATE local_payments SET status = 'synced' WHERE client_payment_id = ?`).run(
          pid,
        );
      }
    }
  } catch (e) {
    setNetworkOnline(db, false, e instanceof Error ? e.message : "offline");
    markOpStatus(db, op.id, "failed");
  }
}
