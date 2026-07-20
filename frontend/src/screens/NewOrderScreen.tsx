import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchActiveMenu } from "../lib/menuApi";
import {
  createManualOrder,
  createPosOrder,
  lookupCustomer,
} from "../lib/manualOrderApi";
import { apiClient } from "../lib/apiClient";
import { fetchOrders } from "../lib/ordersApi";
import type {
  DishOut,
  MenuOut,
  OrderOut,
  OrderStatus,
  RestaurantOut,
} from "../lib/types";
import { isCashierRole, isWaiterRole } from "../lib/navAccess";
import { PageHeader } from "../components/PageHeader";
import { LocationPicker } from "../components/LocationPicker";
import { BottomActionBar } from "../components/BottomActionBar";
import { Button, TouchButton } from "../components/Button";
import { MoneySummary } from "../components/MoneySummary";
import { EmptyState } from "../components/EmptyState";
import { OfflineLimitsBanner } from "../components/OfflineLimitsBanner";
import s from "./NewOrderScreen.module.css";

/** Active tickets a cashier may still collect payment for (not terminal). */
const OPEN_BILL_STATUSES = new Set<OrderStatus>([
  "draft",
  "pending_confirmation",
  "confirmed",
  "preparing",
  "ready",
  "assigned",
  "picked_up",
  "arriving",
]);

/** Fulfillment tabs — mirror the classic terminal. `delivery` is the default so
 *  the delivery address block renders on first paint (keeps existing flow/tests). */
const ORDER_TYPE_TABS = [
  { key: "dine_in", label: "Dining" },
  { key: "takeaway", label: "Take Away" },
  { key: "delivery", label: "Home Delivery" },
  { key: "online", label: "Online" },
] as const;
type OrderTypeKey = (typeof ORDER_TYPE_TABS)[number]["key"];

/** Order types that require a delivery address + fee + map pin. */
const ADDRESS_REQUIRED: ReadonlySet<OrderTypeKey> = new Set(["delivery", "online"]);

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

