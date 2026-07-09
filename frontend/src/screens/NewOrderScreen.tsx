import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchActiveMenu } from "../lib/menuApi";
import { createManualOrder, lookupCustomer } from "../lib/manualOrderApi";
import { apiClient } from "../lib/apiClient";
import type { DishOut, MenuOut, RestaurantOut } from "../lib/types";
import { PageHeader } from "../components/PageHeader";
import { LocationPicker } from "../components/LocationPicker";
import { BottomActionBar } from "../components/BottomActionBar";
import { Button, TouchButton } from "../components/Button";
import { MoneySummary } from "../components/MoneySummary";
import { EmptyState } from "../components/EmptyState";
import { OfflineLimitsBanner } from "../components/OfflineLimitsBanner";
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
  const [activeCategory, setActiveCategory] = useState<string | "all">("all");

  const [aptRoom, setAptRoom] = useState("");
  const [building, setBuilding] = useState("");
  const [receiverName, setReceiverName] = useState("");
  const [addressNotes, setAddressNotes] = useState("");
  const [pin, setPin] = useState<{ lat: number; lng: number } | null>(null);

  const [feeOptions, setFeeOptions] = useState<FeeChoice[]>([]);
  const [feesLoading, setFeesLoading] = useState(true);
  const [fee, setFee] = useState<FeeOption>("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchActiveMenu().then((m) => setMenu(m));
  }, []);

  useEffect(() => {
    apiClient
      .get<RestaurantOut>("/api/v1/me")
      .then((r) => {
        const tiers = (r.settings as Record<string, unknown>)?.delivery_fee_tiers;
        if (Array.isArray(tiers) && tiers.length > 0) {
          const opts = buildFeeOptions(tiers as FeeTier[]);
          const withFree = opts.some((o) => o.value === "0.00")
            ? opts
            : [{ value: "0.00", label: "Free delivery" }, ...opts];
          setFeeOptions(withFree);
          setFee(withFree[0].value);
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

  function clearCart() {
    setQuantities({});
  }

  const dishes: DishOut[] = useMemo(() => {
    if (!menu || menu === "loading") return [];
    return menu.dishes.filter((d) => d.is_available);
  }, [menu]);

  const categories = useMemo(() => {
    const cats = new Set(dishes.map((d) => d.category ?? "Other"));
    return Array.from(cats).sort();
  }, [dishes]);

  const filteredDishes = useMemo(() => {
    const q = search.toLowerCase();
    let list = dishes;
    if (activeCategory !== "all") {
      list = list.filter((d) => (d.category ?? "Other") === activeCategory);
    }
    if (q) {
      list = list.filter(
        (d) =>
          d.name.toLowerCase().includes(q) ||
          String(d.dish_number).includes(q),
      );
    }
    return list;
  }, [dishes, search, activeCategory]);

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
    pin !== null &&
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
          latitude: pin?.lat ?? null,
          longitude: pin?.lng ?? null,
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
      <PageHeader title="New Order" subtitle="Delivery POS · large items · cart always visible" />
      <OfflineLimitsBanner surface="new-order" />

      {error && <div className={s.errorBanner} role="alert">{error}</div>}

      <div className={s.posLayout}>
        {/* LEFT — customer + address */}
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
              <span className={s.fieldHint}>Shown to the rider as the address label.</span>
            </div>

            <div className={s.field}>
              <label className={s.label}>Delivery location {pin ? "✓" : "*"}</label>
              <span className={s.fieldHint}>
                Search an address or drop the pin so the rider navigates to the exact spot.
                {!pin && " Required — without a pin the order can't be assigned to a rider."}
              </span>
              <LocationPicker
                lat={pin?.lat ?? NaN}
                lng={pin?.lng ?? NaN}
                onChange={(lat, lng) => setPin({ lat, lng })}
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

        {/* CENTER — large item grid */}
        <div className={`${s.section} ${s.itemsPane}`}>
          <div className={s.sectionTitle}>Menu</div>
          <input
            className={s.searchInput}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search dishes or number…"
            aria-label="Search dishes"
          />
          <div className={s.catRail} role="tablist" aria-label="Categories">
            <button
              type="button"
              role="tab"
              aria-selected={activeCategory === "all"}
              className={`${s.catChip} ${activeCategory === "all" ? s.catChipActive : ""}`}
              onClick={() => setActiveCategory("all")}
            >
              All
            </button>
            {categories.map((cat) => (
              <button
                key={cat}
                type="button"
                role="tab"
                aria-selected={activeCategory === cat}
                className={`${s.catChip} ${activeCategory === cat ? s.catChipActive : ""}`}
                onClick={() => setActiveCategory(cat)}
              >
                {cat}
              </button>
            ))}
          </div>

          {filteredDishes.length === 0 ? (
            <EmptyState title="No dishes match" description="Try another search or category." />
          ) : (
            <div className={s.itemGrid}>
              {filteredDishes.map((dish) => {
                const qty = quantities[dish.id] ?? 0;
                return (
                  <div
                    key={dish.id}
                    className={`${s.itemTile} ${qty > 0 ? s.itemTileActive : ""}`}
                  >
                    <button
                      type="button"
                      className={s.itemMain}
                      onClick={() => setQty(dish.id, 1)}
                      aria-label={`Add ${dish.name}`}
                    >
                      <span className={s.itemNum}>#{dish.dish_number}</span>
                      <span className={s.itemName}>{dish.name}</span>
                      <span className={s.itemPrice}>AED {dish.price_aed}</span>
                    </button>
                    <div className={s.qtyControls}>
                      <button
                        type="button"
                        className={s.qtyBtn}
                        onClick={() => setQty(dish.id, -1)}
                        disabled={qty === 0}
                        aria-label={`Decrease ${dish.name}`}
                      >
                        −
                      </button>
                      <span
                        className={`${s.qtyValue} ${qty > 0 ? s.qtyValueActive : ""}`}
                        aria-label={`${dish.name} quantity`}
                      >
                        {qty}
                      </span>
                      <button
                        type="button"
                        className={`${s.qtyBtn} ${qty > 0 ? s.qtyBtnActive : ""}`}
                        onClick={() => setQty(dish.id, 1)}
                        aria-label={`Increase ${dish.name}`}
                      >
                        +
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* RIGHT — cart always visible */}
        <aside className={`${s.section} ${s.cartPane}`} aria-label="Cart">
          <div className={s.sectionTitle}>Cart</div>
          {selectedItems.length === 0 ? (
            <p className={s.emptyHint}>Add at least 1 item to continue.</p>
          ) : (
            <div className={s.cartLines}>
              {selectedItems.map(({ dish, qty }) => (
                <div key={dish.id} className={s.cartLine}>
                  <div className={s.cartLineMain}>
                    <span className={s.cartLineName}>
                      {qty}× {dish.name}
                    </span>
                    <span className={s.cartLineAmt}>
                      AED {(parseFloat(dish.price_aed ?? "0") * qty).toFixed(2)}
                    </span>
                  </div>
                  <div className={s.qtyControls}>
                    <button
                      type="button"
                      className={s.qtyBtn}
                      onClick={() => setQty(dish.id, -1)}
                      aria-label={`Remove one ${dish.name}`}
                    >
                      −
                    </button>
                    <button
                      type="button"
                      className={`${s.qtyBtn} ${s.qtyBtnActive}`}
                      onClick={() => setQty(dish.id, 1)}
                      aria-label={`Add one ${dish.name}`}
                    >
                      +
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className={s.summary}>
            <div className={s.summaryLine}>
              <span>Subtotal</span>
              <span>AED {subtotal.toFixed(2)}</span>
            </div>
            <div className={s.summaryLine}>
              <span>Delivery</span>
              <span>{fee === "0.00" || fee === "" ? "Free" : `AED ${fee}`}</span>
            </div>
            <MoneySummary label="TOTAL" amount={total.toFixed(2)} />
          </div>
        </aside>
      </div>

      <BottomActionBar>
        <span className={s.waHint}>
          {phone.trim()
            ? `📱 WhatsApp confirmation will be sent to ${phone.trim()}`
            : "📱 Enter phone to receive WhatsApp confirmation"}
        </span>
        <div className={s.footerSpacer} />
        <Button
          type="button"
          variant="ghost"
          size="lg"
          onClick={clearCart}
          disabled={selectedItems.length === 0}
        >
          Clear
        </Button>
        <Button type="button" variant="ghost" size="lg" onClick={() => navigate("/orders")}>
          Cancel
        </Button>
        <TouchButton type="button" disabled={!canSubmit} onClick={onSubmit}>
          {submitting
            ? "Placing…"
            : `Place Order${total > 0 ? ` — AED ${total.toFixed(2)}` : ""}`}
        </TouchButton>
      </BottomActionBar>
    </div>
  );
}

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
      <div className={s.posLayout}>
        <div className={s.leftCol}>
          <div className={s.section}>
            <span className={`${s.sk} ${s.skTitle}`} />
            <SkField />
            <SkField />
          </div>
        </div>
        <div className={s.section}>
          <span className={`${s.sk} ${s.skTitle}`} />
          <span className={`${s.sk} ${s.skInput}`} />
          <div className={s.itemGrid}>
            {Array.from({ length: 6 }).map((_, i) => (
              <span key={i} className={`${s.sk} ${s.skDish}`} />
            ))}
          </div>
        </div>
        <div className={s.section}>
          <span className={`${s.sk} ${s.skTitle}`} />
          <span className={`${s.sk} ${s.skBar}`} style={{ width: "80%" }} />
        </div>
      </div>
    </div>
  );
}
