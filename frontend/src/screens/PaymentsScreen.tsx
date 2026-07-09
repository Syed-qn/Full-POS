import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { PageHeader } from "../components/PageHeader";
import { SectionBanner } from "../components/SectionBanner";
import { toast } from "../components/Toaster";
import {
  addCashDrawerEvent,
  applyOrderDiscount,
  chargePayment,
  closeCashDrawer,
  createPaymentLink,
  createWalletSession,
  getBillingSettings,
  getCurrentCashDrawer,
  getReconciliationReport,
  issueGiftCard,
  listGiftCards,
  listPaymentLinks,
  markPayLater,
  openCashDrawer,
  redeemGiftCard,
  setBillingSettings,
  type BillingSettings,
  type CashDrawerSession,
  type GiftCardOut,
  type PaymentLinkOut,
} from "../lib/paymentsApi";
import s from "./PaymentsScreen.module.css";

const TENDERS = [
  "cash",
  "card",
  "tap_to_pay",
  "apple_pay",
  "google_pay",
  "online",
  "wallet",
  "room_charge",
  "pay_later",
] as const;

export function PaymentsScreen() {
  const [billing, setBilling] = useState<BillingSettings | null>(null);
  const [drawer, setDrawer] = useState<CashDrawerSession | null>(null);
  const [links, setLinks] = useState<PaymentLinkOut[]>([]);
  const [giftCards, setGiftCards] = useState<GiftCardOut[]>([]);
  const [recon, setRecon] = useState<{
    gateway_txn_count: number;
    matched_line_count: number;
    unmatched_txn_count: number;
    gateway_total_aed: string;
    matched_total_aed: string;
  } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const [orderId, setOrderId] = useState("");
  const [amount, setAmount] = useState("10.00");
  const [tip, setTip] = useState("0.00");
  const [tender, setTender] = useState<(typeof TENDERS)[number]>("cash");
  const [roomNumber, setRoomNumber] = useState("");
  const [terminalId, setTerminalId] = useState("softpos-1");
  const [busy, setBusy] = useState(false);

  const [floatAmt, setFloatAmt] = useState("200.00");
  const [cashEventAmt, setCashEventAmt] = useState("50.00");
  const [closeCount, setCloseCount] = useState("200.00");

  const [svcPct, setSvcPct] = useState("0");
  const [packFee, setPackFee] = useState("0");
  const [minOrder, setMinOrder] = useState("0");

  const [gcAmount, setGcAmount] = useState("50.00");
  const [gcPin, setGcPin] = useState("1234");
  const [gcCode, setGcCode] = useState("");
  const [gcRedeemCode, setGcRedeemCode] = useState("");
  const [gcRedeemPin, setGcRedeemPin] = useState("");
  const [discountAmt, setDiscountAmt] = useState("5.00");
  const [discountType, setDiscountType] = useState<"manager" | "staff">("manager");

  async function load() {
    setLoadError(null);
    try {
      const [b, linkRows, cards, report] = await Promise.all([
        getBillingSettings().catch(() => null),
        listPaymentLinks().catch(() => []),
        listGiftCards().catch(() => []),
        getReconciliationReport().catch(() => null),
      ]);
      setBilling(b);
      if (b) {
        setSvcPct(String(b.service_charge_pct ?? 0));
        setPackFee(String(b.packaging_charge_aed ?? 0));
        setMinOrder(String(b.min_order_aed ?? 0));
      }
      setLinks(Array.isArray(linkRows) ? linkRows : []);
      setGiftCards(Array.isArray(cards) ? cards : []);
      setRecon(report);
      try {
        setDrawer(await getCurrentCashDrawer());
      } catch {
        setDrawer(null);
      }
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Could not load payments.");
    } finally {
      setLoaded(true);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function runCharge() {
    const oid = Number(orderId);
    if (!oid) {
      toast("Order ID is required.", "error");
      return;
    }
    setBusy(true);
    try {
      let walletSessionId: string | undefined;
      if (tender === "apple_pay" || tender === "google_pay" || tender === "tap_to_pay") {
        const session = await createWalletSession({
          order_id: oid,
          tender_type: tender,
          amount_aed: amount,
        });
        walletSessionId = session.session_id;
      }
      if (tender === "pay_later") {
        await markPayLater(oid, amount);
        toast("Pay-later recorded.");
      } else {
        const txn = await chargePayment({
          order_id: oid,
          tender_type: tender,
          amount_aed: amount,
          tip_aed: tip,
          channel: tender === "tap_to_pay" ? "terminal" : tender === "online" ? "online" : "till",
          room_number: tender === "room_charge" ? roomNumber || undefined : undefined,
          terminal_id: tender === "tap_to_pay" ? terminalId || undefined : undefined,
          wallet_session_id: walletSessionId,
        });
        toast(`Charged ${txn.amount_aed} via ${tender} (${txn.status}).`);
      }
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Charge failed.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function runLink() {
    const oid = Number(orderId);
    if (!oid) {
      toast("Order ID is required.", "error");
      return;
    }
    setBusy(true);
    try {
      const link = await createPaymentLink(oid, amount || undefined);
      toast(`Payment link created: ${link.token.slice(0, 8)}…`);
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not create link.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function saveBilling() {
    setBusy(true);
    try {
      const next = await setBillingSettings({
        service_charge_pct: Number(svcPct),
        packaging_charge_aed: Number(packFee),
        min_order_aed: Number(minOrder),
      });
      setBilling(next);
      toast("Billing settings saved.");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save billing settings.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function runDiscount() {
    const oid = Number(orderId);
    if (!oid) {
      toast("Order ID is required.", "error");
      return;
    }
    setBusy(true);
    try {
      await applyOrderDiscount(oid, {
        discount_type: discountType,
        amount_aed: discountAmt,
        reason: `${discountType} discount from payments screen`,
      });
      toast(`${discountType} discount applied.`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Discount failed.", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={s.screen}>
      <PageHeader
        title="Payments & billing"
        subtitle="Till charge, wallet pays, payment links, cash drawer, gift cards, recon"
        right={
          <Button type="button" variant="ghost" onClick={() => void load()}>
            Refresh
          </Button>
        }
      />

      {loadError && <SectionBanner tone="warning">{loadError}</SectionBanner>}

      <section className={s.metrics}>
        <div className={s.metric}>
          <span className={s.metricLabel}>Service charge %</span>
          <strong>{billing?.service_charge_pct ?? "—"}</strong>
        </div>
        <div className={s.metric}>
          <span className={s.metricLabel}>Packaging AED</span>
          <strong>{billing?.packaging_charge_aed ?? "—"}</strong>
        </div>
        <div className={s.metric}>
          <span className={s.metricLabel}>Min order AED</span>
          <strong>{billing?.min_order_aed ?? "—"}</strong>
        </div>
        <div className={s.metric}>
          <span className={s.metricLabel}>Drawer</span>
          <strong>{drawer ? drawer.status : "closed"}</strong>
        </div>
      </section>

      <section className={s.card}>
        <div className={s.cardHead}>
          <h2>Till / POS charge</h2>
          <span>Cash, card, tap-to-pay, Apple/Google Pay, online, room charge, pay later.</span>
        </div>
        <div className={s.formGrid}>
          <label>
            <span>Order ID</span>
            <input
              aria-label="Payment order id"
              value={orderId}
              onChange={(e) => setOrderId(e.target.value)}
            />
          </label>
          <label>
            <span>Amount AED</span>
            <input aria-label="Payment amount" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </label>
          <label>
            <span>Tip AED</span>
            <input aria-label="Payment tip" value={tip} onChange={(e) => setTip(e.target.value)} />
          </label>
          <label>
            <span>Tender</span>
            <select
              className={s.select}
              aria-label="Payment tender"
              value={tender}
              onChange={(e) => setTender(e.target.value as (typeof TENDERS)[number])}
            >
              {TENDERS.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Room number</span>
            <input
              aria-label="Room number"
              value={roomNumber}
              onChange={(e) => setRoomNumber(e.target.value)}
            />
          </label>
          <label>
            <span>Terminal ID</span>
            <input
              aria-label="Terminal id"
              value={terminalId}
              onChange={(e) => setTerminalId(e.target.value)}
            />
          </label>
        </div>
        <div className={s.actions}>
          <Button type="button" disabled={busy} onClick={() => void runCharge()}>
            Charge
          </Button>
          <Button type="button" variant="ghost" disabled={busy} onClick={() => void runLink()}>
            Create payment link
          </Button>
        </div>
      </section>

      <section className={s.card}>
        <div className={s.cardHead}>
          <h2>Manager / staff discount</h2>
          <span>Discretionary till discounts on the selected order.</span>
        </div>
        <div className={s.formGrid}>
          <label>
            <span>Type</span>
            <select
              className={s.select}
              aria-label="Discount type"
              value={discountType}
              onChange={(e) => setDiscountType(e.target.value as "manager" | "staff")}
            >
              <option value="manager">manager</option>
              <option value="staff">staff</option>
            </select>
          </label>
          <label>
            <span>Amount AED</span>
            <input
              aria-label="Discount amount"
              value={discountAmt}
              onChange={(e) => setDiscountAmt(e.target.value)}
            />
          </label>
        </div>
        <Button type="button" disabled={busy} onClick={() => void runDiscount()}>
          Apply discount
        </Button>
      </section>

      <section className={s.grid}>
        <div className={s.card}>
          <div className={s.cardHead}>
            <h2>Cash drawer</h2>
            <span>Open / cash in-out / close with over-short variance.</span>
          </div>
          <div className={s.formGrid}>
            <label>
              <span>Opening float</span>
              <input
                aria-label="Opening float"
                value={floatAmt}
                onChange={(e) => setFloatAmt(e.target.value)}
              />
            </label>
            <label>
              <span>Cash event amount</span>
              <input
                aria-label="Cash event amount"
                value={cashEventAmt}
                onChange={(e) => setCashEventAmt(e.target.value)}
              />
            </label>
            <label>
              <span>Closing count</span>
              <input
                aria-label="Closing count"
                value={closeCount}
                onChange={(e) => setCloseCount(e.target.value)}
              />
            </label>
          </div>
          <div className={s.actions}>
            <Button
              type="button"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const d = await openCashDrawer(floatAmt);
                  setDrawer(d);
                  toast("Drawer opened.");
                } catch (e) {
                  toast(e instanceof Error ? e.message : "Open failed.", "error");
                } finally {
                  setBusy(false);
                }
              }}
            >
              Open drawer
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={busy || !drawer}
              onClick={async () => {
                if (!drawer) return;
                setBusy(true);
                try {
                  await addCashDrawerEvent(drawer.id, {
                    type: "cash_in",
                    amount_aed: cashEventAmt,
                    reason: "till top-up",
                  });
                  toast("Cash in recorded.");
                } catch (e) {
                  toast(e instanceof Error ? e.message : "Cash event failed.", "error");
                } finally {
                  setBusy(false);
                }
              }}
            >
              Cash in
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={busy || !drawer}
              onClick={async () => {
                if (!drawer) return;
                setBusy(true);
                try {
                  await addCashDrawerEvent(drawer.id, {
                    type: "cash_out",
                    amount_aed: cashEventAmt,
                    reason: "safe drop",
                  });
                  toast("Cash out recorded.");
                } catch (e) {
                  toast(e instanceof Error ? e.message : "Cash event failed.", "error");
                } finally {
                  setBusy(false);
                }
              }}
            >
              Cash out
            </Button>
            <Button
              type="button"
              disabled={busy || !drawer}
              onClick={async () => {
                if (!drawer) return;
                setBusy(true);
                try {
                  const d = await closeCashDrawer(drawer.id, closeCount);
                  setDrawer(d);
                  toast(`Drawer closed. Variance ${d.variance_aed ?? "0"}`);
                } catch (e) {
                  toast(e instanceof Error ? e.message : "Close failed.", "error");
                } finally {
                  setBusy(false);
                }
              }}
            >
              Close drawer
            </Button>
          </div>
          {drawer && (
            <div className={s.listItem}>
              <strong>
                Session #{drawer.id} — {drawer.status}
              </strong>
              <span>
                float {drawer.opening_float_aed}
                {drawer.variance_aed != null ? ` · variance ${drawer.variance_aed}` : ""}
              </span>
            </div>
          )}
        </div>

        <div className={s.sideStack}>
          <div className={s.card}>
            <div className={s.cardHead}>
              <h2>Billing settings</h2>
              <span>Service charge, packaging, minimum order surcharge.</span>
            </div>
            <div className={s.formGrid}>
              <label>
                <span>Service charge %</span>
                <input
                  aria-label="Service charge percent"
                  value={svcPct}
                  onChange={(e) => setSvcPct(e.target.value)}
                />
              </label>
              <label>
                <span>Packaging AED</span>
                <input
                  aria-label="Packaging charge"
                  value={packFee}
                  onChange={(e) => setPackFee(e.target.value)}
                />
              </label>
              <label>
                <span>Min order AED</span>
                <input
                  aria-label="Minimum order amount"
                  value={minOrder}
                  onChange={(e) => setMinOrder(e.target.value)}
                />
              </label>
            </div>
            <Button type="button" disabled={busy} onClick={() => void saveBilling()}>
              Save billing settings
            </Button>
          </div>

          <div className={s.card}>
            <div className={s.cardHead}>
              <h2>Gift cards</h2>
              <span>Issue code+PIN cards and redeem at till.</span>
            </div>
            <div className={s.formGrid}>
              <label>
                <span>Issue amount</span>
                <input
                  aria-label="Gift card amount"
                  value={gcAmount}
                  onChange={(e) => setGcAmount(e.target.value)}
                />
              </label>
              <label>
                <span>PIN</span>
                <input aria-label="Gift card pin" value={gcPin} onChange={(e) => setGcPin(e.target.value)} />
              </label>
              <label>
                <span>Code (optional)</span>
                <input
                  aria-label="Gift card code"
                  value={gcCode}
                  onChange={(e) => setGcCode(e.target.value)}
                />
              </label>
              <label>
                <span>Redeem code</span>
                <input
                  aria-label="Redeem gift code"
                  value={gcRedeemCode}
                  onChange={(e) => setGcRedeemCode(e.target.value)}
                />
              </label>
              <label>
                <span>Redeem PIN</span>
                <input
                  aria-label="Redeem gift pin"
                  value={gcRedeemPin}
                  onChange={(e) => setGcRedeemPin(e.target.value)}
                />
              </label>
            </div>
            <div className={s.actions}>
              <Button
                type="button"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    const card = await issueGiftCard({
                      amount_aed: gcAmount,
                      pin: gcPin,
                      code: gcCode || undefined,
                    });
                    toast(`Issued ${card.code} balance ${card.balance_aed}`);
                    await load();
                  } catch (e) {
                    toast(e instanceof Error ? e.message : "Issue failed.", "error");
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Issue card
              </Button>
              <Button
                type="button"
                variant="ghost"
                disabled={busy}
                onClick={async () => {
                  const oid = Number(orderId);
                  if (!oid) {
                    toast("Order ID required to redeem.", "error");
                    return;
                  }
                  setBusy(true);
                  try {
                    await redeemGiftCard({
                      code: gcRedeemCode,
                      pin: gcRedeemPin,
                      order_id: oid,
                      amount_aed: amount,
                    });
                    toast("Gift card redeemed.");
                    await load();
                  } catch (e) {
                    toast(e instanceof Error ? e.message : "Redeem failed.", "error");
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Redeem on order
              </Button>
            </div>
            <div className={s.list}>
              {giftCards.slice(0, 6).map((c) => (
                <div key={c.id} className={s.listItem}>
                  <strong>
                    {c.code} — {c.status}
                  </strong>
                  <span>balance {c.balance_aed}</span>
                </div>
              ))}
              {loaded && giftCards.length === 0 && <div className={s.empty}>No gift cards yet.</div>}
            </div>
          </div>

          <div className={s.card}>
            <div className={s.cardHead}>
              <h2>Payment links</h2>
              <span>Shareable online pay URLs.</span>
            </div>
            <div className={s.list}>
              {links.slice(0, 8).map((l) => (
                <div key={l.id} className={s.listItem}>
                  <strong>
                    Order #{l.order_id} — {l.status}
                  </strong>
                  <span>
                    {l.amount_aed} · {l.url}
                  </span>
                </div>
              ))}
              {loaded && links.length === 0 && <div className={s.empty}>No payment links.</div>}
            </div>
          </div>

          <div className={s.card}>
            <div className={s.cardHead}>
              <h2>PSP reconciliation</h2>
              <span>Gateway charges matched to imported settlements.</span>
            </div>
            {recon ? (
              <div className={s.list}>
                <div className={s.listItem}>
                  <strong>
                    Gateway {recon.gateway_txn_count} · matched {recon.matched_line_count}
                  </strong>
                  <span>
                    total {recon.gateway_total_aed} · unmatched {recon.unmatched_txn_count}
                  </span>
                </div>
              </div>
            ) : (
              <div className={s.empty}>No recon data.</div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
