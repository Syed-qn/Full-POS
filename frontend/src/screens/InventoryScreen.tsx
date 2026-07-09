import { useEffect, useMemo, useState } from "react";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import {
  approveStockAdjustment,
  createBatch,
  createIngredient,
  createPurchaseOrder,
  createVendor,
  getAnomalyAlerts,
  getInventoryValuation,
  getReorderSuggestions,
  getSpoilageReport,
  getStockVarianceReport,
  listExpiringSoon,
  listGrns,
  listIngredients,
  listLowStock,
  listPurchaseOrders,
  listStockAdjustments,
  listStockLocations,
  listVendors,
  receivePurchaseOrder,
  recordStockCount,
  rejectStockAdjustment,
  restockIngredient,
  sendLowStockAlert,
  takeClosingSnapshot,
  wasteIngredient,
} from "../lib/inventoryApi";
import { useManagerPinGate } from "../lib/requireManagerPin";
import type {
  BatchOut,
  GrnOut,
  IngredientOut,
  InventoryValuationOut,
  PurchaseOrderOut,
  ReorderSuggestionOut,
  StockAdjustmentOut,
  StockAnomalyAlertOut,
  StockLocationOut,
  StockVarianceRow,
  VendorOut,
} from "../lib/types";
import s from "./InventoryScreen.module.css";

const EMPTY_FORM = {
  name: "",
  unit: "",
  current_stock: "0.000",
  low_stock_threshold: "0.000",
  par_level: "0.000",
  cost_per_unit_aed: "0.0000",
};

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

function isoToday(): string {
  return new Date().toISOString().slice(0, 10);
}

