import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BranchTransfersPanel } from "../components/BranchTransfersPanel";
import { Button } from "../components/Button";
import { IngredientAddModal } from "../components/IngredientAddModal";
import { PurchaseOrderModal, VendorAddModal } from "../components/PurchaseOrderModal";
import { StockMoveModal, type StockAction } from "../components/StockMoveModal";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import {
  getClosingHistory,
  getInventoryValuation,
  getReorderSuggestions,
  getSpoilageReport,
  getStockVarianceReport,
  listExpiringSoon,
  listGrns,
  listIngredients,
  listLowStock,
  listPurchaseOrders,
  listVendors,
  receivePurchaseOrder,
  sendLowStockAlert,
  takeClosingSnapshot,
} from "../lib/inventoryApi";
import { listBranchTransfers, listSiblingBranches } from "../lib/branchTransfersApi";
import { subscribeLive } from "../lib/liveEvents";
import type {
  BatchOut,
  BranchTransferOut,
  SiblingBranchOut,
  GrnOut,
  IngredientOut,
  InventoryValuationOut,
  PurchaseOrderOut,
  ReorderSuggestionOut,
  StockClosingHistoryRow,
  StockVarianceRow,
  VendorOut,
} from "../lib/types";
import s from "./InventoryScreen.module.css";

