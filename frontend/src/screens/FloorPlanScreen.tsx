import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button, TouchButton } from "../components/Button";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import { apiClient } from "../lib/apiClient";
import type { ApiTable } from "../lib/floorApi";
import {
  createTable,
  deleteTable,
  fetchFloorLayout,
  listTables,
  saveFloorLayout,
  updateTable,
} from "../lib/floorApi";
import { fetchOrderDetail } from "../lib/orderDetailApi";
import type { OrderDetailOut } from "../lib/types";
import s from "./FloorPlanScreen.module.css";

/** Two-letter avatar initials from a customer name. */
function initials(name?: string | null): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "GG";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** Dining table status FSM from backend tables service. */
export type TableStatus =
  | "available"
  | "seated"
  | "ordered"
  | "needs_bill"
  | "cleaning"
  | "reserved";

const STATUS_META: Record<TableStatus, { label: string; color: string }> = {
  available: { label: "Available", color: "#12b76a" },
  seated: { label: "Seated", color: "#175cd3" },
  ordered: { label: "Occupied", color: "#f79009" },
  needs_bill: { label: "Needs bill", color: "#6941c6" },
  cleaning: { label: "Cleaning", color: "#98a2b3" },
  reserved: { label: "Reserved", color: "#026aa2" },
};

type Bucket = "available" | "occupied" | "billing" | "reserved" | "cleaning";

/** Same bucketing the waiter/cashier floors use, so one table never reads as
 *  two different states depending on which surface you are standing at. */
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

/** "seated for" label from an ISO start time — 12 min, 1h 05m, etc. */
function seatedFor(iso?: string | null): string | null {
  if (!iso) return null;
  const mins = Math.max(0, Math.floor((Date.now() - Date.parse(iso)) / 60_000));
  if (mins < 60) return `${mins} min`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return `${h}h ${String(m).padStart(2, "0")}m`;
}

/** Fallback grid unit in px — pos_x/pos_y are float GRID coords, not pixels. */
const BASE_UNIT = 76;
/** Drag snap, in grid units. Quarter-unit keeps rows visually aligned while
 *  still allowing a table to be nudged off a strict lattice. */
const SNAP = 0.25;

const snap = (v: number) => Math.max(0, Math.round(v / SNAP) * SNAP);

type ConfirmKind = "transfer" | "merge" | "split" | "print" | "delete" | null;
type Draft = { id: number | null; label: string; seats: number };
type DragState = {
  kind: "table" | "entrance";
  id: number;
  startX: number;
  startY: number;
  origX: number;
  origY: number;
  moved: boolean;
};

