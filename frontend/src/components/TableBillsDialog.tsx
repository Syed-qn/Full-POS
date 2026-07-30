import { billName, type TableBill } from "../lib/floorApi";
import s from "./TableBillsDialog.module.css";

/**
 * Which bill on this table? Shown when a table carries MORE THAN ONE — two
 * parties sharing it, each paying for their own food.
 *
 * A table with a single bill never sees this: the floor opens it directly, the
 * way it always has. An extra tap on the common case would be a tax paid by
 * every cashier to serve the rare one.
 */
export function TableBillsDialog({
  tableLabel,
  bills,
  onPick,
  onSplit,
  onClose,
}: {
  tableLabel: string;
  bills: TableBill[];
  onPick: (bill: TableBill) => void;
  /** Start a fresh bill on this table. Omit to hide the action. */
  onSplit?: () => void;
  onClose: () => void;
}) {
  return (
    <div className={s.backdrop} role="presentation" onClick={onClose}>
      <div
        className={s.modal}
        role="dialog"
        aria-modal="true"
        aria-label={`Bills on table ${tableLabel}`}
        onClick={(e) => e.stopPropagation()}
        data-testid="table-bills-dialog"
      >
        <h2 className={s.title}>
          Table {tableLabel} · {bills.length} bills
        </h2>
        <p className={s.sub}>Pick the bill you are serving or collecting.</p>

        <ul className={s.list}>
          {bills.map((b, i) => (
            <li key={b.order_id}>
              <button
                type="button"
                className={s.bill}
                onClick={() => onPick(b)}
                data-testid={`table-bill-${b.order_id}`}
              >
                {/* A POSITION, computed rather than stored. The server sends bills
                    oldest-first, so Bill 1 is the party that sat down first and the
                    numbering stays right when one is paid. */}
                <span className={s.who}>{billName(b, i)}</span>
                <span className={s.ref}>
                  {b.order_number ?? `#${b.order_id}`}
                  {b.daily_token != null ? ` · Token ${b.daily_token}` : ""}
                </span>
                <span className={s.amount}>AED {b.total_aed}</span>
              </button>
            </li>
          ))}
        </ul>

        <div className={s.actions}>
          {onSplit && (
            <button
              type="button"
              className={s.split}
              onClick={onSplit}
              data-testid="table-bills-split"
            >
              ＋ Split bill
            </button>
          )}
          <button type="button" className={s.cancel} onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
