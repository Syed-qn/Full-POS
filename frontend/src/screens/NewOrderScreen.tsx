import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchActiveMenu } from "../lib/menuApi";
import { createManualOrder, lookupCustomer } from "../lib/manualOrderApi";
import type { DishOut, MenuOut } from "../lib/types";
import s from "./NewOrderScreen.module.css";

type FeeOption = "0.00" | "5.00" | "10.00";

export function NewOrderScreen() {
  const navigate = useNavigate();

  const [menu, setMenu] = useState<MenuOut | null | "loading">("loading");

  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [lookupStatus, setLookupStatus] = useState<
    "idle" | "found" | "new" | "error"
  >("idle");

  const [quantities, setQuantities] = useState<Record<number, number>>({});
  const [search, setSearch] = useState("");

  const [aptRoom, setAptRoom] = useState("");
  const [building, setBuilding] = useState("");
  const [receiverName, setReceiverName] = useState("");
  const [addressNotes, setAddressNotes] = useState("");

  const [fee, setFee] = useState<FeeOption>("0.00");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchActiveMenu().then((m) => setMenu(m));
  }, []);

  async function onLookup() {
    if (!phone.trim()) return;
    try {
      const result = await lookupCustomer(phone.trim());
      if (result) {
        setLookupStatus("found");
        if (result.name) setName(result.name);
        if (result.last_address) {
          setAptRoom(result.last_address.apt_room);
          setBuilding(result.last_address.building);
          setReceiverName(result.last_address.receiver_name);
          setAddressNotes(result.last_address.notes ?? "");
        }
      } else {
        setLookupStatus("new");
      }
    } catch {
      setLookupStatus("error");
    }
  }

  function setQty(dishId: number, delta: number) {
    setQuantities((prev) => {
      const next = (prev[dishId] ?? 0) + delta;
      if (next <= 0) {
        const copy = { ...prev };
        delete copy[dishId];
        return copy;
      }
      return { ...prev, [dishId]: next };
    });
  }

  const dishes: DishOut[] = useMemo(() => {
    if (!menu || menu === "loading") return [];
    return menu.dishes.filter((d) => d.is_available);
  }, [menu]);

  const filteredDishes = useMemo(() => {
    const q = search.toLowerCase();
    return q
      ? dishes.filter(
          (d) =>
            d.name.toLowerCase().includes(q) ||
            String(d.dish_number).includes(q),
        )
      : dishes;
  }, [dishes, search]);

  const categories = useMemo(() => {
    const cats = new Set(filteredDishes.map((d) => d.category ?? "Other"));
    return Array.from(cats).sort();
  }, [filteredDishes]);

  const selectedItems = useMemo(
    () =>
      Object.entries(quantities)
        .filter(([, qty]) => qty > 0)
        .map(([id, qty]) => {
          const dish = dishes.find((d) => d.id === Number(id));
          return dish ? { dish, qty } : null;
        })
        .filter(Boolean) as { dish: DishOut; qty: number }[],
    [quantities, dishes],
  );

  const subtotal = selectedItems.reduce(
    (acc, { dish, qty }) => acc + parseFloat(dish.price_aed ?? "0") * qty,
    0,
  );
  const total = subtotal + parseFloat(fee);

  const canSubmit =
    phone.trim().length >= 7 &&
    selectedItems.length > 0 &&
    aptRoom.trim() &&
    building.trim() &&
    receiverName.trim() &&
    !submitting;

  async function onSubmit() {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      await createManualOrder({
        customer_phone: phone.trim(),
        customer_name: name.trim() || null,
        items: selectedItems.map(({ dish, qty }) => ({
          dish_id: dish.id,
          qty,
          notes: null,
        })),
        address: {
          apt_room: aptRoom.trim(),
          building: building.trim(),
          receiver_name: receiverName.trim(),
          notes: addressNotes.trim() || null,
        },
        delivery_fee_aed: fee,
      });
      navigate("/orders");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to place order.");
      setSubmitting(false);
    }
  }

  if (menu === "loading") return <div className={s.screen}>Loading menu…</div>;

  if (!menu) {
    return (
      <div className={s.screen}>
        <h1 className={s.heading}>New Order</h1>
        <div className={s.noMenuBanner}>
          No active menu found. Activate a menu before placing manual orders.
        </div>
      </div>
    );
  }

  return (
    <div className={s.screen}>
      <h1 className={s.heading}>New Order</h1>

      {error && <div className={s.errorBanner}>{error}</div>}

      <div className={s.grid}>
        {/* LEFT COLUMN */}
        <div>
          <div className={s.section}>
            <div className={s.sectionTitle}>Customer</div>

            <div className={s.field}>
              <label className={s.label}>Phone *</label>
              <div className={s.inputRow}>
                <input
                  className={s.input}
                  value={phone}
                  onChange={(e) => {
                    setPhone(e.target.value);
                    setLookupStatus("idle");
                  }}
                  placeholder="+971 50 123 4567"
                />
                <button className={s.lookupBtn} onClick={onLookup} type="button">
                  Look up
                </button>
              </div>
              <span
                className={`${s.lookupHint} ${lookupStatus === "new" ? s.lookupHintNew : ""}`}
              >
                {lookupStatus === "found" && "✓ Existing customer — details prefilled"}
                {lookupStatus === "new" && "New customer — will be created"}
                {lookupStatus === "error" && "Lookup failed"}
              </span>
            </div>

            <div className={s.field}>
              <label className={s.label}>Name (optional)</label>
              <input
                className={s.input}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Customer name"
              />
            </div>
          </div>

          <hr className={s.divider} />

          <div className={s.section}>
            <div className={s.sectionTitle}>Delivery Address</div>

            <div className={s.field}>
              <label className={s.label}>Apt / Room *</label>
              <input
                className={s.input}
                value={aptRoom}
                onChange={(e) => setAptRoom(e.target.value)}
                placeholder="Apt 404"
              />
            </div>

            <div className={s.field}>
              <label className={s.label}>Building *</label>
              <input
                className={s.input}
                value={building}
                onChange={(e) => setBuilding(e.target.value)}
                placeholder="Marina Tower"
              />
            </div>

            <div className={s.field}>
              <label className={s.label}>Receiver Name *</label>
              <input
                className={s.input}
                value={receiverName}
                onChange={(e) => setReceiverName(e.target.value)}
                placeholder="Who receives the order"
              />
            </div>

            <div className={s.field}>
              <label className={s.label}>Notes (optional)</label>
              <input
                className={s.input}
                value={addressNotes}
                onChange={(e) => setAddressNotes(e.target.value)}
                placeholder="Gate code, floor, landmarks…"
              />
            </div>

            <div className={s.field}>
              <label className={s.label}>Delivery Fee</label>
              <div className={s.feeRow}>
                {(
                  [
                    { value: "0.00", label: "Free (≤3 km)" },
                    { value: "5.00", label: "AED 5 (3–5 km)" },
                    { value: "10.00", label: "AED 10 (>5 km)" },
                  ] as { value: FeeOption; label: string }[]
                ).map(({ value, label }) => (
                  <button
                    key={value}
                    type="button"
                    className={`${s.feeBtn} ${fee === value ? s.feeBtnActive : ""}`}
                    onClick={() => setFee(value)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN */}
        <div className={s.section}>
          <div className={s.sectionTitle}>Items</div>

          <input
            className={s.searchInput}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search dishes…"
          />

          {categories.map((cat) => (
            <div key={cat}>
              <div className={s.categoryLabel}>{cat}</div>
              {filteredDishes
                .filter((d) => (d.category ?? "Other") === cat)
                .map((dish) => {
                  const qty = quantities[dish.id] ?? 0;
                  return (
                    <div
                      key={dish.id}
                      className={`${s.dishRow} ${qty > 0 ? s.dishRowActive : ""}`}
                    >
                      <span>
                        <span
                          className={`${s.dishName} ${qty > 0 ? s.dishNameActive : ""}`}
                        >
                          {dish.dish_number}. {dish.name}
                        </span>
                        <span className={s.dishPrice}>
                          · AED {dish.price_aed}
                        </span>
                      </span>
                      <div className={s.qtyControls}>
                        <button
                          type="button"
                          className={s.qtyBtn}
                          onClick={() => setQty(dish.id, -1)}
                          disabled={qty === 0}
                        >
                          −
                        </button>
                        <span
                          className={`${s.qtyValue} ${qty > 0 ? s.qtyValueActive : ""}`}
                        >
                          {qty}
                        </span>
                        <button
                          type="button"
                          className={`${s.qtyBtn} ${qty > 0 ? s.qtyBtnActive : ""}`}
                          onClick={() => setQty(dish.id, 1)}
                        >
                          +
                        </button>
                      </div>
                    </div>
                  );
                })}
            </div>
          ))}

          {selectedItems.length === 0 && (
            <p className={s.emptyHint}>Add at least 1 item to continue.</p>
          )}

          <div className={s.summary}>
            <div className={s.summaryTitle}>Order Summary</div>
            {selectedItems.map(({ dish, qty }) => (
              <div key={dish.id} className={s.summaryLine}>
                <span>
                  {qty}× {dish.name}
                </span>
                <span>
                  AED {(parseFloat(dish.price_aed ?? "0") * qty).toFixed(2)}
                </span>
              </div>
            ))}
            <hr className={s.summaryDivider} />
            <div className={s.summaryLine}>
              <span>Subtotal</span>
              <span>AED {subtotal.toFixed(2)}</span>
            </div>
            <div className={s.summaryLine}>
              <span>Delivery</span>
              <span>{fee === "0.00" ? "Free" : `AED ${fee}`}</span>
            </div>
            <hr className={s.summaryDivider} />
            <div className={s.summaryTotal}>
              <span>TOTAL</span>
              <span className={s.summaryTotalAmount}>
                AED {total.toFixed(2)}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className={s.bottomBar}>
        <span className={s.waHint}>
          {phone.trim()
            ? `📱 WhatsApp confirmation will be sent to ${phone.trim()}`
            : "📱 Enter phone to receive WhatsApp confirmation"}
        </span>
        <div className={s.actions}>
          <button
            className={s.cancelBtn}
            type="button"
            onClick={() => navigate("/orders")}
          >
            Cancel
          </button>
          <button
            className={s.placeBtn}
            type="button"
            disabled={!canSubmit}
            onClick={onSubmit}
          >
            {submitting
              ? "Placing…"
              : `Place Order${total > 0 ? ` — AED ${total.toFixed(2)}` : ""}`}
          </button>
        </div>
      </div>
    </div>
  );
}
