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
import { advanceOrder, applyDiscount, quoteDeliveryFee, setOrderPriority } from "../lib/ordersApi";
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

type TableBill = {
  order_id: number;
  order_number?: string | null;
  daily_token?: number | null;
  total_aed: string;
  guest_label?: string | null;
};

type ApiTable = {
  id: number;
  label: string;
  seats: number;
  status: string;
  order_id?: number | null;
  /** Every open bill on this table — more than one when the table is split. */
  bills?: TableBill[];
  bill_count?: number;
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
  /**
   * Which cart line's note dialog is open, and the text being typed into it.
   *
   * Keyed by LINE rather than reusing focusedId: the note belongs to the line
   * whose pencil you tapped, and a stray tap elsewhere in the cart must not
   * redirect a half-typed note onto a different dish. The draft is separate from
   * `notes` so Cancel really cancels — the old inline note bar wrote every
   * keystroke straight through and had no way back.
   */
  const [noteFor, setNoteFor] = useState<number | null>(null);
  const [noteDraft, setNoteDraft] = useState("");
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
      /** The kitchen note that was sent WITH this line ("no onion"). Carried so a
       *  saved or recalled bill shows what the kitchen was told — the note is
       *  half the instruction and the panel used to drop it. */
      notes?: string | null;
    }[]
  >([]);
  /** Status of the table's open order — decides whether KOT still has work. */
  const [tabStatus, setTabStatus] = useState<string | null>(null);
  /**
   * The recalled bill is already PAID, so this till is a reprint window and
   * nothing more: the dish grid and Kot & Bill are locked, because appending to
   * a settled ticket fires food nobody has been charged for. Print Bill and
   * New Bill stay live — reprinting is the reason the bill was looked up, and
   * New Bill is how the cashier gets back to selling.
   */
  const [tabSettled, setTabSettled] = useState(false);
  /**
   * The loaded tab's own identity: bill number ("R3-0009") and queue token (8).
   *
   * The banner used to print `#${openTabOrderId}`, which is the DATABASE id — a
   * number nobody at the counter can act on, and one that does not match either
   * the bill or the token. Order id 9 was showing as "#9" on a bill the cashier
   * knows as R3-0009 / token 8.
   */
  const [tabOrderNumber, setTabOrderNumber] = useState<string | null>(null);
  const [tabToken, setTabToken] = useState<number | null>(null);
  /** Running total already on the tab, so the bill is not shown as 0.00. */
  const [tabTotal, setTabTotal] = useState(0);
  /**
   * Dish ids the waiter has UN-ticked = hold this line back from the kitchen
   * (course_held). Stored as the exception set so new items are sent by
   * default — a forgotten tick must never silently strand a dish.
   */
  const [heldIds, setHeldIds] = useState<Set<number>>(new Set());
  const [transferOpen, setTransferOpen] = useState(false);
  // Till discount applied to the open order (AED off). Shown as a line and folded
  // into the total server-side so payment charges the discounted amount.
  const [discountAed, setDiscountAed] = useState(0);
  const [discountOpen, setDiscountOpen] = useState(false);
  const [discountMode, setDiscountMode] = useState<"pct" | "aed">("pct");
  const [discountInput, setDiscountInput] = useState("");
  // Rush flag (kitchen priority). Toggled on the till; persisted to the order at
  // KOT/Save, or immediately when the order already exists.
  const [rush, setRush] = useState(false);
  // Optional walk-in details for Take Away — phone (saved if entered) and name
  // (falls back to "Take away"). Both blank by default.
  const [takeawayPhone, setTakeawayPhone] = useState("");
  const [takeawayName, setTakeawayName] = useState("");
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
  // Auto-quote: the pinned drop-off, priced against the restaurant's tiers.
  // "quoting" while the request is in flight; "outOfRadius" when the pin is
  // beyond the service radius (the order can't go there); distance is shown
  // next to the fee so the cashier sees WHY it costs what it does.
  const [quoting, setQuoting] = useState(false);
  const [quoteKm, setQuoteKm] = useState<number | null>(null);
  const [outOfRadius, setOutOfRadius] = useState(false);
  const [lookupState, setLookupState] = useState<
    "idle" | "found" | "found_name_only" | "new" | "error"
  >("idle");
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
  /**
   * The order this till is pointed at.
   *
   * An explicit ?order= WINS, even on dine-in, which is what makes recalling a
   * bill work: a settled dine-in bill's table has no open order any more, so
   * resolving dine-in through `selectedTable.order_id` alone found nothing and
   * the till came up empty. The table is still passed alongside it so the strip
   * can name the table the bill was served on.
   *
   * Nothing but ?order= sets takeawayOrderId on dine-in (both writers are
   * takeaway/delivery paths), so this cannot hijack an ordinary dine-in tab.
   */
  /**
   * ?split=1 — the cashier asked for a SECOND bill on this table. The table's
   * existing tab must NOT be adopted, or the round would append to the party
   * already eating. Once the split bill exists, its id lands in takeawayOrderId
   * (set on create) and takes over from there, so a third round appends to the
   * new bill rather than opening a third.
   */
  // Presence, not a fixed "1": each press carries a unique token so the route
  // key changes and the till remounts clean, which is what lets a table take a
  // third, fourth, fifth bill rather than stopping at two.
  const splitMode = params.get("split") != null;
  /**
   * Names the bill being opened. A POSITION and not the row id, because "Bill 2"
   * is something a cashier can say out loud to a guest. The cashier can rename it
   * later; guessing the guest's name here would be worse than numbering it.
   */
  function splitLabel() {
    return `Bill ${(selectedTable?.bill_count ?? 0) + 1}`;
  }
  const openTabOrderId =
    orderType === "dine_in"
      ? (takeawayOrderId ?? (splitMode ? null : selectedTable?.order_id ?? null))
      : takeawayOrderId;
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

  // Auto-price the delivery fee from the dropped pin. Whenever the drop-off pin
  // moves (delivery only), quote it against the restaurant's real distance tiers
  // and set the fee — so the cashier never hand-picks the wrong tier and the
  // summary reflects the actual charge. A pin beyond the radius flags out-of-range.
  useEffect(() => {
    if (orderType !== "delivery" || !pin) {
      setQuoteKm(null);
      setOutOfRadius(false);
      return;
    }
    let cancelled = false;
    setQuoting(true);
    quoteDeliveryFee(pin.lat, pin.lng)
      .then((q) => {
        if (cancelled) return;
        setQuoteKm(q.distance_km);
        setOutOfRadius(q.out_of_radius);
        if (!q.out_of_radius && q.fee_aed != null) {
          const priced = Number(q.fee_aed).toFixed(2);
          setFee(priced);
          // Make sure the computed tier is selectable in the dropdown.
          setFeeOptions((opts) =>
            opts.some((o) => o.value === priced)
              ? opts
              : [...opts, { value: priced, label: `AED ${Number(priced)} (auto)` }].sort(
                  (a, b) => Number(a.value) - Number(b.value),
                ),
          );
        }
      })
      .catch(() => {
        if (!cancelled) {
          setQuoteKm(null);
          setOutOfRadius(false);
        }
      })
      .finally(() => {
        if (!cancelled) setQuoting(false);
      });
    return () => {
      cancelled = true;
    };
  }, [orderType, pin]);

  /** Phone → prefill name + last address (same lookup as the manager screen). */
  async function onLookupCustomer() {
    if (custPhone.trim().length < 7) return;
    try {
      const result = await lookupCustomer(custPhone.trim());
      if (result) {
        // "found" vs "found_name_only": a customer known to THIS branch may still
        // have no saved address here, because addresses are per branch (the same
        // phone can be a regular at another branch and a first delivery at this
        // one). Claiming "details filled in" when only the name came back sent
        // the cashier looking for fields that were never populated.
        setLookupState(result.last_address ? "found" : "found_name_only");
        if (result.name) setCustName(result.name);
        if (result.last_address) {
          setAptRoom(result.last_address.apt_room);
          setBuilding(result.last_address.building);
          setReceiverName(result.last_address.receiver_name);
          setAddressNotes(result.last_address.notes ?? "");
          // Restore the saved drop-off pin so a returning customer's exact
          // location auto-applies on the map (was left blank — the reported bug).
          const { latitude, longitude } = result.last_address;
          if (
            typeof latitude === "number" &&
            typeof longitude === "number" &&
            Number.isFinite(latitude) &&
            Number.isFinite(longitude)
          ) {
            setPin({ lat: latitude, lng: longitude });
          }
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
      setTabSettled(false);
      setTabOrderNumber(null);
      setTabToken(null);
      setDiscountAed(0); // no open order → no discount context
      setRush(false);
      return;
    }
    let cancelled = false;
    fetchOrderDetail(openTabOrderId, { include: "overview" })
      .then((d) => {
        if (cancelled) return;
        setTabItems(Array.isArray(d.items) ? d.items : []);
        setTabStatus(d.status ?? null);
        setTabTotal(Number(d.total ?? 0) || 0);
        setTabOrderNumber(d.order_number ?? null);
        setTabToken(d.daily_token ?? null);
        // Settled = the money is in. There is no "paid" ORDER status — payment
        // lives in paid_total_aed — so this is the only honest test, and it is
        // what locks a recalled bill down to a reprint below.
        const total = Number(d.total ?? 0) || 0;
        const paid = Number(d.paid_total_aed ?? 0) || 0;
        setTabSettled(total > 0 && paid >= total - 0.005);
        setRush(String((d as { priority?: string }).priority ?? "") === "rush");
        // Reopening a delivery order ("Add Item") must pull its saved customer +
        // address back in, so the ticket-bar chip shows who/where instead of an
        // empty "Add delivery details" — the address was captured on create.
        // Take Away carries an optional walk-in name and phone. Recalling a bill
        // left both boxes EMPTY over a bill that had them, so the till showed
        // less about the customer than the receipt did. The placeholders this
        // screen writes when the cashier types nothing ("0000000000" / "Take
        // away" / "Walk-in", see the submit path) are skipped — echoing them back
        // would put fake-looking data in a field the cashier never filled.
        if (orderType === "takeaway" && d.customer) {
          const phone = (d.customer.phone ?? "").trim();
          const name = (d.customer.name ?? "").trim();
          setTakeawayPhone(phone === "0000000000" ? "" : phone);
          setTakeawayName(name === "Take away" || name === "Walk-in" ? "" : name);
        }
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

  /**
   * How to NAME the loaded tab to a human: the bill number, with the queue token
   * beside it because that is what the customer is holding. Falls back to the
   * order id only when the server sent neither — better a wrong-looking number
   * than an empty label.
   */
  const tabRef =
    [tabOrderNumber, tabToken != null ? `Token ${tabToken}` : null]
      .filter(Boolean)
      .join(" · ") || `#${openTabOrderId}`;

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
  // netValue is the full running bill (a pending discount is NOT yet in the order
  // total — persistDiscount only pushes it at KOT/Save/payment, and clears the
  // pending marker at the same time, so this never double-subtracts).
  const netValue = roundTotal + tabTotal;
  const vat = netValue - netValue / (1 + VAT_RATE);
  const subTotal = netValue - vat;

  const isDelivery = orderType === "delivery";
  /** Delivery fee applies on delivery only; the food total already includes VAT. */
  const feeNum = isDelivery ? Number(fee || 0) || 0 : 0;
  const grandTotal = netValue + feeNum;
  /** Net after a pending till discount (what the customer actually pays). */
  const netAfterDiscount = Math.max(0, netValue - discountAed);
  const grandAfterDiscount = Math.max(0, grandTotal - discountAed);
  /** Cash-collect amount: the saved tab total less any pending discount. */
  const codDue = Math.max(0, tabTotal - discountAed);
  /** All the fields a rider needs before a home delivery can leave. */
  const deliverySaved =
    !isDelivery ||
    (custPhone.trim().length >= 7 &&
      aptRoom.trim() !== "" &&
      building.trim() !== "" &&
      receiverName.trim() !== "" &&
      fee !== "" &&
      pin !== null);

  /**
   * What is still missing before this delivery can be saved, in words.
   *
   * "Save details" is disabled by deliverySaved above, and a dead green button
   * beside a form that LOOKS complete reads as a broken screen — the usual
   * culprit is the map pin, which is a field you set by dragging rather than
   * typing, so it is the one thing a cashier does not notice leaving blank. The
   * pin cannot be waived: the fee tier and the 10 km radius are computed from it.
   */
  const deliveryMissing: string[] = isDelivery
    ? [
        custPhone.trim().length >= 7 ? null : "phone",
        aptRoom.trim() !== "" ? null : "apt / room",
        building.trim() !== "" ? null : "building",
        receiverName.trim() !== "" ? null : "receiver name",
        pin !== null ? null : "drop-off pin on the map",
      ].filter((x): x is string => x !== null)
    : [];

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
    setNoteFor(null);
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
    setDiscountAed(0); // next customer starts at full price
    setRush(false);
    setTakeawayPhone("");
    setTakeawayName("");
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
  async function saveRound(fire: boolean): Promise<number | null> {
    const hasItems = lines.length > 0;
    // KOT with an empty cart is valid when a previously-saved round is still
    // parked — that is exactly how you fire what "Save to Table" put on hold.
    const fireOnly = !hasItems && fire && tabUnfired && openTabOrderId != null;
    if (!hasItems && !fireOnly) {
      toast("Add at least one item first.", "error");
      return null;
    }
    if (orderType === "dine_in" && !selectedTable) {
      toast("Pick a table on the floor first.", "error");
      return null;
    }
    // A NEW home delivery cannot leave without a name, phone and address — the
    // rider has nowhere to go. Appending to an existing delivery order (Add
    // Item) is exempt: the address was captured when it was first created.
    if (isDelivery && !openTabOrderId && !deliverySaved) {
      toast("Add the delivery name, phone and address first.", "error");
      setDeliveryOpen(true);
      return null;
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
      // A brand-new Home Delivery fires to the kitchen ATOMICALLY on create
      // (fire_to_kitchen below), so the confirm/advance dance underneath must
      // NOT run for it — advancing an already-"preparing" order would wrongly
      // push it to "ready".
      let firedOnCreate = false;

      if (!hasItems) {
        // fire-only: nothing to append, just confirm the parked order below.
      } else if (orderId) {
        const updated = await addOrderItems(orderId, items);
        orderNumber = updated?.order_number ?? "";
      } else if (isDelivery) {
        // Home delivery goes through the manual-order endpoint, which persists
        // the real customer + address + fee the rider needs (not the walk-in
        // placeholder the POS create uses for dine-in / takeaway). When the
        // cashier hit KOT (fire), the server also sends it straight to the
        // kitchen in the same request — no fragile follow-up /advance to lose.
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
          fire_to_kitchen: fire,
        });
        orderId = created?.id ?? null;
        orderNumber = created?.order_number ?? "";
        firedOnCreate = fire;
        // Keep the till pointed at what we just opened so the next round appends
        // and the payment buttons have something to charge.
        if (orderId) setTakeawayOrderId(orderId);
      } else {
        // Take Away can carry an optional walk-in phone/name; dine-in stays a
        // generic walk-in. The API requires a phone (min 7), so a short/blank
        // entry falls back to the placeholder.
        const taPhone = takeawayPhone.trim();
        const created = await createPosOrder({
          order_type: orderType,
          customer_phone:
            orderType === "takeaway" && taPhone.length >= 7 ? taPhone : "0000000000",
          customer_name:
            orderType === "takeaway" ? takeawayName.trim() || "Take away" : "Walk-in",
          items,
          table_id: selectedTable?.id ?? null,
          covers: orderType === "dine_in" ? covers : null,
          // Attribute the sale so per-staff reporting and the floor plan's
          // waiter column work; falls back to the signed-in staff member.
          staff_id: (waiterId === "" ? staff?.staff_id : waiterId) ?? null,
          address: null,
          delivery_fee_aed: "0.00",
          auto_confirm: fire,
          // Only on a split, and only for the FIRST save: after that the till is
          // pointed at the new bill and the round appends to it. Without this the
          // server merges into the party already at the table — which is the right
          // default everywhere else (it stops a stale till duplicating an order).
          force_new_bill: splitMode && orderType === "dine_in" && openTabOrderId == null,
          guest_label:
            splitMode && orderType === "dine_in" && openTabOrderId == null
              ? splitLabel()
              : null,
        });
        orderId = created?.id ?? null;
        orderNumber = created?.order_number ?? "";
        // Take Away: keep the till pointed at what we just opened so the next
        // round appends to it and the payment buttons have something to charge.
        // A SPLIT dine-in bill needs the same, or the next round would fall back
        // to the table's other tab and bill the wrong party.
        if ((orderType !== "dine_in" || splitMode) && orderId) setTakeawayOrderId(orderId);
      }

      if (fire && orderId && !firedOnCreate) {
        // No-op when the order was already auto-confirmed on create.
        await confirmOrder(orderId);
        // Home Delivery: KOT also SENDS it to the kitchen. Delivery orders are
        // KOT-gated (no tickets at confirm), so advance confirmed -> preparing —
        // that hop fires the kitchen tickets and moves the pill to "Preparing"
        // (kitchen then marks Ready, which auto-dispatches a rider). A brand-new
        // Home Delivery already fired atomically on create (firedOnCreate); this
        // path only runs when firing an EXISTING confirmed tab (append case).
        //
        // Only for an order still sitting at "confirmed": appending items to one
        // that is already preparing/ready must NOT push its status forward, or
        // "Add Item" would wrongly mark it Ready.
        if (isDelivery && openTabOrderId != null && tabStatus === "confirmed") {
          // Surface a real failure instead of silently stranding the order off
          // the kitchen board — the whole reason a KOT could look "sent" yet
          // never reach the kitchen. A 409/no-op race still resolves fine.
          try {
            await advanceOrder(orderId);
          } catch (e) {
            toast(
              e instanceof Error
                ? `Sent, but kitchen not notified: ${e.message}`
                : "Sent, but the kitchen was not notified — retry KOT.",
              "error",
            );
          }
        }
      }

      // Push any pending till discount onto the order now that it exists, so the
      // total (and payment) carry it. This is where the discount is persisted —
      // never on "Apply".
      if (orderId) await persistDiscount(orderId);
      // Same for the Rush flag → kitchen priority, so the ticket fires as rush.
      if (orderId && rush) await persistRush(orderId);

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
      return orderId;
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save the order", "error");
      return null;
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
  async function goPay(tender?: string) {
    if (!openTabOrderId) return;
    // Fire an unsent order to the kitchen before leaving for the checkout screen,
    // so paying never skips the KOT. No-op (guarded) if it was already sent.
    if (tabUnfired) {
      try {
        await confirmOrder(openTabOrderId);
      } catch (e) {
        toast(e instanceof Error ? e.message : "Could not send to kitchen", "error");
      }
    }
    // Bake in any pending till discount before the checkout screen recomputes.
    if (discountAed > 0) await persistDiscount(openTabOrderId);
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
      // Never take money for food the kitchen never heard about: if the order is
      // still a parked draft (e.g. Print Bill without KOT), fire it first. Guarded
      // by tabUnfired so an already-sent ticket is never fired twice.
      if (tabUnfired) {
        try {
          await confirmOrder(openTabOrderId);
        } catch (e) {
          toast(e instanceof Error ? e.message : "Could not send to kitchen", "error");
        }
      }
      // Persist a pending till discount first, then charge the discounted total
      // the server returns — so cash collected matches the bill exactly.
      let chargeAmt = tabTotal;
      if (discountAed > 0) {
        const updated = await applyDiscount(openTabOrderId, { amountAed: discountAed });
        chargeAmt = Number(updated.total_aed) || Math.max(0, tabTotal - discountAed);
        setDiscountAed(0);
      }
      await chargePayment({
        order_id: openTabOrderId,
        tender_type: "cash",
        amount_aed: chargeAmt.toFixed(2),
        channel: "pos_cod",
        terminal_id: "cashier-cod",
      });
      const collected = chargeAmt;
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
  async function printBill(orderId?: number | null) {
    // Accept an explicit id so KOT can print the round it just created (the
    // openTabOrderId state hasn't re-rendered yet at that point). Printing before
    // KOT parks the cart as an (unfired) order first so there's a bill to print.
    let id = orderId ?? openTabOrderId;
    if (id == null && lines.length > 0) {
      id = await saveRound(false);
    }
    toast(
      id
        ? "Bill print queued (when printer configured)."
        : "No open bill to print.",
    );
  }

  /**
   * Cashier Take Away KOT: fire the round to the kitchen, save it, and bring up
   * the bill in one press — the walk-in pays right after, so the bill follows
   * the ticket automatically. Other surfaces keep plain KOT (no auto-bill).
   */
  /**
   * Apply a till discount to the open order. The % or AED the cashier types is
   * resolved to a flat AED amount here (against the pre-discount food gross) and
   * sent to the server, so what shows on the bill is exactly what is charged.
   */
  function submitDiscount() {
    const raw = Number(discountInput);
    if (!Number.isFinite(raw) || raw < 0) {
      toast("Enter a valid discount.", "error");
      return;
    }
    const amount =
      discountMode === "pct"
        ? Math.round((netValue * raw) / 100 * 100) / 100
        : Math.round(raw * 100) / 100;
    const clamped = Math.max(0, Math.min(amount, netValue));
    // Apply is display-only — it does NOT save or fire the order. The discount is
    // pushed to the order later, automatically, when the cashier hits KOT/Save or
    // takes payment (persistDiscount). So "Apply" never sends anything to the
    // kitchen.
    setDiscountAed(clamped);
    setDiscountOpen(false);
    setDiscountInput("");
    toast(clamped > 0 ? `Discount set: ${money(clamped)} off.` : "Discount cleared.");
  }

  /**
   * Push the pending client-side discount onto an order that now exists, and
   * clear the pending marker (the order total then carries it, so the running
   * bill stays correct without double-subtracting). Non-fatal on failure.
   */
  async function persistDiscount(orderId: number): Promise<void> {
    if (discountAed <= 0) return;
    try {
      await applyDiscount(orderId, { amountAed: discountAed });
      setDiscountAed(0);
      setTabRefresh((n) => n + 1);
    } catch {
      /* leave the pending discount in place so the next save retries it */
    }
  }

  /** Sync the order's kitchen priority to the current Rush flag. Non-fatal. */
  async function persistRush(orderId: number): Promise<void> {
    try {
      await setOrderPriority(orderId, rush ? "rush" : "normal");
    } catch {
      /* priority is best-effort — don't block the ticket on it */
    }
  }

  /**
   * Toggle the Rush flag. If the order already exists, flip its kitchen priority
   * immediately; otherwise hold it client-side until KOT/Save persists it.
   */
  async function toggleRush() {
    const next = !rush;
    setRush(next);
    if (openTabOrderId != null) {
      try {
        await setOrderPriority(openTabOrderId, next ? "rush" : "normal");
        setTabRefresh((n) => n + 1);
      } catch (e) {
        setRush(!next); // revert on failure
        toast(e instanceof Error ? e.message : "Could not update rush", "error");
      }
    }
  }

  async function kotThenBill() {
    const id = await saveRound(true);
    // Take Away, Home Delivery and WhatsApp (every cashier channel) get the
    // bill with the KOT; dine-in waiters do not.
    if (id && isCashier && orderType !== "dine_in") printBill(id);
  }

  // Off-shift waiters are hidden — a waiter must be clocked in to take a table.
  const waiterOptions = staffList.filter((m) => m.role === "waiter" && onShiftIds.has(m.id));

  // The action row lives at the bottom of the right (dish) column across every
  // mode, so the left ticket column always runs full height beside it.
  const actionBar = (
    <div className={`${s.actionBar} ${s.actionBarInline}`}>
      {/* New Bill starts the next customer — kept first so it's the outer edge.
          On an open dine-in tab you're adding to the existing bill, not starting
          one, so it hides there; Take Away always keeps it. */}
      {(!openTabOrderId || orderType !== "dine_in") && (
        <button type="button" className={s.act} onClick={startNewBill}>
          New Bill
        </button>
      )}
      {/* KOT: the one button pressed on every order. */}
      <button
        type="button"
        className={`${s.act} ${s.actKot}`}
        disabled={submitting || tabSettled || (lines.length === 0 && !tabUnfired)}
        onClick={() => void kotThenBill()}
        data-testid="waiter-kot"
        title={
          tabSettled
            ? "This bill is already paid. Start a New Bill to sell"
            : lines.length === 0 && tabUnfired
              ? "Fire the saved (not yet sent) items to the kitchen"
              : "Save and fire the ticket to the kitchen / bar stations"
        }
      >
        🖨 {submitting
          ? "Sending…"
          : isCashier && orderType !== "dine_in"
            ? "Kot & Bill"
            : "Kot"}
      </button>
      {/* Cashier: Print Bill sits right after KOT in the left cluster. */}
      {isCashier && (
        <button
          type="button"
          className={s.act}
          disabled={submitting || (lines.length === 0 && !openTabOrderId)}
          onClick={() => void printBill()}
          title="Print the running bill"
          data-testid="cashier-print-bill"
        >
          🧾 Print Bill
        </button>
      )}
      {/* Waiter keeps its own Print Bill here; the cashier's is above by KOT. */}
      {!isCashier && (
        <button
          type="button"
          className={s.act}
          disabled={!openTabOrderId}
          onClick={() => printBill()}
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
          disabled={tabSettled || focusedId == null}
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
      <button
        type="button"
        className={`${s.act} ${rush ? s.actParcelOn : ""}`}
        disabled={submitting || tabSettled || (lines.length === 0 && !openTabOrderId)}
        onClick={() => void toggleRush()}
        aria-pressed={rush}
        data-testid="waiter-rush"
        title={rush ? "Rush ON — tap to clear" : "Flag this order as rush for the kitchen"}
      >
        {rush ? "⚡ Rush ON" : "Rush"}
      </button>
      {/* Cashier: Discount rounds out the left cluster (after Rush). */}
      {isCashier && (
        <button
          type="button"
          className={s.act}
          disabled={submitting || tabSettled || (lines.length === 0 && !openTabOrderId)}
          onClick={() => {
            setDiscountMode("pct");
            setDiscountInput("");
            setDiscountOpen(true);
          }}
          title="Apply a discount to this bill"
          data-testid="cashier-discount"
        >
          % Discount
        </button>
      )}
      {/* Request Bill is a waiter action only — the cashier tenders directly
          via the green "Payment Now" button on the right. */}
      {!isCashier && (
        <button
          type="button"
          className={s.act}
          disabled={submitting || tabSettled || !openTabOrderId || !selectedTable}
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
          disabled={submitting || tabSettled || !openTabOrderId || transferTargets.length === 0}
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
      {/* Deletion happens via the per-line 🗑 in the cart, so there is no bar
          Void on any channel — lines are cleared from the cart. */}

      {/* A SETTLED bill leaves exactly two live controls in this bar: Print Bill,
          because reprinting is why the bill was looked up, and New Bill, because
          that is how the cashier gets back to selling. Everything else above is
          gated on tabSettled — Kot & Bill would fire food against money already
          taken, Other Pay and Open Drawer would charge a second time, Discount
          would rewrite a total that has been paid, and Rush/Parcel/Transfer are
          instructions to a kitchen that finished this order. */}

      <span className={s.spacer} />

      {/* Payment is a cashier-only cluster; waiters send to the kitchen and the
          cashier tenders, so they get no payment control here. */}
      {isCashier && (
        <span className={s.payCluster}>
          <button
            type="button"
            className={s.act}
            disabled={submitting || tabSettled || !openTabOrderId}
            onClick={() => void goPay("card")}
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
            disabled={submitting || tabSettled || !openTabOrderId}
            onClick={() => setCodOpen(true)}
            title="Open the cash drawer and collect at the counter"
            data-testid="cashier-cod"
          >
            💵 Open Drawer
          </button>
        </span>
      )}
    </div>
  );

  return (
    <div className={s.root} data-theme={theme} data-testid="waiter-order-screen">
      <WaiterTopBar active={SECTION_BY_TYPE[orderType]} />

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
                  {tabSettled
                    ? `Paid bill · ${tabRef}`
                    : `Already on ${selectedTable?.label ?? "this tab"} · ${tabRef}`}
                  {tabSettled && <span className={s.tabPaid}> · SETTLED</span>}
                  {!tabSettled && tabUnfired && (
                    <span className={s.tabPending}> · NOT SENT TO KITCHEN</span>
                  )}
                </div>
                {tabItems.map((it, i) => (
                  <div className={s.tabRow} key={`${it.dish_number}-${i}`}>
                    <span>
                      {it.qty}× {it.dish_name}
                      {it.is_takeaway && <em className={s.tabParcel}>📦 PARCEL</em>}
                      {/* The note the kitchen was given. On a reprint this is
                          what settles "but I asked for no onion". */}
                      {it.notes && <em className={s.lineNote}>📝 {it.notes}</em>}
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
                  {tabSettled
                    ? "This bill is paid. Reprint it if you need to, or hit New Bill for the next customer."
                    : tabUnfired
                      ? "Saved but not sent — hit KOT to fire it."
                      : "The kitchen is already on this ticket, so anything you add goes straight through."}
                </div>
              </div>
            )}

            {lines.length === 0 ? (
              // Nothing on a SETTLED bill: the cart is empty because this is a
              // reprint, not because the cashier has yet to ring anything up, and
              // pointing them at a menu they cannot add from contradicts the
              // locked tiles beside it. The panel above already says what to do.
              tabSettled ? null : (
                <p className={s.cartEmpty}>Select items from the menu →</p>
              )
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
                  {/* Note sits on the LINE, next to its delete, because that is
                      the line it applies to — it used to be a NOTE key on the
                      keypad that acted on whichever row happened to be selected. */}
                  <button
                    type="button"
                    className={`${s.rowNote} ${notes[l.id] ? s.rowNoteOn : ""}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      setFocusedId(l.id);
                      setNoteFor(l.id);
                      setNoteDraft(notes[l.id] ?? "");
                    }}
                    aria-label={`${notes[l.id] ? "Edit" : "Add"} kitchen note for ${
                      l.dish?.name ?? "item"
                    }`}
                    title={notes[l.id] ? `Note: ${notes[l.id]}` : "Add a kitchen note"}
                    data-testid={`row-note-${l.id}`}
                  >
                    {/* SVG for the same reason as the bin below: an emoji paints
                        its own colour and would never pick up the amber. */}
                    <svg
                      viewBox="0 0 24 24"
                      width="18"
                      height="18"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden
                    >
                      <path d="M4 4h11l5 5v11H4z" />
                      <path d="M8 10h6M8 14h4" />
                    </svg>
                  </button>
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
            {discountAed > 0 && (
              <div className={s.totRow} data-testid="waiter-discount-row">
                <span>Discount</span>
                <span>−{money(discountAed)}</span>
              </div>
            )}
            {isDelivery && (
              <div className={s.totRow}>
                <span>Delivery fee</span>
                <span data-testid="waiter-delivery-fee">{money(feeNum)}</span>
              </div>
            )}
            <div className={`${s.totRow} ${s.totNet}`}>
              <span>{tabTotal > 0 ? "Table total" : "Net Value"}</span>
              <span data-testid="waiter-net">
                {money(isDelivery ? grandAfterDiscount : netAfterDiscount)}
              </span>
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
                {/* Dead on a settled bill: these type a quantity for a focused
                    cart line, and a reprint has no cart. */}
                {["7", "8", "9", "4", "5", "6", "1", "2", "3", ".", "0", "⌫"].map((k) => (
                  <button
                    key={k}
                    type="button"
                    className={s.key}
                    disabled={tabSettled}
                    onClick={() => pressKey(k)}
                  >
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
                  disabled={tabSettled}
                  onClick={() => setKeyBuf("")}
                  title="Clear the typed number"
                >
                  CLEAR
                </button>
                <button
                  type="button"
                  className={s.keyEnter}
                  disabled={tabSettled}
                  onClick={applyQty}
                >
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
            </div>
          </div>
        </section>

        {/* RIGHT: ticket strip + search + categories + dishes.
            The ticket strip used to run the full width above BOTH columns, which
            spent a whole row of a till screen on a token and two optional fields
            and pushed the cart down with it. It belongs over the menu side: the
            cart column now starts at the top and gets that row back for lines. */}
        <section className={s.right}>
          {/* ── ticket strip ─────────────────────────────────────────────── */}
          <div className={s.ticketBar}>
            {/* Dine-in goes back to the floor. Take Away and Home Delivery have no
                "‹ Orders" back button — they reach their list via the "Order List ›"
                control after the token, and open straight from their tab. */}
            {orderType === "dine_in" ? (
              <button type="button" className={s.backBtn} onClick={() => navigate(floorPath)}>
                ‹ Floor
              </button>
            ) : null}

            {/* The token of the bill ON SCREEN. nextToken means "what the next
                order will be called", so it is only ever right on an EMPTY till:
                on a recalled bill it printed 9 beside a ticket the cashier knows
                as token 8. And a loaded bill with NO token of its own (delivery
                orders need not have one) shows a dash rather than borrowing the
                next one — a wrong number here is worse than no number. */}
            <span className={s.tokenChip}>
              <span className={s.tokenHash}>#</span> Token{" "}
              <strong className={s.tokenNum} data-testid="waiter-token">
                {openTabOrderId != null ? (tabToken ?? "—") : (nextToken ?? "—")}
              </strong>
            </span>

            {/* Take Away: optional walk-in phone + name. Blank is fine — the order
                saves as "Take away" with a placeholder phone; anything typed is kept. */}
            {orderType === "takeaway" && (
              <span className={s.taFields}>
                <input
                  type="text"
                  value={takeawayName}
                  onChange={(e) => setTakeawayName(e.target.value)}
                  placeholder="Name (optional)"
                  aria-label="Customer name (optional)"
                  data-testid="takeaway-name"
                  className={s.taInput}
                  /* A recalled paid bill is not editable, and these two are only
                     read when a NEW order is submitted — leaving them typeable
                     promised an edit to the bill on screen that never happens. */
                  disabled={tabSettled}
                />
                <input
                  type="tel"
                  inputMode="tel"
                  value={takeawayPhone}
                  onChange={(e) => setTakeawayPhone(e.target.value)}
                  placeholder="Phone (optional)"
                  aria-label="Customer phone (optional)"
                  data-testid="takeaway-phone"
                  className={s.taInput}
                  disabled={tabSettled}
                />
                <button
                  type="button"
                  className={s.backBtn}
                  onClick={() => navigate("/cashier/takeaway?from=till")}
                  data-testid="takeaway-order-list"
                >
                  Order List ›
                </button>
              </span>
            )}

            {/* Home Delivery: the customer + address control sits right after the
                token. Empty = a call to capture it; filled = a compact chip. */}
            {isDelivery &&
              (deliverySaved ? (
                <button
                  type="button"
                  className={s.delChip}
                  onClick={() => setDeliveryOpen(true)}
                  data-testid="delivery-summary"
                  title={tabSettled ? "View delivery details" : "Edit delivery details"}
                >
                  <span aria-hidden>🛵</span>
                  <strong>{custName.trim() || receiverName.trim() || "Customer"}</strong>
                  <span className={s.delChipMeta}>
                    {[custPhone.trim(), building.trim()].filter(Boolean).join(" · ")}
                  </span>
                  <span className={s.delChipEdit}>{tabSettled ? "View" : "Edit"}</span>
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

            {/* Home Delivery: jump to the delivery order list, same as Take Away. */}
            {isDelivery && (
              <button
                type="button"
                className={s.backBtn}
                onClick={() => navigate("/cashier/delivery?from=till")}
                data-testid="delivery-order-list"
              >
                Order List ›
              </button>
            )}

            {orderType === "dine_in" && (
              <span className={s.tableChip}>
                Table{" "}
                <strong className={s.tableChipNum} data-testid="waiter-table">
                  {tableLabel}
                </strong>
              </span>
            )}

            {/* Split bills on this table. Shown only when there IS more than one,
                so an ordinary tab keeps the strip uncluttered. Switching is a
                route change to ?order=<id> — the same door the floor's picker and
                the bill lookup use, so there is one loading path, not three. */}
            {orderType === "dine_in" && (selectedTable?.bill_count ?? 0) > 1 && (
              <span className={s.billSwitch} data-testid="bill-switch">
                {(selectedTable?.bills ?? []).map((b, i) => {
                  const active = b.order_id === openTabOrderId;
                  return (
                    <button
                      key={b.order_id}
                      type="button"
                      className={`${s.billTab} ${active ? s.billTabOn : ""}`}
                      aria-current={active}
                      onClick={() => {
                        if (active) return;
                        const p = new URLSearchParams();
                        p.set("type", "dine_in");
                        p.set("order", String(b.order_id));
                        if (selectedTable) {
                          p.set("table", String(selectedTable.id));
                          p.set("label", selectedTable.label);
                        }
                        navigate(`${orderPath}?${p.toString()}`);
                      }}
                      data-testid={`bill-tab-${b.order_id}`}
                      title={`${b.order_number ?? `#${b.order_id}`} · AED ${b.total_aed}`}
                    >
                      {b.guest_label?.trim() || `Bill ${i + 1}`}
                    </button>
                  );
                })}
              </span>
            )}

            {/* Open ANOTHER bill on this table: a second party has sat down and
                will pay for their own food. Hidden once the current bill is
                settled — that till is a reprint window, not a place to sell. */}
            {orderType === "dine_in" && selectedTable && !tabSettled && (
              <button
                type="button"
                className={s.splitBtn}
                onClick={() => {
                  const p = new URLSearchParams();
                  p.set("type", "dine_in");
                  p.set("table", String(selectedTable.id));
                  p.set("label", selectedTable.label);
                  // Unique per press — see the route key in App.tsx.
                  p.set("split", String(Date.now()));
                  navigate(`${orderPath}?${p.toString()}`);
                }}
                data-testid="split-bill-btn"
                title={`Start a separate bill on ${selectedTable.label}`}
              >
                ◧ Split bill
              </button>
            )}

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

            {/* Open the kitchen display in a NEW TAB so the till stays put — the KDS
                board is a chrome-free surface with no "back to till", so navigating
                there in-place would strand the cashier/waiter. Both roles get it. */}
            <button
              type="button"
              className={s.backBtn}
              onClick={() => window.open("/kds", "_blank", "noopener,noreferrer")}
              data-testid="open-kitchen-screen"
              title="Open the kitchen screen in a new tab"
            >
              Kitchen Screen ↗
            </button>
          </div>

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

          {/* Two columns: categories on the left, dishes on the right, each
              scrolling on its own. */}
          <div className={s.pickArea}>
            {/* Category column is hidden until the menu loads — otherwise a lone
                "ALL" button sits beside an empty area while dishes are fetched,
                and the dish area gets the full width in the meantime. */}
            {!menuLoading && (
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
            )}

            <div className={s.dishScroll}>
              {menuLoading ? (
                <div className={s.loadingWrap}>Loading menu…</div>
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
                        className={`${s.dish} ${n > 0 ? s.dishActive : ""} ${
                          tabSettled ? s.dishLocked : ""
                        }`}
                        // NOT disabled, on purpose. A settled bill is a reprint
                        // window and the dish must not go on it — but a dead tile
                        // that swallows the tap is indistinguishable from a frozen
                        // till, and a cashier with a queue will tap it again,
                        // harder, before doubting the bill. So it stays tappable
                        // and ANSWERS: what is wrong, and the one way out.
                        title={tabSettled ? "This bill is paid. Start a New Bill" : undefined}
                        onClick={() => {
                          if (tabSettled) {
                            toast(
                              `${tabRef} is already paid. Hit New Bill to start selling.`,
                              "error",
                            );
                            return;
                          }
                          addDish(d.id);
                        }}
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
          </div>
          {/* Action row under the dish list so the left ticket column runs full
              height — same layout for dine-in, take away and delivery. */}
          {actionBar}
        </section>
      </div>

      {noteFor != null && (
        <div
          className={s.modalBack}
          role="dialog"
          aria-modal="true"
          aria-label="Kitchen note"
          onClick={() => setNoteFor(null)}
        >
          <div
            className={`${s.modal} ${s.noteModal}`}
            onClick={(e) => e.stopPropagation()}
          >
            <div className={s.modalHead}>
              📝 Kitchen note · {lines.find((l) => l.id === noteFor)?.dish?.name ?? "Item"}
            </div>
            <textarea
              className={s.noteInput}
              autoFocus
              rows={3}
              value={noteDraft}
              onChange={(e) => setNoteDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") setNoteFor(null);
                // Enter saves; Shift+Enter is a newline, because a note like
                // "no onion / extra spicy" reads better on two lines.
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  setLineNote(noteFor, noteDraft);
                  setNoteFor(null);
                }
              }}
              placeholder="No onion, extra spicy, well done…"
              aria-label="Kitchen note for this item"
              data-testid="note-input"
            />
            <div className={s.noteActions}>
              {/* Clear is only offered once there IS a note to clear, so the
                  dialog does not present an action that does nothing. */}
              {notes[noteFor] ? (
                <button
                  type="button"
                  className={s.noteClear}
                  onClick={() => {
                    setLineNote(noteFor, "");
                    setNoteFor(null);
                  }}
                  data-testid="note-clear"
                >
                  Clear note
                </button>
              ) : (
                <span className={s.spacer} />
              )}
              <button type="button" className={s.codCancel} onClick={() => setNoteFor(null)}>
                Cancel
              </button>
              <button
                type="button"
                className={s.noteSave}
                onClick={() => {
                  setLineNote(noteFor, noteDraft);
                  setNoteFor(null);
                }}
                data-testid="note-save"
              >
                Save note
              </button>
            </div>
          </div>
        </div>
      )}

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

            {discountAed > 0 && (
              <div className={s.codRow}>
                <span className={s.codName}>Discount</span>
                <span className={s.codAmt}>−{discountAed.toFixed(2)}</span>
              </div>
            )}
            <div className={s.codTotal}>
              <span>Total to collect</span>
              <strong data-testid="cod-total">AED {codDue.toFixed(2)}</strong>
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
                disabled={submitting || !openTabOrderId || codDue <= 0}
                onClick={() => void collectCod()}
                data-testid="cod-collect"
              >
                {submitting ? "Collecting…" : `✔ Collect AED ${codDue.toFixed(2)} (Cash)`}
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
            <div className={s.modalHead}>
              🛵 Delivery details
              {tabSettled && <span className={s.tabPaid}> · VIEW ONLY</span>}
            </div>
            {/* A recalled PAID delivery bill opens here to answer "where did it
                go and who took it", not to be rewritten: the run is done and the
                money is in, so every field is read-only and Save is gone. The map
                stays because seeing the pin is the reason to open it at all. */}
            {tabSettled && (
              <p className={s.delReadOnly}>
                This bill is paid. Details are shown as they were delivered and cannot be changed.
              </p>
            )}

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
                    disabled={tabSettled}
                    data-testid="delivery-phone"
                  />
                  {lookupState === "found" && (
                    <em className={s.delHint}>Returning customer. Details filled in.</em>
                  )}
                  {lookupState === "found_name_only" && (
                    <em className={s.delHint}>
                      Returning customer, but no saved address at this branch. Enter it and pin the
                      drop-off.
                    </em>
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
                    disabled={tabSettled}
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
                      disabled={tabSettled}
                    />
                  </label>
                  <label className={s.delField}>
                    <span>Building</span>
                    <input
                      type="text"
                      value={building}
                      onChange={(e) => setBuilding(e.target.value)}
                      placeholder="Marina Tower"
                      disabled={tabSettled}
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
                    disabled={tabSettled}
                  />
                </label>
                <label className={s.delField}>
                  <span>Notes (optional)</span>
                  <input
                    type="text"
                    value={addressNotes}
                    onChange={(e) => setAddressNotes(e.target.value)}
                    placeholder="Landmark, gate code…"
                    disabled={tabSettled}
                  />
                </label>
                <label className={s.delField}>
                  <span>Delivery fee</span>
                  <select
                    value={fee}
                    onChange={(e) => setFee(e.target.value)}
                    disabled={tabSettled}
                    data-testid="delivery-fee-select"
                  >
                    {feeOptions.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                  {quoting ? (
                    <em className={s.delHint}>Pricing the drop-off…</em>
                  ) : outOfRadius ? (
                    <em className={s.delHint} data-testid="delivery-out-of-radius">
                      ⚠ {quoteKm != null ? `${quoteKm.toFixed(1)} km — ` : ""}beyond the
                      delivery radius.
                    </em>
                  ) : quoteKm != null ? (
                    <em className={s.delHint} data-testid="delivery-distance">
                      📍 {quoteKm.toFixed(1)} km — fee set automatically. Override if needed.
                    </em>
                  ) : null}
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

            {/* Visible, not just a tooltip: on a touch till there is no hover, so
                a title alone would never be read. */}
            {!tabSettled && deliveryMissing.length > 0 && (
              <p className={s.delMissing} data-testid="delivery-missing">
                Still needed to save: {deliveryMissing.join(", ")}.
              </p>
            )}

            <div className={s.codActions}>
              <button
                type="button"
                className={s.codCancel}
                onClick={() => setDeliveryOpen(false)}
              >
                {/* "Cancel" implies discarding an edit. On a paid bill there is
                    no edit to discard, so the only button says what it does. */}
                {tabSettled ? "Close" : "Cancel"}
              </button>
              {!tabSettled && (
                <button
                  type="button"
                  className={s.codCollect}
                  disabled={!deliverySaved}
                  // Say WHY it is disabled. Without this the cashier sees a green
                  // button that ignores them and assumes the form is read-only.
                  title={
                    deliveryMissing.length > 0
                      ? `Still needed: ${deliveryMissing.join(", ")}`
                      : "Save these delivery details"
                  }
                  onClick={() => setDeliveryOpen(false)}
                  data-testid="delivery-save"
                >
                  Save details
                </button>
              )}
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

      {discountOpen && (
        <div
          className={s.modalBack}
          role="dialog"
          aria-modal="true"
          aria-label="Apply a discount"
          onClick={() => setDiscountOpen(false)}
        >
          <div
            className={s.modal}
            style={{ width: "min(92vw, 360px)", maxWidth: "360px" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className={s.modalHead}>Discount this bill</div>
            <div style={{ display: "flex", gap: 8, padding: "12px 16px 0" }}>
              <button
                type="button"
                className={`${s.act} ${discountMode === "pct" ? s.actKot : ""}`}
                style={{ flex: 1 }}
                onClick={() => setDiscountMode("pct")}
              >
                % Percent
              </button>
              <button
                type="button"
                className={`${s.act} ${discountMode === "aed" ? s.actKot : ""}`}
                style={{ flex: 1 }}
                onClick={() => setDiscountMode("aed")}
              >
                AED Amount
              </button>
            </div>
            <div style={{ padding: "12px 16px" }}>
              <input
                type="number"
                min={0}
                step={discountMode === "pct" ? 1 : 0.5}
                inputMode="decimal"
                autoFocus
                value={discountInput}
                onChange={(e) => setDiscountInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void submitDiscount();
                }}
                placeholder={discountMode === "pct" ? "e.g. 10  (% off)" : "e.g. 5.00  (AED off)"}
                style={{
                  width: "100%",
                  padding: "12px 14px",
                  fontSize: 18,
                  borderRadius: 10,
                  border: "1px solid var(--border-default, #cbd5e1)",
                  boxSizing: "border-box",
                }}
                data-testid="discount-input"
              />
              {(() => {
                const raw = Number(discountInput);
                const amt =
                  Number.isFinite(raw) && raw > 0
                    ? discountMode === "pct"
                      ? Math.min(netValue, Math.round(((netValue * raw) / 100) * 100) / 100)
                      : Math.min(netValue, Math.round(raw * 100) / 100)
                    : 0;
                return (
                  <p style={{ marginTop: 10, fontSize: 14, opacity: 0.85 }}>
                    Bill {money(netValue)} → <strong>{money(Math.max(0, netValue - amt))}</strong>
                    {amt > 0 ? `  (−${money(amt)})` : ""}
                  </p>
                );
              })()}
            </div>
            <div style={{ display: "flex", gap: 8, padding: "0 16px 12px" }}>
              <button
                type="button"
                className={s.act}
                onClick={() => setDiscountOpen(false)}
              >
                Cancel
              </button>
              {discountAed > 0 && (
                <button
                  type="button"
                  className={s.act}
                  onClick={() => {
                    setDiscountAed(0);
                    setDiscountOpen(false);
                    setDiscountInput("");
                    toast("Discount cleared.");
                  }}
                >
                  Clear
                </button>
              )}
              <button
                type="button"
                className={`${s.act} ${s.actKot}`}
                style={{ flex: 1 }}
                onClick={() => submitDiscount()}
                data-testid="discount-apply"
              >
                Apply
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
