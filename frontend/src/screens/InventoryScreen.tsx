import { useEffect, useMemo, useState } from "react";
import { Button } from "../components/Button";
import { PageHeader } from "../components/PageHeader";
import { SectionBanner } from "../components/SectionBanner";
import { toast } from "../components/Toaster";
import {
  approveStockAdjustment,
  createIngredient,
  getInventoryValuation,
  getReorderSuggestions,
  listIngredients,
  listLowStock,
  listStockAdjustments,
  rejectStockAdjustment,
  sendLowStockAlert,
} from "../lib/inventoryApi";
import type {
  IngredientOut,
  InventoryValuationOut,
  ReorderSuggestionOut,
  StockAdjustmentOut,
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
  const formatted = typeof value === "string"
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

export function InventoryScreen() {
  const [ingredients, setIngredients] = useState<IngredientOut[]>([]);
  const [valuation, setValuation] = useState<InventoryValuationOut | null>(null);
  const [lowStock, setLowStock] = useState<IngredientOut[]>([]);
  const [reorder, setReorder] = useState<ReorderSuggestionOut[]>([]);
  const [adjustments, setAdjustments] = useState<StockAdjustmentOut[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [alerting, setAlerting] = useState(false);

  async function load() {
    setLoadError(null);
    try {
      const [ingredientRows, valuationReport, pendingAdjustments, lowRows, reorderRows] =
        await Promise.all([
          listIngredients(),
          getInventoryValuation(),
          listStockAdjustments("pending"),
          listLowStock(),
          getReorderSuggestions(),
        ]);
      setIngredients(ingredientRows);
      setValuation(valuationReport);
      setAdjustments(pendingAdjustments);
      setLowStock(lowRows);
      setReorder(reorderRows);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Could not load inventory.");
    } finally {
      setLoaded(true);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const lowStockIds = useMemo(() => new Set(lowStock.map((item) => item.id)), [lowStock]);

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

  async function decideAdjustment(adjustment: StockAdjustmentOut, decision: "approve" | "reject") {
    try {
      if (decision === "approve") {
        await approveStockAdjustment(adjustment.id);
      } else {
        await rejectStockAdjustment(adjustment.id);
      }
      setAdjustments((prev) => prev.filter((entry) => entry.id !== adjustment.id));
      toast(`Adjustment ${decision}d.`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not update adjustment.", "error");
    }
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

  return (
    <div className={s.screen}>
      <PageHeader
        title="Inventory"
        subtitle="Food cost, low-stock alerts, and manager-approved stock corrections"
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

      {loadError && <SectionBanner tone="warning">{loadError}</SectionBanner>}

      <section className={s.metrics}>
        <div className={s.metric}>
          <span className={s.metricLabel}>Inventory value</span>
          <strong>{money(valuation?.total_value_aed)}</strong>
        </div>
        <div className={s.metric}>
          <span className={s.metricLabel}>Ingredients</span>
          <strong>{ingredients.length}</strong>
        </div>
        <div className={s.metric}>
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
                  <tr key={item.id}>
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
                    <td colSpan={6} className={s.empty}>No ingredients yet.</td>
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
                  <strong>{item.ingredient_name} needs {qty(item.suggested_order_qty, "kg")}</strong>
                  <span>Current {qty(item.current_stock)} of par {qty(item.par_level)}</span>
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
                    <strong>#{adjustment.id} to {qty(adjustment.requested_qty)}</strong>
                    <span>{adjustment.reason ?? "No reason supplied"} by {adjustment.requested_by}</span>
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
        </div>
      </section>
    </div>
  );
}
