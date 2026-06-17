import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchActiveMenu } from "../lib/menuApi";
import { createManualOrder, lookupCustomer } from "../lib/manualOrderApi";
import { apiClient } from "../lib/apiClient";
import type { DishOut, MenuOut, RestaurantOut } from "../lib/types";
import { PageHeader } from "../components/PageHeader";
import s from "./NewOrderScreen.module.css";

type FeeOption = string;

interface FeeTier {
  max_km: number;
  fee_aed: number | string;
}

interface FeeChoice {
  value: string;
  label: string;
}

// Turn the restaurant's saved fee tiers into labelled delivery-fee choices.
function buildFeeOptions(tiers: FeeTier[]): FeeChoice[] {
  const sorted = [...tiers].sort((a, b) => Number(a.max_km) - Number(b.max_km));
  return sorted.map((t, i) => {
    const km = Number(t.max_km);
    const fee = Number(t.fee_aed);
    const lower = i === 0 ? 0 : Number(sorted[i - 1].max_km);
    const range = i === 0 ? `≤${km} km` : `${lower}–${km} km`;
    return {
      value: fee.toFixed(2),
      label: fee === 0 ? `Free (${range})` : `AED ${fee} (${range})`,
    };
  });
}

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

  const [feeOptions, setFeeOptions] = useState<FeeChoice[]>([]);
  const [feesLoading, setFeesLoading] = useState(true);
  const [fee, setFee] = useState<FeeOption>("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchActiveMenu().then((m) => setMenu(m));
  }, []);

  // Load delivery-fee tiers from settings so the choices match what the
  // manager configured on the Settings → Fees tab. Nothing is hardcoded:
  // until this resolves we show a loading state, never placeholder fees.
  useEffect(() => {
    apiClient
      .get<RestaurantOut>("/api/v1/me")
      .then((r) => {
        const tiers = (r.settings as Record<string, unknown>)?.delivery_fee_tiers;
        if (Array.isArray(tiers) && tiers.length > 0) {
          const opts = buildFeeOptions(tiers as FeeTier[]);
          setFeeOptions(opts);
          setFee(opts[0].value);
        }
      })
      .catch(() => {})
      .finally(() => setFeesLoading(false));
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
  const total = subtotal + (parseFloat(fee) || 0);

  const canSubmit =
    phone.trim().length >= 7 &&
    selectedItems.length > 0 &&
    aptRoom.trim() &&
    building.trim() &&
    receiverName.trim() &&
    fee !== "" &&
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

  if (menu === "loading") return <NewOrderSkeleton />;

  if (!menu) {
    return (
      <div className={s.screen}>
        <PageHeader title="New Order" subtitle="Place a manual order on behalf of a customer" />
        <div className={s.noMenuBanner}>
          No active menu found. Activate a menu before placing manual orders.
        </div>
      </div>
    );
  }

  return (
    <div className={s.screen}>
      <PageHeader title="New Order" subtitle="Place a manual order on behalf of a customer" />

      {error && <div className={s.errorBanner}>{error}</div>}

      <div className={s.grid}>
        {/* LEFT COLUMN */}
        <div className={s.leftCol}>
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
                {feesLoading ? (
                  <span className={s.feeHint}>Loading delivery fees…</span>
                ) : feeOptions.length === 0 ? (
                  <span className={s.feeHint}>No delivery fees set — configure them in Settings → Fees.</span>
                ) : (
                  feeOptions.map(({ value, label }) => (
                    <button
                      key={value}
                      type="button"
                      className={`${s.feeBtn} ${fee === value ? s.feeBtnActive : ""}`}
                      onClick={() => setFee(value)}
                    >
                      {label}
                    </button>
                  ))
                )}
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

          <div className={s.itemList}>
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
          </div>

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

// A skeleton placeholder that mirrors the real New Order layout (two columns,
// same cards/sections) so the page keeps its shape while the menu loads.
function SkField({ labelWidth }: { labelWidth?: number }) {
  return (
    <div className={s.field}>
      <span className={`${s.sk} ${s.skLabel}`} style={labelWidth ? { width: labelWidth } : undefined} />
      <span className={`${s.sk} ${s.skInput}`} />
    </div>
  );
}

function NewOrderSkeleton() {
  return (
    <div className={s.screen} aria-busy="true" aria-label="Loading new order form">
      <PageHeader title="New Order" subtitle="Place a manual order on behalf of a customer" />

      <div className={s.grid}>
        {/* LEFT COLUMN */}
        <div className={s.leftCol}>
          <div className={s.section}>
            <span className={`${s.sk} ${s.skTitle}`} />
            <div className={s.field}>
              <span className={`${s.sk} ${s.skLabel}`} />
              <div className={s.inputRow}>
                <span className={`${s.sk} ${s.skInput}`} style={{ flex: 1 }} />
                <span className={`${s.sk} ${s.skBtn}`} />
              </div>
            </div>
            <SkField />
          </div>

          <div className={s.section}>
            <span className={`${s.sk} ${s.skTitle}`} />
            <SkField />
            <SkField />
            <SkField labelWidth={96} />
            <SkField labelWidth={88} />
            <div className={s.field}>
              <span className={`${s.sk} ${s.skLabel}`} />
              <div className={s.feeRow}>
                <span className={`${s.sk} ${s.skInput}`} style={{ flex: 1 }} />
                <span className={`${s.sk} ${s.skInput}`} style={{ flex: 1 }} />
                <span className={`${s.sk} ${s.skInput}`} style={{ flex: 1 }} />
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN */}
        <div className={s.section}>
          <span className={`${s.sk} ${s.skTitle}`} />
          <span className={`${s.sk} ${s.skInput}`} />
          <div className={s.itemList}>
            {Array.from({ length: 6 }).map((_, i) => (
              <span key={i} className={`${s.sk} ${s.skDish}`} />
            ))}
          </div>
          <div className={s.summary}>
            <span className={`${s.sk} ${s.skBar}`} style={{ width: 110, marginBottom: 12 }} />
            <div className={s.summaryLine}>
              <span className={`${s.sk} ${s.skLine}`} style={{ width: "40%" }} />
              <span className={`${s.sk} ${s.skLine}`} style={{ width: "20%" }} />
            </div>
            <hr className={s.summaryDivider} />
            <div className={s.summaryLine}>
              <span className={`${s.sk} ${s.skLine}`} style={{ width: "30%" }} />
              <span className={`${s.sk} ${s.skLine}`} style={{ width: "18%" }} />
            </div>
          </div>
        </div>
      </div>

      <div className={s.bottomBar}>
        <span className={`${s.sk} ${s.skBar}`} style={{ width: 240 }} />
        <div className={s.actions}>
          <span className={`${s.sk} ${s.skBtn}`} />
          <span className={`${s.sk} ${s.skBtn}`} style={{ width: 130 }} />
        </div>
      </div>
    </div>
  );
}
