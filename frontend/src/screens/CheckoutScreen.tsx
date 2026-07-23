import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { OfflineLimitsBanner } from "../components/OfflineLimitsBanner";
import { toast } from "../components/Toaster";
import { isCashierRole } from "../lib/navAccess";
import {
  applyOrderDiscount,
  chargePayment,
  createPaymentLink,
  createWalletSession,
  getCurrentCashDrawer,
  listOrderPayments,
  markPayLater,
  openCashDrawer,
  redeemGiftCard,
  refundPayment,
  type PaymentTxn,
} from "../lib/paymentsApi";
import { fetchOrderDetail, orderOutFromDetail } from "../lib/orderDetailApi";
import { usePosTheme } from "../lib/posTheme";
import { useManagerPinGate } from "../lib/requireManagerPin";
import type { OrderDetailOut, OrderOut } from "../lib/types";
import s from "./CheckoutScreen.module.css";

const TENDERS: Array<{ id: string; label: string }> = [
  { id: "cash", label: "Cash" },
  { id: "card", label: "Card" },
  { id: "tap_to_pay", label: "Tap" },
  { id: "apple_pay", label: "Apple Pay" },
  { id: "google_pay", label: "Google Pay" },
  { id: "online", label: "Online" },
  { id: "payment_link", label: "Payment Link" },
  { id: "gift_card", label: "Gift Card" },
  { id: "wallet", label: "Wallet" },
  { id: "pay_later", label: "Pay Later" },
];

const TIP_PRESETS = [0, 5, 10, 15] as const;

/**
 * Last-seen bill per order id, kept for the life of the tab. Reopening a
 * checkout — which a cashier does constantly, bouncing between the till and
 * the pay screen — then paints instantly instead of flashing "Loading bill…".
 * Never authoritative: every mount re-fetches, and Confirm Payment stays
 * disabled until it does.
 */
const billCache = new Map<
  number,
  { detail: OrderDetailOut; basic: OrderOut; paidAed: string }
>();

function parseMoney(v: string): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function formatMoney(n: number): string {
  return n.toFixed(2);
}

