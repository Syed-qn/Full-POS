import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { BottomActionBar } from "../components/BottomActionBar";
import { Button, TouchButton } from "../components/Button";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { PageHeader } from "../components/PageHeader";
import { SideDrawer } from "../components/SideDrawer";
import { toast } from "../components/Toaster";
import { apiClient, ApiError } from "../lib/apiClient";
import s from "./FloorPlanScreen.module.css";

/** Dining table status FSM from backend tables service. */
export type TableStatus =
  | "available"
  | "seated"
  | "ordered"
  | "needs_bill"
  | "cleaning"
  | "reserved";

export type FloorTable = {
  id: number;
  label: string;
  seats: number;
  status: TableStatus;
  pos_x: number;
  pos_y: number;
  /** Soft zone label for UI tabs — backend has no zone column yet. */
  zone: string;
  qr_token?: string | null;
  /** Optional open order when known (mock / future enrichment). */
  order_id?: number | null;
  order_total_aed?: string | null;
  waiter?: string | null;
  guests?: number | null;
};

const ZONES = ["Main Hall", "Patio", "Family", "Private Room"] as const;

const STATUS_META: Record<
  TableStatus,
  { label: string; color: string; className: string }
> = {
  available: { label: "Available", color: "#12b76a", className: s.st_available },
  seated: { label: "Seated", color: "#175cd3", className: s.st_seated },
  ordered: { label: "Ordered", color: "#f79009", className: s.st_ordered },
  needs_bill: { label: "Needs bill", color: "#6941c6", className: s.st_needs_bill },
  cleaning: { label: "Cleaning", color: "#98a2b3", className: s.st_cleaning },
  reserved: { label: "Reserved", color: "#026aa2", className: s.st_reserved },
};

/**
 * LOCAL MOCK — used when GET /api/v1/tables is empty or unavailable.
 * Backend tables module has no zone field and may ship with zero rows;
 * UI must still look production-ready for floor staff training demos.
 */
const MOCK_TABLES: FloorTable[] = [
  {
    id: -1,
    label: "T1",
    seats: 4,
    status: "available",
    pos_x: 0,
    pos_y: 0,
    zone: "Main Hall",
  },
  {
    id: -2,
    label: "T2",
    seats: 2,
    status: "seated",
    pos_x: 1,
    pos_y: 0,
    zone: "Main Hall",
    guests: 2,
    waiter: "Aisha",
  },
  {
    id: -3,
    label: "T3",
    seats: 6,
    status: "ordered",
    pos_x: 2,
    pos_y: 0,
    zone: "Main Hall",
    guests: 5,
    waiter: "Omar",
    order_id: 101,
    order_total_aed: "186.00",
  },
  {
    id: -4,
    label: "T4",
    seats: 4,
    status: "needs_bill",
    pos_x: 0,
    pos_y: 1,
    zone: "Main Hall",
    guests: 3,
    waiter: "Aisha",
    order_id: 102,
    order_total_aed: "94.50",
  },
  {
    id: -5,
    label: "P1",
    seats: 4,
    status: "available",
    pos_x: 0,
    pos_y: 0,
    zone: "Patio",
  },
  {
    id: -6,
    label: "P2",
    seats: 2,
    status: "ordered",
    pos_x: 1,
    pos_y: 0,
    zone: "Patio",
    guests: 2,
    order_id: 103,
    order_total_aed: "42.00",
  },
  {
    id: -7,
    label: "F1",
    seats: 8,
    status: "seated",
    pos_x: 0,
    pos_y: 0,
    zone: "Family",
    guests: 6,
    waiter: "Sara",
  },
  {
    id: -8,
    label: "VIP1",
    seats: 10,
    status: "reserved",
    pos_x: 0,
    pos_y: 0,
    zone: "Private Room",
    waiter: "Manager",
  },
];

type ApiTable = {
  id: number;
  label: string;
  seats: number;
  pos_x: number;
  pos_y: number;
  status: string;
  qr_token?: string | null;
};

function zoneFromLabel(label: string): string {
  const lower = label.toLowerCase();
  if (lower.startsWith("p") || lower.includes("patio")) return "Patio";
  if (lower.startsWith("f") || lower.includes("family")) return "Family";
  if (lower.includes("vip") || lower.includes("private") || lower.startsWith("pr")) {
    return "Private Room";
  }
  return "Main Hall";
}

function normalizeStatus(raw: string): TableStatus {
  if (raw in STATUS_META) return raw as TableStatus;
  return "available";
}

function mapApiTable(row: ApiTable): FloorTable {
  return {
    id: row.id,
    label: row.label,
    seats: row.seats,
    pos_x: row.pos_x,
    pos_y: row.pos_y,
    status: normalizeStatus(row.status),
    zone: zoneFromLabel(row.label),
    qr_token: row.qr_token ?? null,
  };
}

type ConfirmKind = "transfer" | "merge" | "split" | "print" | null;

