import { useEffect, useState } from "react";
import { Button } from "./Button";
import { fetchConversationContext } from "../lib/conversationsApi";
import { issueCouponToCustomer } from "../lib/couponsApi";
import { creditWallet, debitWallet } from "../lib/walletApi";
import type { ChatCustomerContext } from "../lib/types";
import s from "./ChatCustomerPanel.module.css";

/**
 * In-chat manager actions: shows who the customer is, their wallet balance and
 * recent orders (so the manager knows which order/details), and lets them issue a
 * coupon or adjust the wallet right from the conversation.
 */
export function ChatCustomerPanel({
  conversationId,
  onSendToCustomer,
}: {
  conversationId: number;
  onSendToCustomer?: (text: string) => void;
}) {
  const [ctx, setCtx] = useState<ChatCustomerContext | null>(null);
  const [open, setOpen] = useState(false);
  const [couponAmt, setCouponAmt] = useState("");
  const [walletAmt, setWalletAmt] = useState("");
  const [walletReason, setWalletReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function reload() {
    const c = await fetchConversationContext(conversationId);
    setCtx(c);
  }

  useEffect(() => {
    setCtx(null);
    setMsg(null);
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  if (!ctx) return null;
  if (ctx.customer_id === null) {
    return <div className={s.note}>No customer record yet for {ctx.phone}.</div>;
  }
  const cid = ctx.customer_id;

  async function issueCoupon() {
    setBusy(true);
    setMsg(null);
    try {
      const c = await issueCouponToCustomer(cid, couponAmt);
      setCouponAmt("");
      setMsg(`Coupon ${c.code} (AED ${c.discount_aed}) issued.`);
      onSendToCustomer?.(`Here's a coupon for you: ${c.code} — AED ${c.discount_aed} off your next order. 🎁`);
      reload();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Could not issue coupon.");
    } finally {
      setBusy(false);
    }
  }

  async function adjustWallet(kind: "credit" | "debit") {
    setBusy(true);
    setMsg(null);
    try {
      const fn = kind === "credit" ? creditWallet : debitWallet;
      const w = await fn(cid, walletAmt, walletReason || "manager adjustment");
      setWalletAmt("");
      setWalletReason("");
      setMsg(`Wallet updated. New balance AED ${w.balance_aed}.`);
      reload();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Could not adjust wallet.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={s.panel}>
      <button type="button" className={s.header} onClick={() => setOpen((o) => !o)}>
        <span>
          {ctx.name ?? ctx.phone} · Wallet AED {ctx.wallet_balance_aed}
          {ctx.wallet_status === "frozen" ? " (frozen)" : ""}
        </span>
        <span>{open ? "▲" : "▼ actions"}</span>
      </button>

      {open && (
        <div className={s.body}>
          <div className={s.section}>
            <span className={s.label}>Recent orders</span>
            {ctx.recent_orders.length === 0 ? (
              <p className={s.muted}>No orders yet.</p>
            ) : (
              <ul className={s.orders}>
                {ctx.recent_orders.map((o) => (
                  <li key={o.id}>
                    <span className={s.code}>{o.order_number}</span> · {o.status} · AED {o.total_aed}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className={s.section}>
            <span className={s.label}>Issue coupon (AED off, single-use)</span>
            <div className={s.row}>
              <input
                type="number" min="0" step="0.01" placeholder="amount"
                value={couponAmt} onChange={(e) => setCouponAmt(e.target.value)}
                aria-label="coupon amount"
              />
              <Button disabled={busy || !(Number(couponAmt) > 0)} onClick={issueCoupon}>
                Issue
              </Button>
            </div>
          </div>

          <div className={s.section}>
            <span className={s.label}>Adjust wallet</span>
            <div className={s.row}>
              <input
                type="number" min="0" step="0.01" placeholder="amount"
                value={walletAmt} onChange={(e) => setWalletAmt(e.target.value)}
                aria-label="wallet amount"
              />
              <input
                type="text" placeholder="reason"
                value={walletReason} onChange={(e) => setWalletReason(e.target.value)}
                aria-label="wallet reason"
              />
              <Button disabled={busy || !(Number(walletAmt) > 0)} onClick={() => adjustWallet("credit")}>
                Credit
              </Button>
              <Button variant="ghost" disabled={busy || !(Number(walletAmt) > 0)} onClick={() => adjustWallet("debit")}>
                Deduct
              </Button>
            </div>
          </div>

          {msg && <p className={s.msg}>{msg}</p>}
        </div>
      )}
    </div>
  );
}