export function CheckoutScreen() {
  const { id: idParam } = useParams<{ id: string }>();
  const orderId = Number(idParam);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const splitFromQuery = searchParams.get("split") === "1";
  // Fire the "paid" toast + redirect exactly once, and only for a payment made
  // in this session (not when opening an already-settled order).
  const paidThisSession = useRef(false);
  const settledHandled = useRef(false);

  // Paint the last known bill immediately instead of a "Loading bill…" wall on
  // every visit. The figures are still re-fetched — see `stale` below, which
  // holds Confirm Payment until fresh numbers land, so nothing is ever charged
  // off a cached total.
  const cached = billCache.get(orderId);
  const [detail, setDetail] = useState<OrderDetailOut | null>(cached?.detail ?? null);
  const [basic, setBasic] = useState<OrderOut | null>(cached?.basic ?? null);
  const [loading, setLoading] = useState(true);
  const [stale, setStale] = useState(cached != null);
  const [error, setError] = useState<string | null>(null);
  const [paidAed, setPaidAed] = useState(cached?.paidAed ?? "0.00");
  const [lastTxn, setLastTxn] = useState<PaymentTxn | null>(null);
  const [lastChange, setLastChange] = useState(0);

  // Pre-select the tender the cashier chose on the terminal (COD → cash,
  // Other Pay → card); falls back to cash. Only valid tenders are honoured.
  const [tender, setTender] = useState(() => {
    const t = searchParams.get("tender");
    return t && TENDERS.some((x) => x.id === t) ? t : "cash";
  });
  const [amountInput, setAmountInput] = useState("");
  const [tipPct, setTipPct] = useState<(typeof TIP_PRESETS)[number]>(0);
  const [splitMode, setSplitMode] = useState(splitFromQuery);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [giftCode, setGiftCode] = useState("");
  const [giftPin, setGiftPin] = useState("");
  const [txns, setTxns] = useState<PaymentTxn[]>([]);
  const [discountAmt, setDiscountAmt] = useState("5.00");
  const { requestPin, pinGate, pinBusy } = useManagerPinGate();
  const theme = usePosTheme();

  async function load() {
    if (!Number.isFinite(orderId) || orderId <= 0) {
      setError("Invalid order id");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const d = await fetchOrderDetail(orderId, { include: "overview" });
      const b = orderOutFromDetail(d);
      setDetail(d);
      setBasic(b);
      let paid = "0.00";
      try {
        const pay = await listOrderPayments(orderId);
        paid = pay.total_paid_aed ?? "0.00";
        setPaidAed(paid);
        setTxns(Array.isArray(pay.transactions) ? pay.transactions : []);
      } catch {
        setPaidAed(paid);
        setTxns([]);
      }
      // Warm the cache so coming back to this bill paints with no flash.
      billCache.set(orderId, { detail: d, basic: b, paidAed: paid });
      setStale(false);
    } catch (e) {
      // A cached bill on screen is better than blanking it, but it must stay
      // marked stale so it cannot be tendered against.
      setError(e instanceof Error ? e.message : "Failed to load order");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderId]);

  const totalDue = useMemo(() => {
    if (!detail) return 0;
    return Math.max(0, parseMoney(detail.total) - parseMoney(paidAed));
  }, [detail, paidAed]);

  // Bill is fully settled once payments cover the total. On-premise orders are
  // closed + table freed by the backend at this point (settle_on_premise_if_paid).
  const fullyPaid = useMemo(
    () =>
      !!detail &&
      parseMoney(detail.total) > 0 &&
      parseMoney(paidAed) >= parseMoney(detail.total) - 0.001,
    [detail, paidAed],
  );
  // On-premise (dine-in / takeaway / drive-thru) close on payment and free a table;
  // delivery/online keep going to a rider, so the CTA differs.
  const isOnPremise = useMemo(() => {
    const t = String(basic?.order_type ?? "");
    return t === "dine_in" || t === "takeaway" || t === "drive_thru";
  }, [basic]);

  // Bill fully settled by a payment taken here → quick toast, then back to the
  // till. No blocking "paid in full" modal; the receipt still prints via the
  // tender flow. Fires once, and only for a payment made in this session.
  useEffect(() => {
    if (!fullyPaid || !paidThisSession.current || settledHandled.current) return;
    settledHandled.current = true;
    const ref = detail?.order_number || (detail ? `#${detail.id}` : "order");
    const change = lastChange > 0 ? ` · change AED ${formatMoney(lastChange)}` : "";
    toast(
      `Paid in full — ${ref} closed${isOnPremise ? " · table freed" : ""}${change}`,
      "success",
    );
    navigate(isOnPremise ? "/new-order" : "/orders");
  }, [fullyPaid, lastChange, isOnPremise, detail, navigate]);

  const amountNum = amountInput === "" ? totalDue : parseMoney(amountInput);
  const tipAed = tipPct > 0 ? (amountNum * tipPct) / 100 : 0;
  const chargeTotal = amountNum + tipAed;
  const changeDue =
    tender === "cash" && amountNum > totalDue ? amountNum - totalDue : 0;

  useEffect(() => {
    if (detail && amountInput === "") {
      setAmountInput(formatMoney(Math.max(0, parseMoney(detail.total) - parseMoney(paidAed))));
    }
    // only seed when detail/paid loads
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail, paidAed]);

  function appendKey(key: string) {
    setAmountInput((prev) => {
      if (key === "C") return "";
      if (key === "⌫") return prev.slice(0, -1);
      if (key === ".") {
        if (prev.includes(".")) return prev;
        return prev === "" ? "0." : prev + ".";
      }
      // limit to 2 decimal places
      const next = prev + key;
      const parts = next.split(".");
      if (parts[1] && parts[1].length > 2) return prev;
      if (next.length > 12) return prev;
      return next.replace(/^0+(\d)/, "$1");
    });
  }

  async function confirmPayment() {
    if (!detail) return;
    setBusy(true);
    setActionError(null);
    try {
      const amt = formatMoney(amountNum);
      if (amountNum <= 0) {
        throw new Error("Enter an amount greater than zero.");
      }

      if (tender === "payment_link") {
        const link = await createPaymentLink(detail.id, amt);
        toast(`Payment link ready: ${link.url || link.token}`);
        setLastTxn({
          id: link.id,
          order_id: detail.id,
          status: link.status,
          amount_aed: link.amount_aed,
          tender_type: "payment_link",
        });
        return;
      }

      if (tender === "pay_later") {
        const txn = await markPayLater(detail.id, amt);
        setLastTxn(txn);
        toast("Marked pay later");
        await load();
        return;
      }

      if (tender === "gift_card") {
        if (!giftCode || !giftPin) {
          throw new Error("Gift card code and PIN required.");
        }
        await redeemGiftCard({
          code: giftCode,
          pin: giftPin,
          order_id: detail.id,
          amount_aed: amt,
        });
        toast("Gift card redeemed");
        paidThisSession.current = true;
        await load();
        return;
      }

      if (tender === "wallet" || tender === "apple_pay" || tender === "google_pay") {
        const session = await createWalletSession({
          order_id: detail.id,
          tender_type: tender === "wallet" ? "wallet" : tender,
          amount_aed: amt,
        });
        const txn = await chargePayment({
          order_id: detail.id,
          tender_type: tender,
          amount_aed: amt,
          tip_aed: formatMoney(tipAed),
          wallet_session_id: session.session_id,
        });
        setLastTxn(txn);
        paidThisSession.current = true;
        const willSettle =
          parseMoney(detail.total) > 0 &&
          parseMoney(paidAed) + amountNum >= parseMoney(detail.total) - 0.001;
        if (!willSettle) toast(`Payment ${txn.status}`, "success");
        await load();
        return;
      }

      const txn = await chargePayment({
        order_id: detail.id,
        tender_type: tender,
        amount_aed: amt,
        tip_aed: formatMoney(tipAed),
        channel: "pos_checkout",
        terminal_id: "checkout-1",
      });
      // Cash over-tender → change to hand back; surfaced in the settled toast.
      setLastChange(tender === "cash" && amountNum > totalDue ? amountNum - totalDue : 0);
      setLastTxn(txn);
      paidThisSession.current = true;
      // Partial/split payment won't trip the "paid in full" effect — give it its
      // own confirmation. A full payment stays silent here so we don't double-toast.
      const willSettle =
        parseMoney(detail.total) > 0 &&
        parseMoney(paidAed) + amountNum >= parseMoney(detail.total) - 0.001;
      if (!willSettle) toast(`Payment recorded — AED ${amt}`, "success");
      await load();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Payment failed";
      setActionError(msg);
      toast(msg, "error");
    } finally {
      setBusy(false);
    }
  }

  async function handleOpenDrawer() {
    try {
      try {
        await getCurrentCashDrawer();
        toast("Cash drawer already open");
        return;
      } catch {
        /* none */
      }
      await openCashDrawer("200.00");
      toast("Cash drawer opened");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not open drawer", "error");
    }
  }

  function requestManagerDiscount() {
    if (!detail) return;
    const amt = discountAmt.trim();
    if (!amt || Number(amt) <= 0) {
      toast("Enter a discount amount greater than zero.", "error");
      return;
    }
    requestPin({
      actionType: "discount",
      actionLabel: "Manager discount override",
      recordLabel: detail.order_number || String(detail.id),
      orderId: detail.id,
      amountAed: amt,
      confirmTitle: "Apply manager discount?",
      confirmMessage: `Apply AED ${amt} manager discount to this bill. Manager PIN required.`,
      confirmLabel: "Continue to PIN",
      cancelLabel: "Back",
      execute: async ({ reason }) => {
        await applyOrderDiscount(detail.id, {
          discount_type: "manager",
          amount_aed: amt,
          reason: reason || "manager discount at checkout",
        });
        toast("Manager discount applied.");
        await load();
      },
    });
  }

  function requestRefund(txn: PaymentTxn) {
    if (!detail) return;
    const remaining =
      Number(txn.amount_aed) - Number(txn.refunded_amount_aed ?? 0);
    const amt = remaining > 0 ? remaining.toFixed(2) : txn.amount_aed;
    requestPin({
      actionType: "refund",
      actionLabel: "Refund / partial refund",
      recordLabel: `txn #${txn.id}`,
      orderId: detail.id,
      amountAed: amt,
      reasonRequired: true,
      confirmTitle: "Refund this payment?",
      confirmMessage: `Refund AED ${amt} on transaction #${txn.id}. Manager PIN and reason required.`,
      confirmLabel: "Continue to PIN",
      cancelLabel: "Keep payment",
      execute: async () => {
        const result = await refundPayment(txn.id, amt);
        toast(`Refunded AED ${result.refunded_amount_aed ?? amt}.`);
        setLastTxn({ ...txn, status: "refunded", refunded_amount_aed: result.refunded_amount_aed ?? amt });
        await load();
      },
    });
  }

  const refundableTxns = useMemo(
    () =>
      txns.filter((t) => {
        if (!t.id) return false;
        const st = (t.status || "").toLowerCase();
        if (st === "refunded" || st === "failed" || st === "cancelled") return false;
        const paid = Number(t.amount_aed || 0);
        const already = Number(t.refunded_amount_aed || 0);
        return paid - already > 0.001;
      }),
    [txns],
  );

  // Back to where the cashier came from: the table's order terminal when we
  // were handed a table context (?table=&label=), otherwise the order detail.
  const backTable = searchParams.get("table");
  const backLabel = searchParams.get("label");
  const orderTerminal = isCashierRole() ? "/cashier/new-order" : "/new-order";
  const backTo = backTable
    ? `${orderTerminal}?table=${backTable}&label=${encodeURIComponent(backLabel ?? "")}`
    : // No table = a cashier takeaway. Send them to the pickup list, not the
      // manager order screens, which the cashier role cannot open anyway.
      isCashierRole()
      ? "/cashier/takeaway"
      : detail
        ? `/orders/${detail.id}`
        : "/orders";

  if (!Number.isFinite(orderId) || orderId <= 0) {
    return (
      <div className={s.root} data-theme={theme} data-testid="checkout-screen">
        <header className={s.head}>
          <div>
            <h1 className={s.headTitle}>Checkout</h1>
          </div>
          <Link to="/orders" className={s.backBtn}>
            ‹ Orders
          </Link>
        </header>
        <div className={s.stateMsg}>Order id is required.</div>
      </div>
    );
  }

  // Opening a DIFFERENT bill used to swap the whole screen for a centred
  // "Loading bill…" message, which read as a full page reload. Keep the real
  // frame — header, back link and the three panels — and let only the contents
  // be empty, so switching orders looks like the bill changing, not the app
  // restarting.
  if (loading && !detail) {
    return (
      <div className={s.root} data-theme={theme} data-testid="checkout-screen">
        <header className={s.head}>
          <div>
            <h1 className={s.headTitle}>Checkout</h1>
            <p className={s.headSub}>Loading bill…</p>
          </div>
          <Link to={backTo} className={s.backBtn} data-testid="checkout-back">
            ‹ Back to order
          </Link>
        </header>
        <div className={s.grid}>
          <section className={s.panel} aria-busy="true" />
          <section className={s.panel} aria-busy="true" />
          <section className={s.panel} aria-busy="true" />
        </div>
      </div>
    );
  }

  // Only wall off on an error we cannot render past. A failed REFRESH over a
  // cached bill keeps the bill on screen — `stale` already blocks tendering.
  if (!detail || !basic) {
    return (
      <div className={s.root} data-theme={theme} data-testid="checkout-screen">
        <header className={s.head}>
          <div>
            <h1 className={s.headTitle}>Checkout</h1>
          </div>
          <Link to="/orders" className={s.backBtn}>
            ‹ Orders
          </Link>
        </header>
        <div className={s.stateMsg}>
          <p>{error || "Order not found"}</p>
          <button type="button" className={s.ghostBtn} onClick={() => void load()}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={s.root} data-theme={theme} data-testid="checkout-screen">
      {/* ── header ─────────────────────────────────────────────────────── */}
      <header className={s.head}>
        <div>
          <h1 className={s.headTitle}>Checkout</h1>
          <p className={s.headSub}>
            Order {detail.order_number || `#${detail.id}`} ·{" "}
            {basic.customer_name || basic.customer_phone}
          </p>
        </div>
        <Link to={backTo} className={s.backBtn} data-testid="checkout-back">
          ‹ Back to order
        </Link>
      </header>

      <OfflineLimitsBanner surface="checkout" />

      <div className={s.grid}>
        {/* Left — bill */}
        <section className={s.panel} aria-label="Bill summary">
          <div className={s.panelHead}>
            <h3 className={s.panelTitle}>Bill</h3>
            <button
              type="button"
              className={`${s.splitToggle} ${splitMode ? s.splitToggleOn : ""}`}
              onClick={() => setSplitMode((v) => !v)}
              data-testid="split-mode-badge"
            >
              {splitMode ? "◧ Split on" : "◧ Split mode"}
            </button>
          </div>
          {splitMode && (
            <div className={s.splitHint}>Split active — enter a partial amount on the keypad.</div>
          )}
          <div className={s.billScroll}>
            {detail.items.map((item, i) => (
              <div key={i} className={s.itemRow}>
                <div className={s.itemLeft}>
                  <div className={s.itemName}>
                    <span className={s.itemQty}>{item.qty}×</span> {item.dish_name}
                  </div>
                  {item.notes && <div className={s.itemMeta}>{item.notes}</div>}
                </div>
                <div className={s.itemPrice}>AED {item.line_total}</div>
              </div>
            ))}
          </div>
          <div className={s.billTotals}>
            <div className={s.line}>
              <span>Subtotal</span>
              <span>AED {detail.subtotal}</span>
            </div>
            <div className={s.line}>
              <span>Delivery / charges</span>
              <span>AED {detail.delivery_fee_aed}</span>
            </div>
            <div className={s.line}>
              <span>Already paid</span>
              <span>AED {paidAed}</span>
            </div>
            <div className={`${s.line} ${s.lineTotal}`}>
              <span>Order total</span>
              <span>AED {detail.total}</span>
            </div>
          </div>
        </section>

        {/* Center — tenders */}
        <section className={s.panel} aria-label="Tender types">
          <h3 className={s.panelTitle}>Tender</h3>
          <div className={s.tenderGrid} role="group" aria-label="Tender grid">
            {TENDERS.map((t) => (
              <button
                key={t.id}
                type="button"
                className={`${s.tenderBtn} ${tender === t.id ? s.tenderActive : ""}`}
                aria-pressed={tender === t.id}
                onClick={() => setTender(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
          {tender === "gift_card" && (
            <>
              <input
                className={s.input}
                placeholder="Gift card code"
                value={giftCode}
                onChange={(e) => setGiftCode(e.target.value)}
                aria-label="Gift card code"
              />
              <input
                className={s.input}
                placeholder="PIN"
                value={giftPin}
                onChange={(e) => setGiftPin(e.target.value)}
                aria-label="Gift card PIN"
              />
            </>
          )}
          <h3 className={s.panelTitle}>Tip</h3>
          <div className={s.tipRow} role="group" aria-label="Tip percent">
            {TIP_PRESETS.map((p) => (
              <button
                key={p}
                type="button"
                className={`${s.tipBtn} ${tipPct === p ? s.tipActive : ""}`}
                onClick={() => setTipPct(p)}
              >
                {p === 0 ? "No tip" : `${p}%`}
              </button>
            ))}
          </div>

          <h3 className={s.panelTitle}>Manager discount</h3>
          <div className={s.discountRow}>
            <input
              className={s.input}
              aria-label="Manager discount amount"
              value={discountAmt}
              onChange={(e) => setDiscountAmt(e.target.value)}
              placeholder="AED"
            />
            <button
              type="button"
              className={s.ghostBtn}
              disabled={busy || pinBusy}
              onClick={requestManagerDiscount}
            >
              Apply…
            </button>
          </div>

          {refundableTxns.length > 0 && (
            <>
              <h3 className={s.panelTitle}>Refund</h3>
              {refundableTxns.map((txn) => (
                <div key={txn.id} className={s.discountRow}>
                  <span className={s.refundLabel}>
                    #{txn.id} · {txn.tender_type || "pay"} · AED {txn.amount_aed}
                  </span>
                  <button
                    type="button"
                    className={s.dangerBtn}
                    disabled={busy || pinBusy}
                    onClick={() => requestRefund(txn)}
                  >
                    Refund…
                  </button>
                </div>
              ))}
            </>
          )}
        </section>

        {/* Right — amount + keypad */}
        <section className={s.panel} aria-label="Amount and keypad">
          <div className={s.amountBox}>
            <span className={s.amountLabel}>Amount due</span>
            <span className={s.amountValue}>
              <span className={s.amountCur}>AED</span> {formatMoney(totalDue)}
            </span>
          </div>
          <div className={s.line}>
            <span>Tender amount</span>
            <span className={s.mono}>AED {amountInput || "0.00"}</span>
          </div>
          {tipAed > 0 && (
            <div className={s.line}>
              <span>Tip</span>
              <span className={s.mono}>AED {formatMoney(tipAed)}</span>
            </div>
          )}
          <div className={s.line}>
            <span>Charge total</span>
            <span className={s.mono}>AED {formatMoney(chargeTotal)}</span>
          </div>
          {changeDue > 0 && (
            <div className={s.changeDue} data-testid="change-due">
              Change due: AED {formatMoney(changeDue)}
            </div>
          )}
          <div className={s.keypad} role="group" aria-label="Numeric keypad">
            {["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "⌫"].map((k) => (
              <button key={k} type="button" className={s.key} onClick={() => appendKey(k)}>
                {k}
              </button>
            ))}
            <button
              type="button"
              className={`${s.key} ${s.keyWide} ${s.keyClear}`}
              onClick={() => appendKey("C")}
            >
              Clear
            </button>
            <button
              type="button"
              className={`${s.key} ${s.keyExact}`}
              onClick={() => setAmountInput(formatMoney(totalDue))}
            >
              Exact
            </button>
          </div>
          {actionError && (
            <p className={s.error} role="alert">
              {actionError}
            </p>
          )}
          {lastTxn && (
            <p className={s.success} data-testid="last-txn">
              Last: {lastTxn.tender_type || tender} · {lastTxn.status} · AED {lastTxn.amount_aed}
            </p>
          )}
        </section>
      </div>

      {/* ── action bar ─────────────────────────────────────────────────── */}
      <div className={s.actionBar}>
        <button
          type="button"
          className={s.confirmBtn}
          onClick={() => void confirmPayment()}
          disabled={busy || pinBusy || stale}
          data-testid="confirm-payment"
          title={stale ? "Refreshing the bill…" : undefined}
        >
          {busy ? "Processing…" : stale ? "Refreshing bill…" : "✔ Confirm Payment"}
        </button>
        <button
          type="button"
          className={s.act}
          onClick={() => toast("Receipt print queued (when printer configured).")}
        >
          🖨 Print Bill
        </button>
        <button
          type="button"
          className={s.act}
          onClick={() => toast("Receipt share via WhatsApp/email is not configured here.")}
        >
          ✉ Email / WhatsApp
        </button>
        <button type="button" className={s.act} onClick={() => void handleOpenDrawer()}>
          💵 Open Drawer
        </button>
        <span className={s.spacer} />
        <span className={s.barMeta}>
          {detail.order_number || `#${detail.id}`} · AED {detail.total}
        </span>
      </div>

      {pinGate}
    </div>
  );
}