function today(): string {
  // Locale date without pulling in a lib; matches the terminal's date chip.
  return new Date().toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function NewOrderScreen() {
  const navigate = useNavigate();
  const waiterMode = isWaiterRole();
  const cashierMode = isCashierRole();

  const [menu, setMenu] = useState<MenuOut | null | "loading">("loading");

  const [orderType, setOrderType] = useState<OrderTypeKey>("delivery");
  const needsAddress = ADDRESS_REQUIRED.has(orderType);

  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [tableNo, setTableNo] = useState("");
  const [lookupStatus, setLookupStatus] = useState<
    "idle" | "found" | "new" | "error"
  >("idle");

  const [quantities, setQuantities] = useState<Record<number, number>>({});
  /** Per-dish kitchen / customer line notes (API ManualOrderItemIn.notes). */
  const [itemNotes, setItemNotes] = useState<Record<number, string>>({});
  const [kitchenNotes, setKitchenNotes] = useState("");
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
  const [openBillsCount, setOpenBillsCount] = useState<number | null>(null);

  // Token bar / open-ticket navigation.
  const [openOrders, setOpenOrders] = useState<OrderOut[]>([]);
  const [browseIdx, setBrowseIdx] = useState<number | null>(null);

  // Numeric keypad state (touchscreen qty / dish-code entry).
  const [keypad, setKeypad] = useState("");
  const [focusedDishId, setFocusedDishId] = useState<number | null>(null);

  useEffect(() => {
    fetchActiveMenu().then((m) => setMenu(m));
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchOrders({ limit: 50, previewBatch: false })
      .then((rows) => {
        if (cancelled) return;
        const open = rows.filter((o) => OPEN_BILL_STATUSES.has(o.status));
        setOpenOrders(open);
        setOpenBillsCount(open.length);
      })
      .catch(() => {
        if (!cancelled) setOpenBillsCount(null);
      });
    return () => {
      cancelled = true;
    };
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
        setItemNotes((notes) => {
          if (!(dishId in notes)) return notes;
          const n = { ...notes };
          delete n[dishId];
          return n;
        });
        return copy;
      }
      setFocusedDishId(dishId);
      return { ...prev, [dishId]: next };
    });
  }

  function setQtyAbsolute(dishId: number, value: number) {
    setQuantities((prev) => {
      if (value <= 0) {
        const copy = { ...prev };
        delete copy[dishId];
        return copy;
      }
      return { ...prev, [dishId]: Math.min(value, 99) };
    });
  }

  function setItemNote(dishId: number, value: string) {
    setItemNotes((prev) => {
      const trimmed = value.slice(0, 200);
      if (!trimmed) {
        if (!(dishId in prev)) return prev;
        const next = { ...prev };
        delete next[dishId];
        return next;
      }
      return { ...prev, [dishId]: trimmed };
    });
  }

  function clearCart() {
    setQuantities({});
    setItemNotes({});
    setKitchenNotes("");
    setFocusedDishId(null);
    setKeypad("");
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
  const deliveryFee = needsAddress ? parseFloat(fee) || 0 : 0;
  const total = subtotal + deliveryFee;

  // ── Keypad handlers ──────────────────────────────────────────────
  function pressKey(d: string) {
    setKeypad((k) => (k + d).replace(/^0+(?=\d)/, "").slice(0, 3));
  }
  function clearKey() {
    setKeypad("");
  }
  function applyQty() {
    const val = parseInt(keypad, 10);
    const target = focusedDishId ?? selectedItems[selectedItems.length - 1]?.dish.id;
    if (!Number.isFinite(val) || target == null) return;
    setQtyAbsolute(target, val);
    setKeypad("");
  }
  function applyCode() {
    const num = parseInt(keypad, 10);
    if (!Number.isFinite(num)) return;
    const dish = dishes.find((x) => x.dish_number === num);
    if (dish) {
      setQty(dish.id, 1);
      setActiveCategory("all");
    }
    setKeypad("");
  }

  // ── Token / open-ticket navigation ───────────────────────────────
  const browsing = browseIdx != null ? openOrders[browseIdx] : null;
  const tokenNumber = browsing?.order_number ?? String(openOrders.length + 1);
  function stepToken(dir: -1 | 1) {
    if (openOrders.length === 0) return;
    setBrowseIdx((i) => {
      if (i == null) return dir === -1 ? openOrders.length - 1 : 0;
      const next = i + dir;
      if (next < 0 || next >= openOrders.length) return null; // back to NEW ticket
      return next;
    });
  }

  const canSubmit =
    phone.trim().length >= 7 &&
    selectedItems.length > 0 &&
    (!needsAddress ||
      (aptRoom.trim() !== "" &&
        building.trim() !== "" &&
        receiverName.trim() !== "" &&
        fee !== "" &&
        pin !== null)) &&
    !submitting;

  function buildItems() {
    return selectedItems.map(({ dish, qty }) => {
      const lineNote = (itemNotes[dish.id] ?? "").trim();
      const kitchen = kitchenNotes.trim();
      const isFirst = selectedItems[0]?.dish.id === dish.id;
      const combined = [lineNote, isFirst && kitchen ? `Kitchen: ${kitchen}` : ""]
        .filter(Boolean)
        .join(" · ");
      return { dish_id: dish.id, qty, notes: combined || null };
    });
  }

  async function onSubmit(goPay = cashierMode) {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      let order: OrderOut;
      if (needsAddress) {
        order = await createManualOrder({
          customer_phone: phone.trim(),
          customer_name: name.trim() || null,
          items: buildItems(),
          address: {
            apt_room: aptRoom.trim(),
            building: building.trim(),
            receiver_name: receiverName.trim(),
            notes: addressNotes.trim() || null,
            latitude: pin?.lat ?? null,
            longitude: pin?.lng ?? null,
          },
          delivery_fee_aed: fee,
          order_type: orderType,
        });
      } else {
        order = await createPosOrder({
          order_type: orderType,
          customer_phone: phone.trim(),
          customer_name: name.trim() || null,
          items: buildItems(),
          table_id:
            orderType === "dine_in" && tableNo.trim()
              ? Number(tableNo.trim()) || null
              : null,
          address: null,
          delivery_fee_aed: "0.00",
        });
      }
      if (cashierMode && goPay && order?.id) {
        navigate(`/orders/${order.id}/pay`);
      } else if (waiterMode && order?.id) {
        navigate(`/orders/${order.id}`);
      } else if (order?.id) {
        navigate(`/orders/${order.id}`);
      } else {
        navigate("/orders");
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to place order.");
      setSubmitting(false);
    }
  }

  if (menu === "loading") return <NewOrderSkeleton />;

  if (!menu) {
    return (
      <div className={s.screen}>
        <PageHeader
          title={waiterMode ? "Table order" : cashierMode ? "Cashier terminal" : "New Order"}
          subtitle={
            waiterMode
              ? "Quantity, instructions, modifiers — send to kitchen (payment at cashier)"
              : cashierMode
                ? "Terminal · place order then take payment"
                : "Place a manual order on behalf of a customer"
          }
        />
        <div className={s.noMenuBanner}>
          No active menu found. Activate a menu before placing manual orders.
        </div>
      </div>
    );
  }

  const activeTabLabel =
    ORDER_TYPE_TABS.find((t) => t.key === orderType)?.label ?? "";

  return (
    <div className={`${s.screen} ${s.terminal}`}>
      <PageHeader
        title={waiterMode ? "Table order" : cashierMode ? "Cashier terminal" : "New Order"}
        subtitle={
          waiterMode
            ? "Quantity, instructions, modifiers — send to kitchen (payment at cashier)"
            : cashierMode
              ? "Terminal · all order types · pay after place"
              : "Delivery POS · large items · cart always visible"
        }
      />
      <OfflineLimitsBanner surface="new-order" />

      {/* Order-type tabs — classic terminal top rail */}
      <div className={s.typeTabs} role="tablist" aria-label="Order type">
        {ORDER_TYPE_TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={orderType === t.key}
            className={`${s.typeTab} ${orderType === t.key ? s.typeTabActive : ""} ${
              s[`type_${t.key}`] ?? ""
            }`}
            onClick={() => setOrderType(t.key)}
            data-testid={`order-type-${t.key}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Token bar + open-ticket navigation */}
      <div className={s.tokenBar} data-testid="token-bar">
        <div className={s.tokenBlock}>
          <span className={s.tokenLabel}>Token</span>
          <span className={s.tokenValue} data-testid="token-value">
            {browsing ? tokenNumber : `${tokenNumber} · NEW`}
          </span>
        </div>
        <div className={s.tokenNav}>
          <button
            type="button"
            className={s.tokenArrow}
            onClick={() => stepToken(-1)}
            disabled={openOrders.length === 0}
            aria-label="Previous ticket"
          >
            ◀
          </button>
          <button
            type="button"
            className={s.tokenArrow}
            onClick={() => stepToken(1)}
            disabled={openOrders.length === 0}
            aria-label="Next ticket"
          >
            ▶
          </button>
          {browsing && (
            <button
              type="button"
              className={s.tokenOpen}
              onClick={() => navigate(`/orders/${browsing.id}`)}
            >
              Open ticket
            </button>
          )}
        </div>
        <span className={s.tokenType}>{activeTabLabel}</span>
        <span className={s.tokenDate}>{today()}</span>
      </div>

      {cashierMode && (
        <div className={s.cashierStrip} data-testid="cashier-strip" role="navigation" aria-label="Cashier shortcuts">
          <span className={s.cashierStripLabel}>Cashier</span>
          <button
            type="button"
            className={s.cashierChip}
            data-testid="cashier-open-bills"
            onClick={() => navigate("/orders")}
            title="Active orders that may still need payment"
          >
            Open bills
            {openBillsCount != null && (
              <span className={s.cashierChipBadge} data-testid="cashier-open-bills-count">
                {openBillsCount}
              </span>
            )}
          </button>
          <button
            type="button"
            className={s.cashierChip}
            data-testid="cashier-drawer"
            onClick={() => navigate("/payments")}
          >
            Drawer / payments
          </button>
          <button
            type="button"
            className={s.cashierChip}
            data-testid="cashier-customers"
            onClick={() => navigate("/customers")}
          >
            Customers
          </button>
          <button
            type="button"
            className={s.cashierChip}
            data-testid="cashier-floor"
            onClick={() => navigate("/floor")}
          >
            Floor
          </button>
        </div>
      )}

      {error && <div className={s.errorBanner} role="alert">{error}</div>}

      <div className={s.posLayout}>
        {/* LEFT — customer + address / table */}
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

            {orderType === "dine_in" && (
              <div className={s.field}>
                <label className={s.label}>Table (optional)</label>
                <input
                  className={s.input}
                  value={tableNo}
                  onChange={(e) => setTableNo(e.target.value.replace(/[^0-9]/g, ""))}
                  placeholder="Table number"
                  inputMode="numeric"
                  data-testid="table-number"
                />
              </div>
            )}
          </div>

          {needsAddress ? (
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
          ) : (
            <div className={s.section}>
              <div className={s.sectionTitle}>
                {orderType === "dine_in" ? "Dine-in" : "Take away"}
              </div>
              <p className={s.emptyHint}>
                No delivery address needed for {activeTabLabel.toLowerCase()} — pick items and take payment.
              </p>
            </div>
          )}
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
                    className={`${s.itemTile} ${qty > 0 ? s.itemTileActive : ""} ${
                      focusedDishId === dish.id ? s.itemTileFocused : ""
                    }`}
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

        {/* RIGHT — cart + keypad */}
        <aside className={`${s.section} ${s.cartPane}`} aria-label="Cart">
          <div className={s.sectionTitle}>Cart</div>
          {selectedItems.length === 0 ? (
            <p className={s.emptyHint}>Add at least 1 item to continue.</p>
          ) : (
            <div className={s.cartLines}>
              {selectedItems.map(({ dish, qty }) => (
                <div
                  key={dish.id}
                  className={`${s.cartLine} ${focusedDishId === dish.id ? s.cartLineFocused : ""}`}
                  onClick={() => setFocusedDishId(dish.id)}
                >
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
                  <label className={s.itemNoteField}>
                    <span className={s.itemNoteLabel}>Instructions</span>
                    <input
                      className={s.itemNoteInput}
                      type="text"
                      value={itemNotes[dish.id] ?? ""}
                      onChange={(e) => setItemNote(dish.id, e.target.value)}
                      placeholder="No onion, extra sauce…"
                      maxLength={200}
                      aria-label={`Instructions for ${dish.name}`}
                      data-testid={`item-note-${dish.id}`}
                    />
                  </label>
                </div>
              ))}
            </div>
          )}

          {selectedItems.length > 0 && (
            <label className={s.kitchenNoteField} data-testid="kitchen-notes-field">
              <span className={s.itemNoteLabel}>Kitchen notes (whole order)</span>
              <textarea
                className={s.kitchenNoteInput}
                value={kitchenNotes}
                onChange={(e) => setKitchenNotes(e.target.value.slice(0, 300))}
                placeholder="Rush, allergy strip, course timing…"
                rows={2}
                maxLength={300}
                aria-label="Kitchen notes for entire order"
              />
            </label>
          )}

          {/* Numeric keypad — qty / dish-code entry */}
          <div className={s.keypad} data-testid="keypad">
            <div className={s.keypadDisplay} aria-label="Keypad entry">
              {keypad || "0"}
            </div>
            <div className={s.keypadGrid}>
              {["1", "2", "3", "4", "5", "6", "7", "8", "9"].map((d) => (
                <button
                  key={d}
                  type="button"
                  className={s.key}
                  onClick={() => pressKey(d)}
                >
                  {d}
                </button>
              ))}
              <button type="button" className={s.key} onClick={clearKey} aria-label="Clear keypad">
                C
              </button>
              <button type="button" className={s.key} onClick={() => pressKey("0")}>
                0
              </button>
              <button
                type="button"
                className={`${s.key} ${s.keyAccent}`}
                onClick={applyQty}
                title="Set quantity of the focused cart line"
              >
                Qty
              </button>
            </div>
            <button
              type="button"
              className={s.keyCode}
              onClick={applyCode}
              title="Add item by its dish number"
            >
              Add by code #{keypad || "…"}
            </button>
          </div>

          <div className={s.summary}>
            <div className={s.summaryLine}>
              <span>Subtotal</span>
              <span>AED {subtotal.toFixed(2)}</span>
            </div>
            {needsAddress && (
              <div className={s.summaryLine}>
                <span>Delivery</span>
                <span>{fee === "0.00" || fee === "" ? "Free" : `AED ${fee}`}</span>
              </div>
            )}
            <MoneySummary label="TOTAL" amount={total.toFixed(2)} />
          </div>
        </aside>
      </div>

      {/* Classic terminal action row: Cash / Card / KOT / Print / Open Cash / Pending */}
      <div className={s.posActions} role="toolbar" aria-label="Terminal actions">
        <button
          type="button"
          className={`${s.posBtn} ${s.posCash}`}
          onClick={() => onSubmit(true)}
          disabled={!canSubmit}
          data-testid="pos-cash"
        >
          💵 Cash
        </button>
        <button
          type="button"
          className={`${s.posBtn} ${s.posCard}`}
          onClick={() => onSubmit(true)}
          disabled={!canSubmit}
          data-testid="pos-card"
        >
          💳 Card
        </button>
        <button
          type="button"
          className={`${s.posBtn} ${s.posKot}`}
          onClick={() => onSubmit(false)}
          disabled={!canSubmit}
          data-testid="pos-kot"
          title="Send to kitchen without taking payment"
        >
          🍳 KOT
        </button>
        <button
          type="button"
          className={s.posBtnGhost}
          onClick={() => (browsing ? navigate(`/orders/${browsing.id}`) : window.print())}
          data-testid="pos-print"
        >
          🖨 Print Bill
        </button>
        <button
          type="button"
          className={s.posBtnGhost}
          onClick={() => navigate("/payments")}
          data-testid="pos-open-cash"
        >
          💰 Open Cash
        </button>
        <button
          type="button"
          className={s.posBtnGhost}
          onClick={() => navigate("/orders")}
          data-testid="pos-pending"
        >
          📋 Pending {openBillsCount != null ? `(${openBillsCount})` : ""}
        </button>
      </div>

      <BottomActionBar>
        <span className={s.waHint}>
          {waiterMode
            ? "Floor: set qty & notes per item, then send to kitchen"
            : cashierMode
              ? "Cashier: place order → bill opens for payment"
              : phone.trim()
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
        <TouchButton
          type="button"
          disabled={!canSubmit}
          onClick={() => onSubmit()}
          data-testid="new-order-primary-cta"
        >
          {submitting
            ? waiterMode
              ? "Sending…"
              : cashierMode
                ? "Placing…"
                : "Placing…"
            : waiterMode
              ? `Send to kitchen${total > 0 ? ` — AED ${total.toFixed(2)}` : ""}`
              : cashierMode
                ? `Place & Pay${total > 0 ? ` — AED ${total.toFixed(2)}` : ""}`
                : `Place Order${total > 0 ? ` — AED ${total.toFixed(2)}` : ""}`}
        </TouchButton>
      </BottomActionBar>
    </div>
  );
}

function SkField({ labelWidth }: { labelWidth?: number }) {
  return (
    <div className={s.field}>
      <span
        className={`${s.sk} ${s.skLabel}`}
        style={labelWidth ? { width: labelWidth } : undefined}
      />
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
