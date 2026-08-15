import { useEffect } from "react";
import { vatIncludedIn, type TaxConfig } from "../lib/useTaxConfig";
import s from "./BillPreviewDialog.module.css";

export interface BillLine {
  name: string;
  qty: number;
  /** Unit price in AED. Null for a line recovered from an open tab, where only
   *  the line total is known — the slip then prints the total and no rate. */
  unitPrice: number | null;
  lineTotal: number;
}

/**
 * The bill, on screen, before it goes anywhere near a printer.
 *
 * "Print Bill" used to call `window.print()` straight from the button, which
 * handed the browser the whole till — sidebar, keypad, dish grid — and gave the
 * cashier no chance to check the slip first. A bill is the thing the customer
 * argues with, so it gets looked at before it is committed to paper: wrong
 * table, missing round, a line added to the wrong ticket are all cheap to catch
 * here and expensive to catch after the customer is holding it.
 *
 * The printed output is the slip alone. That is done with visibility rather than
 * a hidden iframe: the slip stays a normal part of the React tree, so it can not
 * drift out of sync with what is on screen.
 */
export function BillPreviewDialog({
  lines,
  subtotal,
  deliveryFee,
  adjustments = 0,
  total,
  taxCfg,
  restaurantName,
  orderTypeLabel,
  tokenNumber,
  billNumber,
  tableLabel,
  waiterName,
  customerName,
  terminalName = "order1",
  onClose,
}: {
  lines: BillLine[];
  subtotal: number;
  deliveryFee: number;
  /** Whatever the server's total does not explain — a till discount, a service
   *  or packaging charge. Printed as its own line so the slip always adds up;
   *  silently absorbing it into the subtotal would print a figure the customer
   *  can check and find wrong. */
  adjustments?: number;
  total: number;
  taxCfg: TaxConfig;
  restaurantName: string | null;
  orderTypeLabel: string;
  tokenNumber: number | string | null;
  /** Order number for a saved ticket; "NEW" while the bill is still unsaved. */
  billNumber: string;
  tableLabel: string | null;
  waiterName: string | null;
  customerName: string | null;
  terminalName?: string;
  onClose: () => void;
}) {
  // Escape closes. A till is driven at speed and often by keyboard; a modal that
  // can only be dismissed by finding a button is a modal that gets left open.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const now = new Date();
  const stamp = now.toLocaleString("en-GB", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  });
  // VAT is stated as the tax CONTAINED IN the amount charged, always — never as
  // a figure added on top.
  //
  // The customer is charged `total`, and nothing downstream of this slip adds
  // VAT to it: the server's order total is subtotal + fee + charges − discounts,
  // full stop. So printing an "on top" VAT line produced a bill that did not
  // add up — 29.00 − 9.00 + 4.00 against a total of 20.00 — and the arithmetic
  // on a bill is the one thing a guest always checks. Extracting it from the
  // charged total keeps the slip reconciled and still declares the tax.
  //
  // It is taken AFTER the discount, because tax is due on what was actually
  // paid, not on the pre-discount price.
  const vat = vatIncludedIn(total, taxCfg);

  return (
    <div className={s.backdrop} role="presentation" onClick={onClose}>
      <div
        className={s.modal}
        role="dialog"
        aria-modal="true"
        aria-label="Bill preview"
        onClick={(e) => e.stopPropagation()}
        data-testid="bill-preview-dialog"
      >
        {/* The slip. Sized in mm because it is going to 80mm thermal paper. */}
        <div className={s.slip} data-testid="bill-preview-slip">
          <div className={s.slipHead}>
            <div className={s.shop}>{restaurantName ?? "Bill"}</div>
            <div className={s.kind}>{orderTypeLabel.toUpperCase()}</div>
          </div>

          <div className={s.meta}>
            <span>Date</span>
            <span>{stamp}</span>
            {waiterName && (
              <>
                <span>Waiter</span>
                <span>{waiterName}</span>
              </>
            )}
            {tableLabel && (
              <>
                <span>Table No</span>
                <span>{tableLabel}</span>
              </>
            )}
            <span>Bill No</span>
            <span>{billNumber}</span>
            <span>Terminal</span>
            <span>{terminalName}</span>
            {customerName && (
              <>
                <span>Name</span>
                <span>{customerName}</span>
              </>
            )}
          </div>

          <div className={s.tokenBox}>
            Token No: <strong data-testid="bill-preview-token">{tokenNumber ?? "—"}</strong>
          </div>

          <table className={s.items}>
            <thead>
              <tr>
                <th>Item</th>
                <th className={s.num}>Qty</th>
                <th className={s.num}>Rate</th>
                <th className={s.num}>Amount</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((line, i) => (
                <tr key={`${line.name}-${i}`}>
                  <td>{line.name}</td>
                  <td className={s.num}>{line.qty}</td>
                  {/* A tab line carries no unit price; printing a made-up one
                      would be a wrong number on a document the customer pays. */}
                  <td className={s.num}>
                    {line.unitPrice == null ? "—" : line.unitPrice.toFixed(2)}
                  </td>
                  <td className={s.num}>{line.lineTotal.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className={s.totals}>
            <div>
              <span>Subtotal</span>
              <span>{subtotal.toFixed(2)}</span>
            </div>
            {deliveryFee > 0 && (
              <div>
                <span>Delivery</span>
                <span>{deliveryFee.toFixed(2)}</span>
              </div>
            )}
            {Math.abs(adjustments) >= 0.005 && (
              <div>
                <span>{adjustments < 0 ? "Discount" : "Charges"}</span>
                <span data-testid="bill-preview-adjustments">{adjustments.toFixed(2)}</span>
              </div>
            )}
            <div className={s.grand}>
              <span>TOTAL AED</span>
              <span data-testid="bill-preview-total">{total.toFixed(2)}</span>
            </div>
            {/* Below the total, and worded as "of which", because that is what
                it is. No rate is printed until the server has confirmed one: a
                wrong tax figure on a bill is worse than no line at all. */}
            {taxCfg.ready && taxCfg.percent > 0 && (
              <div className={s.vatNote}>
                <span>of which VAT ({taxCfg.percent}% incl.)</span>
                <span data-testid="bill-preview-vat">{vat.toFixed(2)}</span>
              </div>
            )}
          </div>

          <div className={s.foot}>Thank you · Please come again</div>
        </div>

        <div className={s.actions}>
          <button
            type="button"
            className={s.print}
            onClick={() => window.print()}
            data-testid="bill-preview-print"
          >
            🖨 Print
          </button>
          <button
            type="button"
            className={s.cancel}
            onClick={onClose}
            data-testid="bill-preview-close"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
