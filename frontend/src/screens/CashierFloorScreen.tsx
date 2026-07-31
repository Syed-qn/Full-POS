import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { WaiterTopBar } from "../components/WaiterTopBar";
import { TableBillsDialog } from "../components/TableBillsDialog";
import { toast } from "../components/Toaster";
import { apiClient } from "../lib/apiClient";
import {
  fetchFloorLayout,
  joinTables,
  unjoinTable,
  type TableBill,
} from "../lib/floorApi";
import { usePosTheme } from "../lib/posTheme";
import s from "./WaiterFloorScreen.module.css";
import { useLiveRefresh } from "../lib/useLiveRefresh";

type ApiTable = {
  id: number;
  label: string;
  seats: number;
  status: string;
  pos_x: number;
  pos_y: number;
  rotation?: number;
  order_id?: number | null;
  order_total_aed?: string | null;
  bills?: TableBill[];
  bill_count?: number;
  /** Set on a SECONDARY: the table holding this group's single invoice. */
  merged_into_table_id?: number | null;
  merged_into_label?: string | null;
  /** Set on a PRIMARY: labels of the tables joined to it. */
  joined_labels?: string[];
  guests?: number | null;
  waiter?: string | null;
  seated_since?: string | null;
};

type Bucket = "available" | "occupied" | "billing" | "reserved" | "cleaning" | "held";

/**
 * Collapse the table FSM into the buckets the cashier floor shows. The cashier
 * cares about one thing the waiter doesn't: `needs_bill` — a table whose waiter
 * asked for the bill — gets its own "billing" bucket so it stands out for tender.
 */
function bucketOf(status: string, hasOrder: boolean): Bucket {
  if (status === "needs_bill") return "billing";
  if (hasOrder) return "occupied";
  switch (status) {
    case "ordered":
    case "seated":
      return "occupied";
    case "reserved":
      return "reserved";
    case "cleaning":
      return "cleaning";
    default:
      return "available";
  }
}

const BASE_UNIT = 76;
/** Ceiling for the auto-fit unit: a nearly empty room gives a tiny divisor,
 *  which inflated the unit (and so the floor height) until the page scrolled
 *  with one table on it. Must match FloorPlanScreen so the layout a manager
 *  arranges is the layout floor staff see. */
const MAX_UNIT = BASE_UNIT * 2;

/** Module-level table cache so returning to the floor paints instantly instead
 *  of flashing "Loading floor…". Refreshed live (poll + on each mount). */
let tableCache: ApiTable[] | null = null;

/**
 * Cashier landing screen — the same full-bleed dark floor plan the waiter sees,
 * dine-in only. Tables carrying a bill request (`needs_bill`) are pulled forward
 * with a purple "BILL" badge. Tapping any table with an open tab jumps straight
 * to the checkout to collect payment.
 */
