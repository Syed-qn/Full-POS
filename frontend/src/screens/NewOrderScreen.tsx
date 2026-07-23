import { Fragment, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { logout } from "../lib/auth";
import { fetchOrderDetail } from "../lib/orderDetailApi";
import { fetchActiveMenu } from "../lib/menuApi";
import {
  addOrderItems,
  createManualOrder,
  createPosOrder,
  fetchNextToken,
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
/** "seated for" label from an ISO start time — 00:30h / 01:03h like the floor plan. */
function seatedFor(iso?: string | null): string | null {
  if (!iso) return null;
  const mins = Math.max(0, Math.floor((Date.now() - Date.parse(iso)) / 60_000));
  if (Number.isNaN(mins)) return null;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}h`;
}

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
  const [searchParams] = useSearchParams();
  const waiterMode = isWaiterRole();
  const cashierMode = isCashierRole();

  const [menu, setMenu] = useState<MenuOut | null | "loading">("loading");

  // Counter roles start on Dining (the first tab); the delivery-origin default
  // only makes sense for the manager delivery flow.
  const [orderType, setOrderType] = useState<OrderTypeKey>(() =>
    cashierMode || waiterMode ? "dine_in" : "delivery",
  );
  const needsAddress = ADDRESS_REQUIRED.has(orderType);

  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [tableNo, setTableNo] = useState("");
  const [tables, setTables] = useState<
    {
      id: number;
      label: string;
      status: string;
      seats: number;
      order_id?: number | null;
      order_total_aed?: string | null;
      seated_since?: string | null;
    }[]
  >([]);
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
  // Predicted next daily queue token for a fresh ticket (real one is assigned on save).
  const [nextToken, setNextToken] = useState<number | null>(null);
  // Terminal numeric keypad entry buffer (dish code / quantity multiplier).
  const [keyBuf, setKeyBuf] = useState("");
  // Items already on the open tab when adding another round to a dine-in table.
  const [tabItems, setTabItems] = useState<
    { dish_name: string; qty: number; line_total: string }[]
  >([]);

  // Highlights the last-touched cart line (kept for the tile/cart focus styling).
  const [focusedDishId, setFocusedDishId] = useState<number | null>(null);
  // Which cart lines have their per-item note field expanded (opened via ✎).
  const [openNotes, setOpenNotes] = useState<Record<number, boolean>>({});

  useEffect(() => {
    fetchActiveMenu().then((m) => setMenu(m));
  }, []);

  // Arriving from the Floor Plan ("New table order") → preselect dine-in + table.
  useEffect(() => {
    const table = searchParams.get("table");
    if (table) {
      setOrderType("dine_in");
      setTableNo(table);
    }
  }, [searchParams]);

  // Real tables for the dine-in picker (label + seats + live status).
  useEffect(() => {
    apiClient
      .get<
        {
          id: number;
          label: string;
          status: string;
          seats: number;
          order_id?: number | null;
          order_total_aed?: string | null;
          seated_since?: string | null;
        }[]
      >("/api/v1/tables")
      .then((rows) => setTables(Array.isArray(rows) ? rows : []))
      .catch(() => setTables([]));
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
    fetchNextToken()
      .then((t) => {
        if (!cancelled) setNextToken(t);
      })
      .catch(() => {
        if (!cancelled) setNextToken(null);
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
  }

  const selectedTable = useMemo(
    () => tables.find((t) => String(t.id) === tableNo) ?? null,
    [tables, tableNo],
  );

  const dineInMode = orderType === "dine_in";
  // On-premise (dine-in / takeaway) share the clean single action bar with an
  // immediate "Pay now"; delivery/online are COD-on-arrival, so they get a
  // place-only bar. No mode shows the old stacked terminal toolbar.
  const isOnPremiseType = orderType === "dine_in" || orderType === "takeaway";
  // Dine-in "another round": picking an occupied table appends to its open tab
  // instead of starting a new order.
  const addingToTab =
    orderType === "dine_in" && !!selectedTable?.order_id;

  // When adding a round to an occupied table, load what's already on its tab so
  // the cashier sees the running order (the cart below holds only NEW items).
  const tabOrderId = addingToTab ? selectedTable?.order_id ?? null : null;
  useEffect(() => {
    if (tabOrderId == null) {
      setTabItems([]);
      return;
    }
    let cancelled = false;
    fetchOrderDetail(tabOrderId, { include: "overview" })
      .then((d) => {
        if (!cancelled) setTabItems(Array.isArray(d.items) ? d.items : []);
      })
      .catch(() => {
        if (!cancelled) setTabItems([]);
      });
    return () => {
      cancelled = true;
    };
  }, [tabOrderId]);

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


  // ── Token / open-ticket navigation ───────────────────────────────
  const browsing = browseIdx != null ? openOrders[browseIdx] : null;
  // Only an existing ticket has a real number. A NEW ticket has none yet —
  // the backend assigns the order number on save — so never fabricate one.
  const tokenNumber = browsing?.order_number ?? null;
  function stepToken(dir: -1 | 1) {
    if (openOrders.length === 0) return;
    setBrowseIdx((i) => {
      if (i == null) return dir === -1 ? openOrders.length - 1 : 0;
      const next = i + dir;
      if (next < 0 || next >= openOrders.length) return null; // back to NEW ticket
      return next;
    });
  }

  // ── Terminal keypad ──────────────────────────────────────────────
  function pressKey(k: string) {
    setKeyBuf((b) => {
      if (k === "⌫") return b.slice(0, -1);
      if (k === ".") return b.includes(".") ? b : b === "" ? "0." : b + ".";
      return (b + k).replace(/^0+(?=\d)/, "").slice(0, 6);
    });
  }
  /** Add a dish, honouring a pending keypad quantity ("5" then tap = +5). */
  function addDishQty(dishId: number) {
    const n = parseInt(keyBuf, 10);
    setQty(dishId, Number.isFinite(n) && n > 0 ? n : 1);
    setKeyBuf("");
  }
  /** "Code" key: add the dish whose number matches the buffer. */
  function applyCode() {
    const num = parseInt(keyBuf, 10);
    if (Number.isFinite(num)) {
      const dish = dishes.find((d) => d.dish_number === num);
      if (dish) {
        setActiveCategory("all");
        addDishQty(dish.id);
        return;
      }
    }
    setKeyBuf("");
  }
  /** "Token" key: jump to the open ticket with that daily token. */
  function applyToken() {
    const num = parseInt(keyBuf, 10);
    if (Number.isFinite(num)) {
      const idx = openOrders.findIndex((o) => o.daily_token === num);
      if (idx >= 0) setBrowseIdx(idx);
    }
    setKeyBuf("");
  }
  /** ▲ / ▼ move the highlighted cart line's selection. */
  function moveSelection(dir: -1 | 1) {
    const idx = selectedItems.findIndex((it) => it.dish.id === focusedDishId);
    if (idx < 0) return;
    const next = idx + dir;
    if (next < 0 || next >= selectedItems.length) return;
    setFocusedDishId(selectedItems[next].dish.id);
  }

  const phoneOk = phone.trim().length >= 7;
  const canSubmit =
    selectedItems.length > 0 &&
    !submitting &&
    (needsAddress
      ? // Delivery / Online: phone + full address + fee + map pin required.
        phoneOk &&
        aptRoom.trim() !== "" &&
        building.trim() !== "" &&
        receiverName.trim() !== "" &&
        fee !== "" &&
        pin !== null
      : orderType === "dine_in"
        ? // Dine-in: a table is required; phone is optional (walk-in).
          tableNo !== ""
        : // Takeaway: just items; phone optional (walk-in).
          true);

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
      // Occupied dine-in table → append this round to the existing tab.
      if (addingToTab && selectedTable?.order_id) {
        order = await addOrderItems(selectedTable.order_id, buildItems());
        if (goPay && order?.id) {
          navigate(`/orders/${order.id}/pay`);
        } else {
          navigate(`/orders/${order.id}`);
        }
        return;
      }
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
          // Walk-in dine-in/takeaway may have no phone — send a generic walk-in
          // number so the till can still ring the sale.
          customer_phone: phone.trim() || "0000000000",
          customer_name: name.trim() || (phone.trim() ? null : "Walk-in"),
          items: buildItems(),
          table_id:
            orderType === "dine_in" && tableNo.trim()
              ? Number(tableNo.trim()) || null
              : null,
          covers: null,
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

  // ── Cashier full-screen terminal (HANASIS-style single screen) ──────────
  if (cashierMode) {
    const vat = total - total / 1.05;
    return (
      <div className={s.term} data-testid="cashier-terminal">
        {/* ============ HEADER — order-type switcher across the top ============ */}
        <header className={s.tHeader} data-testid="terminal-header">
          <div className={s.tTabs} role="tablist" aria-label="Order type">
            {ORDER_TYPE_TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={orderType === t.key}
                className={`${s.tTab} ${orderType === t.key ? s.tTabActive : ""}`}
                onClick={() => setOrderType(t.key)}
                data-testid={`order-type-${t.key}`}
              >
                {t.label}
              </button>
            ))}
          </div>
          {selectedTable && (
            <span className={s.tHeaderTable}>🍽️ {selectedTable.label}</span>
          )}
        </header>

        {/* ============ LEFT PANEL ============ */}
        <div className={s.termLeft}>
          {/* Dine-in: pick the table on the floor plan first; dishes go on the right. */}
          {dineInMode && !selectedTable && (
            <div className={s.tFloor} data-testid="terminal-floor-plan">
              <div className={s.tFloorHdr}>Select a table</div>
              {tables.length === 0 ? (
                <p className={s.tFloorEmpty}>
                  No tables set up yet — add tables in Floor Plan first.
                </p>
              ) : (
                <div className={s.tFloorGrid}>
                  {tables.map((t) => {
                    const busyTable = !!t.order_id;
                    const seatCount = Math.min(t.seats ?? 4, 10);
                    const topSeats = Math.ceil(seatCount / 2);
                    const bottomSeats = seatCount - topSeats;
                    const sinceLabel = seatedFor(t.seated_since);
                    return (
                      <button
                        key={t.id}
                        type="button"
                        className={`${s.tTable} ${busyTable ? s.tTableBusy : s.tTableFree}`}
                        onClick={() => setTableNo(String(t.id))}
                        data-testid={`terminal-table-${t.id}`}
                        aria-label={`Table ${t.label}${busyTable ? " — open tab" : " — free"}`}
                      >
                        <span className={s.tSeatRow}>
                          {Array.from({ length: topSeats }).map((_, i) => (
                            <span key={i} className={s.tSeat} />
                          ))}
                        </span>
                        <span className={s.tSeatMid}>
                          <span className={s.tSeatSide} />
                          <span className={s.tTableTop}>
                            <span className={s.tTableLabel}>{t.label}</span>
                            {busyTable && (
                              <>
                                <span className={s.tTablePill}>
                                  💰 {t.order_total_aed ?? "0.00"}
                                </span>
                                {sinceLabel && (
                                  <span className={s.tTablePill}>⏱ {sinceLabel}</span>
                                )}
                              </>
                            )}
                          </span>
                          <span className={s.tSeatSide} />
                        </span>
                        <span className={s.tSeatRow}>
                          {Array.from({ length: bottomSeats }).map((_, i) => (
                            <span key={i} className={s.tSeat} />
                          ))}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {dineInMode && selectedTable && (
            <div className={s.tTableChip} data-testid="terminal-table-chip">
              <span>
                🍽️ Table <strong>{selectedTable.label}</strong>
                {selectedTable.order_id ? " · adding to open tab" : ""}
              </span>
              <button
                type="button"
                className={s.tChangeTable}
                onClick={() => setTableNo("")}
              >
                Change table
              </button>
            </div>
          )}

          {/* token + bill number + ticket nav */}
          <div className={s.tTokenRow}>
            <span className={s.tTokenLabel}>TOKEN</span>
            <span className={s.tTokenNum} data-testid="token-value">
              {browsing ? browsing.daily_token ?? "—" : nextToken ?? "—"}
            </span>
            <button
              type="button"
              className={s.tArrowBtn}
              onClick={() => stepToken(-1)}
              disabled={openOrders.length === 0}
              aria-label="Previous ticket"
            >
              ◀
            </button>
            <span className={s.tBill}>{browsing?.order_number ?? "NEW"}</span>
            <button
              type="button"
              className={s.tArrowBtn}
              onClick={() => stepToken(1)}
              disabled={openOrders.length === 0}
              aria-label="Next ticket"
            >
              ▶
            </button>
          </div>

          {/* assign delivery (delivery/online only) + customers count */}
          <div className={s.tAssignRow}>
            {needsAddress ? (
              <button type="button" className={s.tAssignLink} disabled title="Coming soon">
                Assign Delivery
              </button>
            ) : (
              <span />
            )}
            <span className={s.tCustomers}>
              Customers: <strong>{selectedItems.length > 0 ? 1 : 0}</strong>
            </span>
          </div>
          {/* staffing: waiter for dine-in, driver for delivery/online, nothing for takeaway */}
          {dineInMode && (
            <button
              type="button"
              className={`${s.tSelectBtn} ${s.tSelectFull}`}
              disabled
              title="Coming soon"
            >
              (Select Waiter)
            </button>
          )}
          {needsAddress && (
            <button
              type="button"
              className={`${s.tSelectBtn} ${s.tSelectFull}`}
              disabled
              title="Coming soon"
            >
              (Select Driver)
            </button>
          )}

          {/* customer block — address/flat only for delivery/online */}
          <div className={s.tCustomer}>
            <div className={s.tRow2}>
              <input
                className={s.tInput}
                placeholder="Customer Name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                aria-label="Customer name"
              />
              <input
                className={s.tInput}
                placeholder={needsAddress ? "Tel *" : "Tel (optional)"}
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                aria-label="Phone"
              />
            </div>
            {needsAddress && (
              <div className={s.tRow2}>
                <input
                  className={s.tInput}
                  placeholder="Address"
                  value={building}
                  onChange={(e) => setBuilding(e.target.value)}
                  aria-label="Address"
                />
                <input
                  className={s.tInput}
                  placeholder="Flat / Room No"
                  value={aptRoom}
                  onChange={(e) => setAptRoom(e.target.value)}
                  aria-label="Flat or room number"
                />
              </div>
            )}
            <input
              className={s.tInput}
              placeholder="🔍 Search items or #number"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search items"
            />
          </div>

          {/* Existing tab (when adding a round to an occupied table) */}
          {addingToTab && (
            <div className={s.tTabBanner} data-testid="terminal-open-tab">
              <div className={s.tTabHead}>
                🧾 {selectedTable?.label ?? "Table"} · open tab #{selectedTable?.order_id}
                {selectedTable?.order_total_aed ? ` · AED ${selectedTable.order_total_aed}` : ""}
              </div>
              {tabItems.length > 0 ? (
                <ul className={s.tTabItems}>
                  {tabItems.map((it, i) => (
                    <li key={i}>
                      <span>
                        {it.qty}× {it.dish_name}
                      </span>
                      <span className={s.tTabAmt}>AED {it.line_total}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className={s.tTabHint}>Loading current items…</div>
              )}
              <div className={s.tTabHint}>New items you add below are appended to this tab.</div>
            </div>
          )}

          {/* cart grid */}
          <div className={s.tCartWrap}>
            <table className={s.cartTable}>
              <thead>
                <tr>
                  <th className={s.thRowNo} aria-label="Row" />
                  <th className={s.thCode}>Code</th>
                  <th className={s.thName}>Particulars</th>
                  <th className={s.thNum}>Price</th>
                  <th className={s.thQty}>Qty</th>
                  <th className={s.thNum}>Amount</th>
                </tr>
              </thead>
              <tbody>
                {selectedItems.length === 0 ? (
                  <tr>
                    <td colSpan={6} className={s.tEmptyRow}>
                      No items yet — tap a dish on the right.
                    </td>
                  </tr>
                ) : (
                  selectedItems.map(({ dish, qty }, i) => {
                    const price = parseFloat(dish.price_aed ?? "0");
                    return (
                      <tr
                        key={dish.id}
                        className={`${s.cartTr} ${focusedDishId === dish.id ? s.cartTrActive : ""}`}
                        onClick={() => setFocusedDishId(dish.id)}
                      >
                        <td className={s.tdRowNo}>{i + 1}</td>
                        <td className={s.tdCode}>#{dish.dish_number}</td>
                        <td className={s.tdName}>{dish.name}</td>
                        <td className={s.tdNum}>{price.toFixed(2)}</td>
                        <td className={s.tdQty}>
                          <div className={s.qtyMini}>
                            <button
                              type="button"
                              className={s.qtyMiniBtn}
                              onClick={(e) => {
                                e.stopPropagation();
                                setQty(dish.id, -1);
                              }}
                              aria-label={`Remove one ${dish.name}`}
                            >
                              −
                            </button>
                            <span className={s.qtyMiniNum}>{qty}</span>
                            <button
                              type="button"
                              className={`${s.qtyMiniBtn} ${s.qtyMiniBtnActive}`}
                              onClick={(e) => {
                                e.stopPropagation();
                                setQty(dish.id, 1);
                              }}
                              aria-label={`Add one ${dish.name}`}
                            >
                              +
                            </button>
                          </div>
                        </td>
                        <td className={`${s.tdNum} ${s.tdAmt}`}>{(price * qty).toFixed(2)}</td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* totals */}
          <div className={s.tTotals}>
            <div className={s.tTotRow}>
              <span>Total</span>
              <span>AED {subtotal.toFixed(2)}</span>
            </div>
            <div className={s.tTotRow}>
              <span>VAT (5% incl.)</span>
              <span>AED {vat.toFixed(2)}</span>
            </div>
            <div className={s.tTotRow}>
              <span>Round Off</span>
              <span>AED 0.00</span>
            </div>
            <div className={`${s.tTotRow} ${s.tTotNet}`}>
              <span>Net Value</span>
              <span>AED {total.toFixed(2)}</span>
            </div>
          </div>

          {/* item action row */}
          <div className={s.tActionRow}>
            <button type="button" className={s.tActBtn} disabled title="Coming soon">
              Change Rate
            </button>
            <button
              type="button"
              className={s.tActBtn}
              onClick={() =>
                focusedDishId && setQty(focusedDishId, -(quantities[focusedDishId] ?? 0))
              }
              disabled={focusedDishId == null}
            >
              Cancel Item
            </button>
            <button
              type="button"
              className={s.tActBtn}
              onClick={() =>
                focusedDishId && setOpenNotes((p) => ({ ...p, [focusedDishId]: true }))
              }
              disabled={focusedDishId == null}
            >
              Note
            </button>
            <button
              type="button"
              className={`${s.tActBtn} ${s.tMinus}`}
              onClick={() => focusedDishId && setQty(focusedDishId, -1)}
              disabled={focusedDishId == null}
              aria-label="Decrease selected"
            >
              −
            </button>
            <button
              type="button"
              className={`${s.tActBtn} ${s.tPlus}`}
              onClick={() => focusedDishId && setQty(focusedDishId, 1)}
              disabled={focusedDishId == null}
              aria-label="Increase selected"
            >
              +
            </button>
            <button
              type="button"
              className={`${s.tActBtn} ${s.tMove}`}
              onClick={() => moveSelection(-1)}
              disabled={focusedDishId == null}
              title="Move selection up"
              aria-label="Move selection up"
            >
              ▲
            </button>
            <button
              type="button"
              className={`${s.tActBtn} ${s.tMove}`}
              onClick={() => moveSelection(1)}
              disabled={focusedDishId == null}
              title="Move selection down"
              aria-label="Move selection down"
            >
              ▼
            </button>
          </div>

          {/* button grid */}
          <div className={s.tBtnGrid}>
            <button type="button" className={s.tBtn} onClick={clearCart}>
              New Bill
            </button>
            <button
              type="button"
              className={s.tBtn}
              onClick={() =>
                focusedDishId && setQty(focusedDishId, -(quantities[focusedDishId] ?? 0))
              }
            >
              Delete
            </button>
            <button type="button" className={s.tBtn} onClick={() => window.print()}>
              Print Bill
            </button>
            <button type="button" className={s.tBtn} onClick={() => navigate("/orders")}>
              Pending{openBillsCount != null ? ` (${openBillsCount})` : ""}
            </button>
            <button
              type="button"
              className={s.tBtn}
              onClick={() => onSubmit(false)}
              disabled={!canSubmit}
              data-testid="terminal-kot"
            >
              KOT
            </button>
            <button type="button" className={s.tBtn} onClick={() => navigate("/payments")}>
              Open Cash
            </button>
            <button
              type="button"
              className={`${s.tBtn} ${s.tBtnCash}`}
              onClick={() => onSubmit(true)}
              disabled={!canSubmit}
              data-testid="terminal-cash"
            >
              CASH
            </button>
            <button
              type="button"
              className={`${s.tBtn} ${s.tBtnCard}`}
              onClick={() => onSubmit(true)}
              disabled={!canSubmit}
              data-testid="terminal-card"
            >
              CARD
            </button>
            <button type="button" className={s.tBtn} onClick={() => navigate("/floor")}>
              Table Orders
            </button>
            <button type="button" className={s.tBtn} onClick={() => navigate("/payments")}>
              More Payments
            </button>
          </div>
        </div>

        {/* ============ RIGHT PANEL ============ */}
        <div className={s.termRight}>
          <div className={s.tCatHdr}>
            <span>Select Category</span>
            <input
              type="search"
              className={s.tSearch}
              placeholder="🔍 Search dish or number…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search dishes"
              data-testid="terminal-dish-search"
            />
            <span className={s.tDate}>{today()}</span>
          </div>
          <div className={s.tRightBody}>
            {/* Category tile grid (scrollable column) — like the reference. */}
            <div className={s.tCatGrid} role="tablist" aria-label="Categories">
              <button
                type="button"
                role="tab"
                aria-selected={activeCategory === "all"}
                className={`${s.tCat} ${activeCategory === "all" ? s.tCatActive : ""}`}
                onClick={() => setActiveCategory("all")}
              >
                ALL
              </button>
              {categories.map((cat) => (
                <button
                  key={cat}
                  type="button"
                  role="tab"
                  aria-selected={activeCategory === cat}
                  className={`${s.tCat} ${activeCategory === cat ? s.tCatActive : ""}`}
                  onClick={() => setActiveCategory(cat)}
                >
                  {cat}
                </button>
              ))}
            </div>
            <div className={s.tItemsCol}>
              <div className={s.tItems}>
                {filteredDishes.map((dish) => {
                  const qty = quantities[dish.id] ?? 0;
                  return (
                    <button
                      key={dish.id}
                      type="button"
                      className={`${s.tItemTile} ${qty > 0 ? s.tItemTileActive : ""}`}
                      onClick={() => addDishQty(dish.id)}
                      aria-label={`Add ${dish.name}`}
                    >
                      <span className={s.tItemTop}>
                        <span className={s.tItemNum}>#{dish.dish_number}</span>
                        <span className={s.tItemPrice}>{dish.price_aed}</span>
                      </span>
                      <span className={s.tItemName}>{dish.name}</span>
                      {qty > 0 && <span className={s.tItemQtyBadge}>{qty}</span>}
                    </button>
                  );
                })}
              </div>
              {/* Numeric keypad + side keys */}
              <div className={s.tKeypadWrap} aria-label="Numeric keypad">
                <div className={s.tKeypadMain}>
                  <div className={s.tKeyDisplay} data-testid="keypad-buffer">
                    {keyBuf || "0"}
                  </div>
                  <div className={s.tKeypad}>
                    {["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "⌫"].map((k) => (
                      <button
                        key={k}
                        type="button"
                        className={s.tKey}
                        onClick={() => pressKey(k)}
                      >
                        {k}
                      </button>
                    ))}
                  </div>
                </div>
                <div className={s.tKeypadSide}>
                  <button
                    type="button"
                    className={s.tKeySide}
                    onClick={applyCode}
                    title="Add the dish with this code"
                  >
                    Code
                  </button>
                  <button type="button" className={s.tKeySide} disabled title="Coming soon">
                    Rate
                  </button>
                  <button
                    type="button"
                    className={s.tKeySide}
                    onClick={applyToken}
                    title="Jump to this token's open ticket"
                  >
                    Token
                  </button>
                  <button type="button" className={s.tKeySide} disabled title="Coming soon">
                    Disc
                  </button>
                  <button type="button" className={s.tKeySide} disabled title="Coming soon">
                    Disc%
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ============ BOTTOM STATUS / NAV BAR ============ */}
        <div className={s.tStatusBar}>
          <button
            type="button"
            className={s.tStatusItem}
            data-testid="cashier-signout"
            onClick={() => {
              logout();
              navigate("/login", { replace: true });
            }}
          >
            🔒 Sign-Out
          </button>
          <button type="button" className={s.tStatusItem} onClick={() => navigate("/customers")}>
            Customers
          </button>
          <button type="button" className={s.tStatusItem} onClick={() => navigate("/orders")}>
            Orders
          </button>
          <button type="button" className={s.tStatusItem} onClick={() => navigate("/floor")}>
            Floor
          </button>
          <button type="button" className={s.tStatusItem} onClick={() => navigate("/payments")}>
            Payments
          </button>
          <span className={s.tStatusSpacer} />
          <span className={s.tStatusClock}>{today()}</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`${s.screen} ${s.terminal} ${cashierMode ? s.screenCashier : ""}`}>
      {!cashierMode && (
        <PageHeader
          title={waiterMode ? "Table order" : "New Order"}
          subtitle={
            waiterMode
              ? "Quantity, instructions, modifiers — send to kitchen (payment at cashier)"
              : "Delivery POS · large items · cart always visible"
          }
        />
      )}
      {!cashierMode && <OfflineLimitsBanner surface="new-order" />}

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
            {browsing
              ? browsing.daily_token ?? tokenNumber
              : nextToken != null
                ? `${nextToken} · NEW`
                : "NEW"}
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
          <button
            type="button"
            className={`${s.cashierChip} ${s.cashierSignOut}`}
            data-testid="cashier-signout"
            onClick={() => {
              logout();
              navigate("/login", { replace: true });
            }}
          >
            Sign out
          </button>
        </div>
      )}

      {error && <div className={s.errorBanner} role="alert">{error}</div>}

      <div className={`${s.posLayout} ${cashierMode ? s.posLayoutCashier : ""}`}>
        {/* LEFT — customer + address / table */}
        <div className={s.leftCol}>
          <div className={s.section}>
            <div className={s.sectionTitle}>Customer</div>

            <div className={s.field}>
              <label className={s.label}>
                Phone {needsAddress ? "*" : "(optional)"}
              </label>
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
                <label className={s.label}>Table *</label>
                <select
                  className={s.input}
                  value={tableNo}
                  onChange={(e) => setTableNo(e.target.value)}
                  data-testid="table-select"
                  aria-label="Select table"
                >
                  <option value="">Select table…</option>
                  {tables.map((t) => (
                    <option key={t.id} value={String(t.id)}>
                      {t.label} · {t.seats} seats
                      {t.status !== "available" ? ` · ${t.status}` : " · free"}
                    </option>
                  ))}
                </select>
                {tables.length === 0 && (
                  <span className={s.fieldHint}>
                    No tables set up yet — add tables in Floor Plan first.
                  </span>
                )}
                {selectedTable?.order_id ? (
                  <div className={s.occupiedBanner} data-testid="table-occupied">
                    🧾 {selectedTable.label} has an open tab · bill #
                    {selectedTable.order_id}
                    {selectedTable.order_total_aed
                      ? ` (AED ${selectedTable.order_total_aed})`
                      : ""}
                    . New items will be <strong>added to this tab</strong>.{" "}
                    <button
                      type="button"
                      className={s.linkBtn}
                      onClick={() => navigate(`/orders/${selectedTable.order_id}`)}
                    >
                      View bill
                    </button>
                  </div>
                ) : null}
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
          ) : null}
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
            <div className={s.cartTableWrap}>
              <table className={s.cartTable}>
                <thead>
                  <tr>
                    <th className={s.thCode}>Code</th>
                    <th className={s.thName}>Particulars</th>
                    <th className={s.thNum}>Price</th>
                    <th className={s.thQty}>Qty</th>
                    <th className={s.thNum}>Amount</th>
                    <th className={s.thNote} aria-label="Note" />
                  </tr>
                </thead>
                <tbody>
                  {selectedItems.map(({ dish, qty }) => {
                    const noteOpen = !!openNotes[dish.id] || !!itemNotes[dish.id];
                    const price = parseFloat(dish.price_aed ?? "0");
                    return (
                      <Fragment key={dish.id}>
                        <tr className={s.cartTr}>
                          <td className={s.tdCode}>#{dish.dish_number}</td>
                          <td className={s.tdName}>{dish.name}</td>
                          <td className={s.tdNum}>{price.toFixed(2)}</td>
                          <td className={s.tdQty}>
                            <div className={s.qtyMini}>
                              <button
                                type="button"
                                className={s.qtyMiniBtn}
                                onClick={() => setQty(dish.id, -1)}
                                aria-label={`Remove one ${dish.name}`}
                              >
                                −
                              </button>
                              <span className={s.qtyMiniNum} aria-label={`${dish.name} quantity`}>
                                {qty}
                              </span>
                              <button
                                type="button"
                                className={`${s.qtyMiniBtn} ${s.qtyMiniBtnActive}`}
                                onClick={() => setQty(dish.id, 1)}
                                aria-label={`Add one ${dish.name}`}
                              >
                                +
                              </button>
                            </div>
                          </td>
                          <td className={`${s.tdNum} ${s.tdAmt}`}>{(price * qty).toFixed(2)}</td>
                          <td className={s.tdNoteCell}>
                            <button
                              type="button"
                              className={`${s.noteToggle} ${noteOpen ? s.noteToggleOn : ""}`}
                              onClick={() =>
                                setOpenNotes((prev) => ({ ...prev, [dish.id]: !noteOpen }))
                              }
                              aria-label={`Note for ${dish.name}`}
                              title="Add a note"
                            >
                              ✎
                            </button>
                          </td>
                        </tr>
                        {noteOpen && (
                          <tr className={s.cartNoteTr}>
                            <td colSpan={6}>
                              <input
                                className={s.itemNoteInput}
                                type="text"
                                value={itemNotes[dish.id] ?? ""}
                                onChange={(e) => setItemNote(dish.id, e.target.value)}
                                placeholder={`Note for ${dish.name} — no onion, extra sauce…`}
                                maxLength={200}
                                aria-label={`Instructions for ${dish.name}`}
                                data-testid={`item-note-${dish.id}`}
                              />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
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
            {/* UAE prices are VAT-inclusive → show the 5% portion for the bill,
                does not change what's charged. */}
            <div className={s.summaryLine}>
              <span>VAT (5% incl.)</span>
              <span>AED {(total - total / 1.05).toFixed(2)}</span>
            </div>
            <MoneySummary label="TOTAL" amount={total.toFixed(2)} />
          </div>
        </aside>
      </div>

      {/* ONE clean action bar for every order type — same layout as dine-in
          (no stacked terminal toolbar). On-premise gets an immediate "Pay now";
          delivery/online is COD-on-arrival so it's place-only. */}
      <BottomActionBar>
        <div className={s.dineInActions}>
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
          {isOnPremiseType && (
            <Button
              type="button"
              variant="ghost"
              size="lg"
              disabled={!canSubmit}
              onClick={() => onSubmit(true)}
              data-testid="pos-pay-now"
            >
              💳 Pay now
            </Button>
          )}
          <TouchButton
            type="button"
            disabled={!canSubmit}
            onClick={() => onSubmit(isOnPremiseType ? false : undefined)}
            data-testid="new-order-primary-cta"
          >
            {submitting
              ? addingToTab
                ? "Adding…"
                : waiterMode
                  ? "Sending…"
                  : "Placing…"
              : addingToTab
                ? `➕ Add to tab${total > 0 ? ` — AED ${total.toFixed(2)}` : ""}`
                : dineInMode
                  ? `🍽 Save to Table${total > 0 ? ` — AED ${total.toFixed(2)}` : ""}`
                  : isOnPremiseType
                    ? `🧾 Place Order${total > 0 ? ` — AED ${total.toFixed(2)}` : ""}`
                    : waiterMode
                      ? `Send to kitchen${total > 0 ? ` — AED ${total.toFixed(2)}` : ""}`
                      : cashierMode
                        ? `Place & Pay${total > 0 ? ` — AED ${total.toFixed(2)}` : ""}`
                        : `📱 Place Order${total > 0 ? ` — AED ${total.toFixed(2)}` : ""}`}
          </TouchButton>
        </div>
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
