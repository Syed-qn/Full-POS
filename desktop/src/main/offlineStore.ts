/** Local offline order / payment / print helpers (Category 12). */
import type Database from "better-sqlite3";
import { randomUUID } from "crypto";
import { enqueueOp } from "./pendingOps";
import type { PrinterPort } from "./native/printer";

export function cacheMenuDish(
  db: Database.Database,
  dish: { id: number; updated_at: string; [k: string]: unknown },
): void {
  db.prepare(
    `INSERT INTO local_menu (dish_id, payload, updated_at)
     VALUES (@dish_id, @payload, @updated_at)
     ON CONFLICT(dish_id) DO UPDATE SET payload = @payload, updated_at = @updated_at`,
  ).run({
    dish_id: dish.id,
    payload: JSON.stringify(dish),
    updated_at: dish.updated_at,
  });
}

export function listCachedMenu(db: Database.Database): unknown[] {
  const rows = db.prepare(`SELECT payload FROM local_menu ORDER BY dish_id`).all() as Array<{
    payload: string;
  }>;
  return rows.map((r) => JSON.parse(r.payload));
}

export function saveLocalOrder(
  db: Database.Database,
  order: { id?: number; order_number?: string; [k: string]: unknown },
  offlineCreated = false,
): number {
  const orderId =
    typeof order.id === "number" && order.id > 0
      ? order.id
      : -Math.floor(Math.random() * 1_000_000_000);
  const payload = { ...order, id: orderId, offline: offlineCreated };
  db.prepare(
    `INSERT INTO local_orders (order_id, payload, updated_at, offline_created)
     VALUES (@order_id, @payload, @updated_at, @offline)
     ON CONFLICT(order_id) DO UPDATE SET payload = @payload, updated_at = @updated_at`,
  ).run({
    order_id: orderId,
    payload: JSON.stringify(payload),
    updated_at: new Date().toISOString(),
    offline: offlineCreated ? 1 : 0,
  });
  return orderId;
}

export function listLocalOrders(db: Database.Database): unknown[] {
  const rows = db
    .prepare(`SELECT payload FROM local_orders ORDER BY updated_at DESC`)
    .all() as Array<{ payload: string }>;
  return rows.map((r) => JSON.parse(r.payload));
}

export function queueOfflinePayment(
  db: Database.Database,
  payment: {
    client_payment_id?: string;
    amount_aed: string;
    tender_type?: string;
    order_id?: number;
  },
): string {
  const id = payment.client_payment_id || randomUUID();
  const payload = { ...payment, client_payment_id: id };
  db.prepare(
    `INSERT INTO local_payments (client_payment_id, payload, status, created_at)
     VALUES (@id, @payload, 'queued', @created_at)
     ON CONFLICT(client_payment_id) DO NOTHING`,
  ).run({
    id,
    payload: JSON.stringify(payload),
    created_at: new Date().toISOString(),
  });
  enqueueOp(db, {
    entity: "offline_payment",
    entityId: null,
    op: "create",
    method: "POST",
    path: "/api/v1/reliability/offline-payments",
    payload,
  });
  return id;
}

export function queueLocalPrint(
  db: Database.Database,
  kind: "kot" | "receipt",
  payload: string,
): string {
  const id = randomUUID();
  db.prepare(
    `INSERT INTO local_print_jobs (id, kind, payload, status, created_at)
     VALUES (@id, @kind, @payload, 'pending', @created_at)`,
  ).run({
    id,
    kind,
    payload,
    created_at: new Date().toISOString(),
  });
  return id;
}

export function flushLocalPrintJobs(
  db: Database.Database,
  printer: PrinterPort,
): { printed: number; failed: number } {
  const rows = db
    .prepare(`SELECT id, kind, payload FROM local_print_jobs WHERE status = 'pending'`)
    .all() as Array<{ id: string; kind: string; payload: string }>;
  let printed = 0;
  let failed = 0;
  for (const row of rows) {
    try {
      // sync print via deasync not needed — FileSpoolPrinter is sync under the hood
      // but interface is async; call and ignore promise chain via devalue pattern
      void printer
        .print({
          stationId: 0,
          payload: row.payload,
          kind: row.kind as "kot" | "receipt",
        })
        .then(() => {
          db.prepare(
            `UPDATE local_print_jobs SET status = 'printed', printed_at = @at WHERE id = @id`,
          ).run({ id: row.id, at: new Date().toISOString() });
        })
        .catch(() => {
          db.prepare(`UPDATE local_print_jobs SET status = 'failed' WHERE id = @id`).run({
            id: row.id,
          });
        });
      printed += 1;
    } catch {
      failed += 1;
      db.prepare(`UPDATE local_print_jobs SET status = 'failed' WHERE id = @id`).run({
        id: row.id,
      });
    }
  }
  return { printed, failed };
}

/** Synchronous flush for tests / offline path (awaits not available in sync IPC). */
export async function flushLocalPrintJobsAsync(
  db: Database.Database,
  printer: PrinterPort,
): Promise<{ printed: number; failed: number }> {
  const rows = db
    .prepare(`SELECT id, kind, payload FROM local_print_jobs WHERE status = 'pending'`)
    .all() as Array<{ id: string; kind: string; payload: string }>;
  let printed = 0;
  let failed = 0;
  for (const row of rows) {
    try {
      await printer.print({
        stationId: 0,
        payload: row.payload,
        kind: row.kind as "kot" | "receipt",
      });
      db.prepare(
        `UPDATE local_print_jobs SET status = 'printed', printed_at = @at WHERE id = @id`,
      ).run({ id: row.id, at: new Date().toISOString() });
      printed += 1;
    } catch {
      db.prepare(`UPDATE local_print_jobs SET status = 'failed' WHERE id = @id`).run({
        id: row.id,
      });
      failed += 1;
    }
  }
  return { printed, failed };
}

export function setNetworkOnline(db: Database.Database, online: boolean, error?: string): void {
  db.prepare(
    `UPDATE network_state SET
      online = @online,
      last_online_at = CASE WHEN @online = 1 THEN @now ELSE last_online_at END,
      last_offline_at = CASE WHEN @online = 0 THEN @now ELSE last_offline_at END,
      last_error = @error
     WHERE id = 1`,
  ).run({
    online: online ? 1 : 0,
    now: new Date().toISOString(),
    error: error ?? null,
  });
}

export function getNetworkState(db: Database.Database): {
  online: boolean;
  last_online_at: string | null;
  last_offline_at: string | null;
  last_error: string | null;
} {
  const row = db.prepare(`SELECT * FROM network_state WHERE id = 1`).get() as
    | {
        online: number;
        last_online_at: string | null;
        last_offline_at: string | null;
        last_error: string | null;
      }
    | undefined;
  return {
    online: Boolean(row?.online ?? 1),
    last_online_at: row?.last_online_at ?? null,
    last_offline_at: row?.last_offline_at ?? null,
    last_error: row?.last_error ?? null,
  };
}

export function resolveConflict(
  db: Database.Database,
  id: string,
  action: "retry" | "discard",
): void {
  if (action === "discard") {
    db.prepare(`UPDATE pending_ops SET status = 'synced' WHERE id = ? AND status = 'conflict'`).run(
      id,
    );
  } else {
    db.prepare(
      `UPDATE pending_ops SET status = 'pending', attempts = 0 WHERE id = ? AND status = 'conflict'`,
    ).run(id);
  }
}