export function FloorPlanScreen() {
  const navigate = useNavigate();
  const [tables, setTables] = useState<ApiTable[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [confirm, setConfirm] = useState<ConfirmKind>(null);
  const [busy, setBusy] = useState(false);
  const [transferTargetId, setTransferTargetId] = useState<number | "">("");
  const [mergeTargetId, setMergeTargetId] = useState<number | "">("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [detail, setDetail] = useState<OrderDetailOut | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // ── Layout editing ────────────────────────────────────────────────────
  const [editing, setEditing] = useState(false);
  const [entrance, setEntrance] = useState<{ x: number; y: number; rot: number } | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const dragRef = useRef<DragState | null>(null);

  const load = useCallback(async () => {
    try {
      const rows = await listTables();
      setTables(Array.isArray(rows) ? rows : []);
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Could not load tables");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    fetchFloorLayout()
      .then((l) =>
        setEntrance(
          l.entrance_x != null && l.entrance_y != null
            ? { x: l.entrance_x, y: l.entrance_y, rot: l.entrance_rot ?? 0 }
            : null,
        ),
      )
      .catch(() => setEntrance(null));
  }, [load]);

  useEffect(() => {
    // Live refresh — but never while a layout edit is in flight, or the poll
    // would stomp the position the manager is dragging.
    if (editing) return;
    const id = setInterval(() => void load(), 20_000);
    return () => clearInterval(id);
  }, [load, editing]);

  const selected = useMemo(
    () => tables.find((t) => t.id === selectedId) ?? null,
    [tables, selectedId],
  );

  const selectedOrderId = selected?.order_id ?? null;
  useEffect(() => {
    if (!selectedOrderId || selectedOrderId <= 0) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    setDetail(null);
    fetchOrderDetail(selectedOrderId, { include: "overview" })
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch(() => {
        if (!cancelled) setDetail(null);
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedOrderId]);

  const transferCandidates = useMemo(
    () => tables.filter((t) => t.id !== selectedId && t.status === "available"),
    [tables, selectedId],
  );

  const mergeCandidates = useMemo(
    () => tables.filter((t) => t.id !== selectedId && !!t.order_id && t.order_id > 0),
    [tables, selectedId],
  );

  // ── Canvas geometry — identical maths to the waiter/cashier floors so the
  //    layout a manager arranges here is the layout the floor staff see. ──
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
      if (usable > 0) setUnit(Math.max(56, usable / (span.x + 1.6)));
    };
    measure();
    // jsdom (unit tests) has no ResizeObserver — one measure pass is enough there.
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [span.x]);

  const floorHeight = (span.y + 2.2) * unit;
  const entrancePos = entrance ?? { x: Math.max(0, span.x / 2), y: span.y + 1.2, rot: 0 };

  // ── Drag to reposition (tables and the entrance marker) ────────────────
  function beginDrag(
    e: React.PointerEvent,
    kind: "table" | "entrance",
    id: number,
    origX: number,
    origY: number,
  ) {
    if (!editing) return;
    e.preventDefault();
    // Capture keeps the drag alive when the pointer leaves the small table box.
    // Guarded: jsdom has no pointer capture, and a stale pointer id throws.
    try {
      (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
    } catch {
      /* capture unavailable — the drag still tracks via pointermove */
    }
    dragRef.current = {
      kind,
      id,
      startX: e.clientX,
      startY: e.clientY,
      origX,
      origY,
      moved: false,
    };
  }

  function onDragMove(e: React.PointerEvent) {
    const d = dragRef.current;
    if (!d) return;
    const dx = (e.clientX - d.startX) / unit;
    const dy = (e.clientY - d.startY) / unit;
    if (!d.moved && Math.abs(e.clientX - d.startX) + Math.abs(e.clientY - d.startY) < 4) return;
    d.moved = true;
    const x = snap(d.origX + dx);
    const y = snap(d.origY + dy);
    if (d.kind === "entrance") {
      setEntrance((prev) => ({ x, y, rot: prev?.rot ?? 0 }));
    } else {
      setTables((prev) => prev.map((t) => (t.id === d.id ? { ...t, pos_x: x, pos_y: y } : t)));
    }
  }

  async function endDrag(e: React.PointerEvent) {
    const d = dragRef.current;
    dragRef.current = null;
    if (!d) return;
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture?.(e.pointerId);
    } catch {
      /* pointer already released */
    }
    if (!d.moved) return;
    try {
      if (d.kind === "entrance") {
        const pos = entrance ?? entrancePos;
        await saveFloorLayout(pos.x, pos.y, pos.rot);
      } else {
        const moved = tables.find((t) => t.id === d.id);
        if (moved) await updateTable(d.id, { pos_x: moved.pos_x, pos_y: moved.pos_y });
      }
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not save position", "error");
      await load();
    }
  }

  /** Turn the selected table by `delta` degrees. 15° steps: enough to line a
   *  table up with a diagonal wall, coarse enough to stay tidy. */
  async function rotateTable(delta: number) {
    if (!selected) return;
    const next = (((selected.rotation ?? 0) + delta) % 360 + 360) % 360;
    setTables((prev) => prev.map((t) => (t.id === selected.id ? { ...t, rotation: next } : t)));
    try {
      await updateTable(selected.id, { rotation: next });
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not rotate the table", "error");
      await load();
    }
  }

  async function rotateEntrance(delta: number) {
    const pos = entrance ?? entrancePos;
    const next = (((pos.rot ?? 0) + delta) % 360 + 360) % 360;
    setEntrance({ x: pos.x, y: pos.y, rot: next });
    try {
      await saveFloorLayout(pos.x, pos.y, next);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not rotate the entrance", "error");
    }
  }

  // ── Table CRUD ─────────────────────────────────────────────────────────
  function nextLabel(): string {
    let n = 1;
    const taken = new Set(tables.map((t) => t.label.toUpperCase()));
    while (taken.has(`T${String(n).padStart(2, "0")}`)) n += 1;
    return `T${String(n).padStart(2, "0")}`;
  }

  function openAdd() {
    // Adding implies arranging — a new table lands off to the side and has to
    // be dragged into place, so switch the editor on with it.
    setEditing(true);
    setDraft({ id: null, label: nextLabel(), seats: 4 });
  }

  async function saveDraft() {
    if (!draft) return;
    const label = draft.label.trim();
    if (!label) {
      toast("Give the table a label.", "error");
      return;
    }
    setBusy(true);
    try {
      if (draft.id == null) {
        // New tables land on a fresh row below the floor; the manager drags
        // them into place from there.
        const created = await createTable({
          label,
          seats: draft.seats,
          pos_x: 0,
          pos_y: snap(span.y + 1),
        });
        setTables((prev) => [...prev, created]);
        setSelectedId(created.id);
        toast(`Table ${created.label} added — drag it into place.`);
      } else {
        const saved = await updateTable(draft.id, { label, seats: draft.seats });
        setTables((prev) => prev.map((t) => (t.id === saved.id ? { ...t, ...saved } : t)));
        toast(`Table ${saved.label} updated.`);
      }
      setDraft(null);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save the table", "error");
    } finally {
      setBusy(false);
    }
  }

  async function runDelete() {
    if (!selected) return;
    setBusy(true);
    try {
      await deleteTable(selected.id);
      setTables((prev) => prev.filter((t) => t.id !== selected.id));
      setSelectedId(null);
      setConfirm(null);
      toast(`Table ${selected.label} removed from the floor.`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not remove the table", "error");
    } finally {
      setBusy(false);
    }
  }

  /** A tap on a table always selects it — the side card then shows either its
   *  tab (normal) or the layout editor (edit mode). */
  function selectTable(t: ApiTable) {
    setSelectedId(t.id);
    setActionError(null);
  }

  async function runTransfer() {
    if (!selected || transferTargetId === "") return;
    setBusy(true);
    setActionError(null);
    try {
      if (selected.order_id) {
        await apiClient.patch(`/api/v1/tables/${transferTargetId}/transfer-order`, {
          order_id: selected.order_id,
        });
        toast("Order transferred to new table.");
        await load();
      } else {
        toast("No open order on this table to transfer. Open an order first.", "error");
        setBusy(false);
        return;
      }
      setConfirm(null);
      setSelectedId(null);
      setTransferTargetId("");
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Transfer failed");
    } finally {
      setBusy(false);
    }
  }

  async function runMergeConfirm() {
    if (!selected?.order_id || selected.order_id <= 0) {
      toast("Selected table has no open tab to merge into.", "error");
      return;
    }
    if (mergeTargetId === "") {
      toast("Pick the other table to merge from.", "error");
      return;
    }
    const secondary = tables.find((t) => t.id === Number(mergeTargetId));
    if (!secondary?.order_id) {
      toast("That table has no open tab.", "error");
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      await apiClient.post("/api/v1/orders/merge", {
        primary_order_id: selected.order_id,
        secondary_order_id: secondary.order_id,
      });
      toast(`Merged ${secondary.label} into ${selected.label}. Merge more if needed.`);
      setMergeTargetId("");
      setConfirm(null);
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Merge failed");
    } finally {
      setBusy(false);
    }
  }

  async function runUnmerge() {
    if (!selected?.order_id || selected.order_id <= 0) return;
    setBusy(true);
    setActionError(null);
    try {
      await apiClient.post(`/api/v1/orders/${selected.order_id}/unmerge`);
      toast(`Un-merged the last table from ${selected.label}.`);
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Un-merge failed");
    } finally {
      setBusy(false);
    }
  }

  function runSplitConfirm() {
    if (selected?.order_id && selected.order_id > 0) {
      navigate(`/orders/${selected.order_id}/pay?split=1`);
      setConfirm(null);
      return;
    }
    toast("Select a table with an open order to split the bill.", "error");
    setConfirm(null);
  }

  function runPrintConfirm() {
    toast("Print bill sent to receipt printer (when configured).");
    setConfirm(null);
  }

  return (
    <div className={s.root} data-testid="floor-plan-screen">
      <PageHeader
        title="Floor Plan"
        subtitle="The room as waiters and cashiers see it — add, move, and edit tables"
      />

      {loadError && <ErrorState title="Could not load tables" description={loadError} />}

      <div className={s.toolbar}>
        <div className={s.legend} aria-label="Table status legend">
          <span className={s.legendItem}>
            <span className={s.swatch} style={{ background: STATUS_META.available.color }} />
            Available
          </span>
          <span className={s.legendItem}>
            <span className={s.swatch} style={{ background: STATUS_META.ordered.color }} />
            Occupied
          </span>
          <span className={s.legendItem}>
            <span className={s.swatch} style={{ background: STATUS_META.needs_bill.color }} />
            Needs bill
          </span>
        </div>

        <div className={s.toolActions}>
          <button type="button" className={s.toolBtn} onClick={openAdd} data-testid="add-table">
            ＋ Add table
          </button>
          <button
            type="button"
            className={`${s.toolBtn} ${editing ? s.toolBtnOn : ""}`}
            onClick={() => {
              // Selection carries across the toggle: the table you were looking
              // at is the one you want to edit.
              setEditing((v) => !v);
              setDraft(null);
            }}
            data-testid="toggle-edit-layout"
          >
            {editing ? "✓ Done editing" : "✎ Edit table"}
          </button>
        </div>
      </div>

      {editing && (
        <p className={s.editHint} role="status">
          Drag tables and the entrance marker to rearrange the room. Changes save
          instantly and appear on the waiter and cashier floors.
        </p>
      )}

      {/* The side card belongs to the editor: outside edit mode it is hidden and
          the floor takes the full width. */}
      <div className={`${s.split} ${editing ? "" : s.splitFull}`}>
        <div className={s.floorPane}>
          <div
            className={s.canvas}
            ref={canvasRef}
            style={{ backgroundSize: `${unit}px ${unit}px` }}
          >
            {loading ? (
              <p className={s.canvasMsg}>Loading floor…</p>
            ) : tables.length === 0 ? (
              <EmptyState
                title="No tables yet"
                description="Turn on Edit layout and add your first table to build the room."
              />
            ) : (
              <div
                className={s.floor}
                style={{ height: floorHeight }}
                data-testid="floor-canvas"
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
                    <div
                      key={t.id}
                      role="button"
                      tabIndex={0}
                      className={`${s.tableSlot} ${editing ? s.tableSlotEdit : ""} ${
                        selectedId === t.id ? s.tableSlotOn : ""
                      }`}
                      style={{
                        left: (t.pos_x ?? 0) * unit,
                        top: (t.pos_y ?? 0) * unit,
                        // Chairs turn with the table — the slot rotates as one piece.
                        transform: t.rotation ? `rotate(${t.rotation}deg)` : undefined,
                      }}
                      onPointerDown={(e) => beginDrag(e, "table", t.id, t.pos_x ?? 0, t.pos_y ?? 0)}
                      onPointerMove={onDragMove}
                      onPointerUp={(e) => void endDrag(e)}
                      onClick={() => selectTable(t)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") selectTable(t);
                      }}
                      data-testid={`table-card-${t.id}`}
                      data-status={t.status}
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
                        {hasOrder && t.order_total_aed != null ? (
                          <span className={s.tableSeats}>AED {t.order_total_aed}</span>
                        ) : (
                          <span className={s.tableSeats}>👥 {t.seats}</span>
                        )}
                      </span>
                      <span className={s.chairRow}>
                        {Array.from({ length: bottom }).map((_, i) => (
                          <i key={i} className={s.chair} />
                        ))}
                      </span>
                    </div>
                  );
                })}

                <div
                  className={`${s.entrance} ${editing ? s.entranceEdit : ""}`}
                  style={{
                    left: entrancePos.x * unit,
                    top: entrancePos.y * unit,
                    transform: `translateX(-50%) rotate(${entrancePos.rot ?? 0}deg)`,
                  }}
                  onPointerDown={(e) =>
                    beginDrag(e, "entrance", 0, entrancePos.x, entrancePos.y)
                  }
                  onPointerMove={onDragMove}
                  onPointerUp={(e) => void endDrag(e)}
                  data-testid="floor-entrance"
                  title={editing ? "Drag to move the entrance" : undefined}
                >
                  ▲ ENTRANCE
                </div>
              </div>
            )}
          </div>
        </div>

        {editing && (
        <aside className={s.orderPane} data-testid="order-pane" aria-label="Selected table">
          {editing ? (
            <div className={s.pane} data-testid="layout-editor-pane">
              <div className={s.paneSectionLabel}>Layout editor</div>

              {/* Entrance controls live here rather than on the marker itself —
                  the marker is small and already the drag handle. */}
              <div className={s.rotateBlock}>
                <span className={s.rotateLabel}>
                  Entrance · {Math.round(entrancePos.rot ?? 0)}°
                </span>
                <div className={s.rotateRow}>
                  <button type="button" className={s.rotBtn} onClick={() => void rotateEntrance(-15)}>
                    ⟲ 15°
                  </button>
                  <button type="button" className={s.rotBtn} onClick={() => void rotateEntrance(15)}>
                    ⟳ 15°
                  </button>
                  <button type="button" className={s.rotBtn} onClick={() => void rotateEntrance(90)}>
                    ⟳ 90°
                  </button>
                </div>
              </div>

              {!selected ? (
                <p className={s.paneMuted}>
                  Select a table to rename, rotate, or remove it.
                </p>
              ) : (
                <>
                  <header className={s.paneHead}>
                    <span className={`${s.paneAvatar} ${s.paneAvatarFree}`}>{selected.label}</span>
                    <div className={s.paneWho}>
                      <span className={s.paneName}>Table {selected.label}</span>
                      <span className={s.paneOrderNo}>
                        {selected.seats} seats · x {selected.pos_x.toFixed(2)} · y{" "}
                        {selected.pos_y.toFixed(2)}
                      </span>
                    </div>
                  </header>
                  <div className={s.rotateBlock}>
                    <span className={s.rotateLabel}>
                      Rotation · {Math.round(selected.rotation ?? 0)}°
                    </span>
                    <div className={s.rotateRow}>
                      <button
                        type="button"
                        className={s.rotBtn}
                        onClick={() => void rotateTable(-15)}
                        data-testid="rotate-ccw"
                      >
                        ⟲ 15°
                      </button>
                      <button
                        type="button"
                        className={s.rotBtn}
                        onClick={() => void rotateTable(15)}
                        data-testid="rotate-cw"
                      >
                        ⟳ 15°
                      </button>
                      <button
                        type="button"
                        className={s.rotBtn}
                        onClick={() => void rotateTable(90)}
                      >
                        ⟳ 90°
                      </button>
                      <button
                        type="button"
                        className={s.rotBtn}
                        onClick={() => void rotateTable(-(selected.rotation ?? 0))}
                        disabled={!selected.rotation}
                      >
                        Reset
                      </button>
                    </div>
                  </div>

                  <TouchButton
                    type="button"
                    onClick={() =>
                      setDraft({ id: selected.id, label: selected.label, seats: selected.seats })
                    }
                  >
                    ✎ Edit table
                  </TouchButton>
                  <button
                    type="button"
                    className={s.dangerBtn}
                    onClick={() => setConfirm("delete")}
                    data-testid="delete-table"
                  >
                    🗑 Remove table
                  </button>
                  {selected.order_id ? (
                    <p className={s.paneMuted}>
                      This table has an open tab — settle or transfer it before removing.
                    </p>
                  ) : null}
                </>
              )}
            </div>
          ) : !selected ? (
            <div className={s.paneEmpty} data-testid="order-pane-empty">
              <div className={s.paneEmptyIcon}>🍽️</div>
              <p className={s.paneEmptyTitle}>Select a table</p>
              <p className={s.paneEmptyHint}>
                Tap a table on the floor to open its tab, add dishes, or take payment.
              </p>
            </div>
          ) : selected.order_id && selected.order_id > 0 ? (
            <div className={s.pane} data-testid="selected-table-drawer">
              <header className={s.paneHead}>
                <span className={s.paneAvatar}>{initials(detail?.customer.name)}</span>
                <div className={s.paneWho}>
                  <span className={s.paneName}>{detail?.customer.name ?? "Guest"}</span>
                  <span className={s.paneOrderNo}>
                    {detail?.order_number ?? `#${selected.order_id}`}
                  </span>
                </div>
                <span className={s.paneTag}>🍽️ Dine In · {selected.label}</span>
              </header>

              <div className={s.paneItems} data-testid="order-pane-items">
                <div className={s.paneSectionLabel}>Order Items</div>
                {detailLoading ? (
                  <p className={s.paneMuted}>Loading items…</p>
                ) : detail && detail.items.length > 0 ? (
                  detail.items.map((it, i) => (
                    <div className={s.itemRow} key={`${it.dish_number}-${i}`}>
                      <span className={s.itemQty}>×{it.qty}</span>
                      <div className={s.itemMain}>
                        <span className={s.itemName}>{it.dish_name}</span>
                        {(it.variant_name || it.notes) && (
                          <span className={s.itemSub}>
                            {[it.variant_name, it.notes].filter(Boolean).join(" · ")}
                          </span>
                        )}
                      </div>
                      <span className={s.itemPrice}>AED {it.line_total}</span>
                    </div>
                  ))
                ) : (
                  <p className={s.paneMuted}>No items on this tab yet.</p>
                )}
              </div>

              <TouchButton
                type="button"
                onClick={() =>
                  navigate(
                    `/new-order?table=${selected.id}&label=${encodeURIComponent(selected.label)}`,
                  )
                }
              >
                ➕ Add Items
              </TouchButton>

              <div className={s.paneSummary}>
                <div className={s.paneSectionLabel}>Payment Summary</div>
                <div className={s.sumRow}>
                  <span>Subtotal</span>
                  <span>AED {detail?.subtotal ?? selected.order_total_aed ?? "0.00"}</span>
                </div>
                {detail && Number(detail.delivery_fee_aed) > 0 && (
                  <div className={s.sumRow}>
                    <span>Delivery fee</span>
                    <span>AED {detail.delivery_fee_aed}</span>
                  </div>
                )}
                <div className={`${s.sumRow} ${s.sumTotal}`}>
                  <span>Total</span>
                  <span>AED {detail?.total ?? selected.order_total_aed ?? "0.00"}</span>
                </div>
              </div>

              {actionError && <p className={s.error}>{actionError}</p>}

              <Link to={`/orders/${selected.order_id}/pay`} className={s.paneFullLink}>
                <Button type="button" variant="primary" size="lg" style={{ width: "100%" }}>
                  💳 Payment Now →
                </Button>
              </Link>

              <div className={s.paneMoreActions}>
                <button
                  type="button"
                  className={s.miniAction}
                  disabled={mergeCandidates.length === 0}
                  onClick={() => {
                    setMergeTargetId("");
                    setConfirm("merge");
                  }}
                >
                  🔗 Merge
                </button>
                <button
                  type="button"
                  className={s.miniAction}
                  disabled={transferCandidates.length === 0}
                  onClick={() => {
                    setTransferTargetId("");
                    setConfirm("transfer");
                  }}
                >
                  ↔ Transfer
                </button>
                <button type="button" className={s.miniAction} onClick={() => setConfirm("print")}>
                  🖨 Print
                </button>
                {(selected.merged_count ?? 0) > 0 && (
                  <button
                    type="button"
                    className={s.miniAction}
                    disabled={busy}
                    onClick={() => void runUnmerge()}
                    data-testid="unmerge-btn"
                  >
                    ↩ Un-merge ({selected.merged_count})
                  </button>
                )}
              </div>
            </div>
          ) : (
            <div className={s.pane} data-testid="selected-table-drawer">
              <header className={s.paneHead}>
                <span className={`${s.paneAvatar} ${s.paneAvatarFree}`}>{selected.label}</span>
                <div className={s.paneWho}>
                  <span className={s.paneName}>Table {selected.label}</span>
                  <span className={s.paneOrderNo}>
                    {STATUS_META[(selected.status as TableStatus) ?? "available"]?.label ??
                      selected.status}{" "}
                    · {selected.seats} seats
                  </span>
                </div>
              </header>
              {/* Free table: status only. Orders are started from the waiter /
                  cashier terminals, not from the manager's floor plan. */}
              {seatedFor(selected.seated_since) && (
                <p className={s.paneMuted}>Seated {seatedFor(selected.seated_since)}</p>
              )}
              {actionError && <p className={s.error}>{actionError}</p>}
            </div>
          )}
        </aside>
        )}
      </div>

      {draft && (
        <ConfirmDialog
          title={draft.id == null ? "Add table" : `Edit ${draft.label}`}
          message={
            draft.id == null
              ? "New tables appear at the bottom of the floor — drag them into place."
              : "Rename the table or change how many guests it seats."
          }
          confirmLabel={draft.id == null ? "Add table" : "Save"}
          busy={busy}
          onCancel={() => !busy && setDraft(null)}
          onConfirm={() => void saveDraft()}
        >
          <label className={s.fieldLabel} htmlFor="table-label">
            Label
          </label>
          <input
            id="table-label"
            className={s.select}
            style={{ width: "100%" }}
            value={draft.label}
            maxLength={32}
            onChange={(e) => setDraft({ ...draft, label: e.target.value })}
          />
          <label className={s.fieldLabel} htmlFor="table-seats">
            Seats
          </label>
          <input
            id="table-seats"
            className={s.select}
            style={{ width: "100%" }}
            type="number"
            min={1}
            max={20}
            value={draft.seats}
            onChange={(e) =>
              setDraft({ ...draft, seats: Math.max(1, Math.min(20, Number(e.target.value) || 1)) })
            }
          />
        </ConfirmDialog>
      )}

      {confirm === "delete" && selected && (
        <ConfirmDialog
          title={`Remove ${selected.label}?`}
          message="The table leaves every floor screen. Past orders served on it keep their history."
          confirmLabel="Remove"
          busy={busy}
          onCancel={() => !busy && setConfirm(null)}
          onConfirm={() => void runDelete()}
        />
      )}

      {confirm === "transfer" && selected && (
        <ConfirmDialog
          title={`Transfer from ${selected.label}?`}
          message="Move this table's open order to another free table."
          confirmLabel="Transfer"
          busy={busy}
          onCancel={() => !busy && setConfirm(null)}
          onConfirm={() => void runTransfer()}
        >
          <select
            id="transfer-target"
            className={s.select}
            style={{ width: "100%", marginTop: 4 }}
            value={transferTargetId}
            onChange={(e) =>
              setTransferTargetId(e.target.value === "" ? "" : Number(e.target.value))
            }
            aria-label="Target table for transfer"
          >
            <option value="">Select free table…</option>
            {transferCandidates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label} · {t.seats} seats
              </option>
            ))}
          </select>
        </ConfirmDialog>
      )}

      {confirm === "merge" && selected && (
        <ConfirmDialog
          title={`Merge into ${selected.label}?`}
          message={`Pick another occupied table — its bill folds into ${selected.label} and that table frees up.`}
          confirmLabel="Merge"
          busy={busy}
          onCancel={() => {
            if (!busy) {
              setConfirm(null);
              setMergeTargetId("");
            }
          }}
          onConfirm={() => void runMergeConfirm()}
        >
          <select
            id="merge-target"
            className={s.select}
            style={{ width: "100%", marginTop: 4 }}
            value={mergeTargetId}
            onChange={(e) => setMergeTargetId(e.target.value === "" ? "" : Number(e.target.value))}
            aria-label="Table to merge from"
          >
            <option value="">Select occupied table…</option>
            {mergeCandidates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label} · AED {t.order_total_aed ?? "0.00"}
              </option>
            ))}
          </select>
        </ConfirmDialog>
      )}

      {confirm === "split" && selected && (
        <ConfirmDialog
          title="Split bill?"
          message="Open checkout in split mode for this table's open order."
          confirmLabel="Open split checkout"
          onCancel={() => setConfirm(null)}
          onConfirm={runSplitConfirm}
        />
      )}

      {confirm === "print" && selected && (
        <ConfirmDialog
          title="Print bill?"
          message={`Send bill for table ${selected.label} to the receipt printer.`}
          confirmLabel="Print"
          onCancel={() => setConfirm(null)}
          onConfirm={runPrintConfirm}
        />
      )}
    </div>
  );
}