export function CashierFloorScreen() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const theme = usePosTheme();
  const [tables, setTables] = useState<ApiTable[]>(() => tableCache ?? []);
  const [loading, setLoading] = useState(tableCache === null);
  // Entrance placed by the manager in Floor Plan (null until placed).
  const [entrance, setEntrance] = useState<{ x: number; y: number; rot: number } | null>(null);
  // Table whose several bills the cashier is choosing between (null = no dialog).
  const [billsFor, setBillsFor] = useState<ApiTable | null>(null);
  /**
   * JOIN MODE. One party too big for a table takes several, on ONE invoice. While
   * it is on, tapping a table SELECTS it instead of opening the till: the FIRST
   * table tapped keeps the bill (everything folds onto it) and the rest join to it.
   * A mode rather than a drag-together gesture, because a mis-drag on a busy floor
   * would silently move somebody's food onto a stranger's bill.
   */
  // ?join=<tableId> — the till's Merge button hands off here with that table
  // already set as the one keeping the bill, so the cashier only taps the tables
  // joining it.
  const joinFromTill = Number(params.get("join"));
  const [joinMode, setJoinMode] = useState(joinFromTill > 0);
  const [joinPick, setJoinPick] = useState<number[]>(
    joinFromTill > 0 ? [joinFromTill] : [],
  );
  const [joining, setJoining] = useState(false);
  // Set when the bill-holding table carries several bills and the server needs to
  // be told which one the joined guests share.
  const [joinBillFor, setJoinBillFor] = useState<ApiTable | null>(null);
  // A JOINING table that seats two parties: which of its bills is coming along.
  // Answers accumulate so a join can pull one party from each of several shared
  // tables.
  const [fromOrderIds, setFromOrderIds] = useState<number[]>([]);
  /**
   * The table whose bill we are asking about RIGHT NOW, as it is tapped.
   *
   * Asked at SELECTION, not at confirm: tapping a table that seats two parties is
   * exactly the moment the question arises, and answering it there lets the
   * cashier carry straight on to the next table. Holding it until the Join button
   * meant a cashier picked their tables, pressed Join, and only then got a
   * question about a table they had already moved on from.
   */
  const [askBillFor, setAskBillFor] = useState<ApiTable | null>(null);
  // Which of the BILL-KEEPING table's bills is the group invoice.
  const [intoOrderId, setIntoOrderId] = useState<number | null>(null);

  const load = useCallback(async () => {
    // Layout rides the same poll as the tables: a manager who moves or rotates
    // the entrance must see it here within one refresh, not on the next reload.
    fetchFloorLayout()
      .then((l) =>
        setEntrance(
          l.entrance_x != null && l.entrance_y != null
            ? { x: l.entrance_x, y: l.entrance_y, rot: l.entrance_rot ?? 0 }
            : null,
        ),
      )
      .catch(() => {
        /* keep the entrance we already drew */
      });
    try {
      const rows = await apiClient.get<ApiTable[]>("/api/v1/tables");
      const list = Array.isArray(rows) ? rows : [];
      tableCache = list; // warm cache for the next visit
      setTables(list);
    } catch {
      // Keep the cached floor on a refresh failure rather than blanking it.
      if (tableCache === null) setTables([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    // Fallback only. The live stream below is what keeps this current; this
    // slow tick just repairs anything missed while the connection was down,
    // which is why it is minutes rather than seconds.
    const id = setInterval(() => void load(), 120_000);
    return () => clearInterval(id);
  }, [load]);

  // Another till seating a table, or the kitchen moving an order, lands here
  // immediately instead of on the next poll.
  useLiveRefresh(["tables", "orders"], load);

  const stats = useMemo(() => {
    let available = 0;
    let occupied = 0;
    let billing = 0;
    let covers = 0;
    for (const t of tables) {
      const b = bucketOf(t.status, !!t.order_id);
      if (b === "available") available += 1;
      else if (b === "billing") {
        billing += 1;
        covers += t.guests ?? 0;
      } else if (b === "occupied") {
        occupied += 1;
        covers += t.guests ?? 0;
      }
    }
    return { available, occupied, billing, covers };
  }, [tables]);

  const span = useMemo(() => {
    let maxX = 0;
    let maxY = 0;
    for (const t of tables) {
      maxX = Math.max(maxX, t.pos_x ?? 0);
      maxY = Math.max(maxY, t.pos_y ?? 0);
    }
    if (entrance) {
      maxX = Math.max(maxX, entrance.x);
      maxY = Math.max(maxY, entrance.y);
    }
    return { x: maxX, y: maxY };
  }, [tables, entrance]);

  const canvasRef = useRef<HTMLDivElement | null>(null);
  const [unit, setUnit] = useState(BASE_UNIT);
  useLayoutEffect(() => {
    const el = canvasRef.current;
    if (!el || span.x <= 0) return;
    const measure = () => {
      const usable = el.clientWidth - 40;
      if (usable > 0) {
        setUnit(Math.min(MAX_UNIT, Math.max(56, usable / (span.x + 1.6))));
      }
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [span.x]);

  const floorHeight = (span.y + 2.2) * unit;

  function tillPath(t: ApiTable, extra = "") {
    return `/cashier/new-order?table=${t.id}&label=${encodeURIComponent(t.label)}${extra}`;
  }

  /**
   * Send the join. Every "which bill?" was already answered as each table was
   * tapped, so this only submits — no question can appear at the last moment.
   */
  async function runJoin(overrideInto?: number | null) {
    const [primaryId, ...rest] = joinPick;
    if (!primaryId || rest.length === 0) return;
    const from = fromOrderIds;
    // Passed explicitly by the retry path: a setState in the same tick has not
    // landed yet, so reading intoOrderId here would send the stale value.
    const into = overrideInto ?? intoOrderId;

    setJoining(true);
    try {
      const rows = await joinTables(primaryId, rest, into, from);
      if (Array.isArray(rows)) {
        tableCache = rows;
        setTables(rows);
      }
      const primary = tables.find((t) => t.id === primaryId);
      toast(`Joined ${rest.length + 1} tables onto ${primary?.label ?? "one"} bill.`);
      setJoinPick([]);
      setJoinMode(false);
      setJoinBillFor(null);
      setAskBillFor(null);
      setFromOrderIds([]);
      setIntoOrderId(null);
    } catch (e) {
      // The server refuses to guess which bill, in two different situations, and
      // BOTH must become a question rather than an error the cashier can do
      // nothing about. This is a backstop for the pre-check above: if the floor's
      // cached table data is stale — an old tab, a bill opened on another till —
      // the pre-check can miss and the server is the one that catches it.
      const msg = e instanceof Error ? e.message : "Could not join the tables";
      if (/which one is joining/i.test(msg)) {
        // A JOINING table seats two parties. The message names it, so find it.
        const named = rest
          .map((id) => tables.find((t) => t.id === id))
          .find((t) => t && msg.includes(t.label));
        if (named) {
          setAskBillFor(named);
          return;
        }
      }
      const primary = tables.find((t) => t.id === primaryId);
      if (/which one/i.test(msg) && primary && (primary.bill_count ?? 0) > 1) {
        setJoinBillFor(primary);
        return;
      }
      toast(msg, "error");
    } finally {
      setJoining(false);
    }
  }

  async function runUnjoin(t: ApiTable) {
    try {
      const rows = await unjoinTable(t.id);
      if (Array.isArray(rows)) {
        tableCache = rows;
        setTables(rows);
      }
      toast(`${t.label} is back on its own.`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not un-join", "error");
    }
  }

  function openTable(t: ApiTable) {
    if (joinMode) {
      // Already picked → un-pick, so a wrong tap costs one tap to undo. Any bill
      // chosen for that table is dropped with it, or a table no longer in the join
      // would still be sending one of its parties along.
      if (joinPick.includes(t.id)) {
        const ownIds = new Set((t.bills ?? []).map((b) => b.order_id));
        setJoinPick((prev) => prev.filter((x) => x !== t.id));
        setFromOrderIds((prev) => prev.filter((id) => !ownIds.has(id)));
        setIntoOrderId((prev) => (prev != null && ownIds.has(prev) ? null : prev));
        return;
      }
      // A table seating TWO PARTIES: ask which bill AS IT IS TAPPED. This is the
      // moment the question arises, and answering it here lets the cashier carry
      // straight on to the next table instead of being interrupted at the end.
      if ((t.bill_count ?? 0) > 1) {
        setAskBillFor(t);
        return;
      }
      setJoinPick((prev) => [...prev, t.id]);
      return;
    }
    // A JOINED table holds no bill of its own, so open the one that does. Without
    // this the till would come up empty on a table with guests sitting at it.
    if (t.merged_into_table_id) {
      const primary = tables.find((x) => x.id === t.merged_into_table_id);
      if (primary) {
        openTable(primary);
        return;
      }
    }
    // A table carrying SEVERAL bills has to be asked about — opening "the table"
    // is ambiguous once two parties share it, and guessing would put the cashier
    // in front of the wrong bill with money already on the counter. One bill (or
    // none) opens directly, exactly as it always has.
    if ((t.bill_count ?? 0) > 1) {
      setBillsFor(t);
      return;
    }
    // Same dark order terminal as the waiter, under the cashier namespace.
    // The cashier reviews / adds to the tab there, then collects payment.
    navigate(tillPath(t));
  }

  return (
    <div className={s.root} data-theme={theme} data-testid="cashier-floor-screen">
      <WaiterTopBar active="dining" />

      {/* ── Stats strip + legend ────────────────────────────────────────── */}
      <div className={s.statsBar}>
        <div className={s.stats}>
          <span className={s.stat}>
            <strong className={s.nOccupied} style={{ color: "#b692f6" }}>
              {stats.billing}
            </strong>{" "}
            BILLS DUE
          </span>
          <span className={s.stat}>
            <strong className={s.nOccupied}>{stats.occupied}</strong> DINING
          </span>
          <span className={s.stat}>
            <strong className={s.nAvailable}>{stats.available}</strong> AVAILABLE
          </span>
          <span className={s.stat}>
            <strong className={s.nCovers}>{stats.covers}</strong> COVERS
          </span>
        </div>

        <div className={s.legend}>
          <button
            type="button"
            className={`${s.joinToggle} ${joinMode ? s.joinToggleOn : ""}`}
            onClick={() => {
              setJoinMode((v) => !v);
              setJoinPick([]);
            }}
            data-testid="join-mode-toggle"
            title="Seat one party across several tables on a single invoice"
          >
            {joinMode ? "✕ Cancel join" : "🔗 Join tables"}
          </button>
          <span className={s.legendItem}>
            <i className={`${s.dot} ${s.dotBilling}`} />
            Bill requested
          </span>
          <span className={s.legendItem}>
            <i className={`${s.dot} ${s.dotOccupied}`} />
            Dining
          </span>
          <span className={s.legendItem}>
            <i className={`${s.dot} ${s.dotAvailable}`} />
            Available
          </span>
        </div>
      </div>

      {joinMode && (
        <div className={s.joinBar} data-testid="join-bar">
          <span className={s.joinHint}>
            {joinPick.length === 0
              ? "Tap the table that KEEPS THE BILL first."
              : joinPick.length === 1
                ? `${tables.find((t) => t.id === joinPick[0])?.label ?? "?"} keeps the bill — now tap the tables joining it.`
                : `${tables.find((t) => t.id === joinPick[0])?.label ?? "?"} keeps the bill · joining ${joinPick
                    .slice(1)
                    .map((id) => tables.find((t) => t.id === id)?.label ?? "?")
                    .join(", ")}`}
          </span>
          {/* Exactly one picked table, already in a group → the only sensible
              action is to take it back OUT, so offer that instead of a Join that
              cannot run. */}
          {joinPick.length === 1 &&
          tables.find((t) => t.id === joinPick[0])?.merged_into_table_id ? (
            <button
              type="button"
              className={s.joinGo}
              onClick={() => {
                const t = tables.find((x) => x.id === joinPick[0]);
                if (t) void runUnjoin(t);
                setJoinPick([]);
                setJoinMode(false);
              }}
              data-testid="unjoin-confirm"
            >
              ↩ Un-join {tables.find((t) => t.id === joinPick[0])?.label}
            </button>
          ) : (
            <button
              type="button"
              className={s.joinGo}
              disabled={joinPick.length < 2 || joining}
              onClick={() => void runJoin()}
              data-testid="join-confirm"
            >
              {joining ? "Joining…" : `Join ${joinPick.length} tables`}
            </button>
          )}
        </div>
      )}

      {/* ── Floor canvas ────────────────────────────────────────────────── */}
      <div className={s.canvas} ref={canvasRef} style={{ backgroundSize: `${unit}px ${unit}px` }}>
        {loading ? (
          <p className={s.canvasMsg}>Loading floor…</p>
        ) : tables.length === 0 ? (
          <p className={s.canvasMsg}>
            No tables set up yet — a manager can add them in Floor Plan.
          </p>
        ) : (
          <div className={s.floor} style={{ height: floorHeight }} data-testid="cashier-floor-canvas">
            {tables.map((t) => {
              const hasOrder = !!t.order_id;
              const bucket = bucketOf(t.status, hasOrder);
              const seats = Math.max(1, Math.min(t.seats ?? 4, 12));
              const top = Math.ceil(seats / 2);
              const bottom = seats - top;
              const wide = Math.max(top, bottom);
              const round = seats <= 2;
              return (
                <button
                  key={t.id}
                  type="button"
                  className={s.tableSlot}
                  style={{
                    left: (t.pos_x ?? 0) * unit,
                    top: (t.pos_y ?? 0) * unit,
                    // Angle set by the manager in Floor Plan; chairs turn with it.
                    transform: t.rotation ? `rotate(${t.rotation}deg)` : undefined,
                  }}
                  onClick={() => openTable(t)}
                  data-testid={`cashier-table-${t.id}`}
                  data-bucket={bucket}
                  aria-label={`Table ${t.label}, ${bucket}, ${t.seats} seats`}
                >
                  <span className={s.chairRow}>
                    {Array.from({ length: top }).map((_, i) => (
                      <i key={i} className={s.chair} />
                    ))}
                  </span>
                  <span
                    className={`${s.table} ${s[`b_${bucket}`]} ${round ? s.tableRound : ""}`}
                    style={{
                      width: round ? 60 : Math.max(88, wide * 26 + 22),
                      height: seats >= 8 ? 100 : 60,
                    }}
                  >
                    {bucket === "billing" && <span className={s.billBadge}>BILL</span>}
                    <span className={s.tableLabel}>{t.label}</span>
                    {(t.bill_count ?? 0) > 1 && (
                      // Two parties on one table: say so on the floor, or the
                      // cashier collects one bill and thinks the table is done.
                      <span className={s.splitBadge} data-testid={`cashier-table-bills-${t.id}`}>
                        {t.bill_count} BILLS
                      </span>
                    )}
                    {t.merged_into_label && (
                      // A joined table has no bill of its own — say where it went,
                      // or a cashier hunts for a bill that was never there.
                      <span className={s.joinedTag} data-testid={`cashier-table-joined-${t.id}`}>
                        → {t.merged_into_label}
                      </span>
                    )}
                    {(t.joined_labels?.length ?? 0) > 0 && (
                      <span className={s.groupTag} data-testid={`cashier-table-group-${t.id}`}>
                        +{t.joined_labels?.length}
                      </span>
                    )}
                    {joinMode && joinPick.includes(t.id) && (
                      <span className={s.pickTag}>
                        {joinPick[0] === t.id ? "BILL" : `#${joinPick.indexOf(t.id) + 1}`}
                      </span>
                    )}
                    {hasOrder && t.order_total_aed != null ? (
                      <span className={s.tableSeats}>AED {t.order_total_aed}</span>
                    ) : (
                      <span className={s.tableSeats}>👥 {t.seats}</span>
                    )}
                    {hasOrder && t.guests != null && (
                      <span className={s.tableCovers}>{t.guests}cvr</span>
                    )}
                  </span>
                  <span className={s.chairRow}>
                    {Array.from({ length: bottom }).map((_, i) => (
                      <i key={i} className={s.chair} />
                    ))}
                  </span>
                </button>
              );
            })}
            {entrance ? (
              <div
                className={s.entranceAt}
                style={{
                  left: entrance.x * unit,
                  top: entrance.y * unit,
                  transform: `translateX(-50%) rotate(${entrance.rot}deg)`,
                }}
                data-testid="floor-entrance"
              >
                ▲ ENTRANCE
              </div>
            ) : (
              <div className={s.entrance} style={{ top: floorHeight - 26 }}>
                ▲ ENTRANCE
              </div>
            )}
          </div>
        )}
      </div>

      {/* Tapped a table that seats two parties. Which bill is in the join? Asked
          here, at selection, so the answer is given while that table is still the
          one in hand — then the cashier carries on picking. */}
      {askBillFor && (
        <TableBillsDialog
          tableLabel={askBillFor.label}
          bills={askBillFor.bills ?? []}
          onPick={(b) => {
            const t = askBillFor;
            // The FIRST table picked keeps the bill, so its chosen bill IS the
            // group invoice; any later one is a party travelling onto it.
            if (joinPick.length === 0) setIntoOrderId(b.order_id);
            else setFromOrderIds((prev) => [...prev, b.order_id]);
            setJoinPick((prev) => (prev.includes(t.id) ? prev : [...prev, t.id]));
            setAskBillFor(null);
          }}
          onClose={() => setAskBillFor(null)}
        />
      )}

      {/* Backstop only: the server refused because the bill-keeping table has
          several bills and the floor's cached copy did not show that — a bill
          opened on another till since this screen last refreshed. Ask, then retry. */}
      {joinBillFor && (
        <TableBillsDialog
          tableLabel={joinBillFor.label}
          bills={joinBillFor.bills ?? []}
          onPick={(b) => {
            setIntoOrderId(b.order_id);
            setJoinBillFor(null);
            void runJoin(b.order_id);
          }}
          onClose={() => setJoinBillFor(null)}
        />
      )}

      {billsFor && (
        <TableBillsDialog
          tableLabel={billsFor.label}
          bills={billsFor.bills ?? []}
          onPick={(b) =>
            // ?order= names the exact bill and WINS over the table lookup in the
            // till; the table rides along so the ticket strip can label it.
            navigate(tillPath(billsFor, `&order=${b.order_id}`))
          }
          // Unique per press so the till remounts clean — a table may take any
          // number of bills, not two. See the route key in App.tsx.
          onSplit={() => navigate(tillPath(billsFor, `&split=${Date.now()}`))}
          onClose={() => setBillsFor(null)}
        />
      )}
    </div>
  );
}