function money(value: string | number | null | undefined): string {
  const n = Number(value ?? 0);
  return `AED ${n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function qty(value: string | number, unit?: string): string {
  const n = Number(value);
  const formatted =
    typeof value === "string"
      ? value
      : Number.isFinite(n)
        ? n.toLocaleString(undefined, { maximumFractionDigits: 3 })
        : String(value);
  return unit ? `${formatted} ${unit}` : formatted;
}

function valueFor(valuation: InventoryValuationOut | null, ingredientId: number): string {
  const row = valuation?.rows.find((entry) => entry.ingredient_id === ingredientId);
  return money(row?.value_aed ?? 0);
}

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

type TabId = "stock" | "purchasing" | "counts" | "waste" | "transfers";

const TABS: Array<{ id: TabId; label: string }> = [
  { id: "stock", label: "Stock" },
  { id: "purchasing", label: "Purchasing" },
  { id: "counts", label: "Counts" },
  { id: "waste", label: "Waste" },
  // Transfers is appended at render time, only when this restaurant actually
  // has sibling branches. A single site has nowhere to send stock, and a tab
  // that can only say "no branches" teaches people to stop reading the tab bar.
  // No Locations tab. The three stock areas are auto-created and nothing
  // assigns stock to them — current_stock is one number per ingredient, not
  // per area — so the tab was three names that did nothing. Multi-location
  // stock is a central-kitchen feature; a single site has one storeroom.
  // The API, the rows and listStockLocations all stay, so it is a tab entry
  // away when there is a commissary to track.
];

/** Reason codes are stored as slugs; nobody wants to read "transfer_variance". */
const COUNT_REASON_LABELS: Record<string, string> = {
  count_error: "previous figure was wrong",
  damage: "damaged",
  spoilage: "spoiled",
  shrinkage: "unexplained loss",
  transfer_variance: "moved to or from elsewhere",
  system_correction: "data entry fix",
  other: "other",
};

function countReasonLabel(code: string): string {
  return COUNT_REASON_LABELS[code] ?? code.replace(/_/g, " ");
}

/** Variance as a share of the figure it moved from. Null when there is nothing
 *  to divide by — a count from zero is not "infinity percent". */
function variancePct(previous: string | number, variance: string | number): number | null {
  const from = Math.abs(Number(previous));
  const delta = Number(variance);
  if (!Number.isFinite(from) || !Number.isFinite(delta) || from === 0) return null;
  return (delta / from) * 100;
}

/** Order value: quantity times unit cost, summed over the lines. */
function poTotal(po: PurchaseOrderOut): number {
  return (po.lines ?? []).reduce(
    (sum, line) => sum + Number(line.qty_ordered) * Number(line.unit_cost_aed),
    0,
  );
}

/**
 * Parse a timestamp the way the server meant it.
 *
 * created_at comes back from SQLAlchemy as a NAIVE ISO string — no "Z", no
 * offset — even though the column holds UTC. JavaScript reads a marker-less
 * date-TIME as LOCAL time, so a count taken at 00:02 Dubai (20:02 UTC the
 * previous day) rendered as the previous day. Tag it as UTC when the server
 * did not.
 *
 * A date-ONLY string (closing_date) is a calendar day, not an instant, so it
 * is parsed at local midnight and shows exactly the day the server named. Left
 * to the spec it would be read as UTC midnight and slide a day backwards for
 * anyone west of Greenwich.
 */
function parseServerDate(iso: string): Date {
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) return new Date(`${iso}T00:00:00`);
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso);
  return new Date(hasZone ? iso : `${iso}Z`);
}

function shortDate(iso: string): string {
  const d = parseServerDate(iso);
  return Number.isNaN(d.getTime())
    ? iso.slice(0, 10)
    : d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function isoToday(): string {
  return new Date().toISOString().slice(0, 10);
}

export function InventoryScreen() {
  const [ingredients, setIngredients] = useState<IngredientOut[]>([]);
  const [valuation, setValuation] = useState<InventoryValuationOut | null>(null);
  const [lowStock, setLowStock] = useState<IngredientOut[]>([]);
  const [reorder, setReorder] = useState<ReorderSuggestionOut[]>([]);
  const [variance, setVariance] = useState<StockVarianceRow[]>([]);
  const [vendors, setVendors] = useState<VendorOut[]>([]);
  const [purchaseOrders, setPurchaseOrders] = useState<PurchaseOrderOut[]>([]);
  const [grns, setGrns] = useState<GrnOut[]>([]);
  const [expiring, setExpiring] = useState<BatchOut[]>([]);
  const [closings, setClosings] = useState<StockClosingHistoryRow[]>([]);
  const [spoilage, setSpoilage] = useState<
    Array<{
      ingredient_id: number;
      ingredient_name: string;
      quantity: string;
      reason_type: string;
      reason: string | null;
      created_at: string | null;
    }>
  >([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [alerting, setAlerting] = useState(false);
  const [purchasingBusy, setPurchasingBusy] = useState(false);

  // Every write on this screen now happens in a dialog, so the page itself is
  // only the numbers you read. Each entry holds the row it was opened from, so
  // a stock move started from a table row arrives with that ingredient chosen.
  const [addOpen, setAddOpen] = useState(false);
  const [vendorOpen, setVendorOpen] = useState(false);
  const [poOpen, setPoOpen] = useState(false);
  const [stockMove, setStockMove] = useState<
    { ingredientId: number | ""; action: StockAction } | null
  >(null);
  /** A count is open, so the recorded figures must not be on screen. */
  const blindCount = stockMove?.action === "count";

  // Sub navigation, same bar as the Promotion screen. The page was one column
  // of eight cards, so the stock table you open it for shared the screen with
  // purchase orders, spoilage history and stock areas — five different jobs
  // stacked on each other.
  const [tab, setTab] = useState<TabId>("stock");
  const [siblings, setSiblings] = useState<SiblingBranchOut[]>([]);
  const [transfers, setTransfers] = useState<BranchTransferOut[]>([]);

  // One load at a time. A single stock move fires one event, but a batch of
  // writes (receiving a PO line by line) can fire several within a second, and
  // this page issues 13 requests per load — overlapping them would multiply
  // that for no extra freshness. A load requested while one is running is
  // remembered and run once at the end, so the final state is never missed.
  const inFlight = useRef(false);
  const queued = useRef(false);

  const load = useCallback(async function load(): Promise<void> {
    if (inFlight.current) {
      queued.current = true;
      return;
    }
    inFlight.current = true;
    setLoadError(null);
    try {
      const start = isoDaysAgo(30);
      const end = isoToday();
      const [
        ingredientRows,
        valuationReport,
        lowRows,
        reorderRows,
        varianceRows,
        vendorRows,
        poRows,
        grnRows,
        expiringRows,
        spoilageRows,
        closingRows,
        siblingRows,
        transferRows,
      ] = await Promise.all([
        listIngredients(),
        getInventoryValuation(),
        listLowStock(),
        getReorderSuggestions(),
        getStockVarianceReport().catch(() => []),
        listVendors().catch(() => []),
        listPurchaseOrders().catch(() => []),
        listGrns().catch(() => []),
        listExpiringSoon(7).catch(() => []),
        getSpoilageReport(start, end).catch(() => []),
        getClosingHistory(14).catch(() => []),
        // Swallowed like the rest: a single-branch restaurant, or one whose
        // session cannot reach these, simply gets no Transfers tab rather than
        // an error across the whole screen.
        listSiblingBranches().catch(() => []),
        listBranchTransfers().catch(() => []),
      ]);
      setIngredients(asArray(ingredientRows));
      setVariance(asArray(varianceRows));
      setVendors(asArray(vendorRows));
      setPurchaseOrders(asArray(poRows));
      setGrns(asArray(grnRows));
      setExpiring(asArray(expiringRows));
      setSpoilage(asArray(spoilageRows));
      setClosings(asArray(closingRows));
      setSiblings(asArray(siblingRows));
      setTransfers(asArray(transferRows));
      setValuation(valuationReport);
      setLowStock(asArray(lowRows));
      setReorder(asArray(reorderRows));
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Could not load inventory.");
    } finally {
      setLoaded(true);
      inFlight.current = false;
      if (queued.current) {
        queued.current = false;
        void load();
      }
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Live updates instead of a Refresh button. The server announces "inventory
  // changed" for this branch when a stock move, purchase order or approval
  // commits, so a restock entered on one terminal lands here immediately.
  // Events carry no content, only the fact that something changed, so the
  // refetch below is what actually reads the new figures.
  useEffect(() => subscribeLive((event) => {
    if (event.topic === "inventory") void load();
  }), [load]);

  // Repairs anything missed while the tab was hidden and the stream was
  // dropped. Cheap: it runs when you come back to the tab, not on a timer.
  useEffect(() => {
    function onVisible() {
      if (document.visibilityState === "visible") void load();
    }
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [load]);

  // Everything another branch is blocked on: a request nobody has answered,
  // and a delivery nobody has confirmed — until that second one is confirmed
  // the stock sits in neither branch's count. Both belong on the tab rather
  // than behind it. Direction is the direction the STOCK travels, so a pending
  // row going "out" is another branch asking YOU for something.
  const awaitingMe = useMemo(
    () =>
      transfers.filter(
        (t) =>
          (t.status === "pending" && t.direction === "out") ||
          (t.status === "in_transit" && t.direction === "in"),
      ).length,
    [transfers],
  );
  const visibleTabs = useMemo<Array<{ id: TabId; label: string; badge?: number }>>(
    () =>
      siblings.length > 0
        ? [...TABS, { id: "transfers" as TabId, label: "Transfers", badge: awaitingMe }]
        : TABS,
    [siblings.length, awaitingMe],
  );
  // The tab can disappear — the last sibling branch is removed, or the reload
  // came back without it — and leaving `tab` pointing at it would render an
  // empty screen with no tab selected.
  useEffect(() => {
    if (tab === "transfers" && siblings.length === 0) setTab("stock");
  }, [tab, siblings.length]);

  const lowStockIds = useMemo(() => new Set(lowStock.map((item) => item.id)), [lowStock]);
  const ingredientName = useMemo(() => {
    const map = new Map(ingredients.map((i) => [i.id, i.name]));
    return (id: number) => map.get(id) ?? `#${id}`;
  }, [ingredients]);
  // The spoilage report returns no unit, so "Rice: 3" left you to guess kg,
  // litres or pieces. The ingredient rows already know, so look it up here.
  const unitFor = useMemo(() => {
    const map = new Map(ingredients.map((i) => [i.id, i.unit]));
    return (id: number) => map.get(id) ?? "";
  }, [ingredients]);
  // Purchase order rows used to read "Vendor #1", which is a database id and
  // tells nobody who the supplier is.
  const vendorName = useMemo(() => {
    const map = new Map(vendors.map((v) => [v.id, v.name]));
    return (id: number) => map.get(id) ?? `Vendor #${id}`;
  }, [vendors]);

  /** What was ordered, in the words of the person who ordered it. */
  const poContents = useMemo(() => {
    return (po: PurchaseOrderOut) => {
      const lines = po.lines ?? [];
      if (lines.length === 0) return "No lines";
      if (lines.length === 1) {
        const line = lines[0];
        return `${qty(line.qty_ordered, unitFor(line.ingredient_id))} ${ingredientName(line.ingredient_id)}`;
      }
      return `${lines.length} items`;
    };
  }, [ingredientName, unitFor]);

  function onIngredientCreated(created: IngredientOut) {
    setIngredients((prev) => [created, ...prev]);
    toast(`Ingredient added: ${created.name}`);
  }

  async function sendAlert() {
    setAlerting(true);
    try {
      const result = await sendLowStockAlert();
      toast(result.enqueued ? "Low stock WhatsApp alert queued." : result.reason ?? "No alert queued.");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not send alert.", "error");
    } finally {
      setAlerting(false);
    }
  }

  async function receivePo(poId: number) {
    setPurchasingBusy(true);
    try {
      await receivePurchaseOrder(poId);
      toast(`PO #${poId} received. Goods received note created.`);
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not receive PO.", "error");
    } finally {
      setPurchasingBusy(false);
    }
  }

  return (
    <div className={s.screen}>
      <PageHeader
        title="Inventory"
        subtitle="Stock on hand, purchasing, variance and spoilage"
        // Just the one action. The low-stock alert used to sit here too,
        // duplicating the button on the banner below — and it is only ever
        // meaningful when something IS low, which is exactly when the banner
        // is on screen.
        right={
          <div className={s.actions}>
            <Button size="md" type="button" onClick={() => setAddOpen(true)}>
              New ingredient
            </Button>
          </div>
        }
      />

      {addOpen && (
        <IngredientAddModal onClose={() => setAddOpen(false)} onCreated={onIngredientCreated} />
      )}

      {stockMove && (
        <StockMoveModal
          ingredients={ingredients}
          initialIngredientId={stockMove.ingredientId}
          initialAction={stockMove.action}
          onClose={() => setStockMove(null)}
          onActionChange={(action) =>
            setStockMove((prev) => (prev ? { ...prev, action } : prev))
          }
          onDone={(message) => {
            toast(message);
            void load();
          }}
        />
      )}

      {vendorOpen && (
        <VendorAddModal
          onClose={() => setVendorOpen(false)}
          onCreated={(vendor) => {
            setVendors((prev) => [...prev, vendor]);
            toast(`Vendor added: ${vendor.name}`);
          }}
        />
      )}

      {poOpen && (
        <PurchaseOrderModal
          vendors={vendors}
          ingredients={ingredients}
          onClose={() => setPoOpen(false)}
          onCreated={(po) => {
            setPurchaseOrders((prev) => [po, ...prev]);
            toast(`Purchase order #${po.id} created.`);
          }}
        />
      )}

      {loadError && (
        <ErrorState
          title="Could not load inventory"
          description={loadError}
          action={
            <Button size="md" type="button" onClick={() => void load()}>
              Retry
            </Button>
          }
        />
      )}

      <div className={s.tabBar}>
        <div className={s.tabGroup} role="tablist" aria-label="Inventory sections">
          {visibleTabs.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              className={`${s.tab} ${tab === t.id ? s.tabActive : ""}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
              {t.badge ? (
                <span className={s.tabCount} aria-label={`${t.badge} waiting on you`}>
                  {t.badge}
                </span>
              ) : null}
            </button>
          ))}
        </div>
      </div>

      {/* Summary and the low-stock alert belong to the Stock tab: they are all
          derived from stock on hand, and sitting above the tab bar they framed
          Purchasing, Counts and Waste with figures that had nothing to do with
          those views. */}
      {tab === "stock" && (
      <>
      {/* The banner names the low items outright, which answers the question a
          blind count is asking. */}
      {loaded && !loadError && !blindCount && lowStock.length > 0 && (
        <section className={s.lowStockBanner} role="status" aria-live="polite">
          <div className={s.lowStockCopy}>
            <strong>
              {lowStock.length} low stock item{lowStock.length === 1 ? "" : "s"}
            </strong>
            <span>
              {lowStock
                .slice(0, 6)
                .map((item) => item.name)
                .join(" · ")}
              {lowStock.length > 6 ? ` and ${lowStock.length - 6} more` : ""}
            </span>
          </div>
          {/* Styled to the banner rather than a blue primary: a saturated
              accent button inside an amber alert makes two things compete for
              the same glance. */}
          <button
            type="button"
            className={s.lowStockBtn}
            disabled={alerting}
            onClick={() => void sendAlert()}
          >
            {alerting ? "Sending..." : "Send WhatsApp alert"}
          </button>
        </section>
      )}

      <section className={s.metrics}>
        <div className={s.metric}>
          <span className={s.metricLabel}>Inventory value</span>
          {/* Both of these are computed FROM stock on hand, so leaving them up
              during a blind count hands back the number being hidden. */}
          <strong>{blindCount ? "---" : money(valuation?.total_value_aed)}</strong>
        </div>
        <div className={s.metric}>
          <span className={s.metricLabel}>Ingredients</span>
          <strong>{ingredients.length}</strong>
        </div>
        <div className={`${s.metric} ${!blindCount && lowStock.length > 0 ? s.metricAlert : ""}`}>
          <span className={s.metricLabel}>Low stock</span>
          <strong>{blindCount ? "---" : lowStock.length}</strong>
        </div>
      </section>

      <section className={s.grid}>
        <div className={s.card}>
          <div className={s.cardHead}>
            <div className={s.cardHeadText}>
              <h2>Stock on hand</h2>
              <span>{loaded ? `${ingredients.length} tracked items` : "Loading..."}</span>
            </div>
            <Button size="md"
              type="button"
              onClick={() => setStockMove({ ingredientId: "", action: "restock" })}
            >
              Stock move
            </Button>
          </div>
          {/* Blind count. While a count dialog is open the recorded figures are
              hidden, because a counter who can see "30" types 30 and the
              variance is always zero — the control silently stops working.
              Standard practice is to count without the expected number in
              view. Restock/waste/batch are unaffected: they are additions, not
              a reconciliation, so hiding the figure would only be obstructive. */}
          {blindCount && (
            <p className={s.blindNote} role="status">
              Blind count: stock figures are hidden until you save.
            </p>
          )}
          <div className={s.tableWrap}>
            <table className={s.table}>
              <thead>
                <tr>
                  <th>Ingredient</th>
                  <th className={s.num}>Stock</th>
                  <th className={s.num}>Par</th>
                  <th className={s.num}>Cost</th>
                  <th className={s.num}>Value</th>
                  <th>Status</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {ingredients.map((item) => (
                  <tr key={item.id} className={lowStockIds.has(item.id) ? s.rowLow : undefined}>
                    <td className={s.cellName}>{item.name}</td>
                    <td className={s.num}>
                      {blindCount ? (
                        <span className={s.hidden} aria-label="Hidden for blind count">
                          ---
                        </span>
                      ) : (
                        qty(item.current_stock, item.unit)
                      )}
                    </td>
                    <td className={s.num}>{qty(item.par_level, item.unit)}</td>
                    <td className={s.num}>{money(item.cost_per_unit_aed)}</td>
                    <td className={s.num}>
                      {/* Value gives the stock figure away: divide by cost. */}
                      {blindCount ? (
                        <span className={s.hidden} aria-hidden="true">
                          ---
                        </span>
                      ) : (
                        valueFor(valuation, item.id)
                      )}
                    </td>
                    <td>
                      {/* The Low badge is derived from stock, so it leaks the
                          answer just as plainly as the number would. */}
                      {blindCount ? (
                        <span className={s.hidden} aria-hidden="true">
                          ---
                        </span>
                      ) : (
                        <span className={lowStockIds.has(item.id) ? s.badgeWarn : s.badgeOk}>
                          {lowStockIds.has(item.id) ? "Low" : "OK"}
                        </span>
                      )}
                    </td>
                    <td className={s.cellAction}>
                      <button
                        type="button"
                        className={s.rowBtn}
                        aria-label={`Stock move for ${item.name}`}
                        onClick={() =>
                          setStockMove({
                            ingredientId: item.id,
                            action: lowStockIds.has(item.id) ? "restock" : "count",
                          })
                        }
                      >
                        Move
                      </button>
                    </td>
                  </tr>
                ))}
                {loaded && ingredients.length === 0 && (
                  <tr>
                    <td colSpan={7}>
                      <EmptyState
                        title="No ingredients yet"
                        description="Use New ingredient to track stock, cost and reorders."
                      />
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className={s.sideStack}>
          <div className={s.card}>
            <div className={s.cardHead}>
              <div className={s.cardHeadText}>
                <h2>Reorder queue</h2>
                <span>Suggested quantities to reach par.</span>
              </div>
            </div>
            <div className={s.list}>
              {reorder.map((item) => (
                <div key={item.ingredient_id} className={s.listItem}>
                  <strong>
                    {item.ingredient_name} needs {qty(item.suggested_order_qty, "kg")}
                  </strong>
                  <span>
                    Current {qty(item.current_stock)} of par {qty(item.par_level)}
                  </span>
                </div>
              ))}
              {loaded && reorder.length === 0 && <div className={s.empty}>No reorder suggestions.</div>}
            </div>
          </div>
        </div>
      </section>
      </>
      )}

      {tab === "counts" && (
      <section className={s.panels}>
        <div className={s.card}>
          <div className={s.cardHead}>
            <div className={s.cardHeadText}>
              <h2>Count variance</h2>
              <span>Counted stock against expected.</span>
            </div>
            <Button size="md"
              type="button"
              variant="ghost"
              onClick={async () => {
                try {
                  const rows = await takeClosingSnapshot();
                  // Say what it produced. "Snapshot saved" gave no sign that
                  // anything had been written, which is why the button felt
                  // like it did nothing.
                  toast(`Stock closing saved for today: ${rows.length} ingredient(s).`);
                  await load();
                } catch {
                  toast("Could not take closing snapshot.", "error");
                }
              }}
            >
              End of day snapshot
            </Button>
          </div>
          <div className={s.list}>
            {variance.slice(0, 5).map((v) => {
              const value = Number(v.variance_value_aed ?? 0);
              // Percentage is what the tolerance is actually judged on, so a
              // row that says "4 kg" without it gives no sense of whether the
              // count was fine or a problem. Server-side maths, repeated here:
              // variance over the PREVIOUS figure.
              const pct = variancePct(v.previous_stock, v.variance);
              return (
                <div key={v.id} className={s.listItem}>
                  <strong>
                    {v.ingredient_name}: {qty(v.variance, unitFor(v.ingredient_id))}
                    {pct !== null && ` (${pct.toFixed(1)}%)`}
                    {/* The money is the part that says whether it matters. A
                        quantity alone lets a costly loss read as a small
                        number. */}
                    {value !== 0 && (
                      <span className={value < 0 ? s.lossValue : s.gainValue}>
                        {value < 0 ? "-" : "+"}
                        {money(Math.abs(value))}
                      </span>
                    )}
                  </strong>
                  <span>
                    was {v.previous_stock}, counted {v.counted_stock}
                    {v.reason_code ? ` · ${countReasonLabel(v.reason_code)}` : " · no reason given"}
                    {v.created_at ? ` · ${shortDate(v.created_at)}` : ""}
                  </span>
                </div>
              );
            })}
            {/* The anomaly alert rows used to follow this list. Every alert
                raised BY a count restated the count directly above it — same
                ingredient, same percentage — so the card said everything
                twice. The count rows carry the percentage themselves now. */}
            {loaded && variance.length === 0 && (
              <div className={s.empty}>No counts recorded yet.</div>
            )}
          </div>
        </div>

        {/* What the End of day snapshot button produces. It was writing a row
            per ingredient per day that no screen ever read back, so pressing it
            looked like nothing happened. */}
        <div className={s.card}>
          <div className={s.cardHead}>
            <div className={s.cardHeadText}>
              <h2>Stock closing history</h2>
              <span>What your stock was worth at the end of each day.</span>
            </div>
          </div>
          <div className={s.list}>
            {closings.map((row, i) => {
              // Change against the NEXT row, because the list runs newest
              // first. The last row has nothing before it to compare against.
              const previous = closings[i + 1];
              const change = previous
                ? Number(row.total_value_aed) - Number(previous.total_value_aed)
                : null;
              // A dirham figure alone does not say whether the move was large.
              // AED 40 off AED 900 is noise; off AED 60 it is most of the store.
              const changePct =
                previous !== undefined && change !== null
                  ? variancePct(previous.total_value_aed, change)
                  : null;
              return (
                <div key={row.closing_date} className={s.listItem}>
                  <strong>
                    {shortDate(row.closing_date)}: {money(row.total_value_aed)}
                    {change !== null && change !== 0 && (
                      <span className={change < 0 ? s.lossValue : s.gainValue}>
                        {change < 0 ? "-" : "+"}
                        {money(Math.abs(change))}
                        {changePct !== null && ` (${changePct.toFixed(1)}%)`}
                      </span>
                    )}
                  </strong>
                  <span>
                    {row.items} ingredient{row.items === 1 ? "" : "s"}
                    {change === null ? "" : change < 0 ? " · stock down" : change > 0 ? " · stock up" : " · unchanged"}
                  </span>
                </div>
              );
            })}
            {loaded && closings.length === 0 && (
              <div className={s.empty}>
                No closings yet. Press End of day snapshot to record today.
              </div>
            )}
          </div>
        </div>
      </section>
      )}

      {tab === "purchasing" && (
      <section className={s.card}>
        <div className={s.cardHead}>
          <div className={s.cardHeadText}>
            <h2>Purchasing</h2>
            <span>Suppliers, purchase orders and goods received notes.</span>
          </div>
          <div className={s.actions}>
            <Button size="md" type="button" variant="ghost" onClick={() => setVendorOpen(true)}>
              Add vendor
            </Button>
            <Button size="md" type="button" onClick={() => setPoOpen(true)}>
              New purchase order
            </Button>
          </div>
        </div>
        {/* One row per order. The goods received notes used to be a SECOND
            list underneath, so a single order that had arrived showed up twice
            — once as the order, once as its receipt — and read like two
            separate events. A GRN only ever exists against a PO, so it belongs
            on that PO's row. */}
        <div className={s.list}>
          {purchaseOrders.slice(0, 8).map((po) => {
            const received = grns.filter((g) => g.po_id === po.id);
            return (
              <div key={po.id} className={s.approval}>
                <div>
                  <strong>
                    PO #{po.id} · {vendorName(po.vendor_id)}
                  </strong>
                  <span>
                    {poContents(po)} · {money(poTotal(po))} · {po.status}
                  </span>
                  {received.map((g) => (
                    <span key={g.id}>
                      Received {g.grn_number} by {g.received_by}
                    </span>
                  ))}
                </div>
                {(po.status === "draft" || po.status === "ordered" || po.status === "partial") && (
                  <div className={s.rowActions}>
                    <Button size="md"
                      type="button"
                      disabled={purchasingBusy}
                      aria-label={`Receive purchase order ${po.id}`}
                      onClick={() => void receivePo(po.id)}
                    >
                      Receive
                    </Button>
                  </div>
                )}
              </div>
            );
          })}
          {loaded && purchaseOrders.length === 0 && <div className={s.empty}>No purchase orders yet.</div>}
        </div>
        {/* Suppliers belong beside the orders raised against them, not on a
            shared "locations and suppliers" card as before. */}
        <div className={s.cardHead}>
          <div className={s.cardHeadText}>
            <h2>Suppliers</h2>
            <span>{vendors.length} vendor(s).</span>
          </div>
        </div>
        <div className={s.list}>
          {vendors.map((v) => (
            <div key={v.id} className={s.listItem}>
              <strong>{v.name}</strong>
              <span>{v.phone ?? v.email ?? "No contact details"}</span>
            </div>
          ))}
          {loaded && vendors.length === 0 && <div className={s.empty}>No vendors yet.</div>}
        </div>
      </section>
      )}

      {tab === "waste" && (
      <section className={s.panels}>
        <div className={s.card}>
          <div className={s.cardHead}>
            <div className={s.cardHeadText}>
              <h2>Spoilage and expiring</h2>
              {/* Says "spoilage only" because the report filters on that one
                  reason type — waste logged as wastage, theft or over portion
                  is not here, and a vaguer label made this look like a total. */}
              <span>Spoilage only, last 30 days. Batches expiring within 7 days.</span>
            </div>
          </div>
          <div className={s.list}>
            {spoilage.slice(0, 5).map((row, i) => (
              <div key={`sp-${i}`} className={s.listItem}>
                <strong>
                  {row.ingredient_name}: {qty(row.quantity, unitFor(row.ingredient_id))}
                </strong>
                {/* An empty note used to print the word "None", which reads like
                    a value. Show when it happened instead — that is what you
                    want to know, and it is always there. */}
                <span>
                  {row.reason_type}
                  {row.created_at ? ` · ${shortDate(row.created_at)}` : ""}
                  {row.reason ? ` · ${row.reason}` : ""}
                </span>
              </div>
            ))}
            {expiring.slice(0, 5).map((b) => (
              <div key={b.id} className={s.listItem}>
                <strong>
                  Batch #{b.id} · {ingredientName(b.ingredient_id)}
                </strong>
                <span>
                  expires {b.expiry_date}, remaining {b.qty_remaining ?? b.qty}
                </span>
              </div>
            ))}
            {loaded && spoilage.length === 0 && expiring.length === 0 && (
              <div className={s.empty}>No spoilage or expiring batches.</div>
            )}
          </div>
        </div>
      </section>
      )}

      {tab === "transfers" && siblings.length > 0 && (
        <BranchTransfersPanel
          transfers={transfers}
          branches={siblings}
          ingredients={ingredients}
          loaded={loaded}
          onDone={load}
        />
      )}

    </div>
  );
}
