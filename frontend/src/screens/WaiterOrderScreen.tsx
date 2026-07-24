import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "../components/Toaster";
import { WaiterTopBar, type WaiterSection } from "../components/WaiterTopBar";
import { apiClient } from "../lib/apiClient";
import {
  addOrderItems,
  confirmOrder,
  createManualOrder,
  createPosOrder,
  fetchNextToken,
  fireCourse,
  lookupCustomer,
  setOrderCovers,
  setTableStatus,
} from "../lib/manualOrderApi";
import { useLiveMenu } from "../lib/useLiveMenu";
import { advanceOrder } from "../lib/ordersApi";
import { chargePayment } from "../lib/paymentsApi";
import { getStaffSession, isCashierRole } from "../lib/navAccess";
import { usePosTheme } from "../lib/posTheme";
import { fetchOrderDetail } from "../lib/orderDetailApi";
import { getClockStatus, listStaff } from "../lib/staffApi";
import { LocationPicker } from "../components/LocationPicker";
import type { RestaurantOut, StaffMember } from "../lib/types";
import s from "./WaiterOrderScreen.module.css";

/** VAT is 5% inclusive (AED / UAE) per the platform spec — not the rate on any
 *  reference screenshot. Displayed back out of the inclusive total. */
const VAT_RATE = 0.05;

/* The menu now comes from useLiveMenu, which keeps the module-level cache (so a
   table tap paints instantly) AND polls, so a dish marked unavailable in the
   manager disappears from this terminal without anyone reloading the page. */

/** Category tile colours, cycled in menu order so the pad stays colourful. */
const CAT_COLORS = [
  "#d4471f",
  "#0e7a55",
  "#a86a12",
  "#a51f2e",
  "#a01844",
  "#6b3fa0",
  "#155e8a",
  "#0d7a70",
];

type ApiTable = {
  id: number;
  label: string;
  seats: number;
  status: string;
  order_id?: number | null;
  guests?: number | null;
};

type OrderTypeKey = "dine_in" | "takeaway" | "delivery" | "online";

const SECTION_BY_TYPE: Record<OrderTypeKey, WaiterSection> = {
  dine_in: "dining",
  takeaway: "takeaway",
  delivery: "delivery",
  online: "online",
};

function money(n: number): string {
  return n.toFixed(2);
}

/** Delivery fee tier from restaurant settings (distance → fee). */
interface FeeTier {
  max_km: number;
  fee_aed: number | string;
}
interface FeeChoice {
  value: string;
  label: string;
}

/** Build the picker options from the configured tiers (≤3 km free, etc.). */
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

/**
 * Waiter order terminal — the dark screen a waiter lands on after tapping a
 * table on the floor. Cart + keypad on the left, menu on the right, ticket
 * actions along the bottom. Payment is intentionally NOT available here:
 * waiters send to kitchen, the cashier tenders the bill.
 */