export function InventoryScreen() {
  const [ingredients, setIngredients] = useState<IngredientOut[]>([]);
  const [valuation, setValuation] = useState<InventoryValuationOut | null>(null);
  const [lowStock, setLowStock] = useState<IngredientOut[]>([]);
  const [reorder, setReorder] = useState<ReorderSuggestionOut[]>([]);
  const [adjustments, setAdjustments] = useState<StockAdjustmentOut[]>([]);
  const [variance, setVariance] = useState<StockVarianceRow[]>([]);
  const [alerts, setAlerts] = useState<StockAnomalyAlertOut[]>([]);
  const [locations, setLocations] = useState<StockLocationOut[]>([]);
  const [vendors, setVendors] = useState<VendorOut[]>([]);
  const [purchaseOrders, setPurchaseOrders] = useState<PurchaseOrderOut[]>([]);
  const [grns, setGrns] = useState<GrnOut[]>([]);
  const [expiring, setExpiring] = useState<BatchOut[]>([]);
  const [spoilage, setSpoilage] = useState<
    Array<{ ingredient_name: string; quantity: string; reason_type: string; reason: string | null }>
  >([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [alerting, setAlerting] = useState(false);

  const [opsIngredientId, setOpsIngredientId] = useState<number | "">("");
  const [opsQty, setOpsQty] = useState("1.000");
  const [opsReason, setOpsReason] = useState("");
  const [opsReasonType, setOpsReasonType] = useState<"wastage" | "spoilage" | "theft" | "over_portion" | "other">(
    "spoilage",
  );
  const [opsExpiry, setOpsExpiry] = useState("");
  const [opsBusy, setOpsBusy] = useState(false);
  const { requestPin, pinGate, pinBusy } = useManagerPinGate();

  const [vendorName, setVendorName] = useState("");
  const [vendorPhone, setVendorPhone] = useState("");
  const [poVendorId, setPoVendorId] = useState<number | "">("");
  const [poIngredientId, setPoIngredientId] = useState<number | "">("");
  const [poQty, setPoQty] = useState("5.000");
  const [poCost, setPoCost] = useState("1.0000");
  const [purchasingBusy, setPurchasingBusy] = useState(false);

  async function load() {
    setLoadError(null);
    try {
      const start = isoDaysAgo(30);
      const end = isoToday();
      const [
        ingredientRows,
        valuationReport,
        pendingAdjustments,
        lowRows,
        reorderRows,
        varianceRows,
        alertRows,
        locationRows,
        vendorRows,
        poRows,
        grnRows,
        expiringRows,
        spoilageRows,
      ] = await Promise.all([
        listIngredients(),
        getInventoryValuation(),
        listStockAdjustments("pending"),
        listLowStock(),
        getReorderSuggestions(),
        getStockVarianceReport().catch(() => []),
        getAnomalyAlerts().catch(() => []),
        listStockLocations().catch(() => []),
        listVendors().catch(() => []),
        listPurchaseOrders().catch(() => []),
        listGrns().catch(() => []),
        listExpiringSoon(7).catch(() => []),
        getSpoilageReport(start, end).catch(() => []),
      ]);
      setIngredients(asArray(ingredientRows));
      setVariance(asArray(varianceRows));
      setAlerts(asArray(alertRows));
      setLocations(asArray(locationRows));
      setVendors(asArray(vendorRows));
      setPurchaseOrders(asArray(poRows));
      setGrns(asArray(grnRows));
      setExpiring(asArray(expiringRows));
      setSpoilage(asArray(spoilageRows));
      setValuation(valuationReport);
      setAdjustments(asArray(pendingAdjustments));
      setLowStock(asArray(lowRows));
      setReorder(asArray(reorderRows));
      if (!opsIngredientId && asArray<IngredientOut>(ingredientRows)[0]) {
        setOpsIngredientId(asArray<IngredientOut>(ingredientRows)[0].id);
      }
      if (!poIngredientId && asArray<IngredientOut>(ingredientRows)[0]) {
        setPoIngredientId(asArray<IngredientOut>(ingredientRows)[0].id);
      }
      if (!poVendorId && asArray<VendorOut>(vendorRows)[0]) {
        setPoVendorId(asArray<VendorOut>(vendorRows)[0].id);
      }
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Could not load inventory.");
    } finally {
      setLoaded(true);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const lowStockIds = useMemo(() => new Set(lowStock.map((item) => item.id)), [lowStock]);
  const ingredientName = useMemo(() => {
    const map = new Map(ingredients.map((i) => [i.id, i.name]));
    return (id: number) => map.get(id) ?? `#${id}`;
  }, [ingredients]);

  async function submitIngredient() {
    if (!form.name.trim() || !form.unit.trim()) {
      toast("Ingredient name and unit are required.", "error");
      return;
    }
    setSubmitting(true);
    try {
      const created = await createIngredient(form);
      setIngredients((prev) => [created, ...prev]);
      setForm(EMPTY_FORM);
      toast(`Ingredient added: ${created.name}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not add ingredient.", "error");
    } finally {
      setSubmitting(false);
    }
  }

  function decideAdjustment(adjustment: StockAdjustmentOut, decision: "approve" | "reject") {
    if (decision === "reject") {
      void (async () => {
        try {
          await rejectStockAdjustment(adjustment.id);
          setAdjustments((prev) => prev.filter((entry) => entry.id !== adjustment.id));
          toast("Adjustment rejected.");
          await load();
        } catch (e) {
          toast(e instanceof Error ? e.message : "Could not update adjustment.", "error");
        }
      })();
      return;
    }
    requestPin({
      actionType: "stock_adjustment",
      actionLabel: "Approve stock adjustment",
      recordLabel: `adj #${adjustment.id}`,
      reasonRequired: true,
      confirmTitle: "Approve stock adjustment?",
      confirmMessage: `Approve adjustment #${adjustment.id} to qty ${adjustment.requested_qty}. Manager PIN and reason required.`,
      confirmLabel: "Continue to PIN",
      cancelLabel: "Back",
      execute: async () => {
        await approveStockAdjustment(adjustment.id);
        setAdjustments((prev) => prev.filter((entry) => entry.id !== adjustment.id));
        toast("Adjustment approved.");
        await load();
      },
    });
  }

  async function sendAlert() {
    setAlerting(true);
    try {
      const result = await sendLowStockAlert();
      toast(result.enqueued ? "Low-stock WhatsApp alert queued." : result.reason ?? "No alert queued.");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not send alert.", "error");
    } finally {
      setAlerting(false);
    }
  }

  function runOps(action: "restock" | "waste" | "count" | "batch") {
    if (!opsIngredientId) {
      toast("Select an ingredient first.", "error");
      return;
    }
    if (action === "batch" && !opsExpiry) {
      toast("Expiry date required for FEFO batch.", "error");
      return;
    }
    const id = Number(opsIngredientId);
    const label =
      action === "restock"
        ? "Restock inventory"
        : action === "waste"
          ? "Log waste / spoilage"
          : action === "count"
            ? "Record stock count"
            : "Receive FEFO batch";
    requestPin({
      actionType: "stock_adjustment",
      actionLabel: label,
      recordLabel: `ingredient #${id}`,
      reasonRequired: true,
      amountAed: undefined,
      confirmTitle: `${label}?`,
      confirmMessage: `Change stock for ingredient #${id} (qty ${opsQty}). Manager PIN and reason required.`,
      confirmLabel: "Continue to PIN",
      cancelLabel: "Back",
      execute: async ({ reason }) => {
        setOpsBusy(true);
        try {
          if (action === "restock") {
            await restockIngredient(id, { quantity: opsQty });
            toast("Stock restocked.");
          } else if (action === "waste") {
            await wasteIngredient(id, {
              quantity: opsQty,
              reason: reason || opsReason || undefined,
              reason_type: opsReasonType,
            });
            toast(`${opsReasonType} logged.`);
          } else if (action === "count") {
            const result = await recordStockCount(id, { counted_qty: opsQty });
            toast(`Count saved. Variance ${result.variance}`);
          } else {
            await createBatch(id, { qty: opsQty, expiry_date: opsExpiry });
            toast("Batch received (FEFO).");
          }
          await load();
        } catch (e) {
          toast(e instanceof Error ? e.message : "Stock operation failed.", "error");
          throw e;
        } finally {
          setOpsBusy(false);
        }
      },
    });
  }

  async function addVendor() {
    if (!vendorName.trim()) {
      toast("Vendor name is required.", "error");
      return;
    }
    setPurchasingBusy(true);
    try {
      const v = await createVendor({
        name: vendorName.trim(),
        phone: vendorPhone.trim() || null,
      });
      setVendors((prev) => [...prev, v]);
      setPoVendorId(v.id);
      setVendorName("");
      setVendorPhone("");
      toast(`Vendor added: ${v.name}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not create vendor.", "error");
    } finally {
      setPurchasingBusy(false);
    }
  }

  async function createPo() {
    if (!poVendorId || !poIngredientId) {
      toast("Select vendor and ingredient for the PO.", "error");
      return;
    }
    setPurchasingBusy(true);
    try {
      const po = await createPurchaseOrder({
        vendor_id: Number(poVendorId),
        lines: [
          {
            ingredient_id: Number(poIngredientId),
            qty_ordered: poQty,
            unit_cost_aed: poCost,
          },
        ],
      });
      setPurchaseOrders((prev) => [po, ...prev]);
      toast(`PO #${po.id} created.`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not create purchase order.", "error");
    } finally {
      setPurchasingBusy(false);
    }
  }

  async function receivePo(poId: number) {
    setPurchasingBusy(true);
    try {
      await receivePurchaseOrder(poId);
      toast(`PO #${poId} received (GRN created).`);
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
        subtitle="Food cost, FEFO batches, GRN purchasing, variance, spoilage, and stock closing"
        right={
          <div className={s.actions}>
            <Button type="button" variant="ghost" onClick={() => void load()}>
              Refresh
            </Button>
            <Button type="button" disabled={alerting} onClick={() => void sendAlert()}>
              {alerting ? "Sending..." : "Send WhatsApp low-stock alert"}
            </Button>
          </div>
        }
      />

      {loadError && (
        <ErrorState
          title="Could not load inventory"
          description={loadError}
          action={
            <Button type="button" onClick={() => void load()}>
              Retry
            </Button>
          }
        />
      )}

      {loaded && !loadError && lowStock.length > 0 && (
        <section className={s.lowStockBanner} role="status" aria-live="polite">
          <div className={s.lowStockCopy}>
            <strong>
              {lowStock.length} low-stock item{lowStock.length === 1 ? "" : "s"}
            </strong>
            <span>
              {lowStock
                .slice(0, 6)
                .map((item) => item.name)
                .join(" · ")}
              {lowStock.length > 6 ? ` · +${lowStock.length - 6} more` : ""}
            </span>
          </div>
          <div className={s.lowStockActions}>
            <Button type="button" disabled={alerting} onClick={() => void sendAlert()}>
              {alerting ? "Sending…" : "Send WhatsApp alert"}
            </Button>
          </div>
        </section>
      )}

      <section className={s.metrics}>
        <div className={s.metric}>
          <span className={s.metricLabel}>Inventory value</span>
          <strong>{money(valuation?.total_value_aed)}</strong>
        </div>
        <div className={s.metric}>
          <span className={s.metricLabel}>Ingredients</span>
          <strong>{ingredients.length}</strong>
        </div>
        <div className={`${s.metric} ${lowStock.length > 0 ? s.metricAlert : ""}`}>
          <span className={s.metricLabel}>Low stock</span>
          <strong>{lowStock.length}</strong>
        </div>
        <div className={s.metric}>
          <span className={s.metricLabel}>Pending approvals</span>
          <strong>{adjustments.length}</strong>
        </div>
      </section>

      <section className={s.card}>
        <div className={s.cardHead}>
          <h2>New ingredient</h2>
          <span>Set starting stock, reorder threshold, par level, and cost.</span>
        </div>
        <div className={s.formGrid}>
          <label>
            <span>Ingredient name</span>
            <input
              aria-label="Ingredient name"
              value={form.name}
              onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
            />
          </label>
          <label>
            <span>Unit</span>
            <input
              aria-label="Unit"
              value={form.unit}
              onChange={(e) => setForm((prev) => ({ ...prev, unit: e.target.value }))}
            />
          </label>
          <label>
            <span>Current stock</span>
            <input
              aria-label="Current stock"
              value={form.current_stock}
              onChange={(e) => setForm((prev) => ({ ...prev, current_stock: e.target.value }))}
            />
          </label>
          <label>
            <span>Low-stock threshold</span>
            <input
              aria-label="Low-stock threshold"
              value={form.low_stock_threshold}
              onChange={(e) => setForm((prev) => ({ ...prev, low_stock_threshold: e.target.value }))}
            />
          </label>
          <label>
            <span>Par level</span>
            <input
              aria-label="Par level"
              value={form.par_level}
              onChange={(e) => setForm((prev) => ({ ...prev, par_level: e.target.value }))}
            />
          </label>
          <label>
            <span>Cost per unit</span>
            <input
              aria-label="Cost per unit"
              value={form.cost_per_unit_aed}
              onChange={(e) => setForm((prev) => ({ ...prev, cost_per_unit_aed: e.target.value }))}
            />
          </label>
        </div>
        <Button type="button" disabled={submitting} onClick={() => void submitIngredient()}>
          {submitting ? "Adding..." : "Add ingredient"}
        </Button>
      </section>

      <section className={s.card}>
        <div className={s.cardHead}>
          <h2>Stock operations</h2>
          <span>Restock, waste/spoilage, stock count (variance), FEFO batch receive.</span>
        </div>
        <div className={s.formGrid}>
          <label>
            <span>Ingredient</span>
            <select
              className={s.select}
              aria-label="Ops ingredient"
              value={opsIngredientId}
              onChange={(e) => setOpsIngredientId(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">Select…</option>
              {ingredients.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Quantity / counted qty</span>
            <input
              aria-label="Ops quantity"
              value={opsQty}
              onChange={(e) => setOpsQty(e.target.value)}
            />
          </label>
          <label>
            <span>Waste reason type</span>
            <select
              className={s.select}
              aria-label="Waste reason type"
              value={opsReasonType}
              onChange={(e) =>
                setOpsReasonType(e.target.value as typeof opsReasonType)
              }
            >
              <option value="spoilage">spoilage</option>
              <option value="wastage">wastage</option>
              <option value="theft">theft</option>
              <option value="over_portion">over_portion</option>
              <option value="other">other</option>
            </select>
          </label>
          <label>
            <span>Reason note</span>
            <input
              aria-label="Ops reason"
              value={opsReason}
              onChange={(e) => setOpsReason(e.target.value)}
            />
          </label>
          <label>
            <span>Batch expiry (FEFO)</span>
            <input
              type="date"
              aria-label="Batch expiry"
              value={opsExpiry}
              onChange={(e) => setOpsExpiry(e.target.value)}
            />
          </label>
        </div>
        <div className={s.actions}>
          <Button type="button" disabled={opsBusy || pinBusy} onClick={() => runOps("restock")}>
            Restock
          </Button>
          <Button type="button" disabled={opsBusy || pinBusy} onClick={() => runOps("waste")}>
            Log waste/spoilage
          </Button>
          <Button type="button" disabled={opsBusy || pinBusy} onClick={() => runOps("count")}>
            Record stock count
          </Button>
          <Button type="button" disabled={opsBusy || pinBusy} onClick={() => runOps("batch")}>
            Receive FEFO batch
          </Button>
        </div>
      </section>

      <section className={s.card}>
        <div className={s.cardHead}>
          <h2>Purchasing — vendors, PO &amp; GRN</h2>
          <span>Supplier management, purchase orders, goods received notes.</span>
        </div>
        <div className={s.formGrid}>
          <label>
            <span>New vendor name</span>
            <input
              aria-label="Vendor name"
              value={vendorName}
              onChange={(e) => setVendorName(e.target.value)}
            />
          </label>
          <label>
            <span>Vendor phone</span>
            <input
              aria-label="Vendor phone"
              value={vendorPhone}
              onChange={(e) => setVendorPhone(e.target.value)}
            />
          </label>
          <label>
            <span>PO vendor</span>
            <select
              className={s.select}
              aria-label="PO vendor"
              value={poVendorId}
              onChange={(e) => setPoVendorId(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">Select…</option>
              {vendors.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>PO ingredient</span>
            <select
              className={s.select}
              aria-label="PO ingredient"
              value={poIngredientId}
              onChange={(e) => setPoIngredientId(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">Select…</option>
              {ingredients.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Qty ordered</span>
            <input aria-label="PO qty" value={poQty} onChange={(e) => setPoQty(e.target.value)} />
          </label>
          <label>
            <span>Unit cost</span>
            <input aria-label="PO cost" value={poCost} onChange={(e) => setPoCost(e.target.value)} />
          </label>
        </div>
        <div className={s.actions}>
          <Button type="button" disabled={purchasingBusy} onClick={() => void addVendor()}>
            Add vendor
          </Button>
          <Button type="button" disabled={purchasingBusy} onClick={() => void createPo()}>
            Create purchase order
          </Button>
        </div>
        <div className={s.list}>
          {purchaseOrders.slice(0, 8).map((po) => (
            <div key={po.id} className={s.approval}>
              <div>
                <strong>
                  PO #{po.id} — {po.status}
                </strong>
                <span>
                  Vendor #{po.vendor_id} · {po.lines?.length ?? 0} line(s)
                </span>
              </div>
              {(po.status === "draft" || po.status === "ordered" || po.status === "partial") && (
                <div className={s.rowActions}>
                  <Button
                    type="button"
                    disabled={purchasingBusy}
                    aria-label={`Receive purchase order ${po.id}`}
                    onClick={() => void receivePo(po.id)}
                  >
                    Receive (GRN)
                  </Button>
                </div>
              )}
            </div>
          ))}
          {loaded && purchaseOrders.length === 0 && <div className={s.empty}>No purchase orders yet.</div>}
          {grns.slice(0, 5).map((g) => (
            <div key={g.id} className={s.listItem}>
              <strong>{g.grn_number}</strong>
              <span>
                PO #{g.po_id} · received by {g.received_by}
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className={s.grid}>
        <div className={s.card}>
          <div className={s.cardHead}>
            <h2>Stock on hand</h2>
            <span>{loaded ? `${ingredients.length} tracked items` : "Loading..."}</span>
          </div>
          <div className={s.tableWrap}>
            <table className={s.table}>
              <thead>
                <tr>
                  <th>Ingredient</th>
                  <th>Stock</th>
                  <th>Par</th>
                  <th>Cost</th>
                  <th>Value</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {ingredients.map((item) => (
                  <tr
                    key={item.id}
                    className={lowStockIds.has(item.id) ? s.rowLow : undefined}
                  >
                    <td>{item.name}</td>
                    <td>{qty(item.current_stock, item.unit)}</td>
                    <td>{qty(item.par_level, item.unit)}</td>
                    <td>{money(item.cost_per_unit_aed)}</td>
                    <td>{valueFor(valuation, item.id)}</td>
                    <td>
                      <span className={lowStockIds.has(item.id) ? s.badgeWarn : s.badgeOk}>
                        {lowStockIds.has(item.id) ? "Low" : "OK"}
                      </span>
                    </td>
                  </tr>
                ))}
                {loaded && ingredients.length === 0 && (
                  <tr>
                    <td colSpan={6}>
                      <EmptyState
                        title="No ingredients yet"
                        description="Add ingredients above to track stock, cost, and reorders."
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
              <h2>Reorder queue</h2>
              <span>Suggested quantities to reach par.</span>
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

          <div className={s.card}>
            <div className={s.cardHead}>
              <h2>Stock adjustment approvals</h2>
              <span>Manager approval before changing counted stock.</span>
            </div>
            <div className={s.list}>
              {adjustments.map((adjustment) => (
                <div key={adjustment.id} className={s.approval}>
                  <div>
                    <strong>
                      #{adjustment.id} to {qty(adjustment.requested_qty)}
                    </strong>
                    <span>
                      {adjustment.reason ?? "No reason supplied"} by {adjustment.requested_by}
                    </span>
                  </div>
                  <div className={s.rowActions}>
                    <Button
                      type="button"
                      variant="ghost"
                      aria-label={`Reject adjustment ${adjustment.id}`}
                      onClick={() => void decideAdjustment(adjustment, "reject")}
                    >
                      Reject
                    </Button>
                    <Button
                      type="button"
                      aria-label={`Approve adjustment ${adjustment.id}`}
                      onClick={() => void decideAdjustment(adjustment, "approve")}
                    >
                      Approve
                    </Button>
                  </div>
                </div>
              ))}
              {loaded && adjustments.length === 0 && <div className={s.empty}>No pending approvals.</div>}
            </div>
          </div>

          <div className={s.card}>
            <div className={s.cardHead}>
              <h2>Variance &amp; alerts</h2>
              <Button
                type="button"
                variant="ghost"
                onClick={async () => {
                  try {
                    await takeClosingSnapshot();
                    toast("EOD stock closing snapshot saved.");
                    await load();
                  } catch {
                    toast("Could not take closing snapshot.", "error");
                  }
                }}
              >
                Take EOD snapshot
              </Button>
            </div>
            <div className={s.list}>
              {variance.slice(0, 5).map((v) => (
                <div key={v.id} className={s.listItem}>
                  <strong>
                    {v.ingredient_name}: variance {v.variance}
                  </strong>
                  <span>
                    was {v.previous_stock} → counted {v.counted_stock}
                  </span>
                </div>
              ))}
              {alerts.slice(0, 5).map((a) => (
                <div key={a.id} className={s.listItem}>
                  <strong className={s.badgeWarn}>{a.alert_type}</strong>
                  <span>
                    {a.message ?? ingredientName(a.ingredient_id)} ({a.variance_pct}%)
                  </span>
                </div>
              ))}
              {loaded && variance.length === 0 && alerts.length === 0 && (
                <div className={s.empty}>No variance or anomaly alerts.</div>
              )}
            </div>
          </div>

          <div className={s.card}>
            <div className={s.cardHead}>
              <h2>Spoilage &amp; expiring</h2>
              <span>Last 30 days spoilage + batches expiring within 7 days.</span>
            </div>
            <div className={s.list}>
              {spoilage.slice(0, 5).map((row, i) => (
                <div key={`sp-${i}`} className={s.listItem}>
                  <strong>
                    {row.ingredient_name}: {row.quantity} ({row.reason_type})
                  </strong>
                  <span>{row.reason ?? "—"}</span>
                </div>
              ))}
              {expiring.slice(0, 5).map((b) => (
                <div key={b.id} className={s.listItem}>
                  <strong>
                    Batch #{b.id} · {ingredientName(b.ingredient_id)}
                  </strong>
                  <span>
                    expires {b.expiry_date} · remaining {b.qty_remaining ?? b.qty}
                  </span>
                </div>
              ))}
              {loaded && spoilage.length === 0 && expiring.length === 0 && (
                <div className={s.empty}>No spoilage or expiring batches.</div>
              )}
            </div>
          </div>

          <div className={s.card}>
            <div className={s.cardHead}>
              <h2>Locations &amp; suppliers</h2>
              <span>Central / commissary / branch stock areas.</span>
            </div>
            <div className={s.list}>
              {locations.map((loc) => (
                <div key={loc.id} className={s.listItem}>
                  <strong>{loc.name}</strong>
                  <span>
                    {loc.kitchen_role} · {loc.code}
                  </span>
                </div>
              ))}
              {vendors.map((v) => (
                <div key={v.id} className={s.listItem}>
                  <strong>Vendor: {v.name}</strong>
                  <span>{v.phone ?? v.email ?? "—"}</span>
                </div>
              ))}
              {loaded && locations.length === 0 && vendors.length === 0 && (
                <div className={s.empty}>No locations/vendors yet.</div>
              )}
            </div>
          </div>
        </div>
      </section>

      {pinGate}
    </div>
  );
}
