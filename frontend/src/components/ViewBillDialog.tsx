import { useState } from "react";
import { toast } from "./Toaster";
import { fetchOrderDetail } from "../lib/orderDetailApi";
import { fetchOrders } from "../lib/ordersApi";
import type { OrderDetailOut, OrderOut } from "../lib/types";
import s from "./ViewBillDialog.module.css";

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

const TYPE_LABEL: Record<string, string> = {
  dine_in: "DINING",
  takeaway: "TAKE AWAY",
  delivery: "HOME DELIVERY",
  online: "ONLINE",
};

/** "21-7-2026 07:45:12 PM" — the receipt's date format. */
function fmtDateTime(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const date = `${d.getDate()}-${d.getMonth() + 1}-${d.getFullYear()}`;
  const time = d.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  });
  return `${date} ${time}`;
}

/** "07:48 PM" — short time for the "Updated Time" line. */
function fmtTime(iso?: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  });
}

/**
 * Cashier "View Bill" dialog — smart lookup by full bill number OR queue token,
 * rendered as a thermal-receipt slip.
 *
 * Full order number (has a dash, e.g. R4-0030) → exact bill. A bare number is
 * read as a queue token. The token resets each Dubai MONTH, so the same number
 * recurs across months; we search all history for it and, when several bills
 * share it, show a date-labelled picker so the cashier chooses the right month.
 */
export function ViewBillDialog({ onClose }: { onClose: () => void }) {
  const [term, setTerm] = useState("");
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<OrderDetailOut | null>(null);
  const [matches, setMatches] = useState<OrderOut[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  async function openBill(orderId: number) {
    setLoading(true);
    try {
      const d = await fetchOrderDetail(orderId);
      setDetail(d);
      // Keep `matches` so the receipt can offer a "‹ Back" to the picker.
      setMessage(null);
    } catch {
      setMessage("Could not load that bill. Try again.");
    } finally {
      setLoading(false);
    }
  }

  async function resolve() {
    const raw = term.trim().replace(/^#/, "");
    if (!raw) return;
    setLoading(true);
    setDetail(null);
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
        // The queue token resets monthly, so the same number recurs across
        // months. Search ALL history for that token and let the picker below
        // disambiguate by date (server returns newest first).
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
        await openBill(hits[0].id);
      } else {
        setMatches(hits);
      }
    } catch {
      setMessage("Lookup failed. Check the connection and try again.");
    } finally {
      setLoading(false);
    }
  }

  function reprint() {
    toast(
      detail
        ? `Reprint queued for ${detail.order_number} (when printer configured).`
        : "Open a bill first.",
    );
  }

  const updatedTime =
    detail?.kitchen_ready_at || detail?.delivered_at || detail?.created_at || null;

  return (
    <div
      className={s.back}
      role="dialog"
      aria-modal="true"
      aria-label="View bill"
      onClick={onClose}
    >
      <div className={s.modal} onClick={(e) => e.stopPropagation()}>
        <div className={s.head}>
          <span className={s.headTitle}>🧾 View Bill</span>
          <button
            type="button"
            className={s.close}
            onClick={onClose}
            aria-label="Close"
            data-testid="view-bill-close"
          >
            ✕
          </button>
        </div>

        <form
          className={s.searchRow}
          onSubmit={(e) => {
            e.preventDefault();
            void resolve();
          }}
        >
          <input
            className={s.searchInput}
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder="Bill number (R4-0030) or token (16)…"
            aria-label="Bill number or token"
            data-testid="view-bill-input"
            autoFocus
          />
          <button
            type="submit"
            className={s.searchBtn}
            disabled={loading || term.trim() === ""}
            data-testid="view-bill-search"
          >
            {loading ? "…" : "View"}
          </button>
        </form>

        {message && (
          <p className={s.msg} data-testid="view-bill-message">
            {message}
          </p>
        )}

        {matches.length > 0 && !detail && (
          <div className={s.matches} data-testid="view-bill-matches">
            <p className={s.matchHead}>
              {matches.length} bills share this token — pick by date:
            </p>
            {matches.map((o) => (
              <button
                key={o.id}
                type="button"
                className={s.matchRow}
                onClick={() => void openBill(o.id)}
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

        {detail && (
          <>
            {matches.length > 0 && (
              <button
                type="button"
                className={s.backBtn}
                onClick={() => setDetail(null)}
                data-testid="view-bill-back"
              >
                ‹ Back to list
              </button>
            )}
            {/* Thermal-receipt slip (mono, paper-white). Format is a placeholder
                the user will refine later — kept faithful to the sample. */}
            <div className={s.receipt} data-testid="view-bill-receipt">
              <div className={s.rTop}>
                <div className={s.rLine}>Date:{fmtDateTime(detail.created_at)}</div>
                <div className={s.rSplit}>
                  <span>Updated Time {fmtTime(updatedTime)}</span>
                  <span>#{detail.order_number}</span>
                </div>
                <div className={s.rSplit}>
                  <span>Waiter:{detail.staff_name ?? "-"}</span>
                  {detail.table_label ? <span>Table No: {detail.table_label}</span> : null}
                </div>
              </div>

              <div className={s.rItemsHead}>
                <span>Items</span>
                <span>Qty</span>
              </div>
              <div className={s.rItems}>
                {detail.items.map((i, idx) => (
                  <div className={s.rItemRow} key={`${i.dish_number}-${idx}`}>
                    <span className={s.rItemName}>
                      {i.dish_name}
                      {i.variant_name ? `  ${i.variant_name}` : ""}
                      {i.notes ? <em className={s.rItemNote}>{i.notes}</em> : null}
                    </span>
                    <span className={s.rItemQty}>{i.qty}</span>
                  </div>
                ))}
              </div>

              <div className={s.rRule} />
              <div className={s.rType}>{TYPE_LABEL[detail.order_type ?? ""] ?? "ORDER"}</div>

              <div className={s.rSplit}>
                <span>
                  Token No:{" "}
                  {detail.daily_token != null
                    ? String(detail.daily_token).padStart(4, "0")
                    : "-"}
                </span>
                {detail.table_label ? <span>Terminal: {detail.table_label}</span> : null}
              </div>
              <div className={s.rLine}>Name: {detail.customer?.name?.trim() ?? ""}</div>
            </div>

            <div className={s.actions}>
              <button
                type="button"
                className={s.reprintBtn}
                onClick={reprint}
                data-testid="view-bill-reprint"
              >
                🧾 Reprint
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
