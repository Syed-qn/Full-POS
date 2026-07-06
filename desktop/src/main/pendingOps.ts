import type Database from "better-sqlite3";
import { randomUUID } from "crypto";

export type PendingOpStatus = "pending" | "synced" | "failed" | "conflict";

export interface NewPendingOp {
  entity: string;
  entityId: number | null;
  op: "create" | "update";
  method: string;
  path: string;
  payload: unknown;
}

export interface PendingOp extends NewPendingOp {
  id: string;
  createdAt: string;
  status: PendingOpStatus;
  attempts: number;
}

export function enqueueOp(db: Database.Database, newOp: NewPendingOp): string {
  const id = randomUUID();
  db.prepare(
    `INSERT INTO pending_ops
      (id, entity, entity_id, op, method, path, payload, created_at, status, attempts)
     VALUES (@id, @entity, @entityId, @op, @method, @path, @payload, @createdAt, 'pending', 0)`,
  ).run({
    id,
    entity: newOp.entity,
    entityId: newOp.entityId,
    op: newOp.op,
    method: newOp.method,
    path: newOp.path,
    payload: JSON.stringify(newOp.payload),
    createdAt: new Date().toISOString(),
  });
  return id;
}

export function readPendingOps(db: Database.Database): PendingOp[] {
  const rows = db
    .prepare(`SELECT * FROM pending_ops ORDER BY created_at ASC`)
    .all() as Array<{
    id: string;
    entity: string;
    entity_id: number | null;
    op: "create" | "update";
    method: string;
    path: string;
    payload: string;
    created_at: string;
    status: PendingOpStatus;
    attempts: number;
  }>;
  return rows.map((r) => ({
    id: r.id,
    entity: r.entity,
    entityId: r.entity_id,
    op: r.op,
    method: r.method,
    path: r.path,
    payload: JSON.parse(r.payload),
    createdAt: r.created_at,
    status: r.status,
    attempts: r.attempts,
  }));
}

export function markOpStatus(
  db: Database.Database,
  id: string,
  status: PendingOpStatus,
): void {
  db.prepare(`UPDATE pending_ops SET status = @status WHERE id = @id`).run({
    id,
    status,
  });
}
