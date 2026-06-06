import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { SectionBanner } from "../components/SectionBanner";
import { apiClient } from "../lib/apiClient";
import type { RestaurantOut } from "../lib/types";
import s from "./SettingsScreen.module.css";

type Tab = "general" | "fees" | "batching";

export function SettingsScreen() {
  const [me, setMe] = useState<RestaurantOut | null>(null);
  const [tab, setTab] = useState<Tab>("batching");
  const [ordersPerBatch, setOrdersPerBatch] = useState(3);
  const [itemsPerOrder, setItemsPerOrder] = useState(20);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    apiClient.get<RestaurantOut>("/api/v1/me").then((r) => {
      setMe(r);
      const sset = r.settings as Record<string, number>;
      if (typeof sset.max_orders_per_batch === "number") setOrdersPerBatch(sset.max_orders_per_batch);
      if (typeof sset.max_items_per_order === "number") setItemsPerOrder(sset.max_items_per_order);
    });
  }, []);

  async function save() {
    await apiClient.patch("/api/v1/settings", {
      max_orders_per_batch: ordersPerBatch,
      max_items_per_order: itemsPerOrder,
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <div className={s.screen}>
      <div className={s.tabs}>
        {(["general", "fees", "batching"] as Tab[]).map((t) => (
          <button key={t} className={`${s.tab} ${tab === t ? s.active : ""}`} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>

      {saved && <SectionBanner tone="success">Settings saved.</SectionBanner>}

      {tab === "general" && (
        <div className={s.section}>
          <Field label="Restaurant" value={me?.name ?? "—"} />
          <Field label="Phone" value={me?.phone ?? "—"} />
        </div>
      )}

      {tab === "fees" && (
        <div className={s.section}>
          <p className={s.note}>Fee tiers: ≤3km free · 3–5km AED 5 · &gt;5km AED 10. Max radius 10 km.</p>
        </div>
      )}

      {tab === "batching" && (
        <div className={s.section}>
          <label className={s.field}>
            <span className="label-upper">Max orders per batch</span>
            <input
              aria-label="orders per batch"
              type="number"
              min={1}
              max={6}
              value={ordersPerBatch}
              onChange={(e) => setOrdersPerBatch(Number(e.target.value))}
            />
          </label>
          <label className={s.field}>
            <span className="label-upper">Max items per order</span>
            <input
              aria-label="items per order"
              type="number"
              min={1}
              max={100}
              value={itemsPerOrder}
              onChange={(e) => setItemsPerOrder(Number(e.target.value))}
            />
          </label>
          <Button onClick={save}>Save</Button>
        </div>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className={s.field}>
      <span className="label-upper">{label}</span>
      <span>{value}</span>
    </div>
  );
}
