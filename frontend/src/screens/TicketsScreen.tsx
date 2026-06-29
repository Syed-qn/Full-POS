import { useEffect, useMemo, useState } from "react";
import { PageHeader } from "../components/PageHeader";
import { TicketDetailDrawer } from "../components/TicketDetailDrawer";
import { listTickets } from "../lib/ticketsApi";
import type { Ticket } from "../lib/types";
import s from "./TicketsScreen.module.css";

const STATUS_ORDER: Record<Ticket["status"], number> = {
  open: 0,
  in_progress: 1,
  resolved: 2,
};

export function TicketsScreen() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [selected, setSelected] = useState<Ticket | null>(null);
  const [phone, setPhone] = useState("");

  function reload() {
    listTickets(undefined, phone.trim() || undefined)
      .then(setTickets)
      .catch(() => setTickets([]))
      .finally(() => setLoaded(true));
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const ordered = useMemo(
    () =>
      [...tickets].sort(
        (a, b) =>
          STATUS_ORDER[a.status] - STATUS_ORDER[b.status] ||
          b.id - a.id,
      ),
    [tickets],
  );

  function onResolved() {
    setSelected(null);
    reload();
  }

  return (
    <div className={s.root}>
      <PageHeader
        title="Complaints"
        subtitle="Customer complaint tickets, wallet refunds & replacements"
      />

      <form
        className={s.search}
        onSubmit={(e) => {
          e.preventDefault();
          setLoaded(false);
          reload();
        }}
      >
        <input
          type="search"
          placeholder="Search by phone number"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          aria-label="search complaints by phone"
        />
        <button type="submit">Search</button>
      </form>

      {!loaded && <TicketsSkeleton />}

      {loaded && ordered.length === 0 && (
        <div className={s.empty}>No open complaints — you're all caught up.</div>
      )}

      {loaded && ordered.length > 0 && (
        <div className={s.list}>
          {ordered.map((t) => (
            <button
              key={t.id}
              type="button"
              className={s.row}
              onClick={() => setSelected(t)}
            >
              <span className={s.id}>#{t.id}</span>
              <span className={s.msg}>{t.source_message ?? "(no message)"}</span>
              <span className={s.meta}>
                {t.customer_name ?? t.customer_phone ?? "customer"}
                {t.customer_phone ? ` · ${t.customer_phone}` : ""}
                {" · "}order {t.order_id ? `#${t.order_id}` : "—"}
              </span>
              <span className={`${s.status} ${s[t.status]}`}>{t.status.replace("_", " ")}</span>
            </button>
          ))}
        </div>
      )}

      {selected && (
        <TicketDetailDrawer ticket={selected} onResolved={onResolved} />
      )}
    </div>
  );
}

function TicketsSkeleton() {
  return (
    <div className={s.list} aria-busy="true" aria-label="Loading complaints">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className={s.skRow}>
          <span className={`${s.sk} ${s.skLine}`} style={{ width: "12%" }} />
          <span className={`${s.sk} ${s.skLine}`} style={{ width: "55%" }} />
          <span className={`${s.sk} ${s.skLine}`} style={{ width: "18%" }} />
        </div>
      ))}
    </div>
  );
}
