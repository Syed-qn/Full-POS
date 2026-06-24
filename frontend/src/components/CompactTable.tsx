import type { ReactNode } from "react";
import s from "./CompactTable.module.css";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
}

export function CompactTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  emptyText = "No rows",
  loading = false,
  skeletonRows = 8,
  rowClassName,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  onRowClick?: (row: T) => void;
  emptyText?: string;
  // While true, show shimmer placeholder rows instead of data/empty state.
  loading?: boolean;
  skeletonRows?: number;
  // Optional extra class per row (e.g. to highlight batched orders).
  rowClassName?: (row: T) => string | undefined;
}) {
  if (loading) {
    return (
      <table className={s.table} aria-busy="true" aria-label="Loading rows">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className="label-upper">
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: skeletonRows }).map((_, r) => (
            <tr key={r}>
              {columns.map((c) => (
                <td key={c.key}>
                  <span className={s.sk} style={{ width: `${SK_WIDTHS[r % SK_WIDTHS.length]}%` }} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (rows.length === 0) {
    return <div className={s.empty}>{emptyText}</div>;
  }
  return (
    <table className={s.table}>
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c.key} className="label-upper">
              {c.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={rowKey(row)}
            onClick={() => onRowClick?.(row)}
            className={`${onRowClick ? s.clickable : ""} ${rowClassName?.(row) ?? ""}`.trim()}
          >
            {columns.map((c) => (
              <td key={c.key}>{c.render(row)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// Varied bar widths so skeleton rows look organic rather than a rigid grid.
const SK_WIDTHS = [70, 45, 85, 55, 60, 40, 75];
