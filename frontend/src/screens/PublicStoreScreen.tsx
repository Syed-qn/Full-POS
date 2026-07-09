import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { Button } from "../components/Button";
import {
  fetchPublicStoreMenu,
  placePublicStoreOrder,
} from "../lib/channelsApi";
import s from "./ChannelsScreen.module.css";

type MenuItem = {
  id: number;
  name: string;
  description?: string | null;
  price_aed: string;
  category?: string | null;
};

export function PublicStoreScreen() {
  const { slug = "" } = useParams();
  const [params] = useSearchParams();
  const channel = params.get("channel") || "website";
  const [items, setItems] = useState<MenuItem[]>([]);
  const [cart, setCart] = useState<Record<number, number>>({});
  const [phone, setPhone] = useState("+9715");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [orderNum, setOrderNum] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!slug) return;
    fetchPublicStoreMenu(slug, channel)
      .then(setItems)
      .catch((e) => setError(e instanceof Error ? e.message : "Menu unavailable"));
  }, [slug, channel]);

  const cartLines = useMemo(
    () =>
      Object.entries(cart)
        .filter(([, qty]) => qty > 0)
        .map(([id, qty]) => ({ dish_id: Number(id), qty })),
    [cart],
  );

  async function checkout() {
    if (!slug || cartLines.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const res = await placePublicStoreOrder(slug, {
        customer_phone: phone,
        customer_name: name || undefined,
        items: cartLines,
        channel,
      });
      setOrderNum(res.order_number);
      setCart({});
    } catch (e) {
      setError(e instanceof Error ? e.message : "Order failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={s.screen} style={{ maxWidth: 720, margin: "24px auto", padding: 16 }}>
      <h1 style={{ margin: 0 }}>Order online</h1>
      <p style={{ color: "var(--text-secondary)" }}>
        {slug} · channel: {channel}
      </p>
      {error && <p className={s.error}>{error}</p>}
      {orderNum && (
        <div className={s.card}>
          <strong>Order placed: {orderNum}</strong>
          <span>Thank you — the kitchen has your order.</span>
        </div>
      )}
      <div className={s.grid}>
        {items.map((it) => (
          <div key={it.id} className={s.channelCard}>
            <div className={s.channelName}>{it.name}</div>
            {it.description && <span>{it.description}</span>}
            <div className={s.row}>
              <strong>AED {it.price_aed}</strong>
              <Button
                onClick={() =>
                  setCart((c) => ({ ...c, [it.id]: (c[it.id] || 0) + 1 }))
                }
              >
                Add {cart[it.id] ? `(${cart[it.id]})` : ""}
              </Button>
            </div>
          </div>
        ))}
      </div>
      <div className={s.card} style={{ marginTop: 16 }}>
        <div className={s.row}>
          <label>
            Phone
            <input value={phone} onChange={(e) => setPhone(e.target.value)} />
          </label>
          <label>
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <Button disabled={busy || cartLines.length === 0} onClick={() => void checkout()}>
            Place order ({cartLines.reduce((n, l) => n + l.qty, 0)} items)
          </Button>
        </div>
      </div>
    </div>
  );
}
