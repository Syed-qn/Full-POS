import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { WaiterTopBar } from "../components/WaiterTopBar";
import { apiClient } from "../lib/apiClient";
import { fetchFloorLayout } from "../lib/floorApi";
import { usePosTheme } from "../lib/posTheme";
import s from "./WaiterFloorScreen.module.css";

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
  guests?: number | null;
  waiter?: string | null;
  seated_since?: string | null;
};

type Bucket = "available" | "occupied" | "reserved" | "cleaning" | "held";

/** Collapse the table FSM into the five buckets the floor legend shows. */
function bucketOf(status: string, hasOrder: boolean): Bucket {
  if (hasOrder) return "occupied";
  switch (status) {
    case "ordered":
    case "needs_bill":
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

/** Fallback grid unit in px — pos_x/pos_y are float grid coords, not pixels.
 *  The live unit is derived from the canvas width so the floor fills the room. */
const BASE_UNIT = 76;

/** Module-level table cache so returning to the floor paints instantly instead
 *  of flashing "Loading floor…". Refreshed live (poll + on each mount). */
let tableCache: ApiTable[] | null = null;

/**
 * Waiter landing screen — a full-bleed dark floor plan.
 *
 * Tables sit on one continuous canvas, absolutely placed from pos_x/pos_y
 * (float GRID coordinates, scaled by a unit derived from the canvas width so
 * the room fills the screen at any size).
 */
export function WaiterFloorScreen() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  // Stay inside the current namespace: /waiter/floor → /waiter/new-order,
  // plain /floor (staff) → /new-order.
  const orderBase = pathname.startsWith("/waiter") ? "/waiter/new-order" : "/new-order";
  const theme = usePosTheme();
  const [tables, setTables] = useState<ApiTable[]>(() => tableCache ?? []);
  const [loading, setLoading] = useState(tableCache === null);
  // Entrance placed by the manager in Floor Plan. Null until placed → the
  // marker falls back to the bottom of the room.
  const [entrance, setEntrance] = useState<{ x: number; y: number; rot: number } | null>(null);

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
    const id = setInterval(() => void load(), 20_000);
    return () => clearInterval(id);
  }, [load]);


  const stats = useMemo(() => {
    let available = 0;
    let occupied = 0;
    let reserved = 0;
    let covers = 0;
    for (const t of tables) {
      const b = bucketOf(t.status, !!t.order_id);
      if (b === "available") available += 1;
      else if (b === "occupied") {
        occupied += 1;
        covers += t.guests ?? 0;
      } else if (b === "reserved") reserved += 1;
    }
    return { available, occupied, reserved, covers };
  }, [tables]);

  // Furthest table in grid units — defines how much room the floor needs.
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

  // Scale the grid unit to the available width so the room fills the screen
  // instead of hugging the left edge. Tracks resize.
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const [unit, setUnit] = useState(BASE_UNIT);
  useLayoutEffect(() => {
    const el = canvasRef.current;
    if (!el || span.x <= 0) return;
    const measure = () => {
      // +1.6 leaves a margin past the right-most table for its chairs/padding.
      const usable = el.clientWidth - 40;
      if (usable > 0) setUnit(Math.max(56, usable / (span.x + 1.6)));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [span.x]);

  const floorHeight = (span.y + 2.2) * unit;

  function openTable(t: ApiTable) {
    navigate(`${orderBase}?table=${t.id}&label=${encodeURIComponent(t.label)}`);
  }

  return (
    <div className={s.root} data-theme={theme} data-testid="waiter-floor-screen">
      <WaiterTopBar active="dining" />

      {/* ── Stats strip + legend ────────────────────────────────────────── */}
      <div className={s.statsBar}>
        <div className={s.stats}>
          <span className={s.stat}>
            <strong className={s.nAvailable}>{stats.available}</strong> AVAILABLE
          </span>
          <span className={s.stat}>
            <strong className={s.nOccupied}>{stats.occupied}</strong> OCCUPIED
          </span>
          <span className={s.stat}>
            <strong className={s.nReserved}>{stats.reserved}</strong> RESERVED
          </span>
          <span className={s.stat}>
            <strong className={s.nCovers}>{stats.covers}</strong> COVERS
          </span>
        </div>

        <div className={s.legend}>
          <span className={s.legendItem}>
            <i className={`${s.dot} ${s.dotAvailable}`} />
            Available
          </span>
          <span className={s.legendItem}>
            <i className={`${s.dot} ${s.dotOccupied}`} />
            Occupied
          </span>
          <span className={s.legendItem}>
            <i className={`${s.dot} ${s.dotReserved}`} />
            Reserved
          </span>
          <span className={s.legendItem}>
            <i className={`${s.dot} ${s.dotCleaning}`} />
            Cleaning
          </span>
          <span className={s.legendItem}>
            <i className={`${s.dot} ${s.dotHeld}`} />
            Held
          </span>
        </div>

        <button type="button" className={s.editLayout} disabled title="Layout editor coming soon">
          ✎ Edit Layout
        </button>
      </div>

      {/* ── Floor canvas ────────────────────────────────────────────────── */}
      <div className={s.canvas} ref={canvasRef} style={{ backgroundSize: `${unit}px ${unit}px` }}>
        {loading ? (
          <p className={s.canvasMsg}>Loading floor…</p>
        ) : tables.length === 0 ? (
          <p className={s.canvasMsg}>
            No tables set up yet — a manager can add them in Floor Plan.
          </p>
        ) : (
          <div
            className={s.floor}
            style={{ height: floorHeight }}
            data-testid="waiter-floor-canvas"
          >
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
                  data-testid={`waiter-table-${t.id}`}
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
                    <span className={s.tableLabel}>{t.label}</span>
                    <span className={s.tableSeats}>👥 {t.seats}</span>
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
    </div>
  );
}