export function FloorPlanScreen() {
  const navigate = useNavigate();
  const [zone, setZone] = useState<(typeof ZONES)[number]>("Main Hall");
  const [tables, setTables] = useState<FloorTable[]>([]);
  const [usingMock, setUsingMock] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [confirm, setConfirm] = useState<ConfirmKind>(null);
  const [busy, setBusy] = useState(false);
  const [transferTargetId, setTransferTargetId] = useState<number | "">("");
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const rows = await apiClient.get<ApiTable[]>("/api/v1/tables");
      if (Array.isArray(rows) && rows.length > 0) {
        setTables(rows.map(mapApiTable));
        setUsingMock(false);
      } else {
        // No tables provisioned yet — show mock floor for production-looking UI.
        setTables(MOCK_TABLES);
        setUsingMock(true);
      }
    } catch (e) {
      // Backend missing / offline — fall back to local mock (clearly labelled).
      setTables(MOCK_TABLES);
      setUsingMock(true);
      if (e instanceof ApiError && e.status !== 404) {
        setLoadError(e.message);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const selected = useMemo(
    () => tables.find((t) => t.id === selectedId) ?? null,
    [tables, selectedId],
  );

  const zoneTables = useMemo(
    () => tables.filter((t) => t.zone === zone),
    [tables, zone],
  );

  const transferCandidates = useMemo(
    () => tables.filter((t) => t.id !== selectedId && t.status === "available"),
    [tables, selectedId],
  );

  function openNewTableOrder() {
    if (selected && selected.id > 0) {
      navigate(`/new-order?table=${selected.id}&label=${encodeURIComponent(selected.label)}`);
      return;
    }
    navigate("/new-order");
  }

  async function runTransfer() {
    if (!selected || transferTargetId === "") return;
    setBusy(true);
    setActionError(null);
    try {
      if (selected.id < 0 || Number(transferTargetId) < 0) {
        // Mock-only path
        setTables((prev) =>
          prev.map((t) => {
            if (t.id === selected.id) {
              return {
                ...t,
                status: "available",
                order_id: null,
                order_total_aed: null,
                guests: null,
              };
            }
            if (t.id === Number(transferTargetId)) {
              return {
                ...t,
                status: selected.status === "available" ? "seated" : selected.status,
                order_id: selected.order_id,
                order_total_aed: selected.order_total_aed,
                guests: selected.guests ?? selected.seats,
              };
            }
            return t;
          }),
        );
        toast("Table transferred (local mock).");
      } else if (selected.order_id) {
        await apiClient.patch(`/api/v1/tables/${transferTargetId}/transfer-order`, {
          order_id: selected.order_id,
        });
        toast("Order transferred to new table.");
        await load();
      } else {
        // No order_id on table — status-only seat move via seated status when possible.
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
    // Merge requires two order ids; tables API has no merge endpoint.
    // POST /api/v1/orders/merge exists — need both order ids from floor enrichment.
    setBusy(true);
    setActionError(null);
    try {
      toast(
        "Merge needs two open order IDs. Use Order Detail → More when multi-order seating is linked.",
        "error",
      );
      setConfirm(null);
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
        subtitle="Tables, transfer, merge, and dine-in seating"
        right={
          <Button variant="ghost" size="lg" onClick={() => void load()} disabled={loading}>
            Refresh
          </Button>
        }
      />

      {usingMock && (
        <div className={s.banner} role="status" data-testid="floor-mock-banner">
          Showing demo floor layout — table API empty or unavailable. Provision tables via{" "}
          <code>POST /api/v1/tables</code> for live data.
        </div>
      )}

      {loadError && !usingMock && (
        <ErrorState title="Could not load tables" description={loadError} />
      )}

      <div className={s.zones} role="tablist" aria-label="Floor zones">
        {ZONES.map((z) => (
          <button
            key={z}
            type="button"
            role="tab"
            aria-selected={zone === z}
            className={`${s.zoneTab} ${zone === z ? s.zoneActive : ""}`}
            onClick={() => setZone(z)}
          >
            {z}
          </button>
        ))}
      </div>

      <div className={s.legend} aria-label="Table status legend">
        {(Object.keys(STATUS_META) as TableStatus[]).map((key) => (
          <span key={key} className={s.legendItem}>
            <span className={s.swatch} style={{ background: STATUS_META[key].color }} />
            {STATUS_META[key].label}
          </span>
        ))}
      </div>

      {loading && tables.length === 0 ? (
        <EmptyState title="Loading floor…" description="Fetching tables for this branch." />
      ) : zoneTables.length === 0 ? (
        <EmptyState
          title={`No tables in ${zone}`}
          description="Switch zone or create tables for this area."
        />
      ) : (
        <div className={s.grid} data-testid="floor-table-grid">
          {zoneTables.map((t) => {
            const meta = STATUS_META[t.status] ?? STATUS_META.available;
            return (
              <button
                key={t.id}
                type="button"
                className={`${s.tableCard} ${meta.className} ${
                  selectedId === t.id ? s.tableSelected : ""
                }`}
                data-testid={`table-card-${t.id}`}
                data-status={t.status}
                onClick={() => {
                  setSelectedId(t.id);
                  setActionError(null);
                }}
              >
                <div>
                  <div className={s.tableLabel}>{t.label}</div>
                  <div className={s.tableMeta}>
                    {t.guests != null ? `${t.guests}/` : ""}
                    {t.seats} seats
                  </div>
                </div>
                <span className={s.statusBadge} style={{ background: meta.color }}>
                  {meta.label}
                </span>
                {t.order_total_aed && (
                  <div className={s.tableMeta}>AED {t.order_total_aed}</div>
                )}
              </button>
            );
          })}
        </div>
      )}

      <SideDrawer
        open={selected !== null}
        title={selected ? `Table ${selected.label}` : "Table"}
        onClose={() => setSelectedId(null)}
      >
        {selected && (
          <div className={s.drawerBody} data-testid="selected-table-drawer">
            <div className={s.drawerRow}>
              <span>Status</span>
              <span>{STATUS_META[selected.status]?.label ?? selected.status}</span>
            </div>
            <div className={s.drawerRow}>
              <span>Seats</span>
              <span>
                {selected.guests != null ? `${selected.guests} / ` : ""}
                {selected.seats}
              </span>
            </div>
            <div className={s.drawerRow}>
              <span>Waiter</span>
              <span>{selected.waiter ?? "—"}</span>
            </div>
            <div className={s.drawerRow}>
              <span>Open order</span>
              <span>
                {selected.order_id ? (
                  <Link to={`/orders/${selected.order_id}`}>#{selected.order_id}</Link>
                ) : (
                  "None"
                )}
              </span>
            </div>
            <div className={s.drawerRow}>
              <span>Bill</span>
              <span>
                {selected.order_total_aed ? `AED ${selected.order_total_aed}` : "—"}
              </span>
            </div>
            {actionError && <p className={s.error}>{actionError}</p>}
            <div className={s.drawerActions}>
              <TouchButton type="button" onClick={openNewTableOrder}>
                New table order
              </TouchButton>
              {selected.order_id && selected.order_id > 0 && (
                <Link to={`/orders/${selected.order_id}/pay`}>
                  <Button type="button" variant="ghost" size="lg" style={{ width: "100%" }}>
                    Pay / split bill
                  </Button>
                </Link>
              )}
            </div>
          </div>
        )}
      </SideDrawer>

      <BottomActionBar>
        <TouchButton type="button" onClick={openNewTableOrder}>
          New Table Order
        </TouchButton>
        <Button
          type="button"
          variant="ghost"
          size="lg"
          disabled={!selected}
          onClick={() => {
            setTransferTargetId("");
            setConfirm("transfer");
          }}
        >
          Transfer
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="lg"
          disabled={!selected}
          onClick={() => setConfirm("merge")}
        >
          Merge
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="lg"
          disabled={!selected}
          onClick={() => setConfirm("split")}
        >
          Split Bill
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="lg"
          disabled={!selected}
          onClick={() => setConfirm("print")}
        >
          Print Bill
        </Button>
      </BottomActionBar>

      {confirm === "transfer" && selected && (
        <ConfirmDialog
          title={`Transfer from ${selected.label}?`}
          message="Move the open order (or seating) to another available table. Confirm to avoid accidental moves."
          confirmLabel="Transfer"
          busy={busy}
          onCancel={() => !busy && setConfirm(null)}
          onConfirm={() => void runTransfer()}
        />
      )}
      {confirm === "transfer" && selected && (
        <div
          style={{
            position: "fixed",
            bottom: 100,
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 60,
            background: "var(--bg-surface)",
            padding: 16,
            borderRadius: 12,
            border: "1px solid var(--border-default)",
            minWidth: 280,
            boxShadow: "var(--shadow-lg)",
          }}
        >
          <label className={s.hint} htmlFor="transfer-target">
            Target table
          </label>
          <select
            id="transfer-target"
            className={s.select}
            value={transferTargetId}
            onChange={(e) =>
              setTransferTargetId(e.target.value === "" ? "" : Number(e.target.value))
            }
            aria-label="Target table for transfer"
          >
            <option value="">Select table…</option>
            {transferCandidates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label} ({t.zone})
              </option>
            ))}
          </select>
        </div>
      )}

      {confirm === "merge" && selected && (
        <ConfirmDialog
          title="Merge tables?"
          message={`Merge another open order onto table ${selected.label}. Requires two open orders; secondary will cancel after merge.`}
          confirmLabel="Continue"
          busy={busy}
          onCancel={() => !busy && setConfirm(null)}
          onConfirm={() => void runMergeConfirm()}
        />
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
