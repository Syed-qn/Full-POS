import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { BottomActionBar } from "../components/BottomActionBar";
import { Button, TouchButton } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { MoneySummary } from "../components/MoneySummary";
import { OfflineLimitsBanner } from "../components/OfflineLimitsBanner";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
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
  const [searchParams] = useSearchParams();
  const splitFromQuery = searchParams.get("split") === "1";

  const [detail, setDetail] = useState<OrderDetailOut | null>(null);
  const [basic, setBasic] = useState<OrderOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [paidAed, setPaidAed] = useState("0.00");
  const [lastTxn, setLastTxn] = useState<PaymentTxn | null>(null);

  const [tender, setTender] = useState("cash");
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
      setDetail(d);
      setBasic(orderOutFromDetail(d));
      try {
        const pay = await listOrderPayments(orderId);
        setPaidAed(pay.total_paid_aed ?? "0.00");
        setTxns(Array.isArray(pay.transactions) ? pay.transactions : []);
      } catch {
        setPaidAed("0.00");
        setTxns([]);
      }
    } catch (e) {
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
        toast(`Payment ${txn.status}`);
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
      setLastTxn(txn);
      toast(`Payment ${txn.status || "recorded"}`);
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

  if (!Number.isFinite(orderId) || orderId <= 0) {
    return (
      <ErrorState
        title="Invalid checkout"
        description="Order id is required."
        action={
          <Link to="/orders">
            <Button>Orders</Button>
          </Link>
        }
      />
    );
  }

  if (loading && !detail) {
    return (
      <div className={s.root} data-testid="checkout-screen">
        <PageHeader title="Checkout" />
        <EmptyState title="Loading bill…" />
      </div>
    );
  }

  if (error || !detail || !basic) {
    return (
      <div className={s.root} data-testid="checkout-screen">
        <PageHeader title="Checkout" />
        <ErrorState
          title="Could not load checkout"
          description={error || "Order not found"}
          action={
            <Button type="button" onClick={() => void load()}>
              Retry
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className={s.root} data-testid="checkout-screen">
      <PageHeader
        title="Checkout"
        subtitle={`Order ${detail.order_number || `#${detail.id}`} · ${basic.customer_name || basic.customer_phone}`}
        right={
          <Link to={`/orders/${detail.id}`}>
            <Button variant="ghost" size="lg">
              Back to order
            </Button>
          </Link>
        }
      />
      <OfflineLimitsBanner surface="checkout" />

      <div className={s.grid}>
        {/* Left — bill */}
        <section className={s.panel} aria-label="Bill summary">
          <h3 className={s.panelTitle}>Bill</h3>
          <div className={s.splitBar}>
            <Button
              type="button"
              variant={splitMode ? "primary" : "ghost"}
              size="md"
              onClick={() => setSplitMode((v) => !v)}
            >
              {splitMode ? "Split on" : "Split mode"}
            </Button>
            {splitMode && (
              <span className={s.splitOn} data-testid="split-mode-badge">
                Split active — enter partial amount
              </span>
            )}
          </div>
          {detail.items.map((item, i) => (
            <div key={i} className={s.itemRow}>
              <div>
                <div className={s.itemName}>
                  {item.qty}× {item.dish_name}
                </div>
                {item.notes && <div className={s.itemMeta}>{item.notes}</div>}
              </div>
              <div className={s.itemName}>AED {item.line_total}</div>
            </div>
          ))}
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
          <div className={s.line}>
            <span>Order total</span>
            <span>AED {detail.total}</span>
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
        </section>

        {/* Right — amount + keypad */}
        <section className={s.panel} aria-label="Amount and keypad">
          <div className={s.amountBox}>
            <MoneySummary label="Amount due" amount={formatMoney(totalDue)} size="lg" />
          </div>
          <div className={s.line}>
            <span>Tender amount</span>
            <span className="mono">AED {amountInput || "0.00"}</span>
          </div>
          {tipAed > 0 && (
            <div className={s.line}>
              <span>Tip</span>
              <span>AED {formatMoney(tipAed)}</span>
            </div>
          )}
          <div className={s.line}>
            <span>Charge total</span>
            <span>AED {formatMoney(chargeTotal)}</span>
          </div>
          {changeDue > 0 && (
            <div className={s.changeDue} data-testid="change-due">
              Change due: AED {formatMoney(changeDue)}
            </div>
          )}
          <div className={s.keypad} role="group" aria-label="Numeric keypad">
            {["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "⌫"].map((k) => (
              <button
                key={k}
                type="button"
                className={s.key}
                onClick={() => appendKey(k)}
              >
                {k}
              </button>
            ))}
            <button
              type="button"
              className={`${s.key} ${s.keyWide}`}
              onClick={() => appendKey("C")}
            >
              Clear
            </button>
            <button
              type="button"
              className={s.key}
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
              Last: {lastTxn.tender_type || tender} · {lastTxn.status} · AED{" "}
              {lastTxn.amount_aed}
            </p>
          )}

          <h3 className={s.panelTitle}>Manager discount</h3>
          <div className={s.line}>
            <input
              className={s.input}
              aria-label="Manager discount amount"
              value={discountAmt}
              onChange={(e) => setDiscountAmt(e.target.value)}
              placeholder="AED"
            />
            <Button
              type="button"
              variant="ghost"
              size="md"
              disabled={busy || pinBusy}
              onClick={requestManagerDiscount}
            >
              Apply discount…
            </Button>
          </div>

          {refundableTxns.length > 0 && (
            <>
              <h3 className={s.panelTitle}>Refund</h3>
              {refundableTxns.map((txn) => (
                <div key={txn.id} className={s.line}>
                  <span>
                    #{txn.id} · {txn.tender_type || "pay"} · AED {txn.amount_aed}
                  </span>
                  <Button
                    type="button"
                    variant="danger"
                    size="md"
                    disabled={busy || pinBusy}
                    onClick={() => requestRefund(txn)}
                  >
                    Refund…
                  </Button>
                </div>
              ))}
            </>
          )}
        </section>
      </div>

      <BottomActionBar>
        <TouchButton type="button" onClick={() => void confirmPayment()} disabled={busy || pinBusy}>
          {busy ? "Processing…" : "Confirm Payment"}
        </TouchButton>
        <Button
          type="button"
          variant="ghost"
          size="lg"
          onClick={() => toast("Receipt print queued (when printer configured).")}
        >
          Print
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="lg"
          onClick={() => toast("Receipt share via WhatsApp/email is not configured here.")}
        >
          Email / WhatsApp
        </Button>
        <Button type="button" variant="ghost" size="lg" onClick={() => void handleOpenDrawer()}>
          Open Drawer
        </Button>
      </BottomActionBar>

      {pinGate}
    </div>
  );
}
