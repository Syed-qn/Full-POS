import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { ApiError } from "../lib/apiClient";
import {
  fetchPublicStoreMenu,
  placePublicStoreOrder,
} from "../lib/channelsApi";
import s from "./PublicStoreScreen.module.css";

type MenuItem = {
  id: number;
  name: string;
  description?: string | null;
  price_aed: string;
  category?: string | null;
  image_url?: string | null;
  is_available?: boolean;
};

const ALL = "All";

function money(aed: string | number): string {
  const n = typeof aed === "number" ? aed : Number(aed);
  if (Number.isNaN(n)) return `AED ${aed}`;
  return `AED ${n.toFixed(2)}`;
}

export function PublicStoreScreen() {
  const { slug = "" } = useParams();
  const [params] = useSearchParams();
  const channel = params.get("channel") || "website";
  // QR table ordering: ?table= locks the table (id) and cannot be changed in UI.
  const tableParam = params.get("table");
  const tableId = tableParam && /^\d+$/.test(tableParam) ? Number(tableParam) : null;
  const tableLabel = params.get("table_label") || (tableId != null ? `Table ${tableId}` : null);
  const tableLocked = tableParam != null && tableParam !== "";

  const [items, setItems] = useState<MenuItem[]>([]);
  const [cart, setCart] = useState<Record<number, number>>({});
  const [phone, setPhone] = useState("+9715");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [orderNum, setOrderNum] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [closed, setClosed] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [category, setCategory] = useState(ALL);
  const [storeName, setStoreName] = useState(slug);

  // Customer-facing page: use device width (manager shell forces 1440px).
  useEffect(() => {
    const meta = document.querySelector('meta[name="viewport"]');
    const prev = meta?.getAttribute("content") ?? null;
    meta?.setAttribute("content", "width=device-width, initial-scale=1");
    return () => {
      if (meta && prev !== null) meta.setAttribute("content", prev);
    };
  }, []);

  useEffect(() => {
    if (!slug) return;
    let alive = true;
    setLoading(true);
    setError(null);
    fetchPublicStoreMenu(slug, tableLocked ? "qr" : channel)
      .then((menu) => {
        if (!alive) return;
        setItems(menu);
        setStoreName(slug.replace(/-/g, " "));
      })
      .catch((e) => {
        if (!alive) return;
        const msg = e instanceof Error ? e.message : "Menu unavailable";
        setError(msg);
        if (
          e instanceof ApiError &&
          (e.status === 409 || /not accepting|closed|paused/i.test(e.detail))
        ) {
          setClosed(true);
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [slug, channel, tableLocked]);

  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const it of items) {
      if (it.category?.trim()) set.add(it.category.trim());
    }
    return [ALL, ...Array.from(set).sort()];
  }, [items]);

  const visible = useMemo(() => {
    if (category === ALL) return items;
    return items.filter((it) => (it.category ?? "").trim() === category);
  }, [items, category]);

  const cartLines = useMemo(
    () =>
      Object.entries(cart)
        .filter(([, qty]) => qty > 0)
        .map(([id, qty]) => ({ dish_id: Number(id), qty })),
    [cart],
  );

  const cartCount = cartLines.reduce((n, l) => n + l.qty, 0);

  const cartTotal = useMemo(() => {
    let total = 0;
    for (const line of cartLines) {
      const item = items.find((i) => i.id === line.dish_id);
      if (item) total += Number(item.price_aed) * line.qty;
    }
    return total;
  }, [cartLines, items]);

  function setQty(id: number, qty: number) {
    setCart((c) => {
      const next = { ...c };
      if (qty <= 0) delete next[id];
      else next[id] = qty;
      return next;
    });
  }

  function addOne(id: number) {
    setCart((c) => ({ ...c, [id]: (c[id] || 0) + 1 }));
  }

  async function checkout() {
    if (!slug || cartLines.length === 0 || closed) return;
    if (tableLocked && tableId == null) {
      setError("This QR link is missing a valid table id.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const orderChannel = tableLocked ? "qr" : channel;
      const res = await placePublicStoreOrder(slug, {
        customer_phone: phone,
        customer_name: name || undefined,
        items: cartLines,
        channel: orderChannel,
        ...(tableId != null ? { table_id: tableId } : {}),
      });
      setOrderNum(res.order_number);
      setCart({});
      setSheetOpen(false);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Order failed";
      if (
        e instanceof ApiError &&
        (e.status === 409 || /not accepting|closed|paused/i.test(e.detail || msg))
      ) {
        setClosed(true);
        setError(null);
      } else {
        setError(msg);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={s.page}>
      <header className={s.header}>
        <div className={s.brand}>
          <strong>{storeName || "Order online"}</strong>
          <span>
            {tableLocked ? "Table ordering · QR" : `Online · ${channel}`}
          </span>
        </div>
        {tableLocked ? (
          <div className={s.tableBanner} role="status" data-testid="table-lock-banner">
            <div className={s.lockIcon} aria-hidden>
              🔒
            </div>
            <div>
              <strong>{tableLabel ?? `Table ${tableParam}`}</strong>
              <span>Table locked — you cannot change tables from this QR link.</span>
            </div>
          </div>
        ) : null}
      </header>

      {closed ? (
        <div className={s.closedBanner} role="alert" data-testid="store-closed">
          <h2>We&apos;re not accepting orders right now</h2>
          <p>
            This store is closed or temporarily paused. You can still browse the menu —
            please try again later.
          </p>
        </div>
      ) : null}

      {orderNum ? (
        <div className={s.successCard} role="status">
          <strong>Order placed: {orderNum}</strong>
          <span>
            {tableLocked
              ? "Thanks — your order is headed to the kitchen for your table."
              : "Thank you — the kitchen has your order."}
          </span>
        </div>
      ) : null}

      {error ? <p className={s.error}>{error}</p> : null}

      {loading ? (
        <div className={s.loading}>Loading menu…</div>
      ) : items.length === 0 ? (
        <div className={s.emptyMenu}>
          <p>No dishes available right now.</p>
        </div>
      ) : (
        <>
          {categories.length > 1 ? (
            <div className={s.categories} role="tablist" aria-label="Categories">
              {categories.map((c) => (
                <button
                  key={c}
                  type="button"
                  role="tab"
                  aria-selected={category === c}
                  className={`${s.catChip} ${category === c ? s.catChipActive : ""}`}
                  onClick={() => setCategory(c)}
                >
                  {c}
                </button>
              ))}
            </div>
          ) : null}

          <div className={s.menu}>
            {visible.map((it) => {
              const available = it.is_available !== false;
              const qty = cart[it.id] || 0;
              return (
                <article
                  key={it.id}
                  className={`${s.itemCard} ${!available ? s.unavailable : ""}`}
                >
                  <div className={s.itemBody}>
                    <h3 className={s.itemName}>{it.name}</h3>
                    {it.description ? (
                      <p className={s.itemDesc}>{it.description}</p>
                    ) : null}
                    <p className={s.itemPrice}>{money(it.price_aed)}</p>
                    {!available ? <span className={s.soldOut}>Sold out</span> : null}
                  </div>
                  <button
                    type="button"
                    className={s.addBtn}
                    disabled={!available || closed}
                    onClick={() => addOne(it.id)}
                    aria-label={`Add ${it.name}`}
                  >
                    Add
                    {qty > 0 ? <span className={s.qtyInCart}>{qty} in cart</span> : null}
                  </button>
                </article>
              );
            })}
          </div>
        </>
      )}

      <div className={s.cartBar} data-testid="cart-bar">
        <div className={s.cartSummary}>
          <strong>{cartCount === 0 ? "Cart empty" : `${cartCount} item${cartCount === 1 ? "" : "s"}`}</strong>
          <span>{cartCount === 0 ? "Add dishes to order" : money(cartTotal)}</span>
        </div>
        <button
          type="button"
          className={s.cartCta}
          disabled={cartCount === 0 && !sheetOpen}
          onClick={() => setSheetOpen(true)}
        >
          {closed ? "View cart" : cartCount === 0 ? "Cart" : "View cart"}
        </button>
      </div>

      {sheetOpen ? (
        <div
          className={s.sheetBackdrop}
          role="presentation"
          onClick={(e) => {
            if (e.target === e.currentTarget) setSheetOpen(false);
          }}
        >
          <div
            className={s.sheet}
            role="dialog"
            aria-modal="true"
            aria-label="Your cart"
            data-testid="cart-sheet"
          >
            <div className={s.sheetHandle} aria-hidden />
            <div className={s.sheetHead}>
              <h2>Your cart</h2>
              <button type="button" className={s.sheetClose} onClick={() => setSheetOpen(false)}>
                ✕
              </button>
            </div>

            {cartLines.length === 0 ? (
              <p className={s.emptyMenu}>No items yet. Add something from the menu.</p>
            ) : (
              <div className={s.lines}>
                {cartLines.map((line) => {
                  const item = items.find((i) => i.id === line.dish_id);
                  if (!item) return null;
                  return (
                    <div key={line.dish_id} className={s.line}>
                      <div className={s.lineInfo}>
                        <strong>{item.name}</strong>
                        <span>{money(Number(item.price_aed) * line.qty)}</span>
                      </div>
                      <div className={s.stepper}>
                        <button
                          type="button"
                          aria-label="Decrease quantity"
                          onClick={() => setQty(line.dish_id, line.qty - 1)}
                        >
                          −
                        </button>
                        <span>{line.qty}</span>
                        <button
                          type="button"
                          aria-label="Increase quantity"
                          onClick={() => setQty(line.dish_id, line.qty + 1)}
                        >
                          +
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            <div className={s.totalRow}>
              <span>Total</span>
              <strong>{money(cartTotal)}</strong>
            </div>

            <div className={s.fields}>
              <label className={s.field}>
                Phone
                <input
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  inputMode="tel"
                  autoComplete="tel"
                  placeholder="+9715…"
                />
              </label>
              <label className={s.field}>
                Name (optional)
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoComplete="name"
                  placeholder="Your name"
                />
              </label>
            </div>

            {tableLocked ? (
              <p className={s.itemDesc} data-testid="sheet-table-lock">
                Ordering for {tableLabel ?? `table ${tableParam}`} (locked).
              </p>
            ) : null}

            <button
              type="button"
              className={s.placeBtn}
              disabled={busy || cartLines.length === 0 || closed || phone.trim().length < 7}
              onClick={() => void checkout()}
            >
              {closed
                ? "Store closed"
                : busy
                  ? "Placing…"
                  : `Place order · ${money(cartTotal)}`}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