export function WaiterOrderScreen() {
  const navigate = useNavigate();
  // Namespace all in-terminal navigation off the CURRENT path so waiters stay
  // under /waiter/*, cashiers under /cashier/*, and staff on the plain paths.
  const { pathname } = useLocation();
  const floorPath = pathname.startsWith("/cashier")
    ? "/cashier/floor"
    : pathname.startsWith("/waiter")
      ? "/waiter/floor"
      : "/floor";
  const orderPath = pathname.startsWith("/cashier")
    ? "/cashier/new-order"
    : pathname.startsWith("/waiter")
      ? "/waiter/new-order"
      : "/new-order";
  // Tender is a ROLE capability (cashier), independent of the URL namespace.
  const isCashier = isCashierRole();
  const theme = usePosTheme();
  const [params] = useSearchParams();
  const staff = getStaffSession();

  const tableParam = params.get("table") ?? "";
  const typeParam = (params.get("type") ?? "dine_in") as OrderTypeKey;
  const orderType: OrderTypeKey = ["dine_in", "takeaway", "delivery", "online"].includes(typeParam)
    ? typeParam
    : "dine_in";

  // Cached for an instant repaint on a repeat table tap, and polled so an
  // availability change in the manager reaches this terminal on its own.
  const { dishes, loading: menuLoading, error: menuError } = useLiveMenu({ cache: true });
  const [tables, setTables] = useState<ApiTable[]>([]);
  const [staffList, setStaffList] = useState<StaffMember[]>([]);
  const [onShiftIds, setOnShiftIds] = useState<Set<number>>(new Set());
  const [waiterId, setWaiterId] = useState<number | "">(staff?.staff_id ?? "");
  const [covers, setCovers] = useState(2);
  const [nextToken, setNextToken] = useState<number | null>(null);
  const [activeCat, setActiveCat] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [qty, setQty] = useState<Record<number, number>>({});
  const [focusedId, setFocusedId] = useState<number | null>(null);
  const [keyBuf, setKeyBuf] = useState("");
  const [submitting, setSubmitting] = useState(false);
  /** Per-line kitchen notes, keyed by dish id — the only note the API carries. */
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [noteOpen, setNoteOpen] = useState(false);
  /** Bumped after a send so the open-tab banner re-reads the order. */
  const [tabRefresh, setTabRefresh] = useState(0);
  const [tabItems, setTabItems] = useState<
    {
      dish_number: number;
      dish_name: string;
      qty: number;
      line_total: string;
      course_held?: boolean;
      is_takeaway?: boolean;
    }[]
  >([]);
  /** Status of the table's open order — decides whether KOT still has work. */
  const [tabStatus, setTabStatus] = useState<string | null>(null);
  /** Running total already on the tab, so the bill is not shown as 0.00. */
  const [tabTotal, setTabTotal] = useState(0);
  /**
   * Dish ids the waiter has UN-ticked = hold this line back from the kitchen
   * (course_held). Stored as the exception set so new items are sent by
   * default — a forgotten tick must never silently strand a dish.
   */
  const [heldIds, setHeldIds] = useState<Set<number>>(new Set());
  const [transferOpen, setTransferOpen] = useState(false);
  const [codOpen, setCodOpen] = useState(false);

  // ── Home Delivery: customer + address capture (delivery order_type only) ──
  const [deliveryOpen, setDeliveryOpen] = useState(false);
  const [custPhone, setCustPhone] = useState("");
  const [custName, setCustName] = useState("");
  const [aptRoom, setAptRoom] = useState("");
  const [building, setBuilding] = useState("");
  const [receiverName, setReceiverName] = useState("");
  const [addressNotes, setAddressNotes] = useState("");
  const [pin, setPin] = useState<{ lat: number; lng: number } | null>(null);
  const [feeOptions, setFeeOptions] = useState<FeeChoice[]>([]);
  const [fee, setFee] = useState<string>("");
  const [lookupState, setLookupState] = useState<"idle" | "found" | "new" | "error">("idle");
  /**
   * Dish ids the guest wants PARCELLED even though they are dining in — same
   * tab, same bill, but the kitchen boxes them (order_items.is_takeaway).
   * This is not a takeaway ORDER: order_type stays dine_in.
   */
  const [parcelIds, setParcelIds] = useState<Set<number>>(new Set());
  /**
   * Take Away has no table to hang the tab on, so the till REMEMBERS the order
   * it just created. Without this the cashier fires a KOT and the ticket
   * vanishes — nothing left to add to, print or take money for. Cleared by
   * "New Bill" (and after COD settles), which is how the next customer starts.
   */
  const [takeawayOrderId, setTakeawayOrderId] = useState<number | null>(() => {
    // ?order= reopens an EXISTING takeaway order (the list's "Add Item"), so
    // the next round appends to it instead of starting a second ticket.
    const n = Number(params.get("order"));
    return Number.isInteger(n) && n > 0 ? n : null;
  });

  const selectedTable = useMemo(
    () => tables.find((t) => String(t.id) === tableParam) ?? null,
    [tables, tableParam],
  );
  const openTabOrderId =
    orderType === "dine_in" ? (selectedTable?.order_id ?? null) : takeawayOrderId;
  /** A saved-but-not-fired tab still has KOT work, even with an empty cart. */
  const tabUnfired =
    openTabOrderId != null &&
    (tabStatus === "draft" || tabStatus === "pending_confirmation");

  // ── data ────────────────────────────────────────────────────────────────
  useEffect(() => {
    apiClient
      .get<ApiTable[]>("/api/v1/tables")
      .then((r) => setTables(Array.isArray(r) ? r : []))
      .catch(() => setTables([]));
    fetchNextToken()
      .then(setNextToken)
      .catch(() => setNextToken(null));
    // Staff list is manager-scoped; fall back to just the signed-in waiter.
    // Only CLOCKED-IN waiters can be picked, so read each waiter's shift status.
    listStaff()
      .then((r) => {
        const rows = Array.isArray(r) ? r : [];
        setStaffList(rows);
        const waiters = rows.filter((m) => m.role === "waiter");
        void Promise.all(
          waiters.map(async (m) => {
            try {
              const { status } = await getClockStatus(m.id);
              return status === "clocked_in" || status === "on_break" ? m.id : null;
            } catch {
              return null;
            }
          }),
        ).then((ids) => setOnShiftIds(new Set(ids.filter((x): x is number => x != null))));
      })
      .catch(() => setStaffList([]));
  }, []);

  // Seed the covers stepper from the table's existing party size.
  useEffect(() => {
    if (selectedTable?.guests != null && selectedTable.guests > 0) {
      setCovers(selectedTable.guests);
    }
  }, [selectedTable?.guests]);

  // Delivery fee tiers from restaurant settings — only needed for the delivery
  // capture. Always keep a "Free delivery" option so a near order can be zeroed.
  useEffect(() => {
    if (orderType !== "delivery") return;
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
          setFee((f) => f || withFree[0].value);
        } else {
          setFeeOptions([{ value: "0.00", label: "Free delivery" }]);
          setFee((f) => f || "0.00");
        }
      })
      .catch(() => {
        setFeeOptions([{ value: "0.00", label: "Free delivery" }]);
        setFee((f) => f || "0.00");
      });
  }, [orderType]);

  /** Phone → prefill name + last address (same lookup as the manager screen). */
  async function onLookupCustomer() {
    if (custPhone.trim().length < 7) return;
    try {
      const result = await lookupCustomer(custPhone.trim());
      if (result) {
        setLookupState("found");
        if (result.name) setCustName(result.name);
        if (result.last_address) {
          setAptRoom(result.last_address.apt_room);
          setBuilding(result.last_address.building);
          setReceiverName(result.last_address.receiver_name);
          setAddressNotes(result.last_address.notes ?? "");
        }
      } else {
        setLookupState("new");
      }
    } catch {
      setLookupState("error");
    }
  }

  // Show what is already on the tab when adding another round.
  useEffect(() => {
    if (openTabOrderId == null) {
      setTabItems([]);
      setTabStatus(null);
      setTabTotal(0);
      return;
    }
    let cancelled = false;
    fetchOrderDetail(openTabOrderId, { include: "overview" })
      .then((d) => {
        if (cancelled) return;
        setTabItems(Array.isArray(d.items) ? d.items : []);
        setTabStatus(d.status ?? null);
        setTabTotal(Number(d.total ?? 0) || 0);
        // Reopening a delivery order ("Add Item") must pull its saved customer +
        // address back in, so the ticket-bar chip shows who/where instead of an
        // empty "Add delivery details" — the address was captured on create.
        if (orderType === "delivery") {
          if (d.customer) {
            setCustPhone(d.customer.phone ?? "");
            setCustName(d.customer.name ?? "");
          }
          if (d.address) {
            setAptRoom(d.address.room_apartment ?? "");
            setBuilding(d.address.building ?? "");
            setReceiverName(d.address.receiver_name ?? "");
            setAddressNotes(d.address.additional_details ?? "");
            if (d.address.latitude != null && d.address.longitude != null) {
              setPin({ lat: d.address.latitude, lng: d.address.longitude });
            }
          }
          if (d.delivery_fee_aed != null) {
            setFee(Number(d.delivery_fee_aed).toFixed(2));
          }
        }
      })
      .catch(() => {
        if (cancelled) return;
        setTabItems([]);
        setTabStatus(null);
        setTabTotal(0);
      });
    return () => {
      cancelled = true;
    };
  }, [openTabOrderId, tabRefresh]);

  // ── derived ─────────────────────────────────────────────────────────────
  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const d of dishes) set.add(d.category ?? "Other");
    return [...set];
  }, [dishes]);

  const visibleDishes = useMemo(() => {
    const q = search.trim().toLowerCase();
    let list = dishes;
    if (activeCat !== "all") list = list.filter((d) => (d.category ?? "Other") === activeCat);
    if (q) {
      list = list.filter(
        (d) =>
          d.name.toLowerCase().includes(q) ||
          String(d.dish_number ?? "").includes(q) ||
          (d.category ?? "").toLowerCase().includes(q),
      );
    }
    return list;
  }, [dishes, activeCat, search]);

  const lines = useMemo(
    () =>
      Object.entries(qty)
        .filter(([, n]) => n > 0)
        .map(([id, n]) => {
          const dish = dishes.find((d) => d.id === Number(id));
          const price = Number(dish?.price_aed ?? 0);
          return { dish, id: Number(id), qty: n, price, amount: price * n };
        })
        .filter((l) => l.dish),
    [qty, dishes],
  );

  /** Send-column state, for the header select-all tick. */
  const allSent = lines.length > 0 && lines.every((l) => !heldIds.has(l.id));
  const someSent = lines.some((l) => !heldIds.has(l.id));

  /**
   * Money shown is the RUNNING BILL for the table: what is already on the tab
   * plus the round being added. Showing only the new round read as 0.00 on a
   * table that clearly owed money, which is the number a guest would dispute.
   */
  const roundTotal = lines.reduce((sum, l) => sum + l.amount, 0);
  const netValue = roundTotal + tabTotal;
  const vat = netValue - netValue / (1 + VAT_RATE);
  const subTotal = netValue - vat;

  const isDelivery = orderType === "delivery";
  /** Delivery fee applies on delivery only; the food total already includes VAT. */
  const feeNum = isDelivery ? Number(fee || 0) || 0 : 0;
  const grandTotal = netValue + feeNum;
  /** All the fields a rider needs before a home delivery can leave. */
  const deliverySaved =
    !isDelivery ||
    (custPhone.trim().length >= 7 &&
      aptRoom.trim() !== "" &&
      building.trim() !== "" &&
      receiverName.trim() !== "" &&
      fee !== "" &&
      pin !== null);

  // ── cart ops ────────────────────────────────────────────────────────────
  const setDishQty = useCallback((dishId: number, n: number) => {
    setQty((prev) => {
      const next = { ...prev };
      if (n <= 0) delete next[dishId];
      else next[dishId] = n;
      return next;
    });
  }, []);

  function addDish(dishId: number) {
    const bump = keyBuf ? Math.max(1, parseInt(keyBuf, 10) || 1) : 1;
    setDishQty(dishId, (qty[dishId] ?? 0) + bump);
    setFocusedId(dishId);
    setKeyBuf("");
  }

  function pressKey(k: string) {
    if (k === "⌫") {
      setKeyBuf((b) => b.slice(0, -1));
      return;
    }
    setKeyBuf((b) => (b.length >= 4 ? b : b + k));
  }

  /** ENTER applies the typed number as the focused line's quantity. */
  function applyQty() {
    if (focusedId == null || !keyBuf) return;
    const n = parseInt(keyBuf, 10);
    if (!Number.isNaN(n)) setDishQty(focusedId, n);
    setKeyBuf("");
  }

  function clearAll() {
    setQty({});
    setFocusedId(null);
    setKeyBuf("");
    setNotes({});
    setNoteOpen(false);
    setHeldIds(new Set());
    setParcelIds(new Set());
  }

  /**
   * Close the current ticket and start the next customer. On Take Away this is
   * the ONLY way off a settled order — the till has no floor to return to — so
   * it also drops the remembered order and pulls a fresh counter token.
   */
  function startNewBill() {
    clearAll();
    if (orderType !== "dine_in") {
      setTakeawayOrderId(null);
      // Drop ?order= too, or a reload would reopen the ticket we just closed.
      if (params.get("order")) {
        navigate(`${orderPath}?type=${orderType}`, { replace: true });
      }
      fetchNextToken()
        .then(setNextToken)
        .catch(() => setNextToken(null));
    }
  }

  /**
   * Header tick = send/hold EVERY line at once. `heldIds` is stored as the
   * exception set, so "send all" is simply an empty set and "hold all" is
   * every line id.
   */
  function toggleSendAll() {
    setHeldIds(allSent ? new Set(lines.map((l) => l.id)) : new Set());
  }

  /** Mark/unmark the selected line as parcel (boxed, same bill). */
  function toggleParcel(dishId: number) {
    setParcelIds((prev) => {
      const next = new Set(prev);
      if (next.has(dishId)) next.delete(dishId);
      else next.add(dishId);
      return next;
    });
  }

  function setLineNote(dishId: number, value: string) {
    setNotes((prev) => {
      const next = { ...prev };
      const trimmed = value.slice(0, 200);
      if (!trimmed) delete next[dishId];
      else next[dishId] = trimmed;
      return next;
    });
  }

  // ── submit ──────────────────────────────────────────────────────────────
  /**
   * Persist the cart onto the table's tab.
   *
   * `fire` decides whether the kitchen sees it:
   *  - false ("Save to Table") → POS create with auto_confirm=false, so a NEW
   *    order stays DRAFT and no station tickets are cut yet.
   *  - true  ("KOT")           → save, then POST /orders/{id}/confirm to fire.
   *
   * Rounds appended to an ALREADY-confirmed tab are live the moment they are
   * added — there is no way to append invisibly to a firing ticket — so Save
   * on such a tab tells the truth rather than pretending it parked.
   */
  async function saveRound(fire: boolean) {
    const hasItems = lines.length > 0;
    // KOT with an empty cart is valid when a previously-saved round is still
    // parked — that is exactly how you fire what "Save to Table" put on hold.
    const fireOnly = !hasItems && fire && tabUnfired && openTabOrderId != null;
    if (!hasItems && !fireOnly) {
      toast("Add at least one item first.", "error");
      return;
    }
    if (orderType === "dine_in" && !selectedTable) {
      toast("Pick a table on the floor first.", "error");
      return;
    }
    // A NEW home delivery cannot leave without a name, phone and address — the
    // rider has nowhere to go. Appending to an existing delivery order (Add
    // Item) is exempt: the address was captured when it was first created.
    if (isDelivery && !openTabOrderId && !deliverySaved) {
      toast("Add the delivery name, phone and address first.", "error");
      setDeliveryOpen(true);
      return;
    }
    setSubmitting(true);
    try {
      const items = lines.map((l) => ({
        dish_id: l.id,
        qty: l.qty,
        notes: notes[l.id] ?? null,
        course_held: heldIds.has(l.id),
        is_takeaway: parcelIds.has(l.id),
      }));

      let orderId = openTabOrderId;
      let orderNumber = "";

      if (!hasItems) {
        // fire-only: nothing to append, just confirm the parked order below.
      } else if (orderId) {
        const updated = await addOrderItems(orderId, items);
        orderNumber = updated?.order_number ?? "";
      } else if (isDelivery) {
        // Home delivery goes through the manual-order endpoint, which persists
        // the real customer + address + fee the rider needs (not the walk-in
        // placeholder the POS create uses for dine-in / takeaway).
        const created = await createManualOrder({
          customer_phone: custPhone.trim(),
          customer_name: custName.trim() || null,
          items,
          address: {
            apt_room: aptRoom.trim(),
            building: building.trim(),
            receiver_name: receiverName.trim(),
            notes: addressNotes.trim() || null,
            latitude: pin?.lat ?? null,
            longitude: pin?.lng ?? null,
          },
          delivery_fee_aed: fee || "0.00",
          order_type: "delivery",
        });
        orderId = created?.id ?? null;
        orderNumber = created?.order_number ?? "";
        // Keep the till pointed at what we just opened so the next round appends
        // and the payment buttons have something to charge.
        if (orderId) setTakeawayOrderId(orderId);
      } else {
        const created = await createPosOrder({
          order_type: orderType,
          // Dine-in walk-ins have no phone; the API requires one (min 7), so use
          // the same generic walk-in number the cashier terminal sends.
          customer_phone: "0000000000",
          customer_name: "Walk-in",
          items,
          table_id: selectedTable?.id ?? null,
          covers: orderType === "dine_in" ? covers : null,
          // Attribute the sale so per-staff reporting and the floor plan's
          // waiter column work; falls back to the signed-in staff member.
          staff_id: (waiterId === "" ? staff?.staff_id : waiterId) ?? null,
          address: null,
          delivery_fee_aed: "0.00",
          auto_confirm: fire,
        });
        orderId = created?.id ?? null;
        orderNumber = created?.order_number ?? "";
        // Take Away: keep the till pointed at what we just opened so the next
        // round appends to it and the payment buttons have something to charge.
        if (orderType !== "dine_in" && orderId) setTakeawayOrderId(orderId);
      }

      if (fire && orderId) {
        // No-op when the order was already auto-confirmed on create.
        await confirmOrder(orderId);
        // Home Delivery: KOT also SENDS it to the kitchen. Delivery orders are
        // KOT-gated (no tickets at confirm), so advance confirmed -> preparing —
        // that hop fires the kitchen tickets and moves the pill to "Preparing"
        // (kitchen then marks Ready, which auto-dispatches a rider).
        //
        // Only for a NEW order (or one still sitting at "confirmed"): appending
        // items to an order that is already preparing/ready must NOT push its
        // status forward, or "Add Item" would wrongly mark it Ready.
        if (isDelivery && (openTabOrderId == null || tabStatus === "confirmed")) {
          try {
            await advanceOrder(orderId);
          } catch {
            /* raced past confirmed already — ignore */
          }
        }
      }

      const where = selectedTable ? ` on ${selectedTable.label}` : "";
      const sentCount = lines.length - heldCount;
      toast(
        fire
          ? `${orderNumber || "Ticket"}: ${sentCount} sent${where}` +
              (parcelCount > 0 ? `, ${parcelCount} to parcel` : "") +
              (heldCount > 0 ? `, ${heldCount} held back.` : ".")
          : `Saved ${lines.length} item(s)${where} — kitchen not notified yet.`,
      );

      // A brand-new dine-in order becomes this table's open tab — reload the
      // table list so the banner and "add to tab" path pick it up.
      if (selectedTable) {
        apiClient
          .get<ApiTable[]>("/api/v1/tables")
          .then((r) => setTables(Array.isArray(r) ? r : []))
          .catch(() => undefined);
      }
      // Stay on the ticket: clear the cart, re-read the tab so the waiter can
      // see the round landed, and let them leave via "‹ Floor" when ready.
      clearAll();
      setTabRefresh((n) => n + 1);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save the order", "error");
    } finally {
      setSubmitting(false);
    }
  }

  const tableLabel = selectedTable?.label ?? (orderType === "dine_in" ? "—" : "");

  const heldCount = lines.filter((l) => heldIds.has(l.id)).length;
  const parcelCount = lines.filter((l) => parcelIds.has(l.id)).length;

  /** Free tables this tab could move to. */
  const transferTargets = useMemo(
    () => tables.filter((t) => !t.order_id && t.id !== selectedTable?.id),
    [tables, selectedTable?.id],
  );

  /** Lines already on the tab that the kitchen has NOT been shown. */
  const tabHeldCount = tabItems.filter((i) => i.course_held).length;

  /** Release held lines on the tab to the kitchen. */
  async function fireHeld() {
    if (!openTabOrderId) return;
    setSubmitting(true);
    try {
      await fireCourse(openTabOrderId, 1);
      toast("Held items fired to the kitchen.");
      setTabRefresh((n) => n + 1);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not fire held items", "error");
    } finally {
      setSubmitting(false);
    }
  }

  /** Guest asked for the bill — flag the table so the cashier picks it up. */
  async function requestBill() {
    if (!selectedTable) return;
    setSubmitting(true);
    try {
      await setTableStatus(selectedTable.id, "needs_bill");
      toast(`${selectedTable.label} flagged for billing — cashier notified.`);
      navigate(floorPath);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not request the bill", "error");
    } finally {
      setSubmitting(false);
    }
  }

  /** Persist a covers change on an open tab (party grew / shrank). */
  async function changeCovers(next: number) {
    setCovers(next);
    if (!openTabOrderId) return; // not yet an order — saved on create
    try {
      await setOrderCovers(openTabOrderId, next);
    } catch {
      toast("Could not save the cover count", "error");
    }
  }

  /** Move this table's open tab to another free table. */
  async function transferTo(target: ApiTable) {
    if (!openTabOrderId) return;
    setSubmitting(true);
    try {
      await apiClient.patch(`/api/v1/tables/${target.id}/transfer-order`, {
        order_id: openTabOrderId,
      });
      toast(`Moved ${selectedTable?.label ?? "tab"} → ${target.label}.`);
      setTransferOpen(false);
      clearAll();
      // Follow the tab to its new table so the ticket keeps working.
      navigate(`${orderPath}?table=${target.id}&label=${encodeURIComponent(target.label)}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Transfer failed", "error");
    } finally {
      setSubmitting(false);
    }
  }

  /** Open the checkout for this tab. `tender` pre-selects a payment mode
   *  (cash for COD, card for "other"); table/label carry the back-link. */
  function goPay(tender?: string) {
    if (!openTabOrderId) return;
    const params = new URLSearchParams();
    if (selectedTable) {
      params.set("table", String(selectedTable.id));
      params.set("label", selectedTable.label);
    }
    if (tender) params.set("tender", tender);
    const qs = params.toString();
    navigate(`/orders/${openTabOrderId}/pay${qs ? `?${qs}` : ""}`);
  }

  /** COD quick-collect: charge the full tab as cash and settle in place.
   *  The backend closes the on-premise order + frees the table once paid. */
  async function collectCod() {
    if (!openTabOrderId) return;
    setSubmitting(true);
    try {
      await chargePayment({
        order_id: openTabOrderId,
        tender_type: "cash",
        amount_aed: tabTotal.toFixed(2),
        channel: "pos_cod",
        terminal_id: "cashier-cod",
      });
      const collected = tabTotal;
      setCodOpen(false);
      if (orderType === "dine_in") {
        toast(`Collected AED ${collected.toFixed(2)} · ${selectedTable?.label ?? "tab"} settled.`);
        navigate(floorPath);
      } else {
        // Take Away: no floor to go back to — roll straight into the next
        // customer so the queue keeps moving.
        toast(`Collected AED ${collected.toFixed(2)} — ready for the next order.`);
        startNewBill();
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not collect payment", "error");
    } finally {
      setSubmitting(false);
    }
  }

  /** Print the running bill (queues to printer once one is configured). */
  function printBill() {
    toast(
      openTabOrderId
        ? "Bill print queued (when printer configured)."
        : "No open bill to print.",
    );
  }

  // Off-shift waiters are hidden — a waiter must be clocked in to take a table.
  const waiterOptions = staffList.filter((m) => m.role === "waiter" && onShiftIds.has(m.id));

  // The action row lives at the bottom of the right (dish) column across every
  // mode, so the left ticket column always runs full height beside it.
  const actionBar = (
    <div className={`${s.actionBar} ${s.actionBarInline}`}>
      {/* KOT is first = the outer edge of this left-aligned row, the fastest
          target for the one button pressed on every order. */}
      <button
        type="button"
        className={`${s.act} ${s.actKot}`}
        disabled={submitting || (lines.length === 0 && !tabUnfired)}
        onClick={() => void saveRound(true)}
        data-testid="waiter-kot"
        title={
          lines.length === 0 && tabUnfired
            ? "Fire the saved (not yet sent) items to the kitchen"
            : "Save and fire the ticket to the kitchen / bar stations"
        }
      >
        🖨 {submitting ? "Sending…" : "Kot"}
      </button>
      {/* New Bill only makes sense on a fresh table — on an open tab (old
          table) you're adding to the existing bill, not starting one.
          Take Away always keeps it: once an order is settled, "New Bill" is
          the only way to start the next customer at this till. */}
      {(!openTabOrderId || orderType !== "dine_in") && (
        <button type="button" className={s.act} onClick={startNewBill}>
          New Bill
        </button>
      )}
      {/* Waiter keeps Print Bill here; the cashier gets it in the right-side
          payment cluster instead. */}
      {!isCashier && (
        <button
          type="button"
          className={s.act}
          disabled={!openTabOrderId}
          onClick={printBill}
          title={openTabOrderId ? "Print the running bill for this table" : "No open tab yet"}
        >
          🧾 Print Bill
        </button>
      )}
      {/* Parcel only matters on a dine-in bill; a Take Away order is all boxed. */}
      {orderType === "dine_in" && (
        <button
          type="button"
          className={`${s.act} ${parcelCount > 0 ? s.actParcelOn : ""}`}
          disabled={focusedId == null}
          onClick={() => focusedId != null && toggleParcel(focusedId)}
          data-testid="waiter-parcel"
          title={
            focusedId == null
              ? "Select a line to parcel it"
              : "Box this line — stays on the same bill, kitchen packs it"
          }
        >
          📦 {focusedId != null && parcelIds.has(focusedId) ? "Eat in" : "Parcel"}
        </button>
      )}
      <button type="button" className={s.act} disabled title="Rush flag coming soon">
        Rush
      </button>
      {/* Request Bill is a waiter action only — the cashier tenders directly
          via the green "Payment Now" button on the right. */}
      {!isCashier && (
        <button
          type="button"
          className={s.act}
          disabled={submitting || !openTabOrderId || !selectedTable}
          onClick={() => void requestBill()}
          data-testid="waiter-request-bill"
          title={
            openTabOrderId
              ? "Guest asked for the bill — flag the table for the cashier"
              : "No open tab on this table"
          }
        >
          🧾 Request Bill
        </button>
      )}
      {/* Transfer moves a tab between tables — dine-in only. */}
      {orderType === "dine_in" && (
        <button
          type="button"
          className={s.act}
          disabled={submitting || !openTabOrderId || transferTargets.length === 0}
          onClick={() => setTransferOpen(true)}
          data-testid="waiter-transfer"
          title={
            !openTabOrderId
              ? "No open tab on this table to move"
              : transferTargets.length === 0
                ? "No free table to move to"
                : "Move this tab to another table"
          }
        >
          ⇄ Transfer
        </button>
      )}
      {/* Deletion happens via the per-line 🗑 in the cart, so no bar Delete. */}
      <button type="button" className={`${s.act} ${s.actVoid}`} disabled title="Void needs a manager PIN">
        ⚠ Void
      </button>

      <span className={s.spacer} />

      {/* Payment is a cashier-only cluster; waiters send to the kitchen and the
          cashier tenders, so they get no payment control here. */}
      {isCashier && (
        <span className={s.payCluster}>
          <button
            type="button"
            className={s.act}
            disabled={!openTabOrderId}
            onClick={printBill}
            title={openTabOrderId ? "Print the running bill" : "No open tab yet"}
            data-testid="cashier-print-bill"
          >
            🧾 Print Bill
          </button>
          <button
            type="button"
            className={s.act}
            disabled={submitting || !openTabOrderId}
            onClick={() => goPay("card")}
            title="Card, wallet, online & other payment modes"
            data-testid="cashier-other-pay"
          >
            💳 Other Pay
          </button>
          {/* Last = backed against the screen edge, the fastest target for
              the tender used on most orders. Same order as the Take Away list. */}
          <button
            type="button"
            className={`${s.act} ${s.payBtn}`}
            disabled={submitting || !openTabOrderId}
            onClick={() => setCodOpen(true)}
            title="Collect cash at the counter now"
            data-testid="cashier-cod"
          >
            💵 Cash
          </button>
        </span>
      )}
    </div>
  );

  return (
    <div className={s.root} data-theme={theme} data-testid="waiter-order-screen">
      <WaiterTopBar active={SECTION_BY_TYPE[orderType]} />

      {/* ── ticket strip ─────────────────────────────────────────────── */}
      <div className={s.ticketBar}>
        {/* Each channel goes back to the surface it belongs to: dine-in to the
            floor, Take Away to the pickup list. `from=till` tells the list this
            was a deliberate press, so it shows itself even when empty instead
            of bouncing straight back here. */}
        {orderType === "dine_in" ? (
          <button type="button" className={s.backBtn} onClick={() => navigate(floorPath)}>
            ‹ Floor
          </button>
        ) : (
          <button
            type="button"
            className={s.backBtn}
            onClick={() =>
              navigate(
                `/cashier/${orderType === "delivery" ? "delivery" : "takeaway"}?from=till`,
              )
            }
            data-testid="takeaway-back-list"
          >
            ‹ Orders
          </button>
        )}

        <span className={s.tokenChip}>
          <span className={s.tokenHash}>#</span> Token{" "}
          <strong className={s.tokenNum} data-testid="waiter-token">
            {nextToken ?? "—"}
          </strong>
        </span>

        {/* Home Delivery: the customer + address control sits right after the
            token. Empty = a call to capture it; filled = a compact chip. */}
        {isDelivery &&
          (deliverySaved ? (
            <button
              type="button"
              className={s.delChip}
              onClick={() => setDeliveryOpen(true)}
              data-testid="delivery-summary"
              title="Edit delivery details"
            >
              <span aria-hidden>🛵</span>
              <strong>{custName.trim() || receiverName.trim() || "Customer"}</strong>
              <span className={s.delChipMeta}>
                {[custPhone.trim(), building.trim()].filter(Boolean).join(" · ")}
              </span>
              <span className={s.delChipEdit}>Edit</span>
            </button>
          ) : (
            <button
              type="button"
              className={s.delChipAdd}
              onClick={() => setDeliveryOpen(true)}
              data-testid="delivery-add-details"
            >
              ＋ Add delivery details
            </button>
          ))}

        {orderType === "dine_in" && <span className={s.tableTag}>{tableLabel}</span>}

        {/* Waiter attribution is a dine-in concern; Take Away is a cashier till. */}
        {orderType === "dine_in" && (
          <label className={s.waiterPick}>
            <span aria-hidden>👤</span>
            <select
              value={waiterId}
              onChange={(e) => setWaiterId(e.target.value === "" ? "" : Number(e.target.value))}
              aria-label="Waiter"
              disabled={waiterOptions.length === 0}
            >
              {waiterOptions.length === 0 ? (
                <option value={staff?.staff_id ?? ""}>{staff?.name ?? "— Select Waiter —"}</option>
              ) : (
                <>
                  <option value="">— Select Waiter —</option>
                  {waiterOptions.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
                </>
              )}
            </select>
          </label>
        )}

        {orderType === "dine_in" && (
          <span className={s.covers} aria-label="Covers">
            <span aria-hidden>👥</span>
            <button type="button" onClick={() => void changeCovers(Math.max(1, covers - 1))}>
              −
            </button>
            <strong data-testid="waiter-covers">{covers}</strong>
            <button type="button" onClick={() => void changeCovers(Math.min(30, covers + 1))}>
              +
            </button>
          </span>
        )}

        <span className={s.spacer} />
      </div>

      {/* ── body ─────────────────────────────────────────────────────── */}
      <div className={s.body}>
        {/* LEFT: cart + totals + keypad */}
        <section className={s.left}>
          <div className={s.cartHead}>
            {/* Select-all for the send column. Indeterminate while only some
                lines are ticked, so the header never claims a state the rows
                do not agree on. */}
            <input
              type="checkbox"
              className={s.sendBox}
              ref={(el) => {
                if (el) el.indeterminate = someSent && !allSent;
              }}
              checked={allSent}
              disabled={lines.length === 0}
              onChange={() => toggleSendAll()}
              title={
                lines.length === 0
                  ? "No items yet"
                  : allSent
                    ? "Hold every line back from the kitchen"
                    : "Send every line to the kitchen"
              }
              aria-label="Send all lines to the kitchen"
              data-testid="cart-send-all"
            />
            <span className={s.cCode}>CODE</span>
            <span className={s.cName}>PARTICULARS</span>
            <span className={s.cPrice}>PRICE</span>
            <span className={s.cQty}>QTY</span>
            <span className={s.cAmt}>AMOUNT</span>
            <span aria-hidden />
          </div>

          <div className={s.cartBody}>
            {openTabOrderId && tabItems.length > 0 && (
              <div className={s.tabBanner} data-testid="waiter-open-tab">
                <div className={s.tabBannerHead}>
                  Already on {selectedTable?.label ?? "this tab"} · #{openTabOrderId}
                  {tabUnfired && (
                    <span className={s.tabPending}> · NOT SENT TO KITCHEN</span>
                  )}
                </div>
                {tabItems.map((it, i) => (
                  <div className={s.tabRow} key={`${it.dish_number}-${i}`}>
                    <span>
                      {it.qty}× {it.dish_name}
                      {it.is_takeaway && <em className={s.tabParcel}>📦 PARCEL</em>}
                    </span>
                    <span>{it.line_total}</span>
                  </div>
                ))}
                {tabHeldCount > 0 && (
                  <button
                    type="button"
                    className={s.fireHeldBtn}
                    disabled={submitting}
                    onClick={() => void fireHeld()}
                    data-testid="waiter-fire-held"
                  >
                    ▶ Fire {tabHeldCount} held item{tabHeldCount > 1 ? "s" : ""} to kitchen
                  </button>
                )}
                <div className={s.tabHint}>
                  {tabUnfired
                    ? "Saved but not sent — hit KOT to fire it."
                    : "The kitchen is already on this ticket, so anything you add goes straight through."}
                </div>
              </div>
            )}

            {lines.length === 0 ? (
              <p className={s.cartEmpty}>Select items from the menu →</p>
            ) : (
              lines.map((l) => (
                <div
                  key={l.id}
                  role="button"
                  tabIndex={0}
                  className={`${s.cartRow} ${focusedId === l.id ? s.cartRowActive : ""} ${
                    heldIds.has(l.id) ? s.cartRowHeld : ""
                  }`}
                  onClick={() => setFocusedId(l.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") setFocusedId(l.id);
                  }}
                >
                  <input
                    type="checkbox"
                    className={s.sendBox}
                    checked={!heldIds.has(l.id)}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => {
                      const send = e.target.checked;
                      setHeldIds((prev) => {
                        const next = new Set(prev);
                        if (send) next.delete(l.id);
                        else next.add(l.id);
                        return next;
                      });
                    }}
                    aria-label={`Send ${l.dish?.name ?? "item"} to the kitchen`}
                    title={
                      heldIds.has(l.id)
                        ? "Held back — will NOT be sent"
                        : "Will be sent to the kitchen"
                    }
                  />
                  <span className={s.cCode}>{l.dish?.dish_number ?? "—"}</span>
                  {/* Only the dish TEXT truncates — the PARCEL/note flags must
                      never be the thing that gets ellipsised away. */}
                  {/* Name gets the full column width; flags + note sit on their
                      own row underneath so nothing crowds the CRS column. */}
                  <span className={s.cName}>
                    <span className={s.cNameText} title={l.dish?.name}>
                      {l.dish?.name}
                    </span>
                    {(parcelIds.has(l.id) || heldIds.has(l.id) || notes[l.id]) && (
                      <span className={s.cFlags}>
                        {parcelIds.has(l.id) && (
                          <em className={s.lineParcel}>📦 PARCEL</em>
                        )}
                        {heldIds.has(l.id) && (
                          <em className={s.lineHeld}>⏸ NOT SENT TO KOT</em>
                        )}
                        {notes[l.id] && (
                          <em className={s.lineNote}>📝 {notes[l.id]}</em>
                        )}
                      </span>
                    )}
                  </span>
                  <span className={s.cPrice}>{money(l.price)}</span>
                  <span className={s.cQty}>
                    <span className={s.qtyStepper} onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        className={s.qtyBtn}
                        onClick={() => setDishQty(l.id, l.qty - 1)}
                        aria-label={`Decrease ${l.dish?.name ?? "item"}`}
                        title="Decrease (removes at 0)"
                      >
                        −
                      </button>
                      <span className={s.qtyNum}>{l.qty}</span>
                      <button
                        type="button"
                        className={s.qtyBtn}
                        onClick={() => setDishQty(l.id, l.qty + 1)}
                        aria-label={`Increase ${l.dish?.name ?? "item"}`}
                        title="Increase"
                      >
                        +
                      </button>
                    </span>
                  </span>
                  <span className={s.cAmt}>{money(l.amount)}</span>
                  <button
                    type="button"
                    className={s.rowDel}
                    onClick={(e) => {
                      e.stopPropagation();
                      setDishQty(l.id, 0);
                      if (focusedId === l.id) setFocusedId(null);
                    }}
                    aria-label={`Remove ${l.dish?.name ?? "item"}`}
                    title="Remove line"
                  >
                    {/* SVG, not the 🗑 emoji: emoji render as their own colour
                        glyph and ignore `color`, so it could never go red. */}
                    <svg
                      viewBox="0 0 24 24"
                      width="19"
                      height="19"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden
                    >
                      <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" />
                      <path d="M10 11v6M14 11v6" />
                    </svg>
                  </button>
                </div>
              ))
            )}
          </div>

          <div className={s.totals}>
            {tabTotal > 0 && (
              <div className={s.totRow}>
                <span>Already on tab</span>
                <span>{money(tabTotal)}</span>
              </div>
            )}
            {roundTotal > 0 && tabTotal > 0 && (
              <div className={s.totRow}>
                <span>This round</span>
                <span>{money(roundTotal)}</span>
              </div>
            )}
            <div className={s.totRow}>
              <span>Sub Total</span>
              <span>{money(subTotal)}</span>
            </div>
            <div className={s.totRow}>
              <span>VAT ({VAT_RATE * 100}% incl.)</span>
              <span>{money(vat)}</span>
            </div>
            {isDelivery && (
              <div className={s.totRow}>
                <span>Delivery fee</span>
                <span data-testid="waiter-delivery-fee">{money(feeNum)}</span>
              </div>
            )}
            <div className={`${s.totRow} ${s.totNet}`}>
              <span>{tabTotal > 0 ? "Table total" : "Net Value"}</span>
              <span data-testid="waiter-net">{money(isDelivery ? grandTotal : netValue)}</span>
            </div>
          </div>

          {/* keypad */}
          <div className={s.padWrap}>
            <div className={s.pad}>
              <div className={s.padDisplay}>
                <span>QTY:</span>
                <strong data-testid="waiter-keybuf">{keyBuf || "—"}</strong>
              </div>
              <div className={s.padKeys}>
                {["7", "8", "9", "4", "5", "6", "1", "2", "3", ".", "0", "⌫"].map((k) => (
                  <button key={k} type="button" className={s.key} onClick={() => pressKey(k)}>
                    {k}
                  </button>
                ))}
              </div>
              <div className={s.padActions}>
                {/* Clears the TYPED NUMBER only. It used to call clearAll(),
                    which wiped the whole unsent ticket — a mistyped quantity
                    should never cost the cashier the order. Use "New Bill" to
                    drop the ticket. */}
                <button
                  type="button"
                  className={s.keyClear}
                  onClick={() => setKeyBuf("")}
                  title="Clear the typed number"
                >
                  CLEAR
                </button>
                <button type="button" className={s.keyEnter} onClick={applyQty}>
                  ENTER
                </button>
              </div>
            </div>

            <div className={s.padSide}>
              <button
                type="button"
                className={s.sideKey}
                disabled={focusedId == null}
                onClick={() => focusedId != null && setDishQty(focusedId, (qty[focusedId] ?? 0) + 1)}
              >
                +
              </button>
              <button
                type="button"
                className={s.sideKey}
                disabled={focusedId == null}
                onClick={() => focusedId != null && setDishQty(focusedId, (qty[focusedId] ?? 0) - 1)}
              >
                −
              </button>
              <button
                type="button"
                className={`${s.sideKey} ${s.sideDanger}`}
                disabled={focusedId == null}
                onClick={() => {
                  if (focusedId != null) setDishQty(focusedId, 0);
                  setFocusedId(null);
                }}
              >
                ✕
              </button>
              <button
                type="button"
                className={`${s.sideKey} ${noteOpen ? s.sideKeyOn : ""}`}
                disabled={focusedId == null}
                title={
                  focusedId == null
                    ? "Select a cart line first"
                    : "Add a kitchen note to the selected line"
                }
                onClick={() => setNoteOpen((v) => !v)}
                data-testid="waiter-note-toggle"
              >
                NOTE
              </button>
            </div>
          </div>

          {noteOpen && focusedId != null && (
            <div className={s.noteBar} data-testid="waiter-note-bar">
              <input
                type="text"
                autoFocus
                value={notes[focusedId] ?? ""}
                onChange={(e) => setLineNote(focusedId, e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === "Escape") setNoteOpen(false);
                }}
                placeholder={`Kitchen note for ${
                  dishes.find((d) => d.id === focusedId)?.name ?? "this item"
                }…`}
                aria-label="Kitchen note for the selected item"
              />
              <button type="button" onClick={() => setNoteOpen(false)} aria-label="Close note">
                ✕
              </button>
            </div>
          )}
        </section>

        {/* RIGHT: search + categories + dishes */}
        <section className={s.right}>
          <div className={s.searchWrap}>
            <span aria-hidden>🔍</span>
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search dishes by name, code or category..."
              aria-label="Search dishes"
              data-testid="waiter-dish-search"
            />
          </div>

          <div className={s.catGrid}>
            <button
              type="button"
              className={`${s.cat} ${activeCat === "all" ? s.catActive : ""}`}
              style={{ background: "#3a3a35" }}
              onClick={() => setActiveCat("all")}
            >
              ALL
            </button>
            {categories.map((c, i) => (
              <button
                key={c}
                type="button"
                className={`${s.cat} ${activeCat === c ? s.catActive : ""}`}
                style={{ background: CAT_COLORS[i % CAT_COLORS.length] }}
                onClick={() => setActiveCat(c)}
              >
                {c.toUpperCase()}
              </button>
            ))}
          </div>

          <div className={s.dishScroll}>
            {menuLoading ? (
              <p className={s.msg}>Loading menu…</p>
            ) : menuError ? (
              <p className={s.msg}>{menuError}</p>
            ) : visibleDishes.length === 0 ? (
              <p className={s.msg}>No dishes match.</p>
            ) : (
              <div className={s.dishGrid}>
                {visibleDishes.map((d) => {
                  const n = qty[d.id] ?? 0;
                  return (
                    <button
                      key={d.id}
                      type="button"
                      className={`${s.dish} ${n > 0 ? s.dishActive : ""}`}
                      onClick={() => addDish(d.id)}
                    >
                      <span className={s.dishCode}>
                        {d.dish_number != null ? `#${d.dish_number}` : ""}
                      </span>
                      <span className={s.dishName}>{d.name}</span>
                      <span className={s.dishFoot}>
                        <span className={s.dishPrice}>{d.price_aed ?? "—"}</span>
                      </span>
                      {n > 0 && <span className={s.dishQty}>{n}</span>}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
          {/* Action row under the dish list so the left ticket column runs full
              height — same layout for dine-in, take away and delivery. */}
          {actionBar}
        </section>
      </div>

      {codOpen && (
        <div
          className={s.modalBack}
          role="dialog"
          aria-modal="true"
          aria-label="Collect cash payment"
          onClick={() => !submitting && setCodOpen(false)}
        >
          <div className={s.modal} onClick={(e) => e.stopPropagation()}>
            <div className={s.modalHead}>
              💵 Collect Cash · {selectedTable?.label ?? "Tab"}
            </div>

            <div className={s.codList}>
              {tabItems.length === 0 ? (
                <div className={s.codEmpty}>No items on this tab yet.</div>
              ) : (
                tabItems.map((it, i) => (
                  <div className={s.codRow} key={`${it.dish_number ?? it.dish_name}-${i}`}>
                    <span className={s.codName}>
                      {it.qty}× {it.dish_name}
                      {it.is_takeaway && <em className={s.tabParcel}>📦 PARCEL</em>}
                    </span>
                    <span className={s.codAmt}>{it.line_total}</span>
                  </div>
                ))
              )}
            </div>

            <div className={s.codTotal}>
              <span>Total to collect</span>
              <strong data-testid="cod-total">AED {tabTotal.toFixed(2)}</strong>
            </div>

            <div className={s.codActions}>
              <button
                type="button"
                className={s.codCancel}
                disabled={submitting}
                onClick={() => setCodOpen(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className={s.codCollect}
                disabled={submitting || !openTabOrderId || tabTotal <= 0}
                onClick={() => void collectCod()}
                data-testid="cod-collect"
              >
                {submitting ? "Collecting…" : `✔ Collect AED ${tabTotal.toFixed(2)} (Cash)`}
              </button>
            </div>
          </div>
        </div>
      )}

      {deliveryOpen && (
        <div
          className={s.modalBack}
          role="dialog"
          aria-modal="true"
          aria-label="Delivery details"
          onClick={() => setDeliveryOpen(false)}
        >
          <div
            className={`${s.modal} ${s.delModal}`}
            onClick={(e) => e.stopPropagation()}
          >
            <div className={s.modalHead}>🛵 Delivery details</div>

            <div className={s.delBody}>
              <div className={s.delFields}>
                <label className={s.delField}>
                  <span>Phone</span>
                  <input
                    type="tel"
                    value={custPhone}
                    onChange={(e) => {
                      setCustPhone(e.target.value);
                      setLookupState("idle");
                    }}
                    onBlur={() => void onLookupCustomer()}
                    placeholder="05x xxx xxxx"
                    data-testid="delivery-phone"
                  />
                  {lookupState === "found" && (
                    <em className={s.delHint}>Returning customer — details filled in.</em>
                  )}
                  {lookupState === "new" && (
                    <em className={s.delHint}>New customer.</em>
                  )}
                </label>
                <label className={s.delField}>
                  <span>Customer name</span>
                  <input
                    type="text"
                    value={custName}
                    onChange={(e) => setCustName(e.target.value)}
                    placeholder="Name"
                  />
                </label>
                <div className={s.delTwoUp}>
                  <label className={s.delField}>
                    <span>Apt / Room</span>
                    <input
                      type="text"
                      value={aptRoom}
                      onChange={(e) => setAptRoom(e.target.value)}
                      placeholder="Apt 12"
                    />
                  </label>
                  <label className={s.delField}>
                    <span>Building</span>
                    <input
                      type="text"
                      value={building}
                      onChange={(e) => setBuilding(e.target.value)}
                      placeholder="Marina Tower"
                    />
                  </label>
                </div>
                <label className={s.delField}>
                  <span>Receiver name</span>
                  <input
                    type="text"
                    value={receiverName}
                    onChange={(e) => setReceiverName(e.target.value)}
                    placeholder="Who receives the order"
                  />
                </label>
                <label className={s.delField}>
                  <span>Notes (optional)</span>
                  <input
                    type="text"
                    value={addressNotes}
                    onChange={(e) => setAddressNotes(e.target.value)}
                    placeholder="Landmark, gate code…"
                  />
                </label>
                <label className={s.delField}>
                  <span>Delivery fee</span>
                  <select value={fee} onChange={(e) => setFee(e.target.value)} data-testid="delivery-fee-select">
                    {feeOptions.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <div className={s.delMap}>
                <span className={s.delMapLabel}>
                  {pin ? "📍 Drop-off pinned" : "Pin the exact drop-off — required"}
                </span>
                <LocationPicker
                  lat={pin?.lat ?? 0}
                  lng={pin?.lng ?? 0}
                  onChange={(lat, lng) => setPin({ lat, lng })}
                  className={s.delPicker}
                  instant
                />
              </div>
            </div>

            <div className={s.codActions}>
              <button
                type="button"
                className={s.codCancel}
                onClick={() => setDeliveryOpen(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className={s.codCollect}
                disabled={!deliverySaved}
                onClick={() => setDeliveryOpen(false)}
                data-testid="delivery-save"
              >
                Save details
              </button>
            </div>
          </div>
        </div>
      )}

      {transferOpen && (
        <div
          className={s.modalBack}
          role="dialog"
          aria-modal="true"
          aria-label="Transfer tab to another table"
          onClick={() => setTransferOpen(false)}
        >
          <div className={s.modal} onClick={(e) => e.stopPropagation()}>
            <div className={s.modalHead}>
              Move {selectedTable?.label ?? "tab"} → which table?
            </div>
            <div className={s.modalGrid}>
              {transferTargets.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  className={s.modalTable}
                  disabled={submitting}
                  onClick={() => void transferTo(t)}
                >
                  <strong>{t.label}</strong>
                  <span>{t.seats} seats</span>
                </button>
              ))}
            </div>
            <button
              type="button"
              className={s.modalCancel}
              onClick={() => setTransferOpen(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
