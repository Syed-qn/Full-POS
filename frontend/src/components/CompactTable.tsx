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
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  onRowClick?: (row: T) => void;
  emptyText?: string;
}) {
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
          <tr key={rowKey(row)} onClick={() => onRowClick?.(row)} className={onRowClick ? s.clickable : ""}>
            {columns.map((c) => (
              <td key={c.key}>{c.render(row)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
