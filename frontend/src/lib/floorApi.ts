import { apiClient } from "./apiClient";

/** A dining table as returned by GET /api/v1/tables (live floor enrichment
 *  included). pos_x/pos_y are FLOAT GRID units, not pixels — every floor
 *  surface multiplies them by a unit derived from its own canvas width. */
export type ApiTable = {
  id: number;
  label: string;
  seats: number;
  status: string;
  pos_x: number;
  pos_y: number;
  /** Degrees clockwise — how the table is turned in the room. */
  rotation?: number;
  qr_token?: string | null;
  /** The NEWEST open bill — single-valued for every reader that predates splits. */
  order_id?: number | null;
  order_total_aed?: string | null;
  /** EVERY open bill on this table, OLDEST FIRST — so index 0 is "Bill 1", the
   *  party that sat down first. Empty when the table is free. */
  bills?: TableBill[];
  bill_count?: number;
  guests?: number | null;
  waiter?: string | null;
  merged_count?: number;
  seated_since?: string | null;
};

/** One open bill on a table. A table can hold several at once — two parties
 *  sharing it, each paying for their own food. */
export type TableBill = {
  order_id: number;
  order_number?: string | null;
  daily_token?: number | null;
  total_aed: string;
  /** A name a HUMAN gave this bill ("Ahmed"). Normally null — the "Bill N" a
   *  cashier reads is a POSITION in this list, never a stored value. */
  guest_label?: string | null;
  guests?: number | null;
  waiter?: string | null;
  seated_since?: string | null;
};

/** A stored label that is really a machine guess at a position: an earlier build
 *  STAMPED "Bill 2" onto the order at create time from a stale bill count, which
 *  produced duplicates ("Bill 3 · Bill 2 · Bill 3" on one table) and stayed wrong
 *  the moment an earlier bill was paid. Those rows are still in the database, so
 *  they are ignored rather than migrated — they were never human names. */
const AUTO_LABEL = /^bill\s*\d+$/i;

/** What to call a bill on screen: the name a human gave it, else its POSITION in
 *  the table's oldest-first list. Shared so the floor dialog and the till's
 *  switcher can never disagree about which bill is "Bill 2". */
export function billName(bill: TableBill, index: number): string {
  const given = bill.guest_label?.trim();
  if (given && !AUTO_LABEL.test(given)) return given;
  return `Bill ${index + 1}`;
}

/** Restaurant-wide floor layout. Today: where the entrance marker sits.
 *  Null coordinates mean "never placed" — surfaces fall back to bottom-centre. */
export type FloorLayout = {
  entrance_x: number | null;
  entrance_y: number | null;
  /** Degrees clockwise — the door can face any wall. */
  entrance_rot?: number;
};

export function listTables(): Promise<ApiTable[]> {
  return apiClient.get<ApiTable[]>("/api/v1/tables");
}

/** Seat ONE party across several tables on a single invoice.
 *  `primaryId` is the table that keeps the bill; every id in `tableIds` joins to
 *  it and stays occupied. `intoOrderId` is required when the primary carries more
 *  than one open bill — the server refuses to guess which party the joined guests
 *  belong to. Returns the whole refreshed floor. */
export function joinTables(
  primaryId: number,
  tableIds: number[],
  intoOrderId?: number | null,
): Promise<ApiTable[]> {
  return apiClient.post<ApiTable[]>(`/api/v1/tables/${primaryId}/join`, {
    table_ids: tableIds,
    ...(intoOrderId ? { into_order_id: intoOrderId } : {}),
  });
}

/** Detach one table from its group. The invoice stays with the primary. */
export function unjoinTable(tableId: number): Promise<ApiTable[]> {
  return apiClient.post<ApiTable[]>(`/api/v1/tables/${tableId}/unjoin`, {});
}

export function fetchFloorLayout(): Promise<FloorLayout> {
  return apiClient.get<FloorLayout>("/api/v1/tables/layout");
}

export function saveFloorLayout(
  entrance_x: number,
  entrance_y: number,
  entrance_rot = 0,
): Promise<FloorLayout> {
  return apiClient.put<FloorLayout>("/api/v1/tables/layout", {
    entrance_x,
    entrance_y,
    entrance_rot,
  });
}

export function createTable(body: {
  label: string;
  seats: number;
  pos_x: number;
  pos_y: number;
}): Promise<ApiTable> {
  return apiClient.post<ApiTable>("/api/v1/tables", body);
}

export function updateTable(
  id: number,
  body: Partial<{ label: string; seats: number; pos_x: number; pos_y: number; rotation: number }>,
): Promise<ApiTable> {
  return apiClient.patch<ApiTable>(`/api/v1/tables/${id}`, body);
}

/** Soft delete — the server archives the table so past orders keep their FK. */
export function deleteTable(id: number): Promise<void> {
  return apiClient.delete<void>(`/api/v1/tables/${id}`);
}
