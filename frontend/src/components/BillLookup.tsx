import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { fetchOrders } from "../lib/ordersApi";
import type { OrderOut } from "../lib/types";
import s from "./BillLookup.module.css";

/** "24 Jul 2026" — compact date to tell same-token bills apart in the picker. */
function fmtDate(iso?: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/** A full bill number has a dash (R4-0030); a bare token is just digits. */
function looksLikeOrderNumber(term: string): boolean {
  return /-/.test(term);
}

/**
 * Bill lookup, IN the top bar: a box and one button.
 *
 * Look a bill up by full bill number OR queue token and it opens on the till —
 * items and totals in the left column, Print Bill live, New Bill to clear. A
 * paid bill arrives locked to a reprint (see tabSettled in WaiterOrderScreen).
 *
 * Deliberately not a dialog. It was one, and it rendered the bill a second time
 * as a receipt slip inside itself: the cashier could see the bill but not act on
 * it, two renderings of one bill could disagree, and finding a bill cost two
 * clicks and a modal over the till they were about to use.
 *
 * Full order number (has a dash) → exact bill. A bare number is a queue token,
 * which resets each Dubai MONTH, so the same number recurs across months; we
 * search all history and, when several bills share it, drop a date-labelled
 * picker under the box — anchored to the input, not a modal, so the till stays
 * visible behind it.
 */
export function BillLookup() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  /**
   * Seeded from ?bill= so the box still shows which bill is on screen.
   *
   * Opening a bill remounts the till (the route is keyed on the order id), which
   * wipes component state — so the number the cashier had just typed vanished
   * and the box went blank over a bill it had loaded. Carrying it in the URL
   * rather than in a ref or sessionStorage means it also survives a refresh and
   * the box never disagrees with the bill in the left column.
   */
  const [term, setTerm] = useState(() => params.get("bill") ?? "");
  const [loading, setLoading] = useState(false);
  const [matches, setMatches] = useState<OrderOut[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  /**
   * Hand the bill to the till. ?order= is the same door the order list's "Add
   * Item" uses, so no new loading path had to be invented.
   *
   * A dine-in bill goes back through its TABLE, because that is where a dine-in
   * tab hangs — ?order= only drives the take-away / delivery till. A dine-in row
   * with no table_id (legacy, or a table since deleted) would otherwise open an
   * empty till, so it is refused with a message instead.
   */
  function openBill(o: OrderOut) {
    const type = o.order_type ?? "takeaway";
    const qs = new URLSearchParams({ type });
    if (type === "dine_in") {
      if (o.table_id == null) {
        setMessage(
          `${o.order_number ?? "That bill"} has no table on it, so the till cannot reopen it. Find it under Orders.`,
        );
        return;
      }
      qs.set("table", String(o.table_id));
    } else {
      qs.set("order", String(o.id));
    }
    // Display only — the till ignores it. It keeps the box filled with WHAT THE
    // CASHIER TYPED, so the control still reads as the search they ran: type a
    // token and it says the token; type a bill number and it says that. It used
    // to be overwritten with the resolved order_number, which silently replaced
    // "8" with "R3-0009" and looked like the till had searched something else.
    qs.set("bill", term.trim() || (o.order_number ?? ""));
    setMatches([]);
    setMessage(null);
    navigate(`/cashier/new-order?${qs.toString()}`);
  }

  async function resolve() {
    const raw = term.trim().replace(/^#/, "");
    if (!raw) return;
    setLoading(true);
    setMatches([]);
    setMessage(null);
    try {
      let hits: OrderOut[] = [];
      if (looksLikeOrderNumber(raw)) {
        const rows = await fetchOrders({ q: raw, limit: 25 });
        const needle = raw.toLowerCase();
        hits = rows.filter((o) => (o.order_number ?? "").toLowerCase().includes(needle));
        const exact = hits.find(
          (o) =>
            (o.order_number ?? "").toLowerCase() === needle ||
            (o.order_number ?? "").toLowerCase() === `r${needle}`,
        );
        if (exact) hits = [exact];
      } else if (/^\d+$/.test(raw)) {
        hits = await fetchOrders({ token: Number(raw), limit: 50 });
      } else {
        hits = await fetchOrders({ q: raw, limit: 25 });
      }

      if (hits.length === 0) {
        setMessage(
          /^\d+$/.test(raw)
            ? `No bill with token ${raw}. Try the full bill number (e.g. R4-0030).`
            : `No bill found for "${raw}".`,
        );
      } else if (hits.length === 1) {
        openBill(hits[0]);
      } else {
        setMatches(hits);
      }
    } catch {
      setMessage("Lookup failed. Check the connection and try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={s.wrap}>
      <form
        className={s.row}
        onSubmit={(e) => {
          e.preventDefault();
          void resolve();
        }}
      >
        <input
          className={s.input}
          value={term}
          onChange={(e) => {
            setTerm(e.target.value);
            // Typing a new term invalidates the last answer, so clear it rather
            // than leaving a stale "No bill found" under a different number.
            if (message) setMessage(null);
            if (matches.length) setMatches([]);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setMatches([]);
              setMessage(null);
            }
          }}
          placeholder="Bill no. or token"
          aria-label="Bill number or token"
          data-testid="view-bill-input"
        />
        <button
          type="submit"
          className={s.btn}
          disabled={loading || term.trim() === ""}
          data-testid="view-bill-search"
        >
          {loading ? "…" : "View Bill"}
        </button>
      </form>

      {(message || matches.length > 0) && (
        <div className={s.pop}>
          {message && (
            <p className={s.msg} data-testid="view-bill-message">
              {message}
            </p>
          )}
          {matches.length > 0 && (
            <div data-testid="view-bill-matches">
              <p className={s.matchHead}>
                {matches.length} bills share this token — pick by date:
              </p>
              {matches.map((o) => (
                <button
                  key={o.id}
                  type="button"
                  className={s.matchRow}
                  onClick={() => openBill(o)}
                >
                  <span className={s.matchRef}>{o.order_number}</span>
                  <span className={s.matchDate}>{fmtDate(o.created_at)}</span>
                  <span className={s.matchMeta}>
                    {o.daily_token != null ? `Token ${o.daily_token}` : ""}
                  </span>
                  <span className={s.matchName}>
                    {o.customer_name?.trim() || o.customer_phone || "Walk-in"}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
