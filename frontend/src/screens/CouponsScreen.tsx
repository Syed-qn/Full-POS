import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { PageHeader } from "../components/PageHeader";
import { createCoupon, listCoupons, pauseCoupon } from "../lib/couponsApi";
import type { Coupon, CouponCreateIn, CouponDiscountType, CouponKind } from "../lib/types";
import s from "./CouponsScreen.module.css";

export function CouponsScreen() {
  const [coupons, setCoupons] = useState<Coupon[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // create form
  const [discountType, setDiscountType] = useState<CouponDiscountType>("fixed");
  const [value, setValue] = useState("");
  const [kind, setKind] = useState<CouponKind>("multi_use");
  const [minOrder, setMinOrder] = useState("");
  const [maxDiscount, setMaxDiscount] = useState("");
  const [perCustomer, setPerCustomer] = useState("");
  const [totalLimit, setTotalLimit] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function reload() {
    listCoupons()
      .then(setCoupons)
      .catch(() => setCoupons([]))
      .finally(() => setLoaded(true));
  }

  useEffect(() => {
    reload();
  }, []);

  const valueOk = Number(value) > 0;

  async function submit() {
    setSubmitting(true);
    setError(null);
    const body: CouponCreateIn = {
      discount_type: discountType,
      discount_value: value,
      kind,
      ...(minOrder ? { min_order_aed: minOrder } : {}),
      ...(discountType === "percent" && maxDiscount ? { max_discount_aed: maxDiscount } : {}),
      ...(perCustomer ? { per_customer_limit: Number(perCustomer) } : {}),
      ...(totalLimit ? { total_redemption_limit: Number(totalLimit) } : {}),
    };
    try {
      await createCoupon(body);
      setValue("");
      setMinOrder("");
      setMaxDiscount("");
      setPerCustomer("");
      setTotalLimit("");
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create coupon.");
    } finally {
      setSubmitting(false);
    }
  }

  async function onPause(code: string) {
    try {
      await pauseCoupon(code);
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not pause coupon.");
    }
  }

  function discountLabel(c: Coupon): string {
    if (c.discount_type === "percent") {
      return `${c.percent}%${c.max_discount_aed ? ` (max AED ${c.max_discount_aed})` : ""}`;
    }
    return `AED ${c.discount_aed}`;
  }

  return (
    <div className={s.root}>
      <PageHeader title="Coupons" subtitle="Create and manage discount coupons" />

      <section className={s.card}>
        <h3 className={s.cardTitle}>New coupon</h3>
        <div className={s.form}>
          <label className={s.field}>
            <span>Type</span>
            <select value={discountType} onChange={(e) => setDiscountType(e.target.value as CouponDiscountType)}>
              <option value="fixed">Fixed (AED)</option>
              <option value="percent">Percent (%)</option>
            </select>
          </label>
          <label className={s.field}>
            <span>{discountType === "percent" ? "Percent" : "Amount (AED)"}</span>
            <input type="number" min="0" step="0.01" value={value} onChange={(e) => setValue(e.target.value)} />
          </label>
          <label className={s.field}>
            <span>Kind</span>
            <select value={kind} onChange={(e) => setKind(e.target.value as CouponKind)}>
              <option value="multi_use">Multi-use</option>
              <option value="single_use">Single-use</option>
            </select>
          </label>
          <label className={s.field}>
            <span>Min order (AED)</span>
            <input type="number" min="0" step="0.01" value={minOrder} onChange={(e) => setMinOrder(e.target.value)} />
          </label>
          {discountType === "percent" && (
            <label className={s.field}>
              <span>Max discount (AED)</span>
              <input type="number" min="0" step="0.01" value={maxDiscount} onChange={(e) => setMaxDiscount(e.target.value)} />
            </label>
          )}
          <label className={s.field}>
            <span>Per-customer limit</span>
            <input type="number" min="1" value={perCustomer} onChange={(e) => setPerCustomer(e.target.value)} />
          </label>
          <label className={s.field}>
            <span>Total limit</span>
            <input type="number" min="1" value={totalLimit} onChange={(e) => setTotalLimit(e.target.value)} />
          </label>
        </div>
        <Button disabled={submitting || !valueOk} onClick={submit}>
          Create coupon
        </Button>
        {error && <p className={s.error}>{error}</p>}
      </section>

      {!loaded && <div className={s.list} aria-busy="true" aria-label="Loading coupons" />}

      {loaded && coupons.length === 0 && (
        <div className={s.empty}>No coupons yet — create one above.</div>
      )}

      {loaded && coupons.length > 0 && (
        <table className={s.table}>
          <thead>
            <tr>
              <th>Code</th>
              <th>Discount</th>
              <th>Kind</th>
              <th>Min order</th>
              <th>Limits</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {coupons.map((c) => (
              <tr key={c.id}>
                <td className={s.code}>{c.code}</td>
                <td>{discountLabel(c)}</td>
                <td>{c.kind.replace("_", " ")}</td>
                <td>AED {c.min_order_aed}</td>
                <td>
                  {c.per_customer_limit ? `${c.per_customer_limit}/cust` : "—"}
                  {c.total_redemption_limit ? ` · ${c.total_redemption_limit} total` : ""}
                </td>
                <td>
                  <span className={`${s.status} ${s[c.status] ?? ""}`}>{c.status}</span>
                </td>
                <td>
                  {c.status === "active" && (
                    <Button variant="ghost" onClick={() => onPause(c.code)}>
                      Pause
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
