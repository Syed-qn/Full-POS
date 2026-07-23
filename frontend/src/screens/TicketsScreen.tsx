import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { TicketDetailDrawer } from "../components/TicketDetailDrawer";
import { useTicketsQuery } from "../lib/queries/dashboard";
import type { Ticket } from "../lib/types";
import s from "./TicketsScreen.module.css";

const STATUS_ORDER: Record<Ticket["status"], number> = {
  open: 0,
  in_progress: 1,
  resolved: 2,
};

export function TicketsScreen() {
  const queryClient = useQueryClient();
  const [phoneInput, setPhoneInput] = useState("");
  const [phoneFilter, setPhoneFilter] = useState("");
  const [selected, setSelected] = useState<Ticket | null>(null);

  const { data: tickets = [], isPending } = useTicketsQuery(phoneFilter);

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
    void queryClient.invalidateQueries({ queryKey: ["tickets", "list"] });
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
          setPhoneFilter(phoneInput.trim());
        }}
      >
        {/* No button — typing filters automatically (Enter still works). */}
        <input
          type="search"
          placeholder="Search by phone number"
          value={phoneInput}
          onChange={(e) => {
            const v = e.target.value;
            setPhoneInput(v);
            setPhoneFilter(v.trim());
          }}
          aria-label="search complaints by phone"
        />
      </form>

      {isPending && <TicketsSkeleton />}

      {!isPending && ordered.length === 0 && (
        <EmptyState
          title="No open complaints"
          description={
            phoneFilter
              ? "No tickets match this phone. Clear search to see the full queue."
              : "You're all caught up. New complaints open in a drawer for resolution."
          }
        />
      )}

      {!isPending && ordered.length > 0 && (
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
                {" · "}order {t.order_id ? `#${t.order_id}` : "none"}
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