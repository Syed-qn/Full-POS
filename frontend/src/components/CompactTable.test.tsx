import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CompactTable } from "./CompactTable";

interface Row { id: number; name: string; }
const cols = [
  { key: "id", header: "#", render: (r: Row) => `#${r.id}` },
  { key: "name", header: "Name", render: (r: Row) => r.name },
];

describe("CompactTable", () => {
  it("renders headers and rows", () => {
    render(<CompactTable<Row> columns={cols} rows={[{ id: 1, name: "Ali" }]} rowKey={(r) => r.id} />);
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("Ali")).toBeInTheDocument();
  });

  it("renders empty state when no rows", () => {
    render(<CompactTable<Row> columns={cols} rows={[]} rowKey={(r) => r.id} emptyText="Nothing here" />);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
  });
});
