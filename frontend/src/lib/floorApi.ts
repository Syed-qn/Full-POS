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
  /** EVERY open bill on this table, newest first. Empty when the table is free. */
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
  /** "Guest 2", "Ahmed" — null when nobody labelled it. */
  guest_label?: string | null;
  guests?: number | null;
  waiter?: string | null;
  seated_since?: string | null;
};

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
