import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CompactTable, type Column } from "../components/CompactTable";
import { listCustomers } from "../lib/customerApi";
import type { CustomerDetailOut } from "../lib/types";
import s from "./OrdersScreen.module.css";

export function CustomersScreen() {
  const [customers, setCustomers] = useState<CustomerDetailOut[]>([]);
  const [search, setSearch] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    listCustomers().then((r) => setCustomers(r.items));
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return customers;
    return customers.filter(
      (c) =>
        (c.name ?? "").toLowerCase().includes(q) ||
        c.phone.includes(q),
    );
  }, [customers, search]);

  const columns: Column<CustomerDetailOut>[] = [
    { key: "name", header: "Name", render: (c) => c.name ?? "—" },
    { key: "phone", header: "Phone", render: (c) => c.phone },
    { key: "orders", header: "Orders", render: (c) => String(c.total_orders) },
    { key: "spend", header: "Spend", render: (c) => `AED ${c.total_spend}` },
    { key: "opt", header: "Marketing", render: (c) => c.marketing_opted_in ? "Opted In" : "Opted Out" },
  ];

  return (
    <div className={s.screen}>
      <div className={s.filterBar}>
        <input
          className={s.search}
          placeholder="Search name / phone"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <CompactTable<CustomerDetailOut>
        columns={columns}
        rows={filtered}
        rowKey={(c) => c.id}
        onRowClick={(c) => navigate(`/customers/${c.id}`)}
        emptyText="No customers found"
      />
    </div>
  );
}
